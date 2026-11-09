/*******************************************************************************
 * Copyright (c) 2026 Bruno Pacheco.                                           *
 *                                                                             *
 * This source code and the accompanying materials are made available under    *
 * the terms of the Apache License 2.0 which accompanies this distribution.    *
 ******************************************************************************/

// Unit tests for Layout.h (M3 routing). No CUDA-Q, no network. Run from the
// repository root (it reads tests/data/ibm_fez_coupling.txt):
//
//   g++ -std=c++20 -I plugin plugin/tests/test_layout.cpp -o /tmp/tl && /tmp/tl

#include "Layout.h"
#include "Qasm2ToIsa.h"

#include <fstream>
#include <iostream>
#include <random>
#include <set>

using namespace cudaq::ibm;

static int failures = 0;
#define CHECK(cond, msg)                                                       \
  do {                                                                         \
    if (!(cond)) {                                                             \
      std::cerr << "FAIL: " << msg << "\n";                                    \
      ++failures;                                                              \
    } else {                                                                   \
      std::cout << "ok:   " << msg << "\n";                                    \
    }                                                                          \
  } while (0)

template <typename F>
static bool throws(F f) {
  try {
    f();
  } catch (const std::runtime_error &) {
    return true;
  }
  return false;
}

// ibm_fez wiring, both directions, as IBM's /configuration lists it.
static Chip loadFez() {
  std::ifstream in("tests/data/ibm_fez_coupling.txt");
  if (!in)
    throw std::runtime_error("run from the repository root");
  Chip chip;
  std::string line;
  while (std::getline(in, line)) {
    if (line.empty() || line[0] == '#')
      continue;
    std::istringstream ls(line);
    if (line.rfind("qubits", 0) == 0) {
      std::string word;
      int n = 0;
      ls >> word >> n;
      chip.qubits.assign(n, {});
      continue;
    }
    int a = 0, b = 0;
    ls >> a >> b;
    chip.links.push_back({a, b, 0.01, true});
    chip.links.push_back({b, a, 0.01, true});
  }
  return chip;
}

static bool linked(const std::vector<std::vector<int>> &adj, int a, int b) {
  return std::binary_search(adj[a].begin(), adj[a].end(), b);
}

// Is the set {0..k-1} connected in adj?
static bool prefixConnected(const std::vector<std::vector<int>> &adj, int k) {
  std::vector<char> seen(k, 0);
  std::vector<int> stack{0};
  seen[0] = 1;
  int count = 1;
  while (!stack.empty()) {
    int u = stack.back();
    stack.pop_back();
    for (int v : adj[u])
      if (v < k && !seen[v]) {
        seen[v] = 1;
        ++count;
        stack.push_back(v);
      }
  }
  return count == k;
}

static bool validAssignment(const std::vector<int> &place,
                            const std::vector<std::pair<int, int>> &pairs,
                            const std::vector<std::vector<int>> &adj) {
  std::set<int> distinct(place.begin(), place.end());
  if (distinct.size() != place.size())
    return false;
  for (auto [a, b] : pairs)
    if (!linked(adj, place[a], place[b]))
      return false;
  return true;
}

// ---- 1. Usable region ------------------------------------------------------
static void testRegion() {
  // 0-1-2-3 path, a broken link 3-4 (error 1), 4-5 alone, qubit 6 down.
  Chip chip;
  chip.qubits.assign(7, {});
  chip.qubits[6].operational = false;
  chip.links = {{0, 1, 0.02, true}, {1, 0, 0.03, true}, {1, 2, 0.01, true},
                {2, 3, 0.01, true}, {3, 4, 1.0, true},  {4, 5, 0.01, true},
                {5, 6, 0.01, true}, {2, 6, 0.01, true}};
  Region r = usableRegion(chip);
  CHECK((r.qubits == std::vector<int>{0, 1, 2, 3}),
        "region keeps the largest part, drops broken link and down qubit");
  CHECK(r.adj[4].empty() && r.adj[5].empty() && r.adj[6].empty(),
        "dropped qubits have no links");
  CHECK(r.linkError.at({0, 1}) == 0.03,
        "a link listed in both directions keeps the worse error");
  CHECK(r.linkError.count({4, 5}) == 0, "links outside the region are gone");

  Chip dead;
  dead.qubits.assign(2, {});
  dead.links = {{0, 1, 1.0, true}};
  CHECK(throws([&] { usableRegion(dead); }), "no working link throws");

  Chip notOp;
  notOp.qubits.assign(3, {});
  notOp.links = {{0, 1, 0.01, false}, {1, 2, 0.01, true}};
  CHECK((usableRegion(notOp).qubits == std::vector<int>{1, 2}),
        "a non-operational link is dropped");
}

