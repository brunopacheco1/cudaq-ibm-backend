/*******************************************************************************
 * Copyright (c) 2026 Bruno Pacheco.                                           *
 *                                                                             *
 * This source code and the accompanying materials are made available under    *
 * the terms of the Apache License 2.0 which accompanies this distribution.    *
 ******************************************************************************/

// Milestone M3: make any circuit fit the chip's wiring.
//
// CUDA-Q routes the kernel (pass `qubit-mapping`) on a device graph that we
// write as a file. This header builds that graph from IBM's backend data and
// turns CUDA-Q's qubit labels back into IBM qubit ids. Background and
// evidence: docs/m3-spec.md (until M3 ends), decision 0009.
//
// The steps, in order:
//   1. usableRegion()      drop broken qubits and links, keep the largest
//                          connected part of the chip.
//   2. chooseRoot()        pick the qubit the numbering starts from.
//   3. breadthFirstLayout() number the region 0..k-1 so every prefix is
//                          connected; this is the device file CUDA-Q routes on.
//   4. assignQubits()      after CUDA-Q, map each label of the circuit to a
//                          device qubit so every 2-qubit gate lands on a link.
//
// Pure functions (no I/O, no CUDA-Q), unit tested in tests/test_layout.cpp.

#pragma once

#include <algorithm>
#include <cstddef>
#include <map>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace cudaq::ibm {

// ============================================================================
// Input: what IBM tells us about the chip (/configuration + /properties).
// ============================================================================

struct ChipQubit {
  double readoutError = 0.0; // 0 when IBM gives no value
  bool operational = true;   // IBM's "operational" property, if present
};

struct ChipLink {
  int a = 0, b = 0;     // IBM qubit ids; IBM lists both directions
  double czError = 0.0; // IBM's cz "gate_error"; 1 means broken
  bool operational = true;
};

struct Chip {
  std::vector<ChipQubit> qubits; // index = IBM qubit id (n_qubits entries)
  std::vector<ChipLink> links;   // from coupling_map, errors from properties
};

// ============================================================================
// 1. The usable region.
// ============================================================================

struct Region {
  std::vector<int> qubits;           // IBM ids, ascending
  std::vector<std::vector<int>> adj; // by IBM id, ascending; empty if unused
  std::map<std::pair<int, int>, double> linkError; // key (low id, high id)
};

/// Keep links that work (operational, cz error below 1, both qubits
/// operational), then keep only the largest connected part. A device file
/// with unreachable qubits makes CUDA-Q fail ("disconnected device topology").
inline Region usableRegion(const Chip &chip) {
  const int n = static_cast<int>(chip.qubits.size());
  Region r;
  r.adj.assign(n, {});
  for (const auto &l : chip.links) {
    if (l.a < 0 || l.b < 0 || l.a >= n || l.b >= n || l.a == l.b)
      continue;
    if (!l.operational || l.czError >= 1.0 || !chip.qubits[l.a].operational ||
        !chip.qubits[l.b].operational)
      continue;
    const auto key = std::minmax(l.a, l.b);
    auto [it, fresh] = r.linkError.emplace(key, l.czError);
    if (!fresh) {
      // Same link listed in the other direction: keep the worse error.
      it->second = std::max(it->second, l.czError);
      continue;
    }
    r.adj[l.a].push_back(l.b);
    r.adj[l.b].push_back(l.a);
  }

  // Connected parts, by breadth-first search from each unseen qubit.
  std::vector<int> part(n, -1);
  std::vector<std::vector<int>> parts;
  for (int s = 0; s < n; ++s) {
    if (part[s] != -1 || r.adj[s].empty())
      continue;
    std::vector<int> members{s};
    part[s] = static_cast<int>(parts.size());
    for (std::size_t i = 0; i < members.size(); ++i)
      for (int v : r.adj[members[i]])
        if (part[v] == -1) {
          part[v] = part[s];
          members.push_back(v);
        }
    parts.push_back(std::move(members));
  }
  if (parts.empty())
    throw std::runtime_error("ibm: the chip has no working 2-qubit link");

  // Largest part; on a tie, the one found first (lowest qubit id).
  std::size_t best = 0;
  for (std::size_t p = 1; p < parts.size(); ++p)
    if (parts[p].size() > parts[best].size())
      best = p;

  r.qubits = parts[best];
  std::sort(r.qubits.begin(), r.qubits.end());
  for (int q = 0; q < n; ++q) {
    if (part[q] != static_cast<int>(best)) {
      r.adj[q].clear();
      continue;
    }
    std::sort(r.adj[q].begin(), r.adj[q].end());
  }
  for (auto it = r.linkError.begin(); it != r.linkError.end();)
    it = part[it->first.first] == static_cast<int>(best)
             ? std::next(it)
             : r.linkError.erase(it);
  return r;
}

