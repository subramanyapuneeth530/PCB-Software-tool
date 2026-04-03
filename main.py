"""
main.py  —  PCB Gerber Viewer Pro
──────────────────────────────────────────────────────────────────
Professional-grade Gerber PCB viewer.
Entry point: python main.py
──────────────────────────────────────────────────────────────────
"""
from __future__ import annotations
import sys, os, json, time
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QSplitter, QStatusBar,
    QDialog, QTextEdit, QTabWidget, QProgressBar, QMessageBox,
    QSpinBox, QDoubleSpinBox, QFormLayout, QDialogButtonBox,
    QToolBar, QMenu, QMenuBar, QComboBox, QScrollArea, QFrame,
    QGroupBox, QGridLayout
)
from PyQt6.QtCore import Qt, QPointF, QTimer, pyqtSignal, QThread, QSettings
from PyQt6.QtGui import (
    QColor, QIcon, QAction, QKeySequence, QPainter, QPixmap, QFont
)

from core.primitives import GerberPrimitive
from core.parser     import GerberParser
from core.drill_parser import ExcellonParser
from core.layers     import (
    scan_folder, FileDesc, LayerDef, LAYER_DEFS, run_drc, DRCViolation
)
from core.spatial    import flood_fill
from render.canvas   import PCBCanvas
from ui.theme        import Theme, THEMES
from ui.layer_panel  import LayerPanel


# ── patch LayerDef with QColor helper ─────────────────────────────

def _ld_color_q(self) -> QColor:
    return QColor(self.color)
LayerDef._color_q = _ld_color_q   # type: ignore


# ── Settings path ─────────────────────────────────────────────────

SETTINGS_ORG  = "PCBViewerPro"
SETTINGS_APP  = "GerberViewer"
MAX_RECENT    = 8


# ── Splash screen ─────────────────────────────────────────────────