// ---- 2. Root ---------------------------------------------------------------
static void testRoot() {
  // Path 0-1-2-3. Link errors 0.10, 0.01, 0.01; readout of 2 is bad.
  Chip chip;
  chip.qubits.assign(4, {});
  chip.qubits[2].readoutError = 0.2;
  chip.links = {{0, 1, 0.10, true}, {1, 2, 0.01, true}, {2, 3, 0.01, true}};
  Region r = usableRegion(chip);
  // Scores: q0 0.10, q1 0.055, q2 0.01+0.2, q3 0.01 -> q3.
  CHECK(chooseRoot(r, chip) == 3, "root = lowest mean link error + readout");
  chip.qubits[3].readoutError = 0.05;
  // q3 now 0.06 -> q1 (0.055) wins.
  CHECK(chooseRoot(usableRegion(chip), chip) == 1, "readout error counts");
}

// ---- 3. Breadth-first numbering --------------------------------------------
static void testNumbering(const Chip &fez) {
  Region r = usableRegion(fez);
  CHECK(r.qubits.size() == 156, "all 156 ibm_fez qubits usable");
  bool allPrefixes = true;
  for (int root : {0, 62, 155, 77}) {
    Layout l = breadthFirstLayout(r, root);
    if (l.ibmId.size() != 156 || l.ibmId[0] != root)
      allPrefixes = false;
    for (int k = 1; k <= 156; ++k)
      if (!prefixConnected(l.adj, k))
        allPrefixes = false;
    // Labels are a relabelling: every device link is an IBM link.
    for (std::size_t a = 0; a < l.adj.size(); ++a)
      for (int b : l.adj[a])
        if (!linked(r.adj, l.ibmId[a], l.ibmId[b]))
          allPrefixes = false;
  }
  CHECK(allPrefixes,
        "every prefix 0..k-1 is connected (4 roots, k = 1..156) and links "
        "map back to IBM links");
  CHECK(throws([&] { breadthFirstLayout(r, 999); }), "bad root throws");

  Layout l = breadthFirstLayout(r, 0);
  auto text = deviceFileText(l.adj);
  CHECK(text.rfind("Number of nodes: 156\nNumber of edges: 176\n0 --> {", 0) ==
            0,
        "device file header in IQM's format");
  CHECK(parseDeviceFile(text) == l.adj, "device file round-trips");
  CHECK((parseDeviceFile("Number of nodes: 3\n0 --> {1}\n1 --> {2}\n") ==
         std::vector<std::vector<int>>{{1}, {0, 2}, {1}}),
        "device file listing a link once is made symmetric");
}

