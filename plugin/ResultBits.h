/*******************************************************************************
 * Copyright (c) 2026 Bruno Pacheco.                                           *
 *                                                                             *
 * This source code and the accompanying materials are made available under    *
 * the terms of the Apache License 2.0 which accompanies this distribution.    *
 ******************************************************************************/

// Turning IBM's samples into CUDA-Q bit strings (architecture.md §3.5).
//
// IBM returns each shot as a hex number over the classical register: bit i
// is c[i], the i-th measure statement of the circuit we sent.
//
// Which bits CUDA-Q expects (M3, decision 0009): the target pipeline runs
// `combine-measurements` before routing, so the QASM measures EVERY qubit,
// in allocation order: c[i] is the kernel's qubit i. CUDA-Q records which
// qubits the user really measured in `output_names` (one entry per measured
// qubit, with its allocation number). CUDA-Q's result is those qubits,
// sorted by allocation number. So we keep c[q] for each such q, ascending.
// [V] experiments/m3_bit_order.py: 0 mismatches against cudaq.sample.
//
// Pure functions, unit tested in tests/test_result_bits.cpp.

#pragma once

#include <algorithm>
#include <cctype>
#include <cstddef>
#include <stdexcept>
#include <string>
#include <vector>

namespace cudaq::ibm {

/// "0x5" with 4 bits -> "1010": c[0] left-most, as CUDA-Q prints bits.
/// Any width (IBM sends as many hex digits as needed). Throws on bits set
/// beyond numBits or on a character that is not a hex digit.
inline std::string hexToBits(const std::string &hex, std::size_t numBits) {
  std::size_t start = 0;
  if (hex.size() >= 2 && hex[0] == '0' && (hex[1] == 'x' || hex[1] == 'X'))
    start = 2;
  std::string bits(numBits, '0');
  std::size_t bit = 0; // weight of the right-most digit's lowest bit
  for (std::size_t i = hex.size(); i > start; --i, bit += 4) {
    const char ch = static_cast<char>(std::tolower(hex[i - 1]));
    int digit = 0;
    if (ch >= '0' && ch <= '9')
      digit = ch - '0';
    else if (ch >= 'a' && ch <= 'f')
      digit = ch - 'a' + 10;
    else
      throw std::runtime_error("ibm: sample '" + hex + "' is not hex");
    for (int k = 0; k < 4; ++k)
      if (digit & (1 << k)) {
        if (bit + k >= numBits)
          throw std::runtime_error("ibm: sample '" + hex + "' has more than " +
                                   std::to_string(numBits) + " bits");
        bits[bit + k] = '1';
      }
  }
  return bits;
}

/// Number of bits needed to hold every sample (fallback when IBM gives no
/// num_bits). At least 1.
inline std::size_t widestSample(const std::vector<std::string> &samples) {
  std::size_t width = 1;
  for (const auto &hex : samples) {
    std::size_t start =
        (hex.size() >= 2 && hex[0] == '0' && (hex[1] == 'x' || hex[1] == 'X'))
            ? 2
            : 0;
    while (start < hex.size() && hex[start] == '0')
      ++start;
    if (start == hex.size())
      continue;
    const char ch = static_cast<char>(std::tolower(hex[start]));
    const int lead = (ch >= 'a' && ch <= 'f') ? ch - 'a' + 10 : ch - '0';
    std::size_t top = 0;
    while (lead >> top)
      ++top;
    width = std::max(width, 4 * (hex.size() - start - 1) + top);
  }
  return width;
}

/// Which classical bits to keep: the measured qubits' allocation numbers,
/// sorted, each once. Empty `qubitNums` (no output_names) keeps every bit.
/// Throws if a number is outside the register: the circuit was not compiled
/// the way this file assumes, and guessing would return wrong counts.
inline std::vector<std::size_t> keptBits(std::vector<std::size_t> qubitNums,
                                         std::size_t numBits) {
  if (qubitNums.empty()) {
    std::vector<std::size_t> all(numBits);
    for (std::size_t i = 0; i < numBits; ++i)
      all[i] = i;
    return all;
  }
  std::sort(qubitNums.begin(), qubitNums.end());
  qubitNums.erase(std::unique(qubitNums.begin(), qubitNums.end()),
                  qubitNums.end());
  if (qubitNums.back() >= numBits)
    throw std::runtime_error(
        "ibm: CUDA-Q says qubit " + std::to_string(qubitNums.back()) +
        " was measured, but the circuit has only " + std::to_string(numBits) +
        " classical bits. Was the kernel compiled with the 'ibm' target's "
        "pipeline?");
  return qubitNums;
}

/// The bits at `keep`, in that order.
inline std::string pickBits(const std::string &bits,
                            const std::vector<std::size_t> &keep) {
  std::string out;
  out.reserve(keep.size());
  for (std::size_t i : keep)
    out += bits.at(i);
  return out;
}

} // namespace cudaq::ibm
