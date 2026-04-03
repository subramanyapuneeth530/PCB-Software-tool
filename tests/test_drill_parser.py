"""
tests/test_drill_parser.py
──────────────────────────
Tests for core/drill_parser.py (ExcellonParser).
"""
import textwrap, os, pytest, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.drill_parser import ExcellonParser


def _parse_drill(content: str, tmp_path) -> list:
    p = tmp_path / 'test.drl'
    p.write_text(textwrap.dedent(content), encoding='utf-8')
    return ExcellonParser().parse(str(p))


class TestExcellonParser:
    def test_basic_metric_holes(self, tmp_path):
        holes = _parse_drill("""\
            M48
            METRIC,LZ
            T1C0.800
            %
            T1
            X012345Y054321
            M30
        """, tmp_path)
        assert len(holes) == 1
        assert holes[0].diameter == pytest.approx(0.8)
        assert holes[0].plated is True

    def test_multiple_tools(self, tmp_path):
        holes = _parse_drill("""\
            M48
            METRIC,LZ
            T1C0.800
            T2C1.200
            %
            T1
            X010000Y010000
            T2
            X020000Y020000
            M30
        """, tmp_path)
        assert len(holes) == 2
        assert holes[0].diameter == pytest.approx(0.8)
        assert holes[1].diameter == pytest.approx(1.2)

    def test_inch_units_converted(self, tmp_path):
        holes = _parse_drill("""\
            M48
            INCH,LZ
            T1C0.031
            %
            T1
            X00500Y00500
            M30
        """, tmp_path)
        assert len(holes) == 1
        # 0.031 inches -> approx 0.7874 mm
        assert holes[0].diameter == pytest.approx(0.031 * 25.4, rel=1e-3)

    def test_npth_holes_not_plated(self, tmp_path):
        holes = _parse_drill("""\
            M48
            METRIC,LZ
            T1C2.000
            ; NPTH
            NPTH
            %
            T1
            X050000Y050000
            M30
        """, tmp_path)
        assert len(holes) == 1
        assert holes[0].plated is False

    def test_no_holes_without_tool(self, tmp_path):
        """Coordinates without a tool select should not produce holes."""
        holes = _parse_drill("""\
            M48
            METRIC,LZ
            %
            X010000Y010000
            M30
        """, tmp_path)
        assert len(holes) == 0

    def test_empty_file(self, tmp_path):
        holes = _parse_drill("", tmp_path)
        assert holes == []
