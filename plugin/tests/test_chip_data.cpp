/*******************************************************************************
 * Copyright (c) 2026 Bruno Pacheco.                                           *
 *                                                                             *
 * This source code and the accompanying materials are made available under    *
 * the terms of the Apache License 2.0 which accompanies this distribution.    *
 ******************************************************************************/

// Unit tests for ChipData.h (IBM JSON -> Chip, fail-closed rules). No CUDA-Q,
// no network; needs nlohmann/json (Ubuntu: apt install nlohmann-json3-dev):
//
//   g++ -std=c++20 -I plugin plugin/tests/test_chip_data.cpp -o /tmp/tc &&
//   /tmp/tc
//
// With an argument it reads the two replies from files instead (to try the
// parser on real IBM data): /tmp/tc configuration.json properties.json

#include "ChipData.h"

#include <fstream>
#include <iostream>

using namespace cudaq::ibm;
using nlohmann::json;

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

// Path 0-1-2-3-4, both directions, as IBM lists it.
static json config() {
  return json::parse(R"({"n_qubits": 5, "coupling_map":
      [[0,1],[1,0],[1,2],[2,1],[2,3],[3,2],[3,4],[4,3]]})");
}

static json qubitEntry(double readout) {
  return json::array({{{"name", "T1"}, {"value", 100.0}},
                      {{"name", "readout_error"}, {"value", readout}}});
}

static json oneQubitEntry(const char *gate, int q, json error) {
  return {{"gate", gate},
          {"qubits", {q}},
          {"parameters",
           json::array({{{"name", "gate_error"}, {"value", std::move(error)}},
                        {{"name", "gate_length"}, {"value", 24.0}}})}};
}

static json czEntry(int a, int b, json error) {
  return {{"gate", "cz"},
          {"qubits", {a, b}},
          {"parameters", json::array({{{"name", "gate_error"},
                                       {"value", std::move(error)}}})}};
}

// Complete, healthy properties for the path.
static json props() {
  json p = {{"qubits", json::array()}, {"gates", json::array()}};
  for (int q = 0; q < 5; ++q)
    p["qubits"].push_back(qubitEntry(0.02));
  for (int a = 0; a < 4; ++a) {
    p["gates"].push_back(czEntry(a, a + 1, 0.01));
    p["gates"].push_back(czEntry(a + 1, a, 0.01));
  }
  // Other gates are ignored.
  p["gates"].push_back({{"gate", "sx"}, {"qubits", {0}}});
  return p;
}

static int tryRealData(const char *configPath, const char *propsPath) {
  std::ifstream c(configPath), p(propsPath);
  if (!c || !p) {
    std::cerr << "cannot open the two files\n";
    return 2;
  }
  ChipDataReport report;
  const Chip chip =
      chipFromIbmJson(json::parse(c), json::parse(p), "file", report);
  const Region region = usableRegion(chip);
  std::cout << chip.qubits.size() << " qubits, " << report.unknown.allLinks
            << " links; usable region " << region.qubits.size()
            << " qubits; root " << chooseRoot(region, chip) << "\n"
            << "unreadable entries " << report.unreadable
            << ", links without cz error " << report.unknown.links
            << ", qubits without readout error " << report.unknown.qubits
            << ", qubits with sx or x error 1 " << report.staleQubits << "\n";
  return 0;
}

