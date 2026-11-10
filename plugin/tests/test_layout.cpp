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

#include <cmath>
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

  // IBM lists each link twice; one broken direction breaks the link.
  Chip oneWay;
  oneWay.qubits.assign(3, {});
  oneWay.links = {{0, 1, 0.01, true},
                  {1, 0, 1.0, true},
                  {1, 2, 0.01, true},
                  {2, 1, 0.02, false}};
  CHECK(throws([&] { usableRegion(oneWay); }),
        "a link broken in one direction only is dropped");
  oneWay.links[3].operational = true; // 1-2 now fine both ways
  Region ow = usableRegion(oneWay);
  CHECK((ow.qubits == std::vector<int>{1, 2}) &&
            ow.linkError.at({1, 2}) == 0.02,
        "only the link broken one way is dropped; the other keeps its worse "
        "error");
}

// ---- 1b. Missing data (fail closed) ----------------------------------------
static void testUnknowns() {
  // Path 0-1-2-3, both directions. Link 0-1 known one way, 1-2 known both
  // ways, 2-3 unknown. Qubit 3 has no readout error.
  Chip chip;
  chip.qubits.assign(4, ChipQubit{0.02, true});
  chip.qubits[3].readoutError = UNKNOWN_ERROR;
  chip.links = {{0, 1, 0.03, true},          {1, 0, UNKNOWN_ERROR, true},
                {1, 2, 0.01, true},          {2, 1, 0.02, true},
                {2, 3, UNKNOWN_ERROR, true}, {3, 2, UNKNOWN_ERROR, true}};
  UnknownCount c = closeUnknowns(chip);
  CHECK(c.qubits == 1 && c.links == 1 && c.allLinks == 3,
        "counts 1 qubit and 1 of 3 links without data");
  CHECK(chip.links[1].czError == 0.03 && chip.links[1].operational,
        "a link known one way uses that error both ways");
  CHECK(!chip.links[4].operational && !chip.links[5].operational,
        "a link with no cz error at all is not used");
  CHECK(chip.qubits[3].readoutError == 1.0 && chip.qubits[3].operational,
        "a qubit without readout error gets the worst score but stays");
  Region r = usableRegion(chip);
  CHECK((r.qubits == std::vector<int>{0, 1, 2}),
        "the region leaves out the unknown link");
  CHECK(chooseRoot(r, chip) != 3, "and the root is a qubit we know");

  Chip clean;
  clean.qubits.assign(2, ChipQubit{0.01, true});
  clean.links = {{0, 1, 0.01, true}};
  UnknownCount none = closeUnknowns(clean);
  CHECK(none.qubits == 0 && none.links == 0 && none.allLinks == 1,
        "complete data: nothing changes");
}

// ---- 2. Root and best-first numbering (decision 0012) -----------------------
static bool near(double a, double b) { return std::abs(a - b) < 1e-12; }

// Random error rates on the ibm_fez wiring; same seed, same chip.
static Chip noisyFez(unsigned seed) {
  Chip chip = loadFez();
  std::mt19937 rng(seed);
  std::uniform_real_distribution<double> readout(0.001, 0.12), cz(0.001, 0.03);
  for (auto &q : chip.qubits)
    q.readoutError = readout(rng);
  for (std::size_t i = 0; i + 1 < chip.links.size(); i += 2) // both directions
    chip.links[i].czError = chip.links[i + 1].czError = cz(rng);
  return chip;
}

