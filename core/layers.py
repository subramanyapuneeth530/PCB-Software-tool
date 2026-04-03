"""
core/layers.py
──────────────
Layer definitions, file scanning, and DRC rule checks.
"""
from __future__ import annotations
import os, re
from dataclasses import dataclass
from .primitives import GerberPrimitive
from .spatial import _pt_seg_dist2


# ── Layer definitions ─────────────────────────────────────────────

@dataclass
class LayerDef:
    pattern:      str
    name:         str
    color:        str    # hex
    display:      str
    default_load: bool
    z_order:      int    # lower = drawn first (bottom)

LAYER_DEFS = [
    LayerDef(r'edge\.cuts|edge_cuts|\.gko$|board.*outline',
             'Edge.Cuts', '#FFFF40', 'Board Outline',    True,  0),
    LayerDef(r'b\.cu|b_cu|\.gbl$|back.*copper',
             'B.Cu',      '#4A90D9', 'Back Copper',      True,  1),
    LayerDef(r'in4\.cu|in4_cu|\.g4$|inner.*4',
             'In4.Cu',    '#48C8C8', 'Inner 4',          True,  2),
    LayerDef(r'in3\.cu|in3_cu|\.g3$|inner.*3',
             'In3.Cu',    '#C848C8', 'Inner 3',          True,  3),
    LayerDef(r'in2\.cu|in2_cu|\.g2$|inner.*2',
             'In2.Cu',    '#48C848', 'Inner 2',          True,  4),
    LayerDef(r'in1\.cu|in1_cu|\.g1$|inner.*1',
             'In1.Cu',    '#C84848', 'Inner 1',          True,  5),
    LayerDef(r'f\.cu|f_cu|\.gtl$|front.*copper',
             'F.Cu',      '#E8A020', 'Front Copper',     True,  6),
    LayerDef(r'b\.mask|b_mask|\.gbs$|back.*mask',
             'B.Mask',    '#203060', 'Back Mask',        False, 7),
    LayerDef(r'f\.mask|f_mask|\.gts$|front.*mask',
             'F.Mask',    '#802020', 'Front Mask',       False, 8),
    LayerDef(r'b\.paste|b_paste|back.*paste',
             'B.Paste',   '#555577', 'Back Paste',       False, 9),
    LayerDef(r'f\.paste|f_paste|front.*paste',
             'F.Paste',   '#777799', 'Front Paste',      False, 10),
    LayerDef(r'b\.silks|b_silkscreen|\.gbo$|back.*silk',
             'B.Silk',    '#8888FF', 'Back Silk',        False, 11),
    LayerDef(r'f\.silks|f_silkscreen|\.gto$|front.*silk',
             'F.Silk',    '#E0E0E0', 'Front Silk',       False, 12),
    LayerDef(r'b\.fab|b_fab|back.*fab',
             'B.Fab',     '#606020', 'Back Fab',         False, 13),
    LayerDef(r'f\.fab|f_fab|front.*fab',
             'F.Fab',     '#A0A040', 'Front Fab',        False, 14),
    LayerDef(r'b\.courtyard|b_courtyard|back.*court',
             'B.CrtYd',   '#8040FF', 'Back Courtyard',   False, 15),
    LayerDef(r'f\.courtyard|f_courtyard|front.*court',
             'F.CrtYd',   '#FF40FF', 'Front Courtyard',  False, 16),
    LayerDef(r'drill|\.drl$|\.xln$|\.exc$|\.ncd$',
             'Drill',     '#C0C0C0', 'Drill Holes',      True,  17),
]

GERBER_EXTS = {
    '.gbr', '.gtl', '.gbl', '.gts', '.gbs', '.gto', '.gbo',
    '.gko', '.g1', '.g2', '.g3', '.g4', '.ger', '.art',
    '.gml', '.gm1', '.gm2',
}
DRILL_EXTS = {'.drl', '.xln', '.exc', '.ncd', '.txt'}


def detect_layer(filepath: str) -> LayerDef | None:
    fname = os.path.basename(filepath).lower()
    for ld in LAYER_DEFS:
        if re.search(ld.pattern, fname, re.IGNORECASE):
            return ld
    return None


@dataclass
class FileDesc:
    path:         str
    layer_def:    LayerDef
    layer_name:   str       # may have suffix if duplicate
    is_drill:     bool = False


