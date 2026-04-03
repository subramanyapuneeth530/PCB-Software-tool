"""
core/spatial.py
───────────────
Spatial grid index for fast O(n log n) primitive collision detection.
Replaces the O(n²) all-pairs loop with a grid bucket approach:
  - Divide board space into cells of size `cell_size`
  - Each primitive registers in every cell its bbox overlaps
  - Collision checks only between primitives sharing a cell
"""
from __future__ import annotations
import math
from collections import defaultdict
from .primitives import GerberPrimitive


def _pt_seg_dist2(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = max(0.0, min(1.0,
        ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2


def _prims_touch(a: GerberPrimitive, b: GerberPrimitive) -> bool:
    if not a.bbox or not b.bbox:
        return False
    ax1, ay1, ax2, ay2 = a.bbox
    bx1, by1, bx2, by2 = b.bbox
    if ax2 < bx1 or bx2 < ax1 or ay2 < by1 or by2 < ay1:
        return False

    ar = (a.aperture.radius() if a.aperture else a.width / 2)
    br = (b.aperture.radius() if b.aperture else b.width / 2)
    tol  = ar + br + 0.002
    tol2 = tol * tol

    pa, pb = a.points, b.points

    for px, py in pa:
        if len(pb) == 1:
            if (px - pb[0][0]) ** 2 + (py - pb[0][1]) ** 2 <= tol2:
                return True
        else:
            for j in range(len(pb) - 1):
                if _pt_seg_dist2(px, py,
                                 pb[j][0], pb[j][1],
                                 pb[j+1][0], pb[j+1][1]) <= tol2:
                    return True

    for px, py in pb:
        if len(pa) == 1:
            if (px - pa[0][0]) ** 2 + (py - pa[0][1]) ** 2 <= tol2:
                return True
        else:
            for j in range(len(pa) - 1):
                if _pt_seg_dist2(px, py,
                                 pa[j][0], pa[j][1],
                                 pa[j+1][0], pa[j+1][1]) <= tol2:
                    return True
    return False


class SpatialIndex:
    """Grid-bucketed spatial index for GerberPrimitive lists."""

    def __init__(self, primitives: list[GerberPrimitive],
                 cell_size: float = 2.0):
        self._prims = primitives
        self._cs    = cell_size
        self._grid: dict[tuple, list[int]] = defaultdict(list)
        self._build()

    def _cell(self, x, y) -> tuple:
        return (int(x / self._cs), int(y / self._cs))

    def _cells_for_bbox(self, bbox) -> set:
        x1, y1, x2, y2 = bbox
        cx1, cy1 = self._cell(x1, y1)
        cx2, cy2 = self._cell(x2, y2)
        cells = set()
        for cx in range(cx1, cx2 + 1):
            for cy in range(cy1, cy2 + 1):
                cells.add((cx, cy))
        return cells

    def _build(self):
        for i, p in enumerate(self._prims):
            if p.bbox:
                for cell in self._cells_for_bbox(p.bbox):
                    self._grid[cell].append(i)

    def build_adjacency(self) -> dict[int, list[int]]:
        """Return adjacency list for all touching copper primitives."""
        import re as _re
        COPPER = _re.compile(r'(F|B|In\d+)\.Cu', _re.IGNORECASE)

        copper_set = set(
            i for i, p in enumerate(self._prims)
            if COPPER.search(p.layer) or p.kind in ('pad', 'track', 'via', 'region')
        )

        checked = set()
        adj: dict[int, list[int]] = defaultdict(list)

        for cell, indices in self._grid.items():
            for ii in range(len(indices)):
                ia = indices[ii]
                if ia not in copper_set:
                    continue
                for jj in range(ii + 1, len(indices)):
                    ib = indices[jj]
                    if ib not in copper_set:
                        continue
                    pair = (min(ia, ib), max(ia, ib))
                    if pair in checked:
                        continue
                    checked.add(pair)
                    if _prims_touch(self._prims[ia], self._prims[ib]):
                        adj[ia].append(ib)
                        adj[ib].append(ia)

        return dict(adj)


def flood_fill(start: int, adj: dict) -> set[int]:
    visited, queue = set(), [start]
    while queue:
        cur = queue.pop()
        if cur in visited:
            continue
        visited.add(cur)
        queue.extend(adj.get(cur, []))
    return visited