static void testRoot() {
  // Path 0-1-2-3-4-5, every link 0.01. Qubit 1 is the best single qubit,
  // but it sits between two badly measured ones; 3-4-5 is the good patch.
  Chip chip;
  chip.qubits.assign(6, ChipQubit{0.02, true});
  chip.qubits[0].readoutError = 0.10;
  chip.qubits[1].readoutError = 0.001;
  chip.qubits[2].readoutError = 0.12;
  chip.qubits[4].readoutError = 0.01;
  for (int a = 0; a < 5; ++a)
    chip.links.push_back({a, a + 1, 0.01, true});
  Region r = usableRegion(chip);

  Patch p = growPatch(r, chip, 4, 3);
  CHECK((p.ibmId == std::vector<int>{4, 3, 5}),
        "best-first: equal costs go to the lowest id");
  CHECK(near(p.forecast, 0.99 * (0.98 * 0.99) * (0.98 * 0.99)),
        "forecast = product of (1 - readout) and (1 - cz of the parent link)");
  CHECK((growPatch(r, chip, 1, 6).ibmId == std::vector<int>{1, 0, 2, 3, 4, 5}),
        "best-first from 1: the cheaper neighbour first, the rest in reach");
  CHECK(growPatch(r, chip, 4, 99).ibmId.size() == 6,
        "a limit above the region size gives the whole region");
  CHECK(throws([&] { growPatch(r, chip, 9, 3); }), "bad root throws");

  CHECK(chooseRoot(r, chip, 3) == 4,
        "root = best 3-qubit patch, not the best single qubit");
  // Roots 3, 4 and 5 all grow the patch {3, 4, 5} over the same links:
  CHECK(near(growPatch(r, chip, 3, 3).forecast, p.forecast) &&
            near(growPatch(r, chip, 5, 3).forecast, p.forecast),
        "roots inside one patch give the same forecast");
  // so the tie above went to the lowest readout error (4). Without that:
  chip.qubits[4].readoutError = 0.02;
  CHECK(chooseRoot(usableRegion(chip), chip, 3) == 3,
        "a full tie goes to the lowest id");
  CHECK(chooseRoot(r, chip, 1) == 1, "patch size 1: the best single qubit");

  // A branch: 0 in the middle, arms 1 (good link, bad readout) and 2.
  Chip star;
  star.qubits.assign(4, ChipQubit{0.01, true});
  star.qubits[1].readoutError = 0.05;
  star.links = {{0, 1, 0.001, true}, {0, 2, 0.02, true}, {2, 3, 0.001, true}};
  // Costs from 0: q1 0.051, q2 0.03 -> 2; then q3 0.011 beats q1.
  CHECK((growPatch(usableRegion(star), star, 0, 4).ibmId ==
         std::vector<int>{0, 2, 3, 1}),
        "the cost is readout error + cz error of the best link into the patch");

  // A qubit without readout error (closeUnknowns gives it 1): numbered only
  // when nothing else is in reach, its patch forecasts 0, never the root.
  Chip unknown = star;
  unknown.qubits[2].readoutError = 1.0;
  Region ur = usableRegion(unknown);
  Patch up = growPatch(ur, unknown, 0, 4);
  CHECK((up.ibmId == std::vector<int>{0, 1, 2, 3}) && up.forecast == 0.0,
        "an unknown readout error is numbered late and forecasts 0");
  CHECK(chooseRoot(ur, unknown, 2) == 0, "and is never the root");
}

// ---- 3. Numbering the whole region ------------------------------------------
static void testNumbering(const Chip &fez) {
  Region r = usableRegion(fez);
  CHECK(r.qubits.size() == 156, "all 156 ibm_fez qubits usable");
  bool allPrefixes = true, bestFirst = true;
  for (unsigned seed : {1u, 2u, 3u}) {
    const Chip noisy = noisyFez(seed);
    const Region nr = usableRegion(noisy);
    for (int root : {0, 62, 155, chooseRoot(nr, noisy)}) {
      Layout l = bestFirstLayout(nr, noisy, root);
      std::set<int> distinct(l.ibmId.begin(), l.ibmId.end());
      if (l.ibmId.size() != 156 || distinct.size() != 156 || l.ibmId[0] != root)
        allPrefixes = false;
      for (int k = 1; k <= 156; ++k)
        if (!prefixConnected(l.adj, k))
          allPrefixes = false;
      // Labels are a relabelling: every device link is an IBM link.
      for (std::size_t a = 0; a < l.adj.size(); ++a)
        for (int b : l.adj[a])
          if (!linked(nr.adj, l.ibmId[a], l.ibmId[b]))
            allPrefixes = false;
      // Each label is the cheapest qubit next to the labels before it.
      for (int k = 1; k < 156; ++k) {
        double chosen = 2.0, cheapest = 2.0;
        for (int v = k; v < 156; ++v) {
          double link = 2.0;
          for (int u : l.adj[v])
            if (u < k)
              link = std::min(
                  link, nr.linkError.at(std::minmax(l.ibmId[u], l.ibmId[v])));
          if (link == 2.0)
            continue;
          const double cost = noisy.qubits[l.ibmId[v]].readoutError + link;
          cheapest = std::min(cheapest, cost);
          if (v == k)
            chosen = cost;
        }
        if (chosen != cheapest)
          bestFirst = false;
      }
    }
    // The root's patch is at least as good as any other root's.
    const double top =
        growPatch(nr, noisy, chooseRoot(nr, noisy), ROOT_REGION_SIZE).forecast;
    for (int q : nr.qubits)
      if (growPatch(nr, noisy, q, ROOT_REGION_SIZE).forecast > top + 1e-12)
        bestFirst = false;
  }
  CHECK(allPrefixes,
        "every prefix 0..k-1 is connected (3 noisy chips, 4 roots, k = "
        "1..156), labels are a permutation and links map back to IBM links");
  CHECK(bestFirst, "each label is the cheapest reachable qubit, and no root "
                   "has a better 10-qubit patch than the chosen one");
  CHECK(throws([&] { bestFirstLayout(r, fez, 999); }), "bad root throws");

  Layout l = bestFirstLayout(r, fez, 0);
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
  Layout l = bestFirstLayout(r, fez, 0);

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
  testUnknowns();
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