class SplashScreen(QDialog):
    def __init__(self):
        super().__init__(None,
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint)
        self.setFixedSize(520, 280)
        self.setStyleSheet("""
            QDialog { background: #0D0D1A; border: 2px solid #E8A020; }
            QLabel  { color: #E0E0E0; }
            QProgressBar {
                background: #131325; border: 1px solid #252545;
                border-radius: 4px; height: 6px;
            }
            QProgressBar::chunk { background: #E8A020; border-radius: 3px; }
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 30, 40, 30)

        title = QLabel("PCB Gerber Viewer Pro")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #E8A020;")
        lay.addWidget(title)

        sub = QLabel("Professional Gerber PCB Inspection Tool")
        sub.setStyleSheet("font-size: 12px; color: #8090A0;")
        lay.addWidget(sub)
        lay.addSpacing(20)

        self._status = QLabel("Initialising…")
        self._status.setStyleSheet("font-size: 11px; color: #A0B0C0; font-family: Consolas;")
        lay.addWidget(self._status)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        lay.addWidget(self._bar)
        lay.addSpacing(16)

        ver = QLabel("v3.0  |  RS-274X · Gerber X2 · Excellon  |  © 2025")
        ver.setStyleSheet("font-size: 10px; color: #404060;")
        lay.addWidget(ver, alignment=Qt.AlignmentFlag.AlignRight)

    def set_progress(self, pct: int, text: str):
        self._bar.setValue(pct)
        self._status.setText(text)
        QApplication.processEvents()


# ── Info / Stats panel ────────────────────────────────────────────

class InfoPanel(QWidget):
    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setMinimumWidth(230)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        hdr = QLabel("INFO")
        hdr.setStyleSheet(
            f"font-size:12px; font-weight:bold; color:{theme.hex('accent2')};"
            f"padding:6px 8px 4px; border-bottom:1px solid {theme.hex('accent2')};")
        lay.addWidget(hdr)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea{border:none;}")
        self._inner = QWidget()
        self._il = QVBoxLayout(self._inner)
        self._il.setContentsMargins(8, 8, 8, 8)
        self._il.setSpacing(2)
        self._il.addStretch()
        self._scroll.setWidget(self._inner)
        lay.addWidget(self._scroll)

        self._empty = QLabel("  Click any element\n  to see its properties.")
        self._empty.setStyleSheet(f"color:{theme.hex('panel_border')}; padding:12px;")
        self._il.insertWidget(0, self._empty)

    def show_primitive(self, prim):
        self._clear()
        if prim is None:
            self._empty.show(); return
        self._empty.hide()
        pos = 0
        for k, v in prim.info_lines():
            lk = QLabel(k + ":")
            lk.setStyleSheet(f"color:{self._theme.hex('panel_border')}; "
                             "font-size:10px; padding:1px 0;")
            lv = QLabel(str(v))
            lv.setStyleSheet(f"color:{self._theme.hex('window_text')}; "
                             "font-size:11px; padding:1px 0 3px 10px;")
            lv.setWordWrap(True)
            lv.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            self._il.insertWidget(pos, lk); pos += 1
            self._il.insertWidget(pos, lv); pos += 1

    def show_stats(self, stats: dict):
        self._clear()
        self._empty.hide()
        fields = [
            ("Total primitives", stats.get('primitives', 0)),
            ("Pads",             stats.get('pads', 0)),
            ("Tracks",          stats.get('tracks', 0)),
            ("Regions",         stats.get('regions', 0)),
            ("Vias",            stats.get('vias', 0)),
            ("Drill holes",     stats.get('drill_holes', 0)),
            ("Track length",    f"{stats.get('track_length_mm', 0):.2f} mm"),
            ("Estimated nets",  stats.get('estimated_nets', 0)),
            ("Layers loaded",   stats.get('layers_loaded', 0)),
        ]
        pos = 0
        for k, v in fields:
            lk = QLabel(k + ":")
            lk.setStyleSheet(f"color:{self._theme.hex('panel_border')}; font-size:10px;")
            lv = QLabel(str(v))
            lv.setStyleSheet(f"color:{self._theme.hex('accent')}; "
                             "font-size:12px; font-weight:bold; padding:0 0 4px 10px;")
            self._il.insertWidget(pos, lk); pos += 1
            self._il.insertWidget(pos, lv); pos += 1

    def _clear(self):
        while self._il.count() > 1:
            item = self._il.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._il.insertWidget(0, self._empty)


# ── DRC dialog ────────────────────────────────────────────────────

class DRCDialog(QDialog):
    def __init__(self, violations: list[DRCViolation], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"DRC Results — {len(violations)} violations")
        self.setMinimumSize(700, 450)
        lay = QVBoxLayout(self)
        te  = QTextEdit()
        te.setReadOnly(True)
        te.setFont(QFont('Consolas', 10))
        lines = ["DRC REPORT", "=" * 60, ""]
        if not violations:
            lines.append("  ✓  No violations found.")
        else:
            err = [v for v in violations if v.kind == 'clearance']
            warn = [v for v in violations if v.kind == 'min_width']
            lines.append(f"  Errors:   {len(err)}")
            lines.append(f"  Warnings: {len(warn)}")
            lines.append("")
            for v in violations:
                icon = "✗" if v.kind == 'clearance' else "⚠"
                lines.append(f"  {icon}  {v.message}")
                lines.append(f"      at ({v.x:.3f}, {v.y:.3f}) mm")
                lines.append("")
        te.setPlainText('\n'.join(lines))
        lay.addWidget(te)
        btn = QPushButton("Close")
        btn.clicked.connect(self.accept)
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)


# ── DRC settings dialog ───────────────────────────────────────────

class DRCSettingsDialog(QDialog):
    def __init__(self, min_clear=0.1, min_track=0.05, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DRC Settings")
        self.setFixedSize(340, 160)
        lay = QFormLayout(self)
        self._clear = QDoubleSpinBox()
        self._clear.setRange(0.01, 5.0)
        self._clear.setSingleStep(0.01)
        self._clear.setSuffix(" mm")
        self._clear.setValue(min_clear)
        self._track = QDoubleSpinBox()
        self._track.setRange(0.01, 5.0)
        self._track.setSingleStep(0.01)
        self._track.setSuffix(" mm")
        self._track.setValue(min_track)
        lay.addRow("Min clearance:", self._clear)
        lay.addRow("Min track width:", self._track)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addRow(btns)

    @property
    def values(self):
        return self._clear.value(), self._track.value()


# ── Main Window ───────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._settings   = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self._theme      = Theme(self._settings.value('theme', 'dark'))
        self._folder     = ""
        self._descriptors: list[FileDesc] = []
        self._loaded: set[str] = set()
        self._netlist_path = ""
        self._drc_min_clear = 0.1
        self._drc_min_track = 0.05

        self.setWindowTitle("PCB Gerber Viewer Pro")
        self.setMinimumSize(1280, 800)
        self._theme.apply_palette(QApplication.instance())
        self.setStyleSheet(self._theme.main_stylesheet())

        self._build_menu()
        self._build_toolbar()
        self._build_central()
        self._build_status()
        self._restore_geometry()

    # ── geometry ──────────────────────────────────────────────────

    def _restore_geometry(self):
        geom = self._settings.value('geometry')
        if geom:
            self.restoreGeometry(geom)
        else:
            self.resize(1400, 860)

    def closeEvent(self, e):
        self._settings.setValue('geometry', self.saveGeometry())
        self._settings.setValue('theme', self._theme.name)
        super().closeEvent(e)

    # ── menu bar ──────────────────────────────────────────────────

    def _build_menu(self):
        mb = self.menuBar()

        # File
        fm = mb.addMenu("&File")
        a_open = QAction("&Open Folder…", self)
        a_open.setShortcut(QKeySequence("Ctrl+O"))
        a_open.triggered.connect(self._open_folder)
        fm.addAction(a_open)

        self._recent_menu = fm.addMenu("Recent Folders")
        self._rebuild_recent_menu()
        fm.addSeparator()

        a_export_png = QAction("Export PNG…", self)
        a_export_png.triggered.connect(self._export_png)
        fm.addAction(a_export_png)

        a_export_svg = QAction("Export SVG…", self)
        a_export_svg.triggered.connect(self._export_svg)
        fm.addAction(a_export_svg)

        fm.addSeparator()
        a_quit = QAction("&Quit", self)
        a_quit.setShortcut(QKeySequence("Ctrl+Q"))
        a_quit.triggered.connect(self.close)
        fm.addAction(a_quit)

        # View
        vm = mb.addMenu("&View")
        a_fit = QAction("Fit Board  [F]", self)
        a_fit.setShortcut(QKeySequence("F"))
        a_fit.triggered.connect(self._fit)
        vm.addAction(a_fit)

        a_grid = QAction("Toggle Grid  [G]", self)
        a_grid.triggered.connect(lambda: self._canvas.keyPressEvent(
            type('E', (), {'key': lambda s: Qt.Key.Key_G})()))
        vm.addAction(a_grid)

        vm.addSeparator()
        self._theme_menu = vm.addMenu("Theme")
        for t in THEMES:
            a = QAction(t.replace('_', ' ').title(), self)
            a.triggered.connect(lambda _, tn=t: self._set_theme(tn))
            self._theme_menu.addAction(a)

        # Analysis
        am = mb.addMenu("&Analysis")
        a_stats = QAction("Board &Statistics", self)
        a_stats.triggered.connect(self._show_stats)
        am.addAction(a_stats)

        a_drc = QAction("Run &DRC…", self)
        a_drc.setShortcut(QKeySequence("Ctrl+D"))
        a_drc.triggered.connect(self._run_drc)
        am.addAction(a_drc)

        a_drc_set = QAction("DRC Settings…", self)
        a_drc_set.triggered.connect(self._drc_settings)
        am.addAction(a_drc_set)

        am.addSeparator()
        a_netlist = QAction("Load &Netlist (.net)…", self)
        a_netlist.triggered.connect(self._load_netlist)
        am.addAction(a_netlist)

        # Help
        hm = mb.addMenu("&Help")
        a_about = QAction("About…", self)
        a_about.triggered.connect(self._show_about)
        hm.addAction(a_about)

    # ── toolbar ───────────────────────────────────────────────────

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(type('S', (), {'width': lambda: 16, 'height': lambda: 16})())
        self.addToolBar(tb)

        def act(label: str, slot, tip: str = "", shortcut: str = "",
                checkable=False):
            a = QAction(label, self)
            a.setToolTip(tip + (f"  [{shortcut}]" if shortcut else ""))
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if checkable:
                a.setCheckable(True)
            a.triggered.connect(slot)
            tb.addAction(a)
            return a

        act("Open",      self._open_folder, "Open Gerber folder", "Ctrl+O")
        tb.addSeparator()
        act("Fit",       self._fit,          "Fit board to window", "F")
        act("Clear",     self._clear,        "Clear selection",     "Escape")
        tb.addSeparator()
        self._measure_act = act("Measure",   self._toggle_measure,
                                "Measure distance", "M", checkable=True)
        tb.addSeparator()
        act("Stats",     self._show_stats,   "Board statistics")
        act("DRC",       self._run_drc,      "Design rule check",   "Ctrl+D")
        tb.addSeparator()
        act("PNG",       self._export_png,   "Export PNG")
        act("SVG",       self._export_svg,   "Export SVG")
        tb.addSeparator()

        # Theme picker in toolbar
        theme_lbl = QLabel("  Theme: ")
        theme_lbl.setStyleSheet(f"color:{self._theme.hex('window_text')}; font-size:11px;")
        tb.addWidget(theme_lbl)
        self._theme_combo = QComboBox()
        self._theme_combo.addItems([t.replace('_',' ').title() for t in THEMES])
        self._theme_combo.setCurrentText(self._theme.name.replace('_',' ').title())
        self._theme_combo.currentIndexChanged.connect(
            lambda i: self._set_theme(THEMES[i]))
        self._theme_combo.setFixedWidth(130)
        tb.addWidget(self._theme_combo)

        # Spacer + coord label
        sp = QWidget(); sp.setSizePolicy(
            sp.sizePolicy().horizontalPolicy().Expanding,
            sp.sizePolicy().verticalPolicy().Fixed)
        tb.addWidget(sp)

    # ── central widget ────────────────────────────────────────────

    def _build_central(self):
        self._canvas = PCBCanvas(self._theme)
        self._canvas.statusMsg.connect(self._sb.showMessage
                                       if hasattr(self, '_sb') else lambda m: None)
        self._canvas.primitiveClicked.connect(self._on_prim_clicked)
        self._canvas.measureDone.connect(lambda d: None)

        self._layer_panel = LayerPanel(self._theme)
        self._layer_panel.layerLoad.connect(self._on_layer_load)
        self._layer_panel.layerVis.connect(
            lambda l, v: self._canvas.set_layer_visible(l, v))

        self._info_panel = InfoPanel(self._theme)

        left_tabs = QTabWidget()
        left_tabs.setFixedWidth(245)
        left_tabs.addTab(self._layer_panel, "Layers")
        left_tabs.addTab(self._info_panel,  "Info")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_tabs)
        splitter.addWidget(self._canvas)
        splitter.setSizes([245, 1055])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

    def _build_status(self):
        self._sb = QStatusBar()
        self._sb.showMessage("Open a Gerber folder to begin.  "
                             "Ctrl+O to open, F to fit, M to measure.")
        self.setStatusBar(self._sb)
        self._canvas.statusMsg.connect(self._sb.showMessage)

    # ── folder loading ────────────────────────────────────────────

    def _open_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Gerber Folder",
            self._settings.value('last_folder', ''))
        if not folder:
            return
        self._load_folder(folder)

    def _load_folder(self, folder: str):
        self._folder = folder
        self._settings.setValue('last_folder', folder)
        self._add_recent(folder)
        self._rebuild_recent_menu()

        descs = scan_folder(folder)
        if not descs:
            QMessageBox.warning(self, "No Gerber files",
                                "No Gerber / drill files found in the selected folder.")
            return

        self._descriptors = descs

        # Reset canvas
        self._canvas.layer_primitives.clear()
        self._canvas.flat.clear()
        self._canvas.adj.clear()
        self._canvas.highlighted.clear()
        self._canvas._cache.clear()
        self._canvas.drill_holes.clear()
        self._loaded.clear()

        self._layer_panel.populate(descs)

        # Load default layers with splash-style progress
        defaults = [d for d in descs if d.layer_def.default_load]
        n = max(len(defaults), 1)
        for i, d in enumerate(defaults):
            pct = int(i / n * 80)
            self._sb.showMessage(
                f"Loading {os.path.basename(d.path)}…  ({i+1}/{len(defaults)})")
            QApplication.processEvents()
            self._load_file_desc(d)

        self._canvas._compute_bounds()
        self._canvas.fit_view()
        self._sb.showMessage("Building connectivity…")
        QApplication.processEvents()
        self._canvas.rebuild_connectivity()

        n_loaded = len(self._loaded)
        n_total  = len(descs)
        self.setWindowTitle(
            f"PCB Gerber Viewer Pro — {os.path.basename(folder)}")
        self._sb.showMessage(
            f"Loaded {n_loaded} layers  ({n_total} available).  "
            "Tick optional layers in the panel.  F = fit,  M = measure,  G = grid")

    def _load_file_desc(self, d: FileDesc):
        if d.layer_name in self._loaded:
            return
        if d.is_drill:
            parser = ExcellonParser()
            holes  = parser.parse(d.path)
            if holes:
                existing = list(self._canvas.drill_holes)
                existing.extend(holes)
                self._canvas.set_drill_holes(existing)
                self._loaded.add(d.layer_name)
            return

        parser = GerberParser(d.layer_name)
        prims  = parser.parse(d.path)
        if prims:
            self._canvas.load_layer(d.layer_name, prims,
                                    d.layer_def._color_q())
            self._loaded.add(d.layer_name)
            print(f"  {os.path.basename(d.path):40s}"
                  f"→ {d.layer_name:16s}  ({len(prims)} primitives)")

    def _on_layer_load(self, layer: str, checked: bool):
        if checked:
            desc = next((d for d in self._descriptors
                         if d.layer_name == layer), None)
            if desc and layer not in self._loaded:
                self._sb.showMessage(f"Loading {layer}…")
                QApplication.processEvents()
                self._load_file_desc(desc)
                self._canvas._compute_bounds()
                self._canvas.rebuild_connectivity()
                self._layer_panel.set_loaded(layer, True)
        else:
            self._canvas.unload_layer(layer)
            self._loaded.discard(layer)
            self._canvas.rebuild_connectivity()
            self._layer_panel.set_loaded(layer, False)

    # ── toolbar slots ─────────────────────────────────────────────

    def _fit(self):
        self._canvas.fit_view()

    def _clear(self):
        self._canvas._clear_selection()
        self._canvas.measure_mode = False
        self._measure_act.setChecked(False)
        self._canvas.setCursor(Qt.CursorShape.CrossCursor)
        self._info_panel.show_primitive(None)

    def _toggle_measure(self, checked: bool):
        self._canvas.measure_mode = checked
        self._canvas._mpt1 = self._canvas._mpt2 = None
        cur = (Qt.CursorShape.SizeAllCursor if checked
               else Qt.CursorShape.CrossCursor)
        self._canvas.setCursor(cur)
        if checked:
            self._sb.showMessage("  Measure mode — click first point")
        self._canvas.update()

    def _on_prim_clicked(self, prim):
        self._info_panel.show_primitive(prim)
        tabs = self.centralWidget().widget(0)
        if isinstance(tabs, QTabWidget):
            tabs.setCurrentIndex(1)

    def _show_stats(self):
        if not self._canvas.flat:
            self._sb.showMessage("No board loaded."); return
        stats = self._canvas.board_stats()
        self._info_panel.show_stats(stats)
        tabs = self.centralWidget().widget(0)
        if isinstance(tabs, QTabWidget):
            tabs.setCurrentIndex(1)

    # ── DRC ───────────────────────────────────────────────────────

    def _drc_settings(self):
        dlg = DRCSettingsDialog(self._drc_min_clear,
                                self._drc_min_track, self)
        if dlg.exec():
            self._drc_min_clear, self._drc_min_track = dlg.values

    def _run_drc(self):
        if not self._canvas.flat:
            self._sb.showMessage("No board loaded."); return
        self._sb.showMessage("Running DRC…")
        QApplication.processEvents()
        viols = run_drc(self._canvas.flat, self._canvas.adj,
                        self._drc_min_clear, self._drc_min_track)
        self._canvas.drc_violations = viols
        self._canvas._cache.clear()
        self._canvas.update()
        dlg = DRCDialog(viols, self)
        dlg.exec()
        self._sb.showMessage(
            f"DRC complete — {len(viols)} violation(s) found.")

    # ── Export ────────────────────────────────────────────────────

    def _export_png(self):
        if not self._canvas.flat:
            self._sb.showMessage("No board loaded."); return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PNG", self._folder, "PNG (*.png)")
        if not path:
            return
        px = QPixmap(self._canvas.size())
        self._canvas.render(px)
        px.save(path, "PNG")
        self._sb.showMessage(f"Exported: {path}")

    def _export_svg(self):
        if not self._canvas.flat:
            self._sb.showMessage("No board loaded."); return
        from PyQt6.QtSvg import QSvgGenerator
        path, _ = QFileDialog.getSaveFileName(
            self, "Export SVG", self._folder, "SVG (*.svg)")
        if not path:
            return
        gen = QSvgGenerator()
        gen.setFileName(path)
        gen.setSize(self._canvas.size())
        gen.setViewBox(self._canvas.rect())
        p = QPainter(gen)
        self._canvas.render(p)
        p.end()
        self._sb.showMessage(f"Exported: {path}")

    # ── Theme ─────────────────────────────────────────────────────

    def _set_theme(self, name: str):
        self._theme = Theme(name)
        self._theme.apply_palette(QApplication.instance())
        self.setStyleSheet(self._theme.main_stylesheet())
        self._canvas.set_theme(self._theme)
        self._layer_panel.setStyleSheet(
            self._theme.layer_panel_stylesheet())
        self._settings.setValue('theme', name)

    # ── Netlist ───────────────────────────────────────────────────

    def _load_netlist(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load KiCad Netlist", self._folder,
            "Netlist (*.net *.xml);;All (*)")
        if path:
            self._netlist_path = path
            self._sb.showMessage(
                f"Netlist loaded: {os.path.basename(path)}")

    # ── Recent files ──────────────────────────────────────────────

    def _add_recent(self, folder: str):
        recents = self._settings.value('recent_folders', []) or []
        if folder in recents:
            recents.remove(folder)
        recents.insert(0, folder)
        self._settings.setValue('recent_folders', recents[:MAX_RECENT])

    def _rebuild_recent_menu(self):
        self._recent_menu.clear()
        recents = self._settings.value('recent_folders', []) or []
        for r in recents:
            a = QAction(r, self)
            a.triggered.connect(lambda _, f=r: self._load_folder(f))
            self._recent_menu.addAction(a)
        if not recents:
            self._recent_menu.addAction(QAction("(empty)", self))

    # ── About ─────────────────────────────────────────────────────

    def _show_about(self):
        QMessageBox.about(self, "About PCB Gerber Viewer Pro",
            "<b>PCB Gerber Viewer Pro</b> v3.0<br><br>"
            "Professional-grade Gerber PCB inspection tool.<br>"
            "Supports RS-274X, Gerber X2, and Excellon drill files.<br><br>"
            "Features: spatial grid connectivity, DRC, PNG/SVG export,<br>"
            "measurement tool, minimap, net tracing, layer management.")

    # ── Keyboard shortcuts ────────────────────────────────────────

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_F:
            self._fit()
        elif k == Qt.Key.Key_Escape:
            self._clear()
        elif k == Qt.Key.Key_M:
            checked = not self._measure_act.isChecked()
            self._measure_act.setChecked(checked)
            self._toggle_measure(checked)
        elif k == Qt.Key.Key_G:
            self._canvas.show_grid = not self._canvas.show_grid
            self._canvas.update()
        else:
            super().keyPressEvent(e)


# ── Entry point ───────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PCB Gerber Viewer Pro")
    app.setOrganizationName(SETTINGS_ORG)
    app.setStyle("Fusion")

    # Splash
    splash = SplashScreen()
    splash.show()
    splash.set_progress(10, "Loading themes…")
    QApplication.processEvents()

    theme = Theme('dark')
    theme.apply_palette(app)
    splash.set_progress(40, "Building UI…")
    QApplication.processEvents()

    win = MainWindow()
    splash.set_progress(90, "Ready.")
    QApplication.processEvents()

    import time as _t
    _t.sleep(0.4)
    splash.close()
    win.show()

    # Auto-load from command line
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        QTimer.singleShot(100, lambda: win._load_folder(sys.argv[1]))

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