// ============================================================================
// 2. The root (decision 0009, D2 option C: noise-aware).
//
// Rule chosen by Bruno on 2026-11-09: the score of a qubit is the mean cz
// error of its working links plus its readout error; lowest score wins, ties
// go to the lowest id. The kernel size is not known when the device file is
// written (getPipelineSubstitutions gets no kernel), so the score cannot
// depend on it.
// ============================================================================

inline int chooseRoot(const Region &region, const Chip &chip) {
  int best = -1;
  double bestScore = 0.0;
  for (int q : region.qubits) {
    const auto &nbrs = region.adj[q];
    double sum = 0.0;
    for (int v : nbrs)
      sum += region.linkError.at(std::minmax(q, v));
    const double score =
        sum / static_cast<double>(nbrs.size()) + chip.qubits[q].readoutError;
    if (best == -1 || score < bestScore) {
      best = q;
      bestScore = score;
    }
  }
  return best;
}

// ============================================================================
// 3. Breadth-first numbering.
//
// Label 0 is the root; then its neighbours, then theirs, each group in
// ascending IBM id. Claim: for every k, labels 0..k-1 form a connected
// graph. Proof: every label j > 0 was found from a neighbour that already
// had a smaller label (its "parent"), so following parents from any label
// below k reaches label 0 without leaving 0..k-1.
//
// Why it helps: CUDA-Q's default start layout is "identity" (virtual qubit
// v on device qubit v), so a kernel with n qubits starts on labels 0..n-1,
// which is a connected patch around the root.
// ============================================================================

struct Layout {
  std::vector<int> ibmId;            // device label -> IBM qubit id
  std::vector<std::vector<int>> adj; // by device label, ascending
};

inline Layout breadthFirstLayout(const Region &region, int root) {
  const int n = static_cast<int>(region.adj.size());
  if (root < 0 || root >= n || region.adj[root].empty())
    throw std::runtime_error("ibm: root qubit " + std::to_string(root) +
                             " is not in the usable region");
  std::vector<int> label(n, -1);
  Layout l;
  l.ibmId.push_back(root);
  label[root] = 0;
  for (std::size_t i = 0; i < l.ibmId.size(); ++i)
    for (int v : region.adj[l.ibmId[i]]) // ascending IBM id
      if (label[v] == -1) {
        label[v] = static_cast<int>(l.ibmId.size());
        l.ibmId.push_back(v);
      }
  l.adj.assign(l.ibmId.size(), {});
  for (std::size_t k = 0; k < l.ibmId.size(); ++k) {
    for (int v : region.adj[l.ibmId[k]])
      l.adj[k].push_back(label[v]);
    std::sort(l.adj[k].begin(), l.adj[k].end());
  }
  return l;
}

/// The device file `qubit-mapping{device=file(F)}` reads. Same text format
/// IQM writes (IQMServerHelper.cpp, writeQuantumArchitectureFile).
inline std::string deviceFileText(const std::vector<std::vector<int>> &adj) {
  std::size_t edges = 0;
  for (const auto &a : adj)
    edges += a.size();
  std::ostringstream out;
  out << "Number of nodes: " << adj.size() << "\n";
  out << "Number of edges: " << edges / 2 << "\n";
  for (std::size_t i = 0; i < adj.size(); ++i) {
    out << i << " --> {";
    for (std::size_t j = 0; j < adj[i].size(); ++j)
      out << (j ? ", " : "") << adj[i][j];
    out << "}\n";
  }
  return out.str();
}

/// Read a device file back (for the `mapping_file` target argument). Lines
/// that are not "i --> {a, b}" are ignored, like the header lines.
inline std::vector<std::vector<int>> parseDeviceFile(const std::string &text) {
  std::vector<std::vector<int>> adj;
  std::istringstream in(text);
  std::string line;
  while (std::getline(in, line)) {
    const auto arrow = line.find("-->");
    const auto open = line.find('{');
    const auto close = line.find('}');
    if (arrow == std::string::npos || open == std::string::npos ||
        close == std::string::npos || close < open)
      continue;
    const int node = std::stoi(line.substr(0, arrow));
    if (node < 0)
      throw std::runtime_error("ibm: bad device file line: " + line);
    if (static_cast<int>(adj.size()) <= node)
      adj.resize(node + 1);
    std::stringstream items(line.substr(open + 1, close - open - 1));
    std::string item;
    while (std::getline(items, item, ','))
      if (item.find_first_not_of(" \t") != std::string::npos)
        adj[node].push_back(std::stoi(item));
  }
  for (std::size_t i = 0; i < adj.size(); ++i)
    for (int v : adj[i]) {
      if (v < 0)
        throw std::runtime_error("ibm: bad qubit id in device file");
      if (static_cast<int>(adj.size()) <= v)
        adj.resize(v + 1);
    }
  // Make it symmetric and sorted (the file may list a link once).
  std::vector<std::vector<int>> sym(adj.size());
  for (std::size_t i = 0; i < adj.size(); ++i)
    for (int v : adj[i]) {
      sym[i].push_back(v);
      sym[v].push_back(static_cast<int>(i));
    }
  for (auto &s : sym) {
    std::sort(s.begin(), s.end());
    s.erase(std::unique(s.begin(), s.end()), s.end());
  }
  return sym;
}

