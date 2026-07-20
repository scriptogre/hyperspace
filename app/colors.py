"""Deterministic player colors."""

from dataclasses import dataclass

GOLDEN_ANGLE = 137.507764


@dataclass(frozen=True, slots=True)
class Oklch:
    lightness: float
    chroma: float
    hue: float

    def to_css(self) -> str:
        return f"oklch({self.lightness:.3f} {self.chroma:.3f} {self.hue:.2f}deg)"


def calculate_player_color(seed: int) -> Oklch:
    return Oklch(
        lightness=0.68,
        chroma=0.17,
        hue=seed * GOLDEN_ANGLE % 360,
    )
