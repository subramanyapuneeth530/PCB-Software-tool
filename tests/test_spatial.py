"""
tests/test_spatial.py
─────────────────────
Tests for core/spatial.py:
  _pt_seg_dist2, _prims_touch, SpatialIndex, flood_fill
"""
import math, os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.primitives import Aperture, GerberPrimitive
from core.spatial import _pt_seg_dist2, _prims_touch, SpatialIndex, flood_fill


# ── Geometry helpers ──────────────────────────────────────────────

class TestPtSegDist2:
    def test_point_on_segment(self):
        d2 = _pt_seg_dist2(1.0, 0.0, 0.0, 0.0, 2.0, 0.0)
        assert d2 == pytest.approx(0.0)

    def test_point_off_segment_perpendicular(self):
        d2 = _pt_seg_dist2(1.0, 1.0, 0.0, 0.0, 2.0, 0.0)
        assert d2 == pytest.approx(1.0)

    def test_point_at_segment_end(self):
        # Closest point is the endpoint
        d2 = _pt_seg_dist2(3.0, 0.0, 0.0, 0.0, 2.0, 0.0)
        assert d2 == pytest.approx(1.0)

    def test_degenerate_segment(self):
        # ax==bx, ay==by → point-to-point distance squared
        d2 = _pt_seg_dist2(3.0, 4.0, 0.0, 0.0, 0.0, 0.0)
        assert d2 == pytest.approx(25.0)


# ── Primitive touching ────────────────────────────────────────────

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


class TestPrimsTouch:
    def test_overlapping_pads_touch(self):
        a = _make_pad(0.0, 0.0, 1.0)
        b = _make_pad(0.5, 0.0, 1.0)  # radii overlap
        assert _prims_touch(a, b) is True

    def test_far_pads_do_not_touch(self):
        a = _make_pad(0.0, 0.0, 0.2)
        b = _make_pad(10.0, 0.0, 0.2)
        assert _prims_touch(a, b) is False

    def test_pad_touching_track_endpoint(self):
        pad   = _make_pad(2.0, 0.0, 0.2)
        track = _make_track([(0.0, 0.0), (2.0, 0.0)], width=0.2)
        assert _prims_touch(pad, track) is True

    def test_no_bbox_returns_false(self):
        a = GerberPrimitive(kind='pad', layer='F.Cu', points=[(0.0, 0.0)])
        b = GerberPrimitive(kind='pad', layer='F.Cu', points=[(0.0, 0.0)])
        # no compute_bbox → bbox is None
        assert _prims_touch(a, b) is False


# ── SpatialIndex ──────────────────────────────────────────────────

class TestSpatialIndex:
    def _build_net(self):
        """Simple linear chain: pad → track → pad all on the same net."""
        p0 = _make_pad(0.0, 0.0, 0.3, net='GND')
        tr = _make_track([(0.0, 0.0), (5.0, 0.0)], width=0.2, net='GND')
        p1 = _make_pad(5.0, 0.0, 0.3, net='GND')
        return [p0, tr, p1]

    def test_adjacency_connects_chain(self):
        prims = self._build_net()
        idx = SpatialIndex(prims)
        adj = idx.build_adjacency()
        # p0 (idx 0) and tr (idx 1) should be adjacent
        assert 1 in adj.get(0, []) or 0 in adj.get(1, [])

    def test_isolated_pads_not_adjacent(self):
        a = _make_pad(0.0, 0.0, 0.2, net='NET_A')
        b = _make_pad(50.0, 50.0, 0.2, net='NET_B')
        idx = SpatialIndex([a, b])
        adj = idx.build_adjacency()
        assert adj == {}

    def test_flood_fill_finds_connected_set(self):
        prims = self._build_net()
        idx = SpatialIndex(prims)
        adj = idx.build_adjacency()
        connected = flood_fill(0, adj)
        # All three primitives should be reachable
        assert len(connected) == 3

    def test_flood_fill_single_isolated_node(self):
        adj = {}
        connected = flood_fill(5, adj)
        assert connected == {5}

    def test_flood_fill_two_separate_nets(self):
        a0 = _make_pad(0.0, 0.0, 0.3, net='A')
        a1 = _make_pad(0.3, 0.0, 0.3, net='A')
        b0 = _make_pad(20.0, 0.0, 0.3, net='B')
        prims = [a0, a1, b0]
        idx = SpatialIndex(prims)
        adj = idx.build_adjacency()
        net_a = flood_fill(0, adj)
        net_b = flood_fill(2, adj)
        assert 2 not in net_a
        assert 0 not in net_b
