"""
core/parser.py
──────────────
RS-274X / Gerber X2 parser.
Handles: apertures (C/R/O/P), D01/D02/D03, G01/G02/G03,
         G36/G37 regions, FSLAX format spec, MOMM/MOIN units,
         multi-block %...%  tokens, and Gerber X2 %TO.% attributes.
"""
from __future__ import annotations
import re
from typing import Optional
from .primitives import Aperture, GerberPrimitive


class GerberParser:
    def __init__(self, layer_name: str):
        self.layer_name   = layer_name
        self.apertures: dict[str, Aperture] = {}
        self.current_ap: Optional[Aperture] = None
        self.track_ap:   Optional[Aperture] = None   # aperture at track start
        self.primitives: list[GerberPrimitive] = []
        self.unit_mm      = True
        self.x = self.y   = 0.0
        self.fmt_int      = 2
        self.fmt_dec      = 6
        self.region_mode  = False
        self.region_pts:  list = []
        self.cur_track:   list = []
        self.abs_coords   = True
        # X2 current attributes
        self._net = self._ref = self._pin = ""

    # ── public ──────────────────────────────────────

    def parse(self, filepath: str) -> list[GerberPrimitive]:
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                raw = f.read()
        except OSError as e:
            print(f"  [WARN] {filepath}: {e}")
            return []

        raw = raw.replace('\r\n', '\n').replace('\r', '\n')
        tokens, buf = [], ''
        for line in raw.split('\n'):
            buf += line.strip()
            if buf.endswith('*'):
                tokens.append(buf[:-1])
                buf = ''
        if buf:
            tokens.append(buf)

        for tok in tokens:
            self._process_token(tok.strip())
        self._finish_track()

        for p in self.primitives:
            p.compute_bbox()
        return self.primitives

    # ── tokeniser ────────────────────────────────────

    def _process_token(self, tok: str):
        if not tok:
            return
        # Split concatenated %...% blocks (common in KiCad output)
        if '%' in tok:
            parts = re.split(r'(%[^%]*%)', tok)
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                if part.startswith('%') and part.endswith('%'):
                    self._process_extended(part[1:-1])
                else:
                    self._process_command(part)
            return
        self._process_command(tok)

    # ── extended commands (%...%) ─────────────────────

    def _process_extended(self, cmd: str):
        # Format spec
        if cmd.startswith('FS'):
            m = re.search(r'X(\d)(\d)', cmd)
            if m:
                self.fmt_int = int(m.group(1))
                self.fmt_dec = int(m.group(2))

        # Units
        elif 'MOMM' in cmd or cmd == 'MO,MM':
            self.unit_mm = True
        elif 'MOIN' in cmd or cmd == 'MO,IN':
            self.unit_mm = False

        # Aperture definition
        elif cmd.startswith('ADD'):
            m = re.match(r'ADD(\d+)([A-Z]),([\d.X/]+)', cmd)
            if m:
                code   = 'D' + m.group(1)
                shape  = m.group(2)
                params = [float(p) for p in
                          m.group(3).replace('X', ',').split(',') if p]
                self.apertures[code] = Aperture(shape=shape, params=params)

        # Gerber X2 object attributes
        elif cmd.startswith('TO.N,') or cmd.startswith('TO.N '):
            self._net = cmd[5:].strip().rstrip('*').strip('"')
        elif cmd.startswith('TO.C,') or cmd.startswith('TO.C '):
            self._ref = cmd[5:].strip().rstrip('*').strip('"')
        elif cmd.startswith('TO.P,'):
            # TO.P,<ref>,<pin>
            parts = cmd[5:].split(',', 2)
            if len(parts) >= 2:
                self._ref = parts[0].strip().rstrip('*').strip('"')
                self._pin = parts[1].strip().rstrip('*').strip('"')
        elif cmd.startswith('TD'):
            # Clear object attributes
            self._net = self._ref = self._pin = ""

    # ── drawing commands ──────────────────────────────

    def _process_command(self, cmd: str):
        if not cmd:
            return

        # G codes
        if cmd.startswith('G'):
            code = cmd[:3] if len(cmd) >= 3 else cmd
            if   code == 'G36':
                self.region_mode = True
                self._finish_track()
                self.region_pts = []
            elif code == 'G37':
                self._finish_region()
                self.region_mode = False
            elif code == 'G70': self.unit_mm = False
            elif code == 'G71': self.unit_mm = True
            elif code == 'G90': self.abs_coords = True
            elif code == 'G91': self.abs_coords = False
            rest = cmd[3:].strip()
            if rest:
                self._process_command(rest)
            return

        # Standalone D-code (aperture select)
        if re.match(r'^D\d+$', cmd):
            if cmd in self.apertures:
                self.current_ap = self.apertures[cmd]
            return

        # Coordinate + D01/D02/D03
        m = re.match(
            r'^(?:X([+-]?\d+))?(?:Y([+-]?\d+))?'
            r'(?:I([+-]?\d+))?(?:J([+-]?\d+))?(D0[123])', cmd)
        if m:
            xs, ys, _, _, dc = m.groups()
            nx = self._coord(xs) if xs else self.x
            ny = self._coord(ys) if ys else self.y

            if dc == 'D01':
                if self.region_mode:
                    if not self.region_pts:
                        self.region_pts.append((self.x, self.y))
                    self.region_pts.append((nx, ny))
                else:
                    if not self.cur_track:
                        self.cur_track.append((self.x, self.y))
                        self.track_ap = self.current_ap
                    self.cur_track.append((nx, ny))
            elif dc == 'D02':
                self._finish_track()
            elif dc == 'D03':
                self._finish_track()
                ap = self.current_ap
                self.primitives.append(GerberPrimitive(
                    kind='pad', layer=self.layer_name,
                    points=[(nx, ny)], aperture=ap,
                    net=self._net, ref=self._ref, pin=self._pin))
            self.x, self.y = nx, ny
            return

        # Coord + aperture select at end  (e.g. X1000Y2000D10)
        m2 = re.match(r'^(?:X([+-]?\d+))?(?:Y([+-]?\d+))?(D\d+)$', cmd)
        if m2:
            xs, ys, dc = m2.groups()
            if dc in self.apertures:
                self._finish_track()
                self.current_ap = self.apertures[dc]
            elif dc in ('D01', 'D02', 'D03'):
                self._process_command(
                    (f'X{xs}' if xs else '') + (f'Y{ys}' if ys else '') + dc)

    # ── helpers ───────────────────────────────────────

    def _coord(self, s: str) -> float:
        neg = s.startswith('-')
        digits = s.lstrip('-+').zfill(self.fmt_int + self.fmt_dec)
        fd = self.fmt_dec
        val = float(digits[:-fd] + '.' + digits[-fd:]) if fd else float(digits)
        val = -val if neg else val
        return val if self.unit_mm else val * 25.4

    def _finish_track(self):
        if len(self.cur_track) >= 2:
            ap = self.track_ap or self.current_ap
            w  = ap.params[0] if (ap and ap.shape == 'C' and ap.params) else 0.0
            self.primitives.append(GerberPrimitive(
                kind='track', layer=self.layer_name,
                points=list(self.cur_track), width=w, aperture=ap,
                net=self._net))
        self.cur_track  = []
        self.track_ap   = None

    def _finish_region(self):
        if len(self.region_pts) >= 3:
            self.primitives.append(GerberPrimitive(
                kind='region', layer=self.layer_name,
                points=list(self.region_pts),
                net=self._net))
        self.region_pts = []