// ============================================================================
// 4. Assign each circuit label to a device qubit.
//
// Why this is needed: after routing, CUDA-Q's `regtomem` pass packs the
// device qubits the circuit uses into labels 0..m-1, and the real layout is
// not passed to us (m3-spec §2.4). Routing often borrows a qubit outside
// 0..n-1, so we cannot assume label = device qubit.
//
// Why any valid assignment is correct: a circuit is a list of gates on
// labels. Running it on chip qubits through any one-to-one map where every
// 2-qubit gate lands on a link performs the same computation; only the noise
// differs. Qubits the router borrowed start in |0> wherever they sit.
//
// Search: depth-first, one connected group of interacting labels at a time.
// A label whose partner is placed must sit on a neighbour of the partner (at
// most 3 choices on IBM heavy-hex); a free label tries its own number first,
// so labels stay on the region CUDA-Q routed on whenever possible.
// ============================================================================

inline std::vector<int>
assignQubits(int numLabels, const std::vector<std::pair<int, int>> &pairs,
             const std::vector<std::vector<int>> &adj, long budget = 1000000) {
  const int numDevice = static_cast<int>(adj.size());
  if (numLabels > numDevice)
    throw std::runtime_error(
        "ibm: the circuit needs " + std::to_string(numLabels) +
        " qubits but the usable chip has " + std::to_string(numDevice));

  std::vector<std::vector<int>> partners(numLabels);
  for (auto [a, b] : pairs) {
    if (a < 0 || b < 0 || a >= numLabels || b >= numLabels || a == b)
      throw std::runtime_error("ibm: bad 2-qubit gate on labels " +
                               std::to_string(a) + ", " + std::to_string(b));
    partners[a].push_back(b);
    partners[b].push_back(a);
  }
  for (auto &p : partners) {
    std::sort(p.begin(), p.end());
    p.erase(std::unique(p.begin(), p.end()), p.end());
  }

  // Visit order: each group breadth-first, so a label's first partner is
  // placed before it (except the first label of each group).
  std::vector<int> order;
  std::vector<char> seen(numLabels, 0);
  for (int s = 0; s < numLabels; ++s) {
    if (seen[s])
      continue;
    seen[s] = 1;
    const std::size_t start = order.size();
    order.push_back(s);
    for (std::size_t i = start; i < order.size(); ++i)
      for (int v : partners[order[i]])
        if (!seen[v]) {
          seen[v] = 1;
          order.push_back(v);
        }
  }

  std::vector<int> place(numLabels, -1);
  std::vector<char> used(numDevice, 0);
  long steps = 0;

  auto isLinked = [&](int x, int y) {
    return std::binary_search(adj[x].begin(), adj[x].end(), y);
  };

  // Candidate device qubits for a label, best first.
  auto candidates = [&](int label) {
    std::vector<int> out;
    int anchor = -1;
    for (int p : partners[label])
      if (place[p] != -1) {
        anchor = place[p];
        break;
      }
    if (anchor == -1) {
      out.resize(numDevice);
      std::iota(out.begin(), out.end(), 0);
    } else {
      for (int d : adj[anchor]) {
        bool ok = true;
        for (int p : partners[label])
          if (place[p] != -1 && !isLinked(place[p], d)) {
            ok = false;
            break;
          }
        if (ok)
          out.push_back(d);
      }
    }
    // Prefer the label's own number, then ascending.
    std::stable_partition(out.begin(), out.end(),
                          [&](int d) { return d == label; });
    return out;
  };

  // Explicit recursion is fine: depth <= number of labels (<= chip size).
  auto search = [&](auto &self, std::size_t k) -> bool {
    if (k == order.size())
      return true;
    const int label = order[k];
    for (int d : candidates(label)) {
      if (++steps > budget)
        return false;
      if (used[d])
        continue;
      place[label] = d;
      used[d] = 1;
      if (self(self, k + 1))
        return true;
      place[label] = -1;
      used[d] = 0;
    }
    return false;
  };

  if (!search(search, 0))
    throw std::runtime_error(
        steps > budget
            ? "ibm: gave up placing the circuit on the chip after " +
                  std::to_string(budget) + " steps"
            : "ibm: the circuit's 2-qubit gates do not fit the chip's links; "
              "this should not happen after CUDA-Q routing, please report it");
  return place;
}

} // namespace cudaq::ibm
