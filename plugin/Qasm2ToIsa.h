/*******************************************************************************
 * Copyright (c) 2026 Bruno Pacheco.                                           *
 *                                                                             *
 * This source code and the accompanying materials are made available under    *
 * the terms of the Apache License 2.0 which accompanies this distribution.    *
 ******************************************************************************/

// Milestone M2: turn the OpenQASM 2 that CUDA-Q emits into an IBM "ISA"
// circuit: OpenQASM 3 that uses only the chip's native gates {rz, sx, x, cz}
// on physical qubits ($0, $1, ...).
//
// This is a pure function (text in, text out, no I/O) so it can be unit
// tested without CUDA-Q or a network. See tests/test_qasm2_to_isa.cpp.
//
// The REWRITE RULES section is the quantum heart of this file. Each rule must
// be proven equal (up to global phase) to the gate it replaces; the unit test
// checks that numerically.

#pragma once

#include <cstdio>
#include <functional>
#include <map>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace cudaq::ibm {

/// Output being built: OpenQASM 3 body lines in IBM's native gates.
class IsaBuilder {
  std::vector<std::string> lines;

  static std::string q(int k) { return "$" + std::to_string(k); }
  static std::string num(double v) {
    char buf[32];
    std::snprintf(buf, sizeof buf, "%.17g", v);
    return buf;
  }

public:
  // The four native gates. Nothing else may be emitted.
  void rz(double theta, int a) {
    lines.push_back("rz(" + num(theta) + ") " + q(a) + ";");
  }
  void sx(int a) { lines.push_back("sx " + q(a) + ";"); }
  void x(int a) { lines.push_back("x " + q(a) + ";"); }
  void cz(int a, int b) { lines.push_back("cz " + q(a) + ", " + q(b) + ";"); }
  void measure(int a, int bit) {
    lines.push_back("c[" + std::to_string(bit) + "] = measure " + q(a) + ";");
  }
  const std::vector<std::string> &body() const { return lines; }
};

// ============================================================================
// REWRITE RULES: textbook gate -> IBM native gates {rz, sx, x, cz}.
// All equalities hold up to a global phase, which no measurement can see.
// ============================================================================
constexpr double PI = 3.14159265358979323846;

// h = rz(pi/2) . sx . rz(pi/2)                          [proven 2026-11-08]
inline void ruleH(IsaBuilder &o, int a) {
  o.rz(PI / 2, a);
  o.sx(a);
  o.rz(PI / 2, a);
}

// cx(c, t) = h(t) . cz(c, t) . h(t)   ("H turns Z into X")  [proven 2026-11-08]
inline void ruleCX(IsaBuilder &o, int c, int t) {
  ruleH(o, t);
  o.cz(c, t);
  ruleH(o, t);
}

// Rules below derived by Bruno on 2026-11-09, checked with Qiskit
// Operator.equiv and proven again in the unit test. Gates are listed in
// circuit order (first line = first gate applied).

// z = rz(pi)                                             [proven 2026-11-09]
inline void ruleZ(IsaBuilder &o, int a) { o.rz(PI, a); }

// rx(t) = rz(pi/2) . sx . rz(t+pi) . sx . rz(pi/2)       [proven 2026-11-09]
// Two quarter turns around X (sx) with a Z turn in between make any X turn.
inline void ruleRX(IsaBuilder &o, double t, int a) {
  o.rz(PI / 2, a);
  o.sx(a);
  o.rz(t + PI, a);
  o.sx(a);
  o.rz(PI / 2, a);
}

// ry(t) = sx . rz(t+pi) . sx . rz(pi)                    [proven 2026-11-09]
// From ry(t) = rz(-pi/2) . rx(t) . rz(pi/2) ("turn Y onto X, rotate, turn
// back"), then substitute the rx rule and merge neighbouring rz gates:
// rz(-pi/2) rz(pi/2) = nothing, rz(pi/2) rz(pi/2) = rz(pi).
inline void ruleRY(IsaBuilder &o, double t, int a) {
  o.sx(a);
  o.rz(t + PI, a);
  o.sx(a);
  o.rz(PI, a);
}

// y = rz(pi) . x                                          [proven 2026-11-09]
// y is ry(pi) up to phase: sx rz(2pi) sx rz(pi) = sx sx rz(pi) = x rz(pi),
// and x and rz(pi) give the same gate in either order (up to phase).
inline void ruleY(IsaBuilder &o, int a) {
  o.rz(PI, a);
  o.x(a);
}

// u3(t, p, l) = rz(l) . sx . rz(t+pi) . sx . rz(p+pi)     [proven 2026-11-09]
// u3 = rz(l) . ry(t) . rz(p) in circuit order; substitute the ry rule and
// merge rz(pi) . rz(p) = rz(p+pi). This "ZSX" form covers every 1-qubit gate.
inline void ruleU3(IsaBuilder &o, double t, double p, double l, int a) {
  o.rz(l, a);
  o.sx(a);
  o.rz(t + PI, a);
  o.sx(a);
  o.rz(p + PI, a);
}

