/*******************************************************************************
 * Copyright (c) 2026 Bruno Pacheco.                                           *
 *                                                                             *
 * This source code and the accompanying materials are made available under    *
 * the terms of the Apache License 2.0 which accompanies this distribution.    *
 ******************************************************************************/

// Unit tests for ResultBits.h. No CUDA-Q, no network:
//
//   g++ -std=c++20 -I plugin plugin/tests/test_result_bits.cpp -o /tmp/tr &&
//   /tmp/tr

#include "ResultBits.h"

#include <iostream>

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

int main() {
  // ---- hex -> bits ---------------------------------------------------------
  CHECK(hexToBits("0x1", 2) == "10", "c[0] is the left-most bit");
  CHECK(hexToBits("0x5", 4) == "1010", "0x5 = c[0] and c[2]");
  CHECK(hexToBits("0x0", 3) == "000", "zero");
  CHECK(hexToBits("0xA", 4) == hexToBits("0xa", 4), "upper and lower case");
  CHECK(hexToBits("0x8000000000000000000000001", 100) ==
            "1" + std::string(98, '0') + "1",
        "more than 64 bits (100-qubit GHZ)");
  CHECK(throws([] { hexToBits("0x4", 2); }), "a bit beyond num_bits throws");
  CHECK(throws([] { hexToBits("0xg", 4); }), "not hex throws");

  CHECK(widestSample({"0x0"}) == 1, "widest: all zero -> 1");
  CHECK(widestSample({"0x1", "0x5"}) == 3, "widest: 0x5 -> 3 bits");
  CHECK(widestSample({"0x10"}) == 5, "widest: 0x10 -> 5 bits");

  // ---- which bits to keep --------------------------------------------------
  CHECK((keptBits({}, 3) == std::vector<std::size_t>{0, 1, 2}),
        "no output_names keeps every bit");
  CHECK((keptBits({3, 0, 2}, 5) == std::vector<std::size_t>{0, 2, 3}),
        "measured qubits in allocation order, whatever the mz order");
  CHECK((keptBits({1, 1}, 2) == std::vector<std::size_t>{1}),
        "a qubit listed twice is kept once");
  CHECK(throws([] { keptBits({0, 3}, 3); }),
        "a measured qubit outside the register throws");

  // mz(q[2]); mz(q[0]) on 3 qubits: the circuit measures q0 q1 q2 into
  // c0 c1 c2; CUDA-Q expects q0 then q2.
  CHECK(pickBits(hexToBits("0x4", 3), keptBits({2, 0}, 3)) == "01",
        "shuffled mz: q2=1, q0=0 -> \"01\"");
  CHECK(pickBits("101", keptBits({}, 3)) == "101", "pick all");

  if (failures) {
    std::cerr << failures << " check(s) failed\n";
    return 1;
  }
  std::cout << "all result-bit checks passed\n";
  return 0;
}
