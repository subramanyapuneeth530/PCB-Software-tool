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
        self.tools: dict[str, float] = {}    # tool_id → raw value (pre-conversion)
        self._tools_raw: dict[str, float] = {}  # raw inch values before unit known
        self.holes: list[DrillHole]  = []
        self.unit_mm    = True
        self.cur_tool   = ""
        self.cur_diam   = 0.0
        self.plated     = True
        self._units_set = False      # whether METRIC/INCH seen yet
        # format: (integer_digits, decimal_digits)
        self.fmt        = (2, 4)
        self.leading_zeros = True   # True=leading suppressed, False=trailing
        self._decimal_coords = False # True when FORMAT uses decimal notation

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
                if line == 'M48':
                    header = True
                else:
                    # End of header — now resolve tool diameters with known units
                    self._resolve_tools()
                    header = False
                continue

            if header:
                self._parse_header(line)
            else:
                self._parse_body(line)

        return self.holes

    def _parse_header(self, line: str):
        # Tool definition  T1C0.800  — store raw, convert after units known
        m = re.match(r'T(\d+)C([\d.]+)', line)
        if m:
            tid = m.group(1)
            self._tools_raw[tid] = float(m.group(2))
            return

        # Units
        if 'METRIC' in line:
            self.unit_mm = True
            self._units_set = True
        elif 'INCH' in line or 'ENGLISH' in line:
            self.unit_mm = False
            self._units_set = True

        # Decimal coordinate format detection
        if 'decimal' in line.lower():
            self._decimal_coords = True

        # Integer format spec  00.0000
        m2 = re.search(r'(\d+)\.(\d+)', line)
        if m2 and not self._decimal_coords:
            self.fmt = (len(m2.group(1)), len(m2.group(2)))

        # Plated / non-plated
        if 'NPTH' in line.upper():
            self.plated = False

    def _resolve_tools(self):
        """Convert raw tool diameters to mm using the now-known unit."""
        for tid, raw in self._tools_raw.items():
            self.tools[tid] = raw if self.unit_mm else raw * 25.4

    def _parse_body(self, line: str):
        # Skip G-code motion / mode lines that aren't coordinates
        if re.match(r'^G\d+', line):
            return

        # Tool select  T3
        m = re.match(r'^T(\d+)$', line)
        if m:
            tid = m.group(1)
            self.cur_tool = tid
            self.cur_diam = self.tools.get(tid, 0.0)
            return

        # Inline tool + coordinate  T1X...Y...  (integer or decimal)
        m2 = re.match(r'^T(\d+)(X[+-]?[\d.]+Y[+-]?[\d.]+)', line)
        if m2:
            tid = m2.group(1)
            self.cur_tool = tid
            self.cur_diam = self.tools.get(tid, 0.0)
            line = m2.group(2)

        # Coordinate  X...Y...  (integer OR decimal)
        m3 = re.match(r'^X([+-]?[\d.]+)Y([+-]?[\d.]+)', line)
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
        """Convert a coordinate string to mm.
        Handles both:
          - Integer-encoded:  '394690' with fmt=(2,4) -> 3.9469
          - Decimal-encoded:  '3.9469'  (pass-through)
        """
        neg = s.startswith('-')
        raw = s.lstrip('-+')

        # Decimal notation — already has a dot
        if '.' in raw:
            val = float(raw)
            val = -val if neg else val
            return val if self.unit_mm else val * 25.4

        # Integer-encoded with zero-suppression
        fi, fd = self.fmt
        total  = fi + fd
        raw    = raw.zfill(total)
        val    = float(raw[:-fd] + '.' + raw[-fd:]) if fd else float(raw)
        val    = -val if neg else val
        return val if self.unit_mm else val * 25.4
