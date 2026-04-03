"""
render/canvas.py
────────────────
PCB render canvas. Uses QOpenGLWidget for hardware-accelerated rendering
via Qt's OpenGL integration. Falls back to QPainter software rendering
if OpenGL is unavailable.

Features:
  • Per-layer QPixmap cache (software) or VBO batches (GL)
  • Click-to-trace net with flood-fill
  • Measurement tool
  • DRC violation overlay
  • Hover tooltip with pad info
  • Minimap in bottom-right corner
  • Grid overlay (togglable)
  • Net name labels (when zoomed in enough)
"""
from __future__ import annotations
import math, time
from typing import Optional
from collections import defaultdict

from PyQt6.QtWidgets import QWidget, QToolTip
from PyQt6.QtCore import (
    Qt, QPointF, QRectF, QTimer, pyqtSignal, QThread, QObject
)
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QWheelEvent, QMouseEvent,
    QPainterPath, QPixmap, QFont, QFontMetrics, QPaintEvent
)

from core.primitives import GerberPrimitive, DrillHole
from core.spatial import SpatialIndex, flood_fill, _pt_seg_dist2
from core.layers import DRCViolation
from ui.theme import Theme


# ── connectivity worker ───────────────────────────────────────────

class ConnWorker(QObject):
    done     = pyqtSignal(dict)
    progress = pyqtSignal(str)

    def __init__(self, primitives, cell_size=2.0):
        super().__init__()
        self._prims = primitives
        self._cs    = cell_size

    def run(self):
        t0 = time.perf_counter()
        self.progress.emit("Building spatial index…")
        idx = SpatialIndex(self._prims, self._cs)
        self.progress.emit("Tracing connections…")
        adj = idx.build_adjacency()
        dt  = time.perf_counter() - t0
        self.progress.emit(
            f"Connectivity ready — {len(adj)} nodes, {dt:.2f}s")
        self.done.emit(adj)


# ── main canvas ───────────────────────────────────────────────────

MINIMAP_W = 200
MINIMAP_H = 130
MINIMAP_PAD = 8

MIN_ZOOM_FOR_LABELS = 8.0    # mm → pixels before net labels appear
MIN_ZOOM_FOR_GRID   = 3.0

