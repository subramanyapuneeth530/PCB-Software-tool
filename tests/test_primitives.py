"""
tests/test_primitives.py
────────────────────────
Tests for core/primitives.py
Covers: Aperture geometry helpers, GerberPrimitive bbox / length / info,
DrillHole bbox.
"""
import math
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.primitives import Aperture, GerberPrimitive, DrillHole


# ── Aperture ──────────────────────────────────────────────────────

class TestAperture:
    def test_circle_radius(self):
        ap = Aperture(shape='C', params=[1.0])
        assert ap.radius() == pytest.approx(0.5)

    def test_rect_radius_uses_larger_dim(self):
        ap = Aperture(shape='R', params=[2.0, 1.0])
        assert ap.radius() == pytest.approx(1.0)

    def test_oblong_radius(self):
        ap = Aperture(shape='O', params=[1.0, 3.0])
        assert ap.radius() == pytest.approx(1.5)

    def test_unknown_shape_radius_zero(self):
        ap = Aperture(shape='P', params=[])
        assert ap.radius() == 0.0

    def test_width_first_param(self):
        ap = Aperture(shape='C', params=[0.8])
        assert ap.width() == pytest.approx(0.8)

    def test_height_second_param(self):
        ap = Aperture(shape='R', params=[0.5, 1.2])
        assert ap.height() == pytest.approx(1.2)

    def test_height_falls_back_to_width_for_circle(self):
        ap = Aperture(shape='C', params=[0.6])
        assert ap.height() == pytest.approx(0.6)

    def test_size_str_circle(self):
        ap = Aperture(shape='C', params=[1.0])
        assert '1.0000' in ap.size_str()
        assert 'mm' in ap.size_str()

    def test_size_str_rect(self):
        ap = Aperture(shape='R', params=[0.5, 1.0])
        s = ap.size_str()
        assert '0.5000' in s and '1.0000' in s

    def test_size_str_unknown(self):
        ap = Aperture(shape='P', params=[])
        assert ap.size_str() == 'unknown'


# ── GerberPrimitive ───────────────────────────────────────────────

class TestGerberPrimitive:
    def _track(self, pts, width=0.1):
        p = GerberPrimitive(kind='track', layer='F.Cu', points=pts, width=width)
        p.compute_bbox()
        return p

    def test_bbox_single_point(self):
        p = GerberPrimitive(kind='pad', layer='F.Cu', points=[(5.0, 10.0)])
        p.compute_bbox()
        assert p.bbox is not None
        x1, y1, x2, y2 = p.bbox
        assert x1 < 5.0 < x2
        assert y1 < 10.0 < y2

    def test_bbox_includes_width_pad(self):
        """pad with no aperture should still expand bbox by width/2"""
        p = GerberPrimitive(kind='pad', layer='F.Cu', points=[(0.0, 0.0)], width=1.0)
        p.compute_bbox()
        x1, y1, x2, y2 = p.bbox
        assert x1 <= -0.5 and x2 >= 0.5

    def test_bbox_aperture_radius_expands(self):
        ap = Aperture(shape='C', params=[2.0])   # radius = 1.0
        p = GerberPrimitive(kind='pad', layer='F.Cu',
                            points=[(0.0, 0.0)], aperture=ap)
        p.compute_bbox()
        x1, _, x2, _ = p.bbox
        assert x2 - x1 >= 2.0

    def test_length_mm_straight_horizontal(self):
        p = self._track([(0.0, 0.0), (3.0, 0.0)])
        assert p.length_mm() == pytest.approx(3.0)

    def test_length_mm_diagonal(self):
        p = self._track([(0.0, 0.0), (3.0, 4.0)])
        assert p.length_mm() == pytest.approx(5.0)

    def test_length_mm_multi_segment(self):
        p = self._track([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)])
        assert p.length_mm() == pytest.approx(2.0)

    def test_info_lines_track(self):
        p = self._track([(0.0, 0.0), (1.0, 0.0)], width=0.2)
        info = dict(p.info_lines())
        assert info['Kind'] == 'track'
        assert 'Width' in info
        assert '0.2000' in info['Width']

    def test_info_lines_pad_with_x2(self):
        ap = Aperture(shape='C', params=[0.5])
        p = GerberPrimitive(kind='pad', layer='F.Cu',
                            points=[(1.5, 2.5)], aperture=ap,
                            net='GND', ref='C1', pin='1')
        p.compute_bbox()
        info = dict(p.info_lines())
        assert info['Net'] == 'GND'
        assert info['Ref'] == 'C1'
        assert info['Pin'] == '1'

    def test_info_lines_region(self):
        pts = [(0, 0), (1, 0), (1, 1), (0, 1)]
        p = GerberPrimitive(kind='region', layer='F.Cu', points=pts)
        p.compute_bbox()
        info = dict(p.info_lines())
        assert info['Vertices'] == '4'


# ── DrillHole ─────────────────────────────────────────────────────

class TestDrillHole:
    def test_bbox_symmetric(self):
        hole = DrillHole(x=5.0, y=10.0, diameter=1.0)
        x1, y1, x2, y2 = hole.bbox()
        assert x1 == pytest.approx(4.5)
        assert x2 == pytest.approx(5.5)
        assert y1 == pytest.approx(9.5)
        assert y2 == pytest.approx(10.5)

    def test_plated_default_true(self):
        hole = DrillHole(x=0.0, y=0.0, diameter=0.8)
        assert hole.plated is True

    def test_non_plated(self):
        hole = DrillHole(x=0.0, y=0.0, diameter=1.0, plated=False)
        assert hole.plated is False
