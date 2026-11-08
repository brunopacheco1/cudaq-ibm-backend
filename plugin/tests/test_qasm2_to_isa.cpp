/*******************************************************************************
 * Copyright (c) 2026 Bruno Pacheco.                                           *
 *                                                                             *
 * This source code and the accompanying materials are made available under    *
 * the terms of the Apache License 2.0 which accompanies this distribution.    *
 ******************************************************************************/

// Unit tests for Qasm2ToIsa.h. No CUDA-Q, no network, no Qiskit:
//
//   g++ -std=c++20 -I plugin plugin/tests/test_qasm2_to_isa.cpp -o /tmp/t &&
//   /tmp/t
//
// The key test PROVES each rewrite rule numerically: it builds the full
// unitary matrix of the input circuit (textbook gates) and of the output
// circuit (IBM native gates) and checks they are equal up to a global phase.
// To add a rule (z, y, rx, ry, u3): add its textbook matrix in
// textbookGate() below, add a case to kRuleCases, then implement the rule.

#include "Qasm2ToIsa.h"

#include <cmath>
#include <complex>
#include <iostream>
#include <regex>

using cplx = std::complex<double>;
using Mat = std::vector<std::vector<cplx>>;
using cudaq::ibm::PI;

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

// ---- Tiny unitary simulator ------------------------------------------------
// Qubit k is bit k of the basis-state index.

static Mat identity(int n) {
  int d = 1 << n;
  Mat m(d, std::vector<cplx>(d, 0));
  for (int i = 0; i < d; ++i)
    m[i][i] = 1;
  return m;
}

// Apply a 1-qubit gate g (2x2) on qubit k: U <- G_k . U
static void apply1(Mat &u, const Mat &g, int k) {
  int d = u.size();
  for (int col = 0; col < d; ++col)
    for (int i = 0; i < d; ++i) {
      if (i & (1 << k))
        continue;
      int j = i | (1 << k);
      cplx a = u[i][col], b = u[j][col];
      u[i][col] = g[0][0] * a + g[0][1] * b;
      u[j][col] = g[1][0] * a + g[1][1] * b;
    }
}

// Controlled-G with control c, target t.
static void applyControlled(Mat &u, const Mat &g, int c, int t) {
  int d = u.size();
  for (int col = 0; col < d; ++col)
    for (int i = 0; i < d; ++i) {
      if (!(i & (1 << c)) || (i & (1 << t)))
        continue;
      int j = i | (1 << t);
      cplx a = u[i][col], b = u[j][col];
      u[i][col] = g[0][0] * a + g[0][1] * b;
      u[j][col] = g[1][0] * a + g[1][1] * b;
    }
}

static bool equalUpToPhase(const Mat &a, const Mat &b) {
  // Find the phase from the largest entry, then compare everything.
  cplx phase = 0;
  for (size_t i = 0; i < a.size() && phase == cplx(0); ++i)
    for (size_t j = 0; j < a.size(); ++j)
      if (std::abs(a[i][j]) > 1e-6) {
        phase = b[i][j] / a[i][j];
        break;
      }
  if (std::abs(std::abs(phase) - 1) > 1e-9)
    return false;
  for (size_t i = 0; i < a.size(); ++i)
    for (size_t j = 0; j < a.size(); ++j)
      if (std::abs(a[i][j] * phase - b[i][j]) > 1e-9)
        return false;
  return true;
}

// ---- Gate matrices ----------------------------------------------------------
static const cplx I1(0, 1);

static Mat rzM(double t) {
  return {{std::exp(-I1 * t / 2.0), 0}, {0, std::exp(I1 * t / 2.0)}};
}
static Mat sxM() {
  return {{cplx(0.5, 0.5), cplx(0.5, -0.5)}, {cplx(0.5, -0.5), cplx(0.5, 0.5)}};
}
static Mat xM() { return {{0, 1}, {1, 0}}; }
static Mat zM() { return {{1, 0}, {0, -1}}; }

// Textbook definitions of the gates CUDA-Q emits (OpenQASM 2 / qelib1.inc).
static bool textbookGate(const std::string &name, const std::vector<double> &p,
                         Mat &g) {
  const double r = 1 / std::sqrt(2.0);
  if (name == "h")
    g = {{r, r}, {r, -r}};
  else if (name == "x")
    g = xM();
  else if (name == "y")
    g = {{0, -I1}, {I1, 0}};
  else if (name == "z")
    g = zM();
  else if (name == "rz")
    g = rzM(p.at(0));
  else if (name == "rx")
    g = {{std::cos(p.at(0) / 2), -I1 * std::sin(p.at(0) / 2)},
         {-I1 * std::sin(p.at(0) / 2), std::cos(p.at(0) / 2)}};
  else if (name == "ry")
    g = {{std::cos(p.at(0) / 2), -std::sin(p.at(0) / 2)},
         {std::sin(p.at(0) / 2), std::cos(p.at(0) / 2)}};
  else
    return false;
  return true;
}

// ---- Circuit -> unitary
// ------------------------------------------------------
static std::vector<double> parseArgs(const std::string &s) {
  std::vector<double> v;
  std::stringstream ss(s);
  std::string a;
  while (std::getline(ss, a, ','))
    v.push_back(std::stod(a));
  return v;
}