// ---- 4. Assignment ---------------------------------------------------------
static void testAssign(const Chip &fez) {
  Region r = usableRegion(fez);
  Layout l = breadthFirstLayout(r, 0);

  // Fits as is: identity.
  std::vector<std::pair<int, int>> chain;
  for (int i = 0; i + 1 < 5; ++i)
    if (linked(l.adj, i, i + 1))
      chain.emplace_back(i, i + 1);
  auto id = assignQubits(5, chain, l.adj);
  CHECK((id == std::vector<int>{0, 1, 2, 3, 4}),
        "a circuit that already fits keeps label = device qubit");

  // Simulate CUDA-Q: the router used device qubits U (sorted, with gaps),
  // regtomem packed them to labels 0..m-1. We must find a valid placement.
  std::mt19937 rng(7);
  int ok = 0, total = 0;
  for (int trial = 0; trial < 300; ++trial) {
    // A connected set U grown from the prefix plus a few extra neighbours.
    int n = 2 + static_cast<int>(rng() % 60);
    std::set<int> u;
    for (int i = 0; i < n; ++i)
      u.insert(i);
    int extra = static_cast<int>(rng() % 4);
    for (int e = 0; e < extra; ++e) {
      std::vector<int> frontier;
      for (int a : u)
        for (int b : l.adj[a])
          if (!u.count(b))
            frontier.push_back(b);
      if (!frontier.empty())
        u.insert(frontier[rng() % frontier.size()]);
    }
    std::vector<int> used(u.begin(), u.end()); // label -> true device qubit
    std::map<int, int> labelOf;
    for (std::size_t i = 0; i < used.size(); ++i)
      labelOf[used[i]] = static_cast<int>(i);
    std::vector<std::pair<int, int>> pairs;
    for (int g = 0; g < 3 * n; ++g) {
      int a = used[rng() % used.size()];
      if (l.adj[a].empty())
        continue;
      int b = l.adj[a][rng() % l.adj[a].size()];
      if (u.count(b))
        pairs.emplace_back(labelOf[a], labelOf[b]);
    }
    ++total;
    auto place = assignQubits(static_cast<int>(used.size()), pairs, l.adj);
    if (validAssignment(place, pairs, l.adj))
      ++ok;
  }
  CHECK(ok == total, "300 packed random circuits on ibm_fez all get a valid "
                     "placement (" +
                         std::to_string(ok) + "/" + std::to_string(total) +
                         ")");

  // Heavy-hex has no triangles, so a 3-qubit cycle cannot fit.
  CHECK(throws([&] { assignQubits(3, {{0, 1}, {1, 2}, {0, 2}}, l.adj); }),
        "a circuit that cannot fit throws");
  CHECK(throws([&] { assignQubits(157, {}, l.adj); }),
        "more labels than chip qubits throws");
  CHECK(throws([&] { assignQubits(2, {{0, 0}}, l.adj); }),
        "a 2-qubit gate on one label throws");
  CHECK(throws([&] {
          assignQubits(3, {{0, 1}, {1, 2}, {0, 2}}, l.adj, /*budget=*/5);
        }),
        "the step budget stops the search");
}

// ---- 5. QASM side ----------------------------------------------------------
static void testQasm() {
  const std::string qasm2 = "OPENQASM 2.0;\n"
                            "include \"qelib1.inc\";\n"
                            "qreg var0[3];\n"
                            "creg c[2];\n"
                            "h var0[0];\n"
                            "cx var0[0], var0[2];\n"
                            "cx var0[2], var0[1];\n"
                            "measure var0[0] -> c[0];\n"
                            "measure var0[1] -> c[1];\n";
  auto in = qasm2Interactions(qasm2);
  CHECK(in.numQubits == 3, "interactions: qreg size");
  CHECK((in.pairs == std::vector<std::pair<int, int>>{{0, 2}, {2, 1}}),
        "interactions: 2-qubit pairs in labels, measurements ignored");

  auto isa = qasm2ToIsaQasm3(qasm2, {7, 9, 8});
  CHECK(isa.qasm3.find("cz $7, $8;") != std::string::npos &&
            isa.qasm3.find("cz $8, $9;") != std::string::npos &&
            isa.qasm3.find("c[1] = measure $9;") != std::string::npos,
        "labels are rewritten to physical qubits");
  CHECK(isa.qasm3.find("$0") == std::string::npos &&
            isa.qasm3.find("$1;") == std::string::npos,
        "no label leaks through unmapped");
  CHECK(throws([&] { qasm2ToIsaQasm3(qasm2, {7, 9}); }),
        "a label without a physical qubit throws");
}

int main() {
  const Chip fez = loadFez();
  testRegion();
  testRoot();
  testNumbering(fez);
  testAssign(fez);
  testQasm();
  if (failures) {
    std::cerr << failures << " check(s) failed\n";
    return 1;
  }
  std::cout << "all layout checks passed\n";
  return 0;
}
