from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegisterField:
    name: str
    address: int
    count: int = 1
    scale: float = 1.0
    signed: bool = False

    def decode(self, registers: list[int]) -> float:
        if len(registers) != self.count:
            raise ValueError(f"{self.name} expects {self.count} registers, got {len(registers)}")

        if self.count == 1:
            raw = registers[0]
            if self.signed and raw >= 0x8000:
                raw -= 0x10000
            return raw / self.scale

        raw = 0
        for register in registers:
            raw = (raw << 16) | register

        bit_width = self.count * 16
        if self.signed and raw >= (1 << (bit_width - 1)):
            raw -= 1 << bit_width

        return raw / self.scale

    def encode(self, value: float) -> list[int]:
        raw = int(round(value * self.scale))

        if self.count == 1:
            if self.signed and raw < 0:
                raw = (1 << 16) + raw
            return [raw & 0xFFFF]

        bit_width = self.count * 16
        if self.signed and raw < 0:
            raw = (1 << bit_width) + raw

        registers: list[int] = []
        for shift in range(self.count - 1, -1, -1):
            registers.append((raw >> (shift * 16)) & 0xFFFF)
        return registers