def scan_folder(folder: str) -> list[FileDesc]:
    seen: dict[str, int] = {}
    result: list[FileDesc] = []

    for fname in sorted(os.listdir(folder)):
        fp   = os.path.join(folder, fname)
        ext  = os.path.splitext(fname)[1].lower()
        is_g = ext in GERBER_EXTS
        is_d = ext in DRILL_EXTS

        if not (is_g or is_d):
            continue

        ld = detect_layer(fp)
        if ld is None:
            base = os.path.splitext(fname)[0]
            ld = LayerDef(r'', base, '#AAAAAA', base, False, 99)

        # Deduplicate layer names
        name = ld.name
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0

        result.append(FileDesc(
            path=fp, layer_def=ld, layer_name=name, is_drill=is_d))

    return result


# ── DRC ──────────────────────────────────────────────────────────

@dataclass
class DRCViolation:
    kind:    str    # 'clearance' | 'min_width' | 'unconnected'
    message: str
    x: float
    y: float
    prim_a: int     # global primitive index
    prim_b: int = -1


def run_drc(primitives: list[GerberPrimitive],
            adj: dict[int, list[int]],
            min_clearance_mm: float = 0.1,
            min_track_mm:     float = 0.05) -> list[DRCViolation]:
    """
    Basic DRC:
      1. Track width below minimum
      2. Clearance between copper that is NOT connected
      3. (future) unconnected net endpoints
    Returns list of DRCViolation.
    Runs on copper primitives only.
    """
    import re as _re
    COPPER = _re.compile(r'(F|B|In\d+)\.Cu', _re.IGNORECASE)
    copper = [(i, p) for i, p in enumerate(primitives)
              if COPPER.search(p.layer) or p.kind in ('pad', 'track', 'via', 'region')]

    violations: list[DRCViolation] = []

    # 1 — min track width
    for i, p in copper:
        if p.kind == 'track' and 0 < p.width < min_track_mm:
            cx, cy = p.points[0]
            violations.append(DRCViolation(
                kind='min_width',
                message=f"Track width {p.width:.4f}mm < min {min_track_mm:.4f}mm on {p.layer}",
                x=cx, y=cy, prim_a=i))

    # 2 — clearance between non-connected copper
    # Only check nearby pairs (grid-based would be better for large boards)
    # For correctness we check all pairs up to a reasonable cutoff
    MAX_PAIRS = 200_000
    checked = set()
    pair_count = 0

    for ii in range(len(copper)):
        ia, a = copper[ii]
        if not a.bbox: continue
        ax1, ay1, ax2, ay2 = a.bbox
        ar = (a.aperture.radius() if a.aperture else a.width / 2)

        for jj in range(ii + 1, len(copper)):
            if pair_count > MAX_PAIRS: break
            ib, b = copper[jj]
            if not b.bbox: continue

            # Skip if connected
            if ib in adj.get(ia, []):
                continue

            bx1, by1, bx2, by2 = b.bbox
            # Quick bbox clearance check
            gap_x = max(0.0, max(ax1, bx1) - min(ax2, bx2))
            gap_y = max(0.0, max(ay1, by1) - min(ay2, by2))
            if gap_x > min_clearance_mm + 0.5 or gap_y > min_clearance_mm + 0.5:
                continue

            pair = (min(ia, ib), max(ia, ib))
            if pair in checked: continue
            checked.add(pair)
            pair_count += 1

            br = (b.aperture.radius() if b.aperture else b.width / 2)

            # Detailed clearance
            pa, pb_pts = a.points, b.points
            min_d2 = float('inf')
            for px, py in pa:
                if len(pb_pts) == 1:
                    d2 = (px - pb_pts[0][0])**2 + (py - pb_pts[0][1])**2
                else:
                    for j in range(len(pb_pts) - 1):
                        d2 = _pt_seg_dist2(px, py,
                                           pb_pts[j][0], pb_pts[j][1],
                                           pb_pts[j+1][0], pb_pts[j+1][1])
                        min_d2 = min(min_d2, d2)
                        if min_d2 == 0: break
                min_d2 = min(min_d2, d2)
                if min_d2 == 0: break

            dist = max(0.0, min_d2**0.5 - ar - br)
            if dist < min_clearance_mm:  # dist==0 means overlapping — also a violation
                cx = (a.points[0][0] + b.points[0][0]) / 2
                cy = (a.points[0][1] + b.points[0][1]) / 2
                violations.append(DRCViolation(
                    kind='clearance',
                    message=f"Clearance {dist:.4f}mm < min {min_clearance_mm:.4f}mm "
                            f"({a.layer} ↔ {b.layer})",
                    x=cx, y=cy, prim_a=ia, prim_b=ib))

    return violations
