"""
tests/test_parser.py
────────────────────
Tests for core/parser.py (GerberParser).
Uses in-memory Gerber strings via tmp_path fixtures — no display needed.
"""
import textwrap, os, pytest, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.parser import GerberParser


def _parse(content: str, tmp_path, layer='F.Cu') -> list:
    """Write `content` to a temp file and parse it."""
    p = tmp_path / 'test.gbr'
    p.write_text(textwrap.dedent(content), encoding='utf-8')
    return GerberParser(layer).parse(str(p))


# ── Format / Units ────────────────────────────────────────────────

class TestFormatAndUnits:
    def test_default_mm(self, tmp_path):
        primitives = _parse("""\
            %FSLAX26Y26*%
            %MOMM*%
            %ADD10C,0.200*%
            D10*
            X100000Y200000D03*
            M02*
        """, tmp_path)
        assert len(primitives) == 1
        pad = primitives[0]
        assert pad.kind == 'pad'
        # FSLAX26 → 2 int digits + 6 decimal digits
        # X100000 → zfill(8) = '00100000' → '00.100000' = 0.1 mm
        # Y200000 → zfill(8) = '00200000' → '00.200000' = 0.2 mm
        assert pad.points[0][0] == pytest.approx(0.1)
        assert pad.points[0][1] == pytest.approx(0.2)

    def test_inch_converted_to_mm(self, tmp_path):
        primitives = _parse("""\
            %FSLAX25Y25*%
            %MOIN*%
            %ADD10C,0.040*%
            D10*
            X1000Y0D03*
            M02*
        """, tmp_path)
        # X1000 with FSLAX25 = 0.01000 inches × 25.4 = 0.254 mm
        assert len(primitives) == 1
        assert primitives[0].points[0][0] == pytest.approx(0.254, rel=1e-4)


# ── Aperture definitions ──────────────────────────────────────────

class TestApertureDefinitions:
    def test_circle_aperture(self, tmp_path):
        prims = _parse("""\
            %FSLAX26Y26*%
            %MOMM*%
            %ADD11C,0.300*%
            D11*
            X0Y0D03*
            M02*
        """, tmp_path)
        ap = prims[0].aperture
        assert ap.shape == 'C'
        assert ap.params[0] == pytest.approx(0.3)

    def test_rect_aperture(self, tmp_path):
        prims = _parse("""\
            %FSLAX26Y26*%
            %MOMM*%
            %ADD12R,0.600X0.400*%
            D12*
            X0Y0D03*
            M02*
        """, tmp_path)
        ap = prims[0].aperture
        assert ap.shape == 'R'
        assert ap.params[0] == pytest.approx(0.6)
        assert ap.params[1] == pytest.approx(0.4)

    def test_oblong_aperture(self, tmp_path):
        prims = _parse("""\
            %FSLAX26Y26*%
            %MOMM*%
            %ADD13O,1.000X0.500*%
            D13*
            X0Y0D03*
            M02*
        """, tmp_path)
        assert prims[0].aperture.shape == 'O'


# ── Drawing commands ──────────────────────────────────────────────

class TestDrawCommands:
    def test_d03_flash_creates_pad(self, tmp_path):
        prims = _parse("""\
            %FSLAX26Y26*%
            %MOMM*%
            %ADD10C,0.2*%
            D10*
            X500000Y500000D03*
            M02*
        """, tmp_path)
        assert len(prims) == 1
        assert prims[0].kind == 'pad'

    def test_d01_creates_track(self, tmp_path):
        prims = _parse("""\
            %FSLAX26Y26*%
            %MOMM*%
            %ADD10C,0.2*%
            D10*
            X0Y0D02*
            X1000000Y0D01*
            M02*
        """, tmp_path)
        tracks = [p for p in prims if p.kind == 'track']
        assert len(tracks) == 1
        assert tracks[0].width == pytest.approx(0.2)

    def test_d02_does_not_create_primitive(self, tmp_path):
        prims = _parse("""\
            %FSLAX26Y26*%
            %MOMM*%
            %ADD10C,0.2*%
            D10*
            X0Y0D02*
            X1000000Y0D02*
            M02*
        """, tmp_path)
        assert len(prims) == 0

    def test_region_mode_g36_g37(self, tmp_path):
        prims = _parse("""\
            %FSLAX26Y26*%
            %MOMM*%
            G36*
            X0Y0D02*
            X1000000Y0D01*
            X1000000Y1000000D01*
            X0Y1000000D01*
            X0Y0D01*
            G37*
            M02*
        """, tmp_path)
        regions = [p for p in prims if p.kind == 'region']
        assert len(regions) == 1
        assert len(regions[0].points) >= 3

    def test_multiple_pads(self, tmp_path):
        prims = _parse("""\
            %FSLAX26Y26*%
            %MOMM*%
            %ADD10C,0.2*%
            D10*
            X0Y0D03*
            X1000000Y0D03*
            X2000000Y0D03*
            M02*
        """, tmp_path)
        pads = [p for p in prims if p.kind == 'pad']
        assert len(pads) == 3


# ── Gerber X2 attributes ─────────────────────────────────────────

class TestGerberX2:
    def test_x2_net_attr(self, tmp_path):
        prims = _parse("""\
            %FSLAX26Y26*%
            %MOMM*%
            %ADD10C,0.2*%
            %TO.N,GND*%
            D10*
            X0Y0D03*
            M02*
        """, tmp_path)
        assert prims[0].net == 'GND'

    def test_x2_comp_ref_pin(self, tmp_path):
        prims = _parse("""\
            %FSLAX26Y26*%
            %MOMM*%
            %ADD10C,0.5*%
            %TO.P,U1,3*%
            D10*
            X0Y0D03*
            M02*
        """, tmp_path)
        assert prims[0].ref == 'U1'
        assert prims[0].pin == '3'

    def test_x2_attrs_cleared_by_td(self, tmp_path):
        prims = _parse("""\
            %FSLAX26Y26*%
            %MOMM*%
            %ADD10C,0.2*%
            %TO.N,VCC*%
            D10*
            X0Y0D03*
            %TD*%
            X1000000Y0D03*
            M02*
        """, tmp_path)
        assert prims[0].net == 'VCC'
        assert prims[1].net == ''

    def test_x2_track_inherits_net(self, tmp_path):
        prims = _parse("""\
            %FSLAX26Y26*%
            %MOMM*%
            %ADD10C,0.15*%
            %TO.N,SDA*%
            D10*
            X0Y0D02*
            X2000000Y0D01*
            M02*
        """, tmp_path)
        tracks = [p for p in prims if p.kind == 'track']
        assert tracks[0].net == 'SDA'