// Any gate without a rule makes the converter throw "unsupported gate", so we
// never send a wrong circuit to hardware.

// ============================================================================
// Parser: CUDA-Q's OpenQASM 2 output (see tests for real examples).
// ============================================================================

/// Result of a conversion.
struct IsaCircuit {
  std::string qasm3; // the program to send to IBM
  int numQubits = 0; // size of the qreg CUDA-Q declared
  int numClbits = 0; // one per measurement, in program order
};

inline IsaCircuit qasm2ToIsaQasm3(const std::string &qasm2) {
  // "name(args) operands;"  e.g. "rz(1.5e+00) var0[1];"  "cx var0[0], var0[1];"
  static const std::regex gateRe(
      R"(^\s*([a-z][a-z0-9_]*)\s*(?:\(([^)]*)\))?\s+([^;]*);\s*$)");
  static const std::regex operandRe(R"(([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\])");
  static const std::regex qregRe(
      R"(^\s*qreg\s+([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\];)");
  static const std::regex measureRe(
      R"(^\s*measure\s+([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]\s*->)");

  IsaBuilder out;
  IsaCircuit result;
  std::string qregName;

  auto qubit = [&](const std::string &reg, int idx) {
    if (reg != qregName)
      throw std::runtime_error("ibm: unknown quantum register '" + reg + "'");
    return idx; // M2: virtual qubit k runs on physical qubit k (M3 maps)
  };

  std::istringstream in(qasm2);
  std::string line;
  while (std::getline(in, line)) {
    // Skip comments, blank lines and headers.
    auto first = line.find_first_not_of(" \t\r");
    if (first == std::string::npos || line.compare(first, 2, "//") == 0 ||
        line.compare(first, 8, "OPENQASM") == 0 ||
        line.compare(first, 7, "include") == 0 ||
        line.compare(first, 4, "creg") == 0 ||
        line.compare(first, 7, "barrier") == 0)
      continue;

    std::smatch m;
    if (std::regex_search(line, m, qregRe)) {
      if (!qregName.empty())
        throw std::runtime_error("ibm: more than one qreg is not supported");
      qregName = m[1];
      result.numQubits = std::stoi(m[2]);
      continue;
    }
    if (std::regex_search(line, m, measureRe)) {
      out.measure(qubit(m[1], std::stoi(m[2])), result.numClbits++);
      continue;
    }
    if (!std::regex_match(line, m, gateRe))
      throw std::runtime_error("ibm: cannot parse QASM line: " + line);

    const std::string name = m[1];
    std::vector<double> args;
    {
      std::stringstream as(m[2].str());
      std::string a;
      while (std::getline(as, a, ','))
        args.push_back(std::stod(a));
    }
    std::vector<int> qs;
    {
      const std::string ops = m[3];
      for (std::sregex_iterator it(ops.begin(), ops.end(), operandRe), end;
           it != end; ++it)
        qs.push_back(qubit((*it)[1], std::stoi((*it)[2])));
    }
    auto expect = [&](std::size_t nq, std::size_t na) {
      if (qs.size() != nq || args.size() != na)
        throw std::runtime_error("ibm: wrong operands for '" + name +
                                 "' in: " + line);
    };

    // ---- Dispatch: one entry per gate CUDA-Q can emit ----------------------
    if (name == "x") {
      expect(1, 0);
      out.x(qs[0]); // native
    } else if (name == "rz") {
      expect(1, 1);
      out.rz(args[0], qs[0]); // native
    } else if (name == "h") {
      expect(1, 0);
      ruleH(out, qs[0]);
    } else if (name == "z") {
      expect(1, 0);
      ruleZ(out, qs[0]);
    } else if (name == "y") {
      expect(1, 0);
      ruleY(out, qs[0]);
    } else if (name == "rx") {
      expect(1, 1);
      ruleRX(out, args[0], qs[0]);
    } else if (name == "ry") {
      expect(1, 1);
      ruleRY(out, args[0], qs[0]);
    } else if (name == "u3") {
      expect(1, 3);
      ruleU3(out, args[0], args[1], args[2], qs[0]);
    } else if (name == "cx") {
      expect(2, 0);
      ruleCX(out, qs[0], qs[1]);
    } else {
      throw std::runtime_error("ibm: unsupported gate '" + name +
                               "' (no rewrite rule yet) in: " + line);
    }
  }

  if (qregName.empty())
    throw std::runtime_error("ibm: no qreg found in the QASM from CUDA-Q");
  if (result.numClbits == 0)
    throw std::runtime_error("ibm: circuit has no measurements");

  std::string s = "OPENQASM 3.0;\ninclude \"stdgates.inc\";\n";
  s += "bit[" + std::to_string(result.numClbits) + "] c;\n";
  for (const auto &l : out.body())
    s += l + "\n";
  result.qasm3 = s;
  return result;
}

} // namespace cudaq::ibm