int main(int argc, char **argv) {
  if (argc == 3)
    return tryRealData(argv[1], argv[2]);

  // ---- Healthy data --------------------------------------------------------
  {
    ChipDataReport r;
    Chip chip = chipFromIbmJson(config(), props(), "t", r);
    CHECK(r.clean() && chip.qubits.size() == 5 && chip.links.size() == 8,
          "complete data: 5 qubits, 8 link entries, nothing to report");
    CHECK(chip.links[0].czError == 0.01 && chip.qubits[0].readoutError == 0.02,
          "error rates are read");
    CHECK(usableRegion(chip).qubits.size() == 5, "the whole path is usable");
  }

  // ---- Broken parts, as IBM marks them --------------------------------------
  {
    json p = props();
    p["gates"][0] = czEntry(0, 1, 1.0);                                // 0-1
    p["qubits"][4].push_back({{"name", "operational"}, {"value", 0}}); // q4
    ChipDataReport r;
    Chip chip = chipFromIbmJson(config(), p, "t", r);
    CHECK(r.clean(), "broken parts are data, not unreadable entries");
    CHECK((usableRegion(chip).qubits == std::vector<int>{1, 2, 3}),
          "gate_error 1 and operational 0 are left out of the region");
    p["qubits"][4].back()["value"] = false;
    ChipDataReport r2;
    CHECK(!chipFromIbmJson(config(), p, "t", r2).qubits[4].operational,
          "operational given as a boolean works too");
  }

  // ---- 1-qubit gates whose benchmark went stale (IBM reports error 1) -------
  {
    json p = props();
    for (int q = 0; q < 5; ++q) {
      p["gates"].push_back(oneQubitEntry("sx", q, 0.0003));
      p["gates"].push_back(oneQubitEntry("x", q, 0.0003));
      p["gates"].push_back(oneQubitEntry("rx", q, 1.0)); // not in the ISA set
    }
    ChipDataReport r;
    Chip chip = chipFromIbmJson(config(), p, "t", r);
    CHECK(r.clean() && r.staleQubits == 0 &&
              usableRegion(chip).qubits.size() == 5,
          "healthy sx and x errors change nothing; other gates are ignored");

    p["gates"].push_back(oneQubitEntry("sx", 0, 1));  // 1 as an integer
    p["gates"].push_back(oneQubitEntry("x", 0, 1.0)); // same qubit again
    p["gates"].push_back(oneQubitEntry("x", 4, 1.0));
    ChipDataReport r2;
    Chip stale = chipFromIbmJson(config(), p, "t", r2);
    CHECK(r2.clean() && r2.staleQubits == 2,
          "sx or x error 1 is data, counted once per qubit");
    CHECK((usableRegion(stale).qubits == std::vector<int>{1, 2, 3}),
          "and those qubits are left out of the region");

    json bad = props();
    bad["gates"].push_back(oneQubitEntry("sx", 2, nullptr));
    ChipDataReport r3;
    Chip unread = chipFromIbmJson(config(), bad, "t", r3);
    CHECK(r3.unreadable == 1 && !unread.qubits[2].operational,
          "an unreadable sx error makes the qubit broken");

    json far = props();
    far["gates"].push_back(oneQubitEntry("sx", 99, 1.0)); // not on the chip
    ChipDataReport r4;
    CHECK(usableRegion(chipFromIbmJson(config(), far, "t", r4)).qubits.size() ==
                  5 &&
              r4.staleQubits == 0,
          "an sx entry for a qubit outside the chip is ignored");
  }

  // ---- Fail closed on what we cannot read
  // ------------------------------------
  {
    json p = props();
    p["gates"][0] = czEntry(0, 1, nullptr); // gate_error null, one direction
    ChipDataReport r;
    Chip chip = chipFromIbmJson(config(), p, "t", r);
    CHECK(r.unreadable == 1, "an unreadable gate_error is counted");
    CHECK((usableRegion(chip).qubits == std::vector<int>{1, 2, 3, 4}),
          "and its link is not used, though the other direction is fine");
  }
  {
    json p = props();
    p["qubits"][2].push_back({{"name", "operational"}, {"value", "maybe"}});
    ChipDataReport r;
    Chip chip = chipFromIbmJson(config(), p, "t", r);
    CHECK(r.unreadable == 1 && !chip.qubits[2].operational,
          "an unreadable operational flag makes the qubit broken");
  }
  {
    json p = props();
    json oneWay = json::array(); // keep only cz(a, b) with a < b
    for (const auto &g : p["gates"])
      if (g["gate"] != "cz" || g["qubits"][0].get<int>() < g["qubits"][1])
        oneWay.push_back(g);
    p["gates"] = oneWay;
    ChipDataReport r;
    Chip chip = chipFromIbmJson(config(), p, "t", r);
    CHECK(r.clean() && usableRegion(chip).qubits.size() == 5,
          "a link listed in one direction only is fine");
  }
  {
    json p = props();
    p["gates"].erase(0);
    p["gates"].erase(0); // no data at all for 0-1
    p["qubits"][3] = json::array({{{"name", "T1"}, {"value", 90.0}}});
    ChipDataReport r;
    Chip chip = chipFromIbmJson(config(), p, "t", r);
    CHECK(r.unknown.links == 1 && r.unknown.qubits == 1,
          "a link and a qubit without error rates are reported");
    Region region = usableRegion(chip);
    CHECK((region.qubits == std::vector<int>{1, 2, 3, 4}),
          "a link with no cz error is not used");
    CHECK(chooseRoot(region, chip) != 3,
          "a qubit with no readout error is never the root");
  }
  {
    json p = props();
    p["gates"][0]["qubits"] = "zero and one"; // which link? unknown
    ChipDataReport r;
    chipFromIbmJson(config(), p, "t", r);
    CHECK(r.unreadable == 1, "a gate entry without readable qubits is counted");
  }

  // ---- Format changes are errors
  // ---------------------------------------------
  {
    ChipDataReport r;
    json p = props();
    p.erase("gates");
    CHECK(throws([&] { chipFromIbmJson(config(), p, "t", r); }),
          "properties without 'gates' throw");
    p = props();
    p["qubits"] = 7;
    CHECK(throws([&] { chipFromIbmJson(config(), p, "t", r); }),
          "properties whose 'qubits' is not a list throw");
    p = props();
    for (auto &g : p["gates"])
      if (g["gate"] == "cz")
        g["gate"] = "ecr";
    CHECK(throws([&] { chipFromIbmJson(config(), p, "t", r); }),
          "no cz error for any link throws (not a cz backend)");
    json c = config();
    c.erase("coupling_map");
    CHECK(throws([&] { chipFromIbmJson(c, props(), "t", r); }),
          "configuration without coupling_map throws");
  }

  if (failures) {
    std::cerr << failures << " check(s) failed\n";
    return 1;
  }
  std::cout << "all chip-data checks passed\n";
  return 0;
}
