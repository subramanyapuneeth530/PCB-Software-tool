"""
core/primitives.py
──────────────────
Core data structures: Aperture, GerberPrimitive, DrillHole.
No Qt dependencies here — safe to import in tests without a display.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Aperture:
    shape: str        # C R O P
    params: list

    def radius(self) -> float:
        if self.shape == 'C' and self.params:
            return self.params[0] / 2
        if self.shape in ('R', 'O') and len(self.params) >= 2:
            return max(self.params[0], self.params[1]) / 2
        return 0.0

    def width(self) -> float:
        return self.params[0] if self.params else 0.0

    def height(self) -> float:
        return self.params[1] if len(self.params) >= 2 else self.width()

    def size_str(self) -> str:
        if self.shape == 'C' and self.params:
            return f"⌀ {self.params[0]:.4f} mm"
        if self.shape in ('R', 'O') and len(self.params) >= 2:
            return f"{self.params[0]:.4f} × {self.params[1]:.4f} mm"
        return "unknown"


@dataclass
class GerberPrimitive:
    kind: str           # track pad region via arc
    layer: str
    points: list        # [(x, y), ...]
    width: float = 0.0
    aperture: Optional[Aperture] = None
    bbox: Optional[tuple] = None

    # Gerber X2 attributes
    net: str = ""       # %TO.N,<net>%
    ref: str = ""       # %TO.C,<ref>%
    pin: str = ""       # %TO.P,<ref>,<pin>%

    def compute_bbox(self):
        if not self.points:
            return
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        pad = max(self.width / 2, 0.001)
        if self.aperture:
            pad = max(pad, self.aperture.radius())
        self.bbox = (min(xs) - pad, min(ys) - pad,
                     max(xs) + pad, max(ys) + pad)

    def length_mm(self) -> float:
        total = 0.0
        for i in range(len(self.points) - 1):
            dx = self.points[i+1][0] - self.points[i][0]
            dy = self.points[i+1][1] - self.points[i][1]
            total += math.hypot(dx, dy)
        return total

    def info_lines(self) -> list[tuple[str, str]]:
        rows = [("Kind", self.kind), ("Layer", self.layer)]
        if self.ref:  rows.append(("Ref", self.ref))
        if self.pin:  rows.append(("Pin", self.pin))
        if self.net:  rows.append(("Net", self.net))
        if self.kind == 'track':
            rows.append(("Length", f"{self.length_mm():.4f} mm"))
            rows.append(("Width",  f"{self.width:.4f} mm"))
        elif self.kind in ('pad', 'via'):
            x, y = self.points[0]
            rows.append(("X", f"{x:.4f} mm"))
            rows.append(("Y", f"{y:.4f} mm"))
            if self.aperture:
                rows.append(("Size", self.aperture.size_str()))
                rows.append(("Shape", self.aperture.shape))
        elif self.kind == 'region':
            rows.append(("Vertices", str(len(self.points))))
        return rows


@dataclass
class DrillHole:
    x: float
    y: float
    diameter: float
    plated: bool = True
    tool_id: str = ""

    def bbox(self):
        r = self.diameter / 2
        return (self.x - r, self.y - r, self.x + r, self.y + r)