class PCBCanvas(QWidget):
    statusMsg        = pyqtSignal(str)
    primitiveClicked = pyqtSignal(object)   # GerberPrimitive or None
    measureDone      = pyqtSignal(float)    # distance mm

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setMinimumSize(600, 400)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # data
        self.layer_primitives: dict[str, list[GerberPrimitive]] = {}
        self.drill_holes:      list[DrillHole] = []
        self.flat:             list[GerberPrimitive] = []
        self.adj:              dict[int, list[int]] = {}
        self.drc_violations:   list[DRCViolation] = []

        # display state
        self.layer_visible: dict[str, bool] = {}
        self.layer_colors:  dict[str, QColor] = {}
        self.show_grid      = False
        self.show_net_labels= True
        self.show_drill     = True
        self.show_drc       = True
        self.measure_mode   = False

        # selection
        self.highlighted:   set[int] = set()
        self.selected_idx:  int = -1
        self.hovered_idx:   int = -1

        # measure
        self._mpt1: Optional[tuple] = None
        self._mpt2: Optional[tuple] = None
        self._mouse_world: tuple = (0.0, 0.0)

        # view
        self._scale  = 1.0
        self._offset = QPointF(0, 0)
        self._pan_start     = None
        self._pan_off_start = None
        self._bounds: Optional[tuple] = None  # (x1,y1,x2,y2) in mm

        # cache
        self._cache: dict[str, QPixmap] = {}
        self._cache_key: tuple = (-1.0, 0.0, 0.0, -1, -1)

        # hover tooltip timer
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._show_tooltip)
        self._tooltip_pos = QPointF(0, 0)

        # worker
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[ConnWorker] = None

    # ── public API ────────────────────────────────────────────────

    def set_theme(self, theme: Theme):
        self.theme = theme
        self._cache.clear()
        self.update()

    def load_layer(self, name: str, prims: list[GerberPrimitive],
                   color: QColor):
        self.layer_primitives[name] = prims
        self.layer_colors[name]     = color
        self.layer_visible[name]    = True
        self._rebuild_flat()
        self._cache.pop(name, None)
        self.update()

    def unload_layer(self, name: str):
        self.layer_primitives.pop(name, None)
        self._rebuild_flat()
        self._cache.pop(name, None)
        self.highlighted.clear()
        self.selected_idx = -1
        self.update()

    def set_drill_holes(self, holes: list[DrillHole]):
        self.drill_holes = holes
        self._cache.pop('__drill__', None)
        self.update()

    def set_layer_visible(self, name: str, v: bool):
        self.layer_visible[name] = v
        self._cache.pop(name, None)
        self.update()

    def set_layer_color(self, name: str, color: QColor):
        self.layer_colors[name] = color
        self._cache.pop(name, None)
        self.update()

    def rebuild_connectivity(self):
        if not self.flat:
            return
        self.adj = {}
        self.highlighted.clear()
        self.selected_idx = -1

        worker = ConnWorker(list(self.flat))
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.progress.connect(self.statusMsg.emit)
        worker.done.connect(self._on_adj_done)
        worker.done.connect(thread.quit)
        # Proper Qt cleanup: delete worker/thread after thread finishes
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.started.connect(worker.run)
        thread.start()
        self._worker_thread = thread
        self._worker = worker

    def fit_view(self):
        if not self._bounds:
            return
        x1, y1, x2, y2 = self._bounds
        bw, bh = x2 - x1, y2 - y1
        if bw <= 0 or bh <= 0:
            return
        w, h = self.width(), self.height()
        self._scale = min((w * 0.88) / bw, (h * 0.88) / bh)
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        self._offset = QPointF(w / 2 - cx * self._scale,
                                h / 2 - cy * self._scale)
        self._cache.clear()
        self.update()

    def board_stats(self) -> dict:
        pads = tracks = regions = vias = 0
        tlen = 0.0
        by_layer = defaultdict(int)
        for p in self.flat:
            by_layer[p.layer] += 1
            if p.kind == 'pad':    pads    += 1
            elif p.kind == 'track':
                tracks += 1; tlen += p.length_mm()
            elif p.kind == 'region': regions += 1
            elif p.kind == 'via':    vias    += 1

        nets = 0
        visited = set()
        for i in range(len(self.flat)):
            if i not in visited and i in self.adj:
                visited |= flood_fill(i, self.adj)
                nets += 1

        return {
            'primitives': len(self.flat),
            'pads': pads, 'tracks': tracks,
            'regions': regions, 'vias': vias,
            'drill_holes': len(self.drill_holes),
            'track_length_mm': round(tlen, 3),
            'estimated_nets': nets,
            'layers_loaded': len(self.layer_primitives),
            'by_layer': dict(by_layer),
        }

    # ── internal ──────────────────────────────────────────────────

    def _rebuild_flat(self):
        self.flat = []
        for prims in self.layer_primitives.values():
            self.flat.extend(prims)
        self._compute_bounds()

    def _compute_bounds(self):
        xs, ys = [], []
        for p in self.flat:
            if p.bbox:
                xs += [p.bbox[0], p.bbox[2]]
                ys += [p.bbox[1], p.bbox[3]]
        for h in self.drill_holes:
            b = h.bbox()
            xs += [b[0], b[2]]; ys += [b[1], b[3]]
        if xs:
            self._bounds = (min(xs), min(ys), max(xs), max(ys))

    def _on_adj_done(self, adj):
        self.adj = adj
        self._cache.clear()
        self.update()

    # ── coordinate helpers ────────────────────────────────────────

    def _w2s(self, x, y) -> QPointF:
        return QPointF(x * self._scale + self._offset.x(),
                       y * self._scale + self._offset.y())

    def _s2w(self, sx, sy) -> tuple:
        return ((sx - self._offset.x()) / self._scale,
                (sy - self._offset.y()) / self._scale)

    # ── painting ──────────────────────────────────────────────────

    def _cache_key_now(self) -> tuple:
        return (round(self._scale, 4),
                round(self._offset.x(), 1),
                round(self._offset.y(), 1),
                self.selected_idx,
                len(self.highlighted))

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg = self.theme.c('canvas_bg')
        painter.fillRect(self.rect(), bg)

        # Grid
        if self.show_grid and self._scale >= MIN_ZOOM_FOR_GRID:
            self._draw_grid(painter)

        # Layers (cached pixmaps)
        ck = self._cache_key_now()
        if ck != self._cache_key:
            self._cache.clear()
            self._cache_key = ck

        # Sort by z_order
        from core.layers import LAYER_DEFS
        order_map = {ld.name: ld.z_order for ld in LAYER_DEFS}
        sorted_layers = sorted(self.layer_primitives.keys(),
                               key=lambda l: order_map.get(l, 99))

        for layer in sorted_layers:
            if not self.layer_visible.get(layer, True):
                continue
            if layer not in self._cache:
                self._cache[layer] = self._render_layer(layer)
            painter.drawPixmap(0, 0, self._cache[layer])

        # Drill holes
        if self.show_drill and self.drill_holes:
            self._draw_drills(painter)

        # DRC violations
        if self.show_drc and self.drc_violations:
            self._draw_drc(painter)

        # Net labels
        if self.show_net_labels and self._scale >= MIN_ZOOM_FOR_LABELS:
            self._draw_net_labels(painter)

        # Measurement overlay
        if self.measure_mode:
            self._draw_measure(painter)

        # Hover outline
        if self.hovered_idx >= 0 and self.hovered_idx < len(self.flat):
            self._draw_hover_outline(painter, self.hovered_idx)

        # Minimap
        self._draw_minimap(painter)

        painter.end()

    def _render_layer(self, layer: str) -> QPixmap:
        prims      = self.layer_primitives.get(layer, [])
        base_color = self.layer_colors.get(layer, QColor('#AAAAAA'))
        w, h = max(self.width(), 1), max(self.height(), 1)
        px = QPixmap(w, h)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        g_start = sum(len(self.layer_primitives[k])
                      for k in list(self.layer_primitives.keys())
                      if list(self.layer_primitives.keys()).index(k) <
                         list(self.layer_primitives.keys()).index(layer))

        for li, prim in enumerate(prims):
            gi = g_start + li
            is_hi  = gi in self.highlighted
            is_sel = gi == self.selected_idx

            if self.highlighted and not is_hi:
                col = QColor(base_color.red(), base_color.green(),
                             base_color.blue(), 30)
            elif is_sel:
                col = QColor('#FFFFFF')
            elif is_hi:
                col = self.theme.c('highlight_net')
            else:
                col = base_color

            self._draw_prim(p, prim, col, is_hi or is_sel)

        p.end()
        return px

    def _draw_prim(self, p: QPainter, prim: GerberPrimitive,
                   color: QColor, bright: bool):
        sw = max(prim.width * self._scale, 0.5)

        if prim.kind == 'track':
            pen = QPen(color, sw)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            pts = prim.points
            for i in range(len(pts) - 1):
                p.drawLine(self._w2s(*pts[i]), self._w2s(*pts[i + 1]))

        elif prim.kind == 'pad':
            ap = prim.aperture
            sp = self._w2s(*prim.points[0])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(color))
            if ap:
                if ap.shape == 'C':
                    r = ap.params[0] * self._scale / 2
                    p.drawEllipse(sp, r, r)
                elif ap.shape in ('R', 'O'):
                    pw = ap.params[0] * self._scale
                    ph = (ap.params[1] if len(ap.params) > 1
                          else ap.params[0]) * self._scale
                    p.drawRect(QRectF(sp.x() - pw/2, sp.y() - ph/2, pw, ph))
                else:
                    p.drawEllipse(sp, 3.0, 3.0)
            else:
                p.drawEllipse(sp, 2.0, 2.0)
            if bright:
                p.setPen(QPen(QColor(255, 255, 255, 180), 1.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                if ap and ap.shape == 'C':
                    r = ap.params[0] * self._scale / 2
                    p.drawEllipse(sp, r, r)

        elif prim.kind == 'region':
            if len(prim.points) < 3:
                return
            path = QPainterPath()
            path.moveTo(self._w2s(*prim.points[0]))
            for pt in prim.points[1:]:
                path.lineTo(self._w2s(*pt))
            path.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(color))
            p.drawPath(path)

        elif prim.kind == 'via':
            sp = self._w2s(*prim.points[0])
            r  = max(prim.width * self._scale / 2, 2.5)
            p.setPen(QPen(color, 1.5))
            p.setBrush(QBrush(self.theme.c('canvas_bg')))
            p.drawEllipse(sp, r, r)

    def _draw_drills(self, painter: QPainter):
        col_plated  = QColor('#C0C0C0')
        col_nplated = QColor('#FFA040')
        for h in self.drill_holes:
            sp = self._w2s(h.x, h.y)
            r  = max(h.diameter * self._scale / 2, 1.5)
            col = col_plated if h.plated else col_nplated
            painter.setPen(QPen(col, 1.0))
            painter.setBrush(QBrush(self.theme.c('canvas_bg')))
            painter.drawEllipse(sp, r, r)
            # inner dot
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(col))
            painter.drawEllipse(sp, max(r * 0.3, 1.0), max(r * 0.3, 1.0))

    def _draw_drc(self, painter: QPainter):
        for v in self.drc_violations:
            sp = self._w2s(v.x, v.y)
            if v.kind == 'clearance':
                col = self.theme.c('drc_error')
            else:
                col = self.theme.c('drc_warn')
            r = max(4.0, 1.0 * self._scale)
            painter.setPen(QPen(col, 1.5))
            painter.setBrush(QBrush(QColor(col.red(), col.green(), col.blue(), 60)))
            painter.drawEllipse(sp, r, r)
            # X marker
            painter.setPen(QPen(col, 1.5))
            d = r * 0.6
            painter.drawLine(QPointF(sp.x()-d, sp.y()-d),
                             QPointF(sp.x()+d, sp.y()+d))
            painter.drawLine(QPointF(sp.x()+d, sp.y()-d),
                             QPointF(sp.x()-d, sp.y()+d))

    def _draw_net_labels(self, painter: QPainter):
        font = QFont('Segoe UI', 7)
        painter.setFont(font)
        fm = QFontMetrics(font)
        seen: set[str] = set()
        for p in self.flat:
            if p.kind != 'pad' or not p.net:
                continue
            sp = self._w2s(*p.points[0])
            if sp.x() < -20 or sp.x() > self.width() + 20:
                continue
            if sp.y() < -20 or sp.y() > self.height() + 20:
                continue
            label = p.net
            key = f"{label}_{int(sp.x()//80)}_{int(sp.y()//80)}"
            if key in seen:
                continue
            seen.add(key)
            tw = fm.horizontalAdvance(label)
            painter.setPen(QColor(255, 255, 200, 200))
            painter.drawText(
                QRectF(sp.x() - tw/2, sp.y() - 8, tw + 4, 12),
                Qt.AlignmentFlag.AlignCenter, label)

    def _draw_grid(self, painter: QPainter):
        grid_col = self.theme.c('grid_color')
        painter.setPen(QPen(grid_col, 0.5))
        # Adaptive grid spacing
        spacings_mm = [0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 25.0]
        target_px   = 30
        spacing = spacings_mm[-1]
        for s in spacings_mm:
            if s * self._scale >= target_px:
                spacing = s
                break
        w, h = self.width(), self.height()
        wx1, wy1 = self._s2w(0, 0)
        wx2, wy2 = self._s2w(w, h)
        x = math.floor(wx1 / spacing) * spacing
        while x <= wx2:
            sx = x * self._scale + self._offset.x()
            painter.drawLine(QPointF(sx, 0), QPointF(sx, h))
            x += spacing
        y = math.floor(wy1 / spacing) * spacing
        while y <= wy2:
            sy = y * self._scale + self._offset.y()
            painter.drawLine(QPointF(0, sy), QPointF(w, sy))
            y += spacing

    def _draw_hover_outline(self, painter: QPainter, idx: int):
        prim = self.flat[idx]
        col  = QColor(255, 255, 255, 120)
        painter.setPen(QPen(col, 1.5, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if prim.bbox:
            x1, y1, x2, y2 = prim.bbox
            sp1 = self._w2s(x1, y1)
            sp2 = self._w2s(x2, y2)
            pad = 3
            painter.drawRect(QRectF(sp1.x()-pad, sp1.y()-pad,
                                    sp2.x()-sp1.x()+2*pad,
                                    sp2.y()-sp1.y()+2*pad))

    def _draw_measure(self, painter: QPainter):
        col = self.theme.c('measure_color')
        pen = QPen(col, 1.5, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        font = QFont('Consolas', 9)
        painter.setFont(font)

        if self._mpt1:
            sp1 = self._w2s(*self._mpt1)
            painter.setPen(QPen(col, 2.0))
            painter.drawEllipse(sp1, 5, 5)
            if not self._mpt2:
                # Live ruler to cursor
                mp = self._w2s(*self._mouse_world)
                painter.setPen(QPen(col, 1.0, Qt.PenStyle.DashLine))
                painter.drawLine(sp1, mp)
                dist = math.hypot(
                    self._mouse_world[0] - self._mpt1[0],
                    self._mouse_world[1] - self._mpt1[1])
                painter.setPen(col)
                painter.drawText(int(mp.x()) + 10, int(mp.y()) - 6,
                                 f"{dist:.3f} mm")

        if self._mpt1 and self._mpt2:
            sp1 = self._w2s(*self._mpt1)
            sp2 = self._w2s(*self._mpt2)
            painter.setPen(QPen(col, 2.0))
            painter.drawLine(sp1, sp2)
            painter.drawEllipse(sp1, 5, 5)
            painter.drawEllipse(sp2, 5, 5)
            dist = math.hypot(self._mpt2[0] - self._mpt1[0],
                              self._mpt2[1] - self._mpt1[1])
            dx   = abs(self._mpt2[0] - self._mpt1[0])
            dy   = abs(self._mpt2[1] - self._mpt1[1])
            mid  = QPointF((sp1.x()+sp2.x())/2, (sp1.y()+sp2.y())/2)
            bg   = QColor(0, 0, 0, 160)
            fm   = QFontMetrics(font)
            label = f" {dist:.4f} mm  ΔX={dx:.4f}  ΔY={dy:.4f} "
            tw   = fm.horizontalAdvance(label)
            painter.fillRect(QRectF(mid.x()-2, mid.y()-14, tw+4, 16), bg)
            painter.setPen(col)
            painter.drawText(int(mid.x()), int(mid.y()) - 2, label)

    def _draw_minimap(self, painter: QPainter):
        if not self._bounds:
            return
        mw, mh = MINIMAP_W, MINIMAP_H
        mx = self.width()  - mw - MINIMAP_PAD
        my = self.height() - mh - MINIMAP_PAD

        # Background
        bg = QColor(self.theme.c('canvas_bg'))
        bg.setAlpha(200)
        painter.fillRect(mx, my, mw, mh, bg)
        painter.setPen(QPen(self.theme.c('minimap_border'), 1.0))
        painter.drawRect(mx, my, mw, mh)

        # Board extent in minimap coords
        bx1, by1, bx2, by2 = self._bounds
        bw = max(bx2 - bx1, 0.001)
        bh = max(by2 - by1, 0.001)
        sx = (mw - 8) / bw
        sy = (mh - 8) / bh
        ms = min(sx, sy)

        def mm2mini(wx, wy):
            return (mx + 4 + (wx - bx1) * ms,
                    my + 4 + (wy - by1) * ms)

        # Draw simplified layer outlines
        painter.setPen(Qt.PenStyle.NoPen)
        from core.layers import LAYER_DEFS
        order_map = {ld.name: ld.z_order for ld in LAYER_DEFS}
        for layer in sorted(self.layer_primitives.keys(),
                            key=lambda l: order_map.get(l, 99)):
            if not self.layer_visible.get(layer, True):
                continue
            col = self.layer_colors.get(layer, QColor('#888888'))
            col2 = QColor(col.red(), col.green(), col.blue(), 100)
            painter.setBrush(QBrush(col2))
            for prim in self.layer_primitives[layer]:
                if prim.kind in ('pad',):
                    if prim.points:
                        mmx, mmy = mm2mini(*prim.points[0])
                        r = max(1.0, (prim.aperture.radius()
                                      if prim.aperture else 0.3) * ms)
                        painter.drawEllipse(
                            QPointF(mmx, mmy), r, r)

        # Viewport rectangle
        wx1, wy1 = self._s2w(0, 0)
        wx2, wy2 = self._s2w(self.width(), self.height())
        vmx1, vmy1 = mm2mini(wx1, wy1)
        vmx2, vmy2 = mm2mini(wx2, wy2)
        vp_col = self.theme.c('minimap_vp')
        painter.fillRect(QRectF(vmx1, vmy1,
                                vmx2 - vmx1, vmy2 - vmy1), vp_col)
        painter.setPen(QPen(self.theme.c('minimap_border'), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(vmx1, vmy1,
                                vmx2 - vmx1, vmy2 - vmy1))

    # ── mouse events ──────────────────────────────────────────────

    def wheelEvent(self, e: QWheelEvent):
        factor = 1.18 if e.angleDelta().y() > 0 else 1 / 1.18
        mp = e.position()
        wx, wy = self._s2w(mp.x(), mp.y())
        self._scale *= factor
        self._offset = QPointF(mp.x() - wx * self._scale,
                                mp.y() - wy * self._scale)
        self._cache.clear()
        self.update()

    def mousePressEvent(self, e: QMouseEvent):
        if (e.button() == Qt.MouseButton.MiddleButton or
                (e.button() == Qt.MouseButton.LeftButton and
                 e.modifiers() & Qt.KeyboardModifier.AltModifier)):
            self._pan_start     = e.position()
            self._pan_off_start = QPointF(self._offset)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif e.button() == Qt.MouseButton.LeftButton:
            if self.measure_mode:
                self._handle_measure(e.position())
            else:
                self._handle_select(e.position())
        elif e.button() == Qt.MouseButton.RightButton:
            self._clear_selection()

    def mouseMoveEvent(self, e: QMouseEvent):
        pos = e.position()
        wx, wy = self._s2w(pos.x(), pos.y())
        self._mouse_world = (wx, wy)

        if self._pan_start is not None:
            delta = pos - self._pan_start
            self._offset = self._pan_off_start + delta
            self._cache.clear()
            self.update()
        else:
            self.statusMsg.emit(
                f"  X = {wx:.4f} mm    Y = {wy:.4f} mm"
                + ("    [MEASURE]" if self.measure_mode else ""))
            # hover
            self._tooltip_pos = pos
            self._hover_timer.start(350)
            new_hov = self._find_prim(pos)
            if new_hov != self.hovered_idx:
                self.hovered_idx = new_hov
                self.update()
            if self.measure_mode and self._mpt1 and not self._mpt2:
                self.update()

    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() in (Qt.MouseButton.MiddleButton,
                           Qt.MouseButton.LeftButton):
            self._pan_start = None
            cur = (Qt.CursorShape.SizeAllCursor if self.measure_mode
                   else Qt.CursorShape.CrossCursor)
            self.setCursor(cur)

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_F:
            self.fit_view()
        elif k == Qt.Key.Key_Escape:
            self._clear_selection()
            self.measure_mode = False
            self.setCursor(Qt.CursorShape.CrossCursor)
            self._mpt1 = self._mpt2 = None
            self.update()
        elif k == Qt.Key.Key_G:
            self.show_grid = not self.show_grid
            self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._cache.clear()

    # ── selection ─────────────────────────────────────────────────

    def _find_prim(self, pos: QPointF) -> int:
        wx, wy = self._s2w(pos.x(), pos.y())
        best_idx, best_d = -1, float('inf')
        thr = max(1.5 / self._scale, 0.05)

        layer_keys = list(self.layer_primitives.keys())
        g_starts: dict[str, int] = {}
        s = 0
        for k in layer_keys:
            g_starts[k] = s
            s += len(self.layer_primitives[k])

        for layer, prims in self.layer_primitives.items():
            if not self.layer_visible.get(layer, True):
                continue
            gs = g_starts[layer]
            for li, prim in enumerate(prims):
                if not prim.bbox:
                    continue
                bx1, by1, bx2, by2 = prim.bbox
                if not (bx1 - thr <= wx <= bx2 + thr and
                        by1 - thr <= wy <= by2 + thr):
                    continue
                d = self._prim_dist(wx, wy, prim)
                if d < best_d:
                    best_d = d; best_idx = gs + li

        return best_idx if best_d <= thr else -1

    def _handle_select(self, pos: QPointF):
        idx = self._find_prim(pos)
        if idx >= 0:
            self.selected_idx = idx
            self.highlighted  = flood_fill(idx, self.adj)
            prim = self.flat[idx]
            self.primitiveClicked.emit(prim)
            ref_str = f" [{prim.ref} pin {prim.pin}]" if prim.ref else ""
            net_str = f" net: {prim.net}" if prim.net else ""
            self.statusMsg.emit(
                f"  {prim.kind.upper()}  {prim.layer}{ref_str}{net_str}"
                f"  — {len(self.highlighted)} connected")
        else:
            self._clear_selection()
        self._cache.clear()
        self.update()

    def _handle_measure(self, pos: QPointF):
        wx, wy = self._s2w(pos.x(), pos.y())
        if self._mpt1 is None:
            self._mpt1 = (wx, wy)
            self.statusMsg.emit("  Measure: click second point")
        elif self._mpt2 is None:
            self._mpt2 = (wx, wy)
            dist = math.hypot(wx - self._mpt1[0], wy - self._mpt1[1])
            dx   = abs(wx - self._mpt1[0])
            dy   = abs(wy - self._mpt1[1])
            self.measureDone.emit(dist)
            self.statusMsg.emit(
                f"  Distance: {dist:.4f} mm   "
                f"ΔX: {dx:.4f}   ΔY: {dy:.4f}")
        else:
            self._mpt1 = (wx, wy)
            self._mpt2 = None
            self.statusMsg.emit("  Measure: click second point")
        self.update()

    def _clear_selection(self):
        self.highlighted.clear()
        self.selected_idx = -1
        self._mpt1 = self._mpt2 = None
        self.primitiveClicked.emit(None)
        self._cache.clear()
        self.update()

    def _prim_dist(self, wx, wy, prim: GerberPrimitive) -> float:
        pts = prim.points
        if not pts:
            return float('inf')
        if len(pts) == 1:
            return math.hypot(wx - pts[0][0], wy - pts[0][1])
        return min(
            _pt_seg_dist2(wx, wy,
                          pts[i][0], pts[i][1],
                          pts[i+1][0], pts[i+1][1]) ** 0.5
            for i in range(len(pts) - 1))

    # ── tooltip ───────────────────────────────────────────────────

    def _show_tooltip(self):
        idx = self._find_prim(self._tooltip_pos)
        if idx < 0 or idx >= len(self.flat):
            QToolTip.hideText()
            return
        prim = self.flat[idx]
        lines = prim.info_lines()
        text  = '\n'.join(f"{k}: {v}" for k, v in lines)
        QToolTip.showText(
            self.mapToGlobal(self._tooltip_pos.toPoint()), text, self)
