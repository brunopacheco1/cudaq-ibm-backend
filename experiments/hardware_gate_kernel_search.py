# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""How the sequences of tests/gate_rule_kernel.py were picked.

Wanted, for a run on real hardware: per gate under test (rx, ry, z, y, u3)
a few one-qubit gates that end in a CERTAIN bit, and that stop giving that
bit when the gate is wrong. A certain answer is easy to judge on a noisy
chip; a distribution is not.

A sequence is   A  G  B  G  C   or   A  G  C : G is the gate under test, A,
B, C are words of at most two gates that already ran on hardware (h, x,
sdg). A fault is applied to every G:

    drop        the gate is left out
    X, Y, Z     an extra Pauli gate right before it
    neg, half   for gates with angles: the sign flipped, or half the angle

One sequence is never enough: for each one, some fault leaves the bit
certain (a Z before a gate on a qubit in 0 is invisible). So the search
takes TWO sequences per gate, on two qubits, and scores the pair by the
highest probability, under any fault, that both qubits still give their bit.

    python3 experiments/hardware_gate_kernel_search.py      # numpy only

Run 2026-11-11: worst fault 0.073 for rx and ry (half the angle), 0.008 for
u3, 0 for z and y. The sequences printed are the ones in
tests/gate_rule_kernel.py. Whether the built plugin really fails on wrong
rules is a separate check: experiments/plant_rule_faults.py.
"""

import itertools
import math

import numpy as np

PI = math.pi
I2 = np.eye(2, dtype=complex)
X = np.array([[0, 1], [1, 0]], dtype=complex)
Y = np.array([[0, -1j], [1j, 0]])
Z = np.diag([1, -1]).astype(complex)
H = (X + Z) / math.sqrt(2)


def rx(t): return math.cos(t / 2) * I2 - 1j * math.sin(t / 2) * X
def ry(t): return math.cos(t / 2) * I2 - 1j * math.sin(t / 2) * Y
def r1(t): return np.diag([1, np.exp(1j * t)])


def u3(t, p, l):
    return np.array(
        [[math.cos(t / 2), -np.exp(1j * l) * math.sin(t / 2)],
         [np.exp(1j * p) * math.sin(t / 2),
          np.exp(1j * (p + l)) * math.cos(t / 2)]])


FIXED = {"h": H, "x": X, "y": Y, "z": Z, "sdg": r1(-PI / 2)}
ROTATIONS = {"rx": rx, "ry": ry, "u3": u3}
PROVEN = ("h", "x", "sdg")
WORDS = ([()] + [(g,) for g in PROVEN]
         + [w for w in itertools.product(PROVEN, repeat=2)
            if w[0] != w[1] or w[0] == "sdg"])
ANGLES = [PI / 2, -PI / 2, PI, 3 * PI / 2,
          PI / 4, 3 * PI / 4, -PI / 4, -3 * PI / 4]
U3_ANGLES = [(PI / 2, PI / 2, PI / 4), (PI / 2, PI / 4, PI / 2),
             (3 * PI / 4, PI / 2, PI / 2), (PI / 2, 3 * PI / 4, PI / 4),
             (PI / 4, PI / 2, 3 * PI / 4), (3 * PI / 2, PI / 4, PI / 2)]


def faults(name: str) -> list[str]:
    return ["drop", "X", "Y", "Z"] + (
        ["neg", "half"] if name in ROTATIONS else [])


def matrix(name: str, angles: tuple, fault) -> np.ndarray:
    if fault == "drop":
        return I2
    if fault == "neg":
        angles = [-a for a in angles]
    if fault == "half":
        angles = [a / 2 for a in angles]
    m = ROTATIONS[name](*angles) if name in ROTATIONS else FIXED[name]
    if fault in ("X", "Y", "Z"):
        m = m @ {"X": X, "Y": Y, "Z": Z}[fault]   # the Pauli acts first
    return m


def probability_of_1(ops: list[tuple], gate=None, fault=None) -> float:
    state = np.array([1, 0], dtype=complex)
    for name, angles in ops:
        state = matrix(name, angles, fault if name == gate else None) @ state
    return float(abs(state[1]) ** 2)


def candidates(name: str) -> dict[tuple, tuple]:
    """Every sequence with a certain bit, keyed by what each fault leaves of
    it: {(probability of the right bit per fault): (ops, bit)}."""
    if name in FIXED:
        uses = [(name, ())]
    elif name == "u3":
        uses = [(name, a) for a in U3_ANGLES]
    else:
        uses = [(name, (a,)) for a in ANGLES]
    found = {}
    for first in uses:
        for second in [None] + uses:
            for a, b, c in itertools.product(WORDS, repeat=3):
                if second is None and b:
                    continue
                ops = ([(g, ()) for g in a] + [first] + [(g, ()) for g in b]
                       + ([second] if second else []) + [(g, ()) for g in c])
                p = probability_of_1(ops)
                if min(p, 1 - p) > 1e-9:
                    continue
                bit = round(p)
                left = tuple(
                    round(q if bit else 1 - q, 4)
                    for q in (probability_of_1(ops, name, f)
                              for f in faults(name)))
                if left not in found or len(ops) < len(found[left][0]):
                    found[left] = (ops, bit)
    return found


def show(ops: list[tuple]) -> str:
    return "; ".join(
        g + ("(" + ", ".join(f"{a / PI:g} pi" for a in angles) + ")"
             if angles else "")
        for g, angles in ops)


def main() -> None:
    for name in ("rx", "ry", "z", "y", "u3"):
        found = candidates(name)
        table = np.array(list(found))
        best = None
        for i in range(len(table)):
            both = (table[i] * table).max(axis=1)   # worst fault per partner
            j = int(both.argmin())
            size = len(found[tuple(table[i])][0]) + len(found[tuple(table[j])][0])
            key = (round(float(both[j]), 4), size)
            if best is None or key < best[0]:
                best = (key, i, j)
        (worst, _), i, j = best
        print(f"{name}: worst fault leaves {worst:.3f}  "
              f"(faults: {', '.join(faults(name))})")
        for k in (i, j):
            ops, bit = found[tuple(table[k])]
            print(f"    expects {bit}:  {show(ops)}")
            print(f"        left per fault: "
                  f"{', '.join(f'{v:g}' for v in table[k])}")


if __name__ == "__main__":
    main()
