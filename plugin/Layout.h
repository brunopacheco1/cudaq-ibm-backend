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
// evidence: docs/m3-spec.md (until M3 ends), decisions 0009 and 0012.
//
// The steps, in order:
//   1. usableRegion()      drop broken qubits and links, keep the largest
//                          connected part of the chip.
//   2. chooseRoot()        pick the qubit the numbering starts from.
//   3. bestFirstLayout()   number the region 0..k-1 so every prefix is
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

/// Marks an error rate IBM did not give us (or we could not read).
constexpr double UNKNOWN_ERROR = -1.0;

struct UnknownCount {
  int qubits = 0;   // qubits with no readout error
  int links = 0;    // links with no cz error in either direction
  int allLinks = 0; // links on the chip (each pair counted once)
};

/// Fail closed on missing data (decision 0009, item 3): what we cannot read,
/// we do not trust. Call this on a chip whose error rates started as
/// UNKNOWN_ERROR and were then filled from /properties.
///   - A link with no cz error in either direction is marked not operational
///     (an unknown link must not look like a perfect one).
///   - A link known in one direction only uses that value for both.
///   - A qubit with no readout error gets the worst score (1), so it is never
///     picked as the root, but it stays usable.
inline UnknownCount closeUnknowns(Chip &chip) {
  UnknownCount count;
  for (auto &q : chip.qubits)
    if (q.readoutError < 0.0) {
      q.readoutError = 1.0;
      ++count.qubits;
    }
  std::map<std::pair<int, int>, double> known; // pair -> worst known error
  for (const auto &l : chip.links)
    if (l.czError >= 0.0) {
      auto [it, fresh] = known.emplace(std::minmax(l.a, l.b), l.czError);
      if (!fresh)
        it->second = std::max(it->second, l.czError);
    }
  std::map<std::pair<int, int>, bool> unknownPairs, allPairs;
  for (auto &l : chip.links) {
    const auto key = std::minmax(l.a, l.b);
    allPairs[key] = true;
    if (l.czError >= 0.0)
      continue;
    if (auto it = known.find(key); it != known.end()) {
      l.czError = it->second;
    } else {
      l.czError = 1.0;
      l.operational = false;
      unknownPairs[key] = true;
    }
  }
  count.links = static_cast<int>(unknownPairs.size());
  count.allLinks = static_cast<int>(allPairs.size());
  return count;
}

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
/// IBM lists each link in both directions; if either direction is broken,
/// the link is dropped, and otherwise it keeps the worse of the two errors.
inline Region usableRegion(const Chip &chip) {
  const int n = static_cast<int>(chip.qubits.size());
  Region r;
  r.adj.assign(n, {});
  std::map<std::pair<int, int>, std::pair<double, bool>> pairs; // error, ok
  for (const auto &l : chip.links) {
    if (l.a < 0 || l.b < 0 || l.a >= n || l.b >= n || l.a == l.b)
      continue;
    const bool ok = l.operational && l.czError < 1.0 &&
                    chip.qubits[l.a].operational &&
                    chip.qubits[l.b].operational;
    auto [it, fresh] =
        pairs.emplace(std::minmax(l.a, l.b), std::make_pair(l.czError, ok));
    if (!fresh) {
      it->second.first = std::max(it->second.first, l.czError);
      it->second.second = it->second.second && ok;
    }
  }
  for (const auto &[key, state] : pairs) {
    if (!state.second)
      continue;
    r.linkError.emplace(key, state.first);
    r.adj[key.first].push_back(key.second);
    r.adj[key.second].push_back(key.first);
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
// 2 and 3. The root and the numbering (decision 0012).
//
// Label 0 is the root. The next label always goes to the qubit, linked to an
// already numbered one, with the lowest cost = its readout error + the cz
// error of its best link into the numbered set ("best-first"). Ties go to
// the lowest IBM id.
//
// Claim: for every k, labels 0..k-1 form a connected graph. Proof: every
// label j > 0 was reached over a link from a qubit that already had a
// smaller label (its "parent"), so following parents from any label below k
// reaches label 0 without leaving 0..k-1.
//
// Why it helps: low labels are a connected patch of good qubits. The
// assignment search (step 4) tries each circuit label on the device qubit
// with the same number first, then on low numbers, so a circuit with m
// labels lands on or near labels 0..m-1. (The router itself does not stay
// there: with placement=auto its greedy start begins at the most central
// qubit of the device file. That does not matter, because only the packed
// labels reach us; m3-spec §2.4.)
//
// The root: grow such a patch of ROOT_REGION_SIZE qubits from every qubit
// and keep the root whose patch has the best forecast.
//
// Forecast of a patch: the product of (1 - readout error) over its qubits
// and (1 - cz error) over the link each qubit was reached by. It is the
// chance that a circuit touching every qubit once and every such link once
// runs without an error. Crude, but the first hardware run agreed with it
// (ibm_fez, 2026-11-10: 82.9% forecast, 81.2% measured).
//
// History: until 2026-11-10 the root was the qubit with the lowest (mean cz
// error of its links + readout error) and the numbering was breadth-first.
// On the first hardware run that picked qubit 114, whose neighbour 113 had a
// readout error of 11.7% and got label 1, so a 5-qubit job ran through it.
// ============================================================================

struct Layout {
  std::vector<int> ibmId;            // device label -> IBM qubit id
  std::vector<std::vector<int>> adj; // by device label, ascending
};

/// How many qubits the root's patch has when roots are compared. The kernel
/// size is not known when the device file is written
/// (getPipelineSubstitutions gets no kernel), so this is fixed.
constexpr std::size_t ROOT_REGION_SIZE = 10;

struct Patch {
  std::vector<int> ibmId; // in numbering order; ibmId[0] is the root
  double forecast = 0.0;  // see above; 0 when a readout error is unknown
};

/// The first `limit` qubits in best-first order from `root`.
inline Patch growPatch(const Region &region, const Chip &chip, int root,
                       std::size_t limit) {
  const int n = static_cast<int>(region.adj.size());
  if (root < 0 || root >= n || region.adj[root].empty())
    throw std::runtime_error("ibm: root qubit " + std::to_string(root) +
                             " is not in the usable region");
  constexpr double NOT_REACHED = 2.0;           // above any error rate
  std::vector<double> bestLink(n, NOT_REACHED); // best cz error into the patch
  std::vector<char> inPatch(n, 0);
  Patch patch;
  patch.forecast = 1.0;
  int next = root;
  double nextLink = 0.0;
  while (next != -1 && patch.ibmId.size() < limit) {
    inPatch[next] = 1;
    patch.ibmId.push_back(next);
    patch.forecast *= (1.0 - chip.qubits[next].readoutError) * (1.0 - nextLink);
    for (int v : region.adj[next])
      if (!inPatch[v])
        bestLink[v] =
            std::min(bestLink[v], region.linkError.at(std::minmax(next, v)));
    next = -1;
    double nextCost = 0.0;
    for (int v : region.qubits) { // ascending IBM id: ties go to the lowest
      if (inPatch[v] || bestLink[v] == NOT_REACHED)
        continue;
      const double cost = chip.qubits[v].readoutError + bestLink[v];
      if (next == -1 || cost < nextCost) {
        next = v;
        nextCost = cost;
        nextLink = bestLink[v];
      }
    }
  }
  return patch;
}

/// The root whose patch of `size` qubits has the best forecast. Two roots
/// inside the same patch often give the same forecast; then the one with the
/// lower readout error wins (it becomes label 0), then the lowest IBM id.
/// Forecasts closer than 1e-12 count as equal, so that the choice does not
/// depend on the order of the multiplications.
inline int chooseRoot(const Region &region, const Chip &chip,
                      std::size_t size = ROOT_REGION_SIZE) {
  constexpr double SAME = 1e-12;
  int best = -1;
  double bestForecast = 0.0;
  for (int q : region.qubits) {
    const double forecast = growPatch(region, chip, q, size).forecast;
    const bool better = best == -1 || forecast > bestForecast + SAME;
    const bool tieWon =
        !better && forecast > bestForecast - SAME &&
        chip.qubits[q].readoutError < chip.qubits[best].readoutError;
    if (better || tieWon) {
      best = q;
      bestForecast = forecast;
    }
  }
  return best;
}

/// Number the whole region best-first from `root`.
inline Layout bestFirstLayout(const Region &region, const Chip &chip,
                              int root) {
  const Patch all = growPatch(region, chip, root, region.qubits.size());
  std::vector<int> label(region.adj.size(), -1);
  for (std::size_t k = 0; k < all.ibmId.size(); ++k)
    label[all.ibmId[k]] = static_cast<int>(k);
  Layout l;
  l.ibmId = all.ibmId;
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
// Search: depth-first with backtracking (so it is complete: it finds a map
// whenever one exists, unless the step budget runs out). To stay fast on a
// full chip it always places next the label with the most placed partners
// (fewest choices: on IBM heavy-hex at most 3), and it checks ahead:
//   - a label can only sit on a device qubit with at least as many links as
//     the label has partners;
//   - after placing a label, each unplaced partner must still have a free
//     candidate, otherwise it backs up at once.
// Every label tries the device qubit with its own number first, then the
// others in ascending order, so the circuit stays on low device labels,
// which are the ones near the root.
//
// Known limit: above about 100 labels the search may hit the step budget and
// refuse the circuit with a clear error, never a wrong placement. Stress test
// on ibm_fez (experiments/m3_search_stress.cpp, 40 cases each): nothing
// refused at 100 labels; sparse, chain-like circuits refused in 4 of 40 cases
// at 130 and up to 7 of 40 at 156; dense circuits never.
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

  // Size of each label's connected group: big groups are placed first,
  // while the chip is still empty (small ones fit in the gaps later).
  std::vector<int> groupSize(numLabels, 0);
  {
    std::vector<int> group(numLabels, -1), sizes;
    for (int s = 0; s < numLabels; ++s) {
      if (group[s] != -1)
        continue;
      const int id = static_cast<int>(sizes.size());
      std::vector<int> members{s};
      group[s] = id;
      for (std::size_t i = 0; i < members.size(); ++i)
        for (int v : partners[members[i]])
          if (group[v] == -1) {
            group[v] = id;
            members.push_back(v);
          }
      sizes.push_back(static_cast<int>(members.size()));
    }
    for (int l = 0; l < numLabels; ++l)
      groupSize[l] = sizes[group[l]];
  }

  std::vector<int> place(numLabels, -1);
  std::vector<char> used(numDevice, 0);
  long steps = 0;

  auto isLinked = [&](int x, int y) {
    return std::binary_search(adj[x].begin(), adj[x].end(), y);
  };
  auto fits = [&](int label, int d) {
    return !used[d] && adj[d].size() >= partners[label].size();
  };

  // Free device qubits a label can take now, given its placed partners.
  // Only called for labels with at least one placed partner.
  auto anchoredCandidates = [&](int label) {
    std::vector<int> out;
    int anchor = -1;
    for (int p : partners[label])
      if (place[p] != -1) {
        anchor = place[p];
        break;
      }
    for (int d : adj[anchor]) {
      if (!fits(label, d))
        continue;
      bool ok = true;
      for (int p : partners[label])
        if (place[p] != -1 && !isLinked(place[p], d)) {
          ok = false;
          break;
        }
      if (ok)
        out.push_back(d);
    }
    return out;
  };

  // Next label: most placed partners, then fewest candidates, then biggest
  // group, then most partners, then lowest number. -1 when all are placed.
  auto nextLabel = [&]() {
    int best = -1, bestPlaced = -1, bestPartners = -1, bestGroup = -1;
    std::size_t bestChoices = 0;
    for (int l = 0; l < numLabels; ++l) {
      if (place[l] != -1)
        continue;
      int placed = 0;
      for (int p : partners[l])
        placed += place[p] != -1;
      const int total = static_cast<int>(partners[l].size());
      const std::size_t choices =
          placed ? anchoredCandidates(l).size() : static_cast<std::size_t>(-1);
      const bool better =
          best == -1 || placed > bestPlaced ||
          (placed == bestPlaced &&
           (choices < bestChoices ||
            (choices == bestChoices &&
             (groupSize[l] > bestGroup ||
              (groupSize[l] == bestGroup && total > bestPartners)))));
      if (better) {
        best = l;
        bestPlaced = placed;
        bestChoices = choices;
        bestGroup = groupSize[l];
        bestPartners = total;
      }
    }
    return best;
  };

  // Every unplaced partner of `label` still has somewhere to go.
  auto lookAhead = [&](int label) {
    for (int p : partners[label])
      if (place[p] == -1 && anchoredCandidates(p).empty())
        return false;
    return true;
  };

  // Recursion depth <= number of labels (<= chip size).
  auto search = [&](auto &self) -> bool {
    const int label = nextLabel();
    if (label == -1)
      return true;
    bool anchored = false;
    for (int p : partners[label])
      anchored = anchored || place[p] != -1;
    std::vector<int> options;
    if (anchored) {
      options = anchoredCandidates(label);
    } else {
      for (int d = 0; d < numDevice; ++d)
        if (fits(label, d))
          options.push_back(d);
    }
    // Prefer the label's own number, then ascending.
    std::stable_partition(options.begin(), options.end(),
                          [&](int d) { return d == label; });
    for (int d : options) {
      if (++steps > budget)
        return false;
      place[label] = d;
      used[d] = 1;
      if (lookAhead(label) && self(self))
        return true;
      place[label] = -1;
      used[d] = 0;
    }
    return false;
  };

  if (!search(search))
    throw std::runtime_error(
        steps > budget
            ? "ibm: gave up placing the circuit on the chip after " +
                  std::to_string(budget) + " steps"
            : "ibm: the circuit's 2-qubit gates do not fit the chip's links; "
              "this should not happen after CUDA-Q routing, please report it");
  return place;
}

} // namespace cudaq::ibm
