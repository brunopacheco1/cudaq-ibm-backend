// Copyright (c) 2026 Bruno Pacheco.
// Licensed under the Apache License 2.0.

// M3 experiment: how far does the label -> qubit search (Layout.h,
// assignQubits) scale on ibm_fez?
//
// Each case picks a random connected set of device qubits, builds a circuit
// whose 2-qubit gates all sit on links inside that set (a spanning tree plus
// a share of the other links), relabels the qubits 0..m-1 (in device order,
// or shuffled), and asks assignQubits for a placement. A placement always
// exists (the original one). The search either finds one (checked valid) or
// gives up when its step budget runs out, which the plugin reports as a
// clear error.
//
// Result (2026-11-10, 40 cases per cell, budget 10^6 steps), refused cases:
//
//   kind              order      m=100  130  150  156
//   sparse (tree+10%) in order       0    4    0    0
//   sparse (tree+10%) shuffled       0    4    6    7
//   dense  (tree+50%) in order       0    0    0    0
//   dense  (tree+50%) shuffled       0    0    0    0
//
// Worst case about 1.2 s. No wrong placement. Sparse, chain-like circuits are
// what routed circuits look like, so: fine up to about 100 qubits, may be
// refused above that.
//
// Run from the repository root:
//   g++ -O2 -std=c++20 -I plugin experiments/m3_search_stress.cpp -o /tmp/ss
//   /tmp/ss

#include "Layout.h"

#include <chrono>
#include <fstream>
#include <iostream>
#include <random>
#include <set>

using namespace cudaq::ibm;

int main() {
  std::ifstream in("tests/data/ibm_fez_coupling.txt");
  if (!in) {
    std::cerr << "run from the repository root\n";
    return 2;
  }
  std::vector<std::vector<int>> adj(156);
  std::string line;
  while (std::getline(in, line)) {
    if (line.empty() || !isdigit(static_cast<unsigned char>(line[0])))
      continue;
    std::istringstream ls(line);
    int a = 0, b = 0;
    ls >> a >> b;
    adj[a].push_back(b);
    adj[b].push_back(a);
  }
  for (auto &a : adj) {
    std::sort(a.begin(), a.end());
    a.erase(std::unique(a.begin(), a.end()), a.end());
  }

  std::mt19937 rng(7);
  for (int extraPercent : {10, 50})
    for (int shuffle = 0; shuffle < 2; ++shuffle)
      for (int size : {100, 130, 150, 156}) {
        int refused = 0;
        double worst = 0;
        for (int trial = 0; trial < 40; ++trial) {
          // A random connected set of `size` device qubits.
          std::vector<int> set{static_cast<int>(rng() % 156)};
          std::vector<char> inSet(156, 0);
          inSet[set[0]] = 1;
          while (static_cast<int>(set.size()) < size) {
            const int u = set[rng() % set.size()];
            const int v = adj[u][rng() % adj[u].size()];
            if (!inSet[v]) {
              inSet[v] = 1;
              set.push_back(v);
            }
          }
          std::sort(set.begin(), set.end());

          // Labels 0..size-1 for the set, in device order or shuffled.
          std::vector<int> perm(size), label(156, -1);
          std::iota(perm.begin(), perm.end(), 0);
          if (shuffle)
            std::shuffle(perm.begin(), perm.end(), rng);
          for (int i = 0; i < size; ++i)
            label[set[i]] = perm[i];

          // Circuit: a spanning tree of the set plus some other links.
          std::set<std::pair<int, int>> tree;
          std::vector<char> seen(156, 0);
          std::vector<int> stack{set[0]};
          seen[set[0]] = 1;
          while (!stack.empty()) {
            const int u = stack.back();
            stack.pop_back();
            for (int v : adj[u])
              if (inSet[v] && !seen[v]) {
                seen[v] = 1;
                stack.push_back(v);
                tree.insert(std::minmax(u, v));
              }
          }
          std::vector<std::pair<int, int>> pairs;
          for (int u : set)
            for (int v : adj[u])
              if (u < v && inSet[v] &&
                  (tree.count({u, v}) ||
                   static_cast<int>(rng() % 100) < extraPercent))
                pairs.push_back({label[u], label[v]});

          const auto start = std::chrono::steady_clock::now();
          try {
            const auto place = assignQubits(size, pairs, adj);
            for (auto [a, b] : pairs)
              if (!std::binary_search(adj[place[a]].begin(),
                                      adj[place[a]].end(), place[b])) {
                std::cout << "WRONG PLACEMENT\n";
                return 1;
              }
          } catch (const std::exception &) {
            ++refused;
          }
          worst = std::max(worst, std::chrono::duration<double>(
                                      std::chrono::steady_clock::now() - start)
                                      .count());
        }
        std::cout << (extraPercent == 10 ? "sparse" : "dense ") << " "
                  << (shuffle ? "shuffled" : "in order") << " m=" << size
                  << ": refused " << refused << "/40, worst " << worst
                  << " s\n";
      }
  return 0;
}
