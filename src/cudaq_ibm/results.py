"""Step 4: turn IBM Sampler results into CUDA-Q style counts.

Two details matter here.

1. **Format.** IBM's Sampler returns one hex string per shot for each
   classical register, for example ``"0x3"``. We count them.
2. **Bit order.** Qiskit and IBM are *little-endian*: bit 0 is the
   right-most character of a bit string. CUDA-Q writes qubit 0 as the
   *left-most* character. So ``x(q[0])`` on 3 qubits gives ``"100"`` in
   CUDA-Q but ``"001"`` in Qiskit. We flip each register to match CUDA-Q.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping, Sequence


def hex_to_bits(sample: str, num_bits: int) -> str:
    """``"0x1"`` with 3 bits -> ``"100"`` (CUDA-Q order: bit 0 first)."""
    little_endian = format(int(sample, 16), f"0{num_bits}b")
    return little_endian[::-1]


def samples_to_counts(
    data: Mapping[str, Mapping[str, Sequence[str]]],
    registers: Iterable[tuple[str, int]],
) -> dict[str, int]:
    """Combine per-register hex samples into CUDA-Q style counts.

    ``registers`` lists ``(name, size)`` in circuit order. Each shot's bit
    string is the registers joined in that order, matching how CUDA-Q
    lists measured qubits.
    """
    registers = list(registers)
    if not registers:
        raise ValueError("circuit has no classical registers")
    per_register = [data[name]["samples"] for name, _ in registers]
    shots = len(per_register[0])
    if any(len(s) != shots for s in per_register):
        raise ValueError("registers report different shot counts")

    counts: Counter[str] = Counter()
    for shot in range(shots):
        counts["".join(
            hex_to_bits(per_register[i][shot], size)
            for i, (_, size) in enumerate(registers)
        )] += 1
    return dict(counts)