// Input side: OpenQASM 2 with textbook gates (measurements ignored).
static Mat unitaryOfQasm2(const std::string &q2, int n) {
  static const std::regex g(R"(^\s*([a-z0-9]+)(?:\(([^)]*)\))?\s+([^;]*);)");
  static const std::regex op(R"(\[(\d+)\])");
  Mat u = identity(n);
  std::istringstream in(q2);
  std::string line;
  while (std::getline(in, line)) {
    std::smatch m;
    if (!std::regex_search(line, m, g))
      continue;
    std::string name = m[1];
    if (name == "qreg" || name == "creg" || name == "measure" ||
        name == "include")
      continue;
    std::vector<int> qs;
    std::string ops = m[3];
    for (std::sregex_iterator it(ops.begin(), ops.end(), op), e; it != e; ++it)
      qs.push_back(std::stoi((*it)[1]));
    Mat gm;
    if (name == "cx")
      applyControlled(u, xM(), qs[0], qs[1]);
    else if (name == "cz")
      applyControlled(u, zM(), qs[0], qs[1]);
    else if (textbookGate(name, parseArgs(m[2]), gm))
      apply1(u, gm, qs[0]);
    else
      throw std::runtime_error("test: no textbook matrix for " + name);
  }
  return u;
}

// Output side: OpenQASM 3 that may contain ONLY rz, sx, x, cz, measure.
static Mat unitaryOfIsa(const std::string &q3, int n, bool &onlyNative) {
  static const std::regex g(R"(^([a-z]+)(?:\(([^)]*)\))?\s+([^;]*);$)");
  static const std::regex op(R"(\$(\d+))");
  Mat u = identity(n);
  onlyNative = true;
  std::istringstream in(q3);
  std::string line;
  while (std::getline(in, line)) {
    if (line.rfind("OPENQASM", 0) == 0 || line.rfind("include", 0) == 0 ||
        line.rfind("bit[", 0) == 0 ||
        line.find("= measure") != std::string::npos)
      continue;
    std::smatch m;
    if (!std::regex_match(line, m, g)) {
      onlyNative = false;
      continue;
    }
    std::vector<int> qs;
    std::string ops = m[3];
    for (std::sregex_iterator it(ops.begin(), ops.end(), op), e; it != e; ++it)
      qs.push_back(std::stoi((*it)[1]));
    std::string name = m[1];
    if (name == "rz")
      apply1(u, rzM(parseArgs(m[2]).at(0)), qs[0]);
    else if (name == "sx")
      apply1(u, sxM(), qs[0]);
    else if (name == "x")
      apply1(u, xM(), qs[0]);
    else if (name == "cz")
      applyControlled(u, zM(), qs[0], qs[1]);
    else
      onlyNative = false;
  }
  return u;
}

static std::string wrap(int n, const std::string &body) {
  // Same shape as CUDA-Q's OpenQASM 2 output.
  std::string s =
      "// Code generated by NVIDIA's nvq++ compiler\nOPENQASM 2.0;\n\n"
      "include \"qelib1.inc\";\n\nqreg var0[" +
      std::to_string(n) + "];\n" + body;
  for (int k = 0; k < n; ++k)
    s += "creg var" + std::to_string(k + 4) + "[1];\nmeasure var0[" +
         std::to_string(k) + "] -> var" + std::to_string(k + 4) + "[0];\n";
  return s;
}

static void proveEquivalent(const std::string &label, int n,
                            const std::string &body) {
  std::string q2 = wrap(n, body);
  auto isa = cudaq::ibm::qasm2ToIsaQasm3(q2);
  bool onlyNative = false;
  Mat out = unitaryOfIsa(isa.qasm3, n, onlyNative);
  CHECK(onlyNative, label + ": output uses only rz, sx, x, cz");
  CHECK(equalUpToPhase(unitaryOfQasm2(q2, n), out),
        label + ": same unitary as input (up to global phase)");
}

// One entry per rewrite rule. Add z, y, rx, ry, u3 here when you write them.
static const std::vector<std::tuple<std::string, int, std::string>> kRuleCases =
    {
        {"x", 1, "x var0[0];\n"},
        {"rz", 1, "rz(7.000000e-01) var0[0];\n"},
        {"h", 1, "h var0[0];\n"},
        {"cx 0->1", 2, "cx var0[0], var0[1];\n"},
        {"cx 1->0", 2, "cx var0[1], var0[0];\n"},
};

int main() {
  // 1. Every rule, proven numerically.
  for (auto &[label, n, body] : kRuleCases)
    proveEquivalent(label, n, body);

  // 2. A real Bell circuit, exactly as CUDA-Q 0.16 prints it.
  proveEquivalent("bell (CUDA-Q output)", 2,
                  "h var0[0];\ncx var0[0], var0[1];\n");

  // 3. Output shape IBM expects.
  auto bell = cudaq::ibm::qasm2ToIsaQasm3(
      wrap(2, "h var0[0];\ncx var0[0], var0[1];\n"));
  CHECK(bell.numQubits == 2 && bell.numClbits == 2, "bell: 2 qubits, 2 bits");
  CHECK(bell.qasm3.rfind(
            "OPENQASM 3.0;\ninclude \"stdgates.inc\";\nbit[2] c;\n", 0) == 0,
        "bell: QASM3 header and one 2-bit register 'c'");
  CHECK(bell.qasm3.find("c[1] = measure $1;") != std::string::npos,
        "bell: measurement of qubit 1 into c[1]");

  // 4. Gates without a rule must be refused, never sent.
  bool threw = false;
  try {
    cudaq::ibm::qasm2ToIsaQasm3(wrap(1, "y var0[0];\n"));
  } catch (const std::runtime_error &e) {
    threw =
        std::string(e.what()).find("unsupported gate 'y'") != std::string::npos;
  }
  CHECK(threw, "unsupported gate 'y' is refused");

  std::cout << (failures ? "\nFAILED: " : "\nALL PASSED")
            << (failures ? std::to_string(failures) : "") << "\n";
  return failures ? 1 : 0;
}
