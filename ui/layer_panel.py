"""
ui/layer_panel.py
─────────────────
Left-side layer panel with lazy load/unload and eye toggle.
"""
from __future__ import annotations
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QCheckBox, QPushButton, QScrollArea, QFrame
)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import pyqtSignal, Qt
from ui.theme import Theme


class LayerRow(QWidget):
    loadToggled = pyqtSignal(str, bool)
    visToggled  = pyqtSignal(str, bool)

    def __init__(self, layer: str, display: str,
                 color: QColor, loaded: bool, theme: Theme):
        super().__init__()
        self.layer = layer
        self._theme = theme
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 1, 4, 1)
        lay.setSpacing(5)

        # Color swatch
        self._swatch = QLabel()
        self._swatch.setFixedSize(10, 10)
        r, g, b = color.red(), color.green(), color.blue()
        self._swatch.setStyleSheet(
            f"background: rgb({r},{g},{b}); border-radius: 2px;")
        lay.addWidget(self._swatch)

        # Load checkbox
        self._cb = QCheckBox(display)
        self._cb.setChecked(loaded)
        self._cb.setToolTip(f"Load / unload  {layer}")
        self._cb.toggled.connect(lambda v: self.loadToggled.emit(layer, v))
        lay.addWidget(self._cb, 1)

        # Eye button
        self._eye = QPushButton("●")
        self._eye.setFixedSize(18, 18)
        self._eye.setCheckable(True)
        self._eye.setChecked(True)
        self._eye.setToolTip("Toggle visibility")
        self._apply_eye_style(True)
        self._eye.toggled.connect(self._on_eye)
        lay.addWidget(self._eye)

    def _on_eye(self, checked: bool):
        self._apply_eye_style(checked)
        self.visToggled.emit(self.layer, checked)

    def _apply_eye_style(self, on: bool):
        c = self._theme.hex('accent') if on else self._theme.hex('panel_border')
        self._eye.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;"
            f"color:{c};font-size:10px;padding:0;}}")

    def set_loaded(self, v: bool):
        self._cb.blockSignals(True)
        self._cb.setChecked(v)
        self._cb.blockSignals(False)


class LayerPanel(QWidget):
    layerLoad   = pyqtSignal(str, bool)
    layerVis    = pyqtSignal(str, bool)

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setFixedWidth(240)
        self.setStyleSheet(theme.layer_panel_stylesheet())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QLabel("LAYERS")
        hdr.setObjectName("hdr")
        root.addWidget(hdr)

        sub = QLabel("  ✓ loaded    ○ available")
        sub.setObjectName("sub")
        root.addWidget(sub)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._inner  = QWidget()
        self._il     = QVBoxLayout(self._inner)
        self._il.setContentsMargins(2, 4, 2, 4)
        self._il.setSpacing(1)
        self._il.addStretch()
        self._scroll.setWidget(self._inner)
        root.addWidget(self._scroll)

        self._rows: dict[str, LayerRow] = {}

    def populate(self, descriptors):
        # clear
        while self._il.count() > 1:
            item = self._il.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows.clear()

        def section(text: str):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {self._theme.hex('panel_border')};"
                "font-size: 10px; padding: 6px 4px 2px 4px;"
                f"border-top: 1px solid {self._theme.hex('panel_border')};")
            return lbl

        defaults  = [d for d in descriptors if d.layer_def.default_load]
        optionals = [d for d in descriptors if not d.layer_def.default_load]

        pos = 0
        if defaults:
            self._il.insertWidget(pos, section("Default layers")); pos += 1
            for d in defaults:
                row = LayerRow(d.layer_name, d.layer_def.display,
                               d.layer_def._color_q(),
                               d.layer_def.default_load, self._theme)
                row.loadToggled.connect(self.layerLoad.emit)
                row.visToggled.connect(self.layerVis.emit)
                self._il.insertWidget(pos, row); pos += 1
                self._rows[d.layer_name] = row

        if optionals:
            self._il.insertWidget(pos, section("Optional layers")); pos += 1
            for d in optionals:
                row = LayerRow(d.layer_name, d.layer_def.display,
                               d.layer_def._color_q(), False, self._theme)
                row.loadToggled.connect(self.layerLoad.emit)
                row.visToggled.connect(self.layerVis.emit)
                self._il.insertWidget(pos, row); pos += 1
                self._rows[d.layer_name] = row

    def set_loaded(self, layer: str, v: bool):
        if layer in self._rows:
            self._rows[layer].set_loaded(v)
