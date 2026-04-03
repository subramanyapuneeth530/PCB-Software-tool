"""
tests/test_layers.py
────────────────────
Tests for core/layers.py:
  detect_layer, scan_folder, run_drc
"""
import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.layers import detect_layer, scan_folder, run_drc, LAYER_DEFS
from core.primitives import Aperture, GerberPrimitive


# ── detect_layer ──────────────────────────────────────────────────

class TestDetectLayer:
    def _name(self, filename) -> str | None:
        ld = detect_layer(filename)
        return ld.name if ld else None

    def test_kicad_front_copper(self):
        assert self._name('job-F_Cu.gbr') == 'F.Cu'

    def test_kicad_back_copper(self):
        assert self._name('job-B_Cu.gbr') == 'B.Cu'

    def test_kicad_edge_cuts(self):
        assert self._name('job-Edge_Cuts.gbr') == 'Edge.Cuts'

    def test_altium_gtl(self):
        assert self._name('board.GTL') == 'F.Cu'

    def test_altium_gbl(self):
        assert self._name('board.GBL') == 'B.Cu'

    def test_drill_drl(self):
        assert self._name('drill.drl') == 'Drill'

    def test_drill_xln(self):
        assert self._name('holes.xln') == 'Drill'

    def test_front_silk(self):
        result = self._name('job-F_Silkscreen.gbr')
        assert result == 'F.Silk'

    def test_front_mask(self):
        result = self._name('job-F_Mask.gbr')
        assert result == 'F.Mask'

    def test_unknown_extension_returns_none(self):
        assert detect_layer('schematic.sch') is None

    def test_inner_layer_1(self):
        assert self._name('job-In1_Cu.gbr') == 'In1.Cu'


# ── scan_folder ───────────────────────────────────────────────────

class TestScanFolder:
    def test_scan_finds_gerber_files(self, tmp_path):
        (tmp_path / 'F_Cu.gbr').write_text('', encoding='utf-8')
        (tmp_path / 'B_Cu.gbr').write_text('', encoding='utf-8')
        (tmp_path / 'Edge_Cuts.gbr').write_text('', encoding='utf-8')
        results = scan_folder(str(tmp_path))
        names = [r.layer_name for r in results]
        assert 'F.Cu' in names
        assert 'B.Cu' in names
        assert 'Edge.Cuts' in names

    def test_scan_ignores_non_gerber(self, tmp_path):
        (tmp_path / 'README.md').write_text('', encoding='utf-8')
        (tmp_path / 'main.py').write_text('', encoding='utf-8')
        results = scan_folder(str(tmp_path))
        assert results == []

    def test_scan_deduplicates_layer_names(self, tmp_path):
        (tmp_path / 'board1-F_Cu.gbr').write_text('', encoding='utf-8')
        (tmp_path / 'board2-F_Cu.gbr').write_text('', encoding='utf-8')
        results = scan_folder(str(tmp_path))
        layer_names = [r.layer_name for r in results]
        assert len(layer_names) == len(set(layer_names)), "Layer names should be unique"

    def test_scan_marks_drill_file(self, tmp_path):
        (tmp_path / 'board.drl').write_text('', encoding='utf-8')
        results = scan_folder(str(tmp_path))
        assert results[0].is_drill is True


# ── run_drc ───────────────────────────────────────────────────────

def _make_pad(x, y, diam, layer='F.Cu', net=''):
    ap = Aperture(shape='C', params=[diam])
    p = GerberPrimitive(kind='pad', layer=layer, points=[(x, y)],
                        aperture=ap, net=net)
    p.compute_bbox()
    return p

def _make_track(pts, width, layer='F.Cu', net=''):
    p = GerberPrimitive(kind='track', layer=layer, points=pts, width=width, net=net)
    p.compute_bbox()
    return p


class TestRunDRC:
    def test_no_violations_well_spaced(self):
        a = _make_pad(0.0, 0.0, 0.2, net='A')
        b = _make_pad(10.0, 0.0, 0.2, net='B')
        violations = run_drc([a, b], {})
        clearance_v = [v for v in violations if v.kind == 'clearance']
        assert len(clearance_v) == 0

    def test_clearance_violation_overlapping(self):
        a = _make_pad(0.0, 0.0, 0.8, net='A')
        b = _make_pad(0.5, 0.0, 0.8, net='B')  # overlapping, different nets
        violations = run_drc([a, b], {})
        kinds = [v.kind for v in violations]
        assert 'clearance' in kinds

    def test_no_violation_if_connected(self):
        a = _make_pad(0.0, 0.0, 0.8, net='GND')
        b = _make_pad(0.5, 0.0, 0.8, net='GND')
        # Mark as connected via adjacency dict
        adj = {0: [1], 1: [0]}
        violations = run_drc([a, b], adj)
        clearance_v = [v for v in violations if v.kind == 'clearance']
        assert len(clearance_v) == 0

    def test_min_width_violation(self):
        thin = _make_track([(0.0, 0.0), (5.0, 0.0)], width=0.01, net='N')
        violations = run_drc([thin], {}, min_track_mm=0.05)
        kinds = [v.kind for v in violations]
        assert 'min_width' in kinds

    def test_min_width_ok_above_threshold(self):
        ok = _make_track([(0.0, 0.0), (5.0, 0.0)], width=0.2, net='N')
        violations = run_drc([ok], {}, min_track_mm=0.05)
        width_v = [v for v in violations if v.kind == 'min_width']
        assert len(width_v) == 0
