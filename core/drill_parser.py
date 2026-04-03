"""
core/drill_parser.py
────────────────────
Excellon drill file parser (.drl / .xln / .exc / .ncd).
Handles: tool definitions, metric/imperial, leading/trailing zero suppression,
         DRILL / ROUTE modes, plated vs non-plated.
"""
from __future__ import annotations
import re
from .primitives import DrillHole


class ExcellonParser:
    def __init__(self):
        self.tools: dict[str, float] = {}    # tool_id → diameter mm
        self.holes: list[DrillHole]  = []
        self.unit_mm    = True
        self.cur_tool   = ""
        self.cur_diam   = 0.0
        self.plated     = True
        # format: (integer_digits, decimal_digits)
        self.fmt        = (2, 4)
        self.leading_zeros = True   # True=leading suppressed, False=trailing

    def parse(self, filepath: str) -> list[DrillHole]:
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except OSError as e:
            print(f"  [WARN] drill {filepath}: {e}")
            return []

        header = True
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith(';'):
                continue

            # Header end markers
            if line in ('%', 'M95', 'M48'):
                if line == 'M48': header = True
                else: header = False
                continue

            if header:
                self._parse_header(line)
            else:
                self._parse_body(line)

        return self.holes

    def _parse_header(self, line: str):
        # Tool definition  T1C0.800
        m = re.match(r'T(\d+)C([\d.]+)', line)
        if m:
            tid = m.group(1)
            d   = float(m.group(2))
            if not self.unit_mm:
                d *= 25.4
            self.tools[tid] = d
            return

        # Units
        if 'METRIC' in line:
            self.unit_mm = True
        elif 'INCH' in line or 'ENGLISH' in line:
            self.unit_mm = False

        # Format  FMAT,2  or  00.0000
        m2 = re.search(r'(\d+)\.(\d+)', line)
        if m2:
            self.fmt = (len(m2.group(1)), len(m2.group(2)))

        # Plated / non-plated
        if 'NPTH' in line.upper():
            self.plated = False

    def _parse_body(self, line: str):
        # Tool select  T3
        m = re.match(r'^T(\d+)$', line)
        if m:
            tid = m.group(1)
            self.cur_tool = tid
            self.cur_diam = self.tools.get(tid, 0.0)
            return

        # Inline tool + coordinate  T1X123456Y654321
        m2 = re.match(r'^T(\d+)(X[+-]?\d+Y[+-]?\d+)', line)
        if m2:
            tid = m2.group(1)
            self.cur_tool = tid
            self.cur_diam = self.tools.get(tid, 0.0)
            line = m2.group(2)

        # Coordinate  X123456Y654321
        m3 = re.match(r'^X([+-]?\d+)Y([+-]?\d+)', line)
        if m3:
            x = self._coord(m3.group(1))
            y = self._coord(m3.group(2))
            if self.cur_diam > 0:
                self.holes.append(DrillHole(
                    x=x, y=y, diameter=self.cur_diam,
                    plated=self.plated, tool_id=self.cur_tool))

        # End of file
        if line in ('M00', 'M30'):
            pass

    def _coord(self, s: str) -> float:
        neg = s.startswith('-')
        digits = s.lstrip('-+')
        fi, fd = self.fmt
        total  = fi + fd
        digits = digits.zfill(total)
        val = float(digits[:-fd] + '.' + digits[-fd:]) if fd else float(digits)
        val = -val if neg else val
        return val if self.unit_mm else val * 25.4
