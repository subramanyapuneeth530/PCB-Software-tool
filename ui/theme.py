"""
ui/theme.py
───────────
Theme system: dark (default), light, high-contrast.
Provides Qt palette, stylesheet strings, and layer color overrides.
"""
from __future__ import annotations
from PyQt6.QtGui import QColor, QPalette, QFont
from PyQt6.QtWidgets import QApplication


THEMES = ['dark', 'light', 'high_contrast']

# ── per-theme palette colors ──────────────────────────────────────

_DARK = {
    'window':        '#0D0D1A',
    'window_text':   '#E0E0E0',
    'base':          '#131325',
    'alt_base':      '#1A1A30',
    'text':          '#E0E0E0',
    'button':        '#16213E',
    'button_text':   '#E0E0E0',
    'highlight':     '#E8A020',
    'highlight_text':'#0D0D1A',
    'tooltip_base':  '#16213E',
    'tooltip_text':  '#E0E0E0',
    'canvas_bg':     '#0D0D1A',
    'toolbar_bg':    '#16213E',
    'toolbar_border':'#E8A020',
    'panel_bg':      '#131325',
    'panel_border':  '#252545',
    'accent':        '#E8A020',
    'accent2':       '#4A90D9',
    'highlight_net': '#FFD700',
    'measure_color': '#00FF88',
    'drc_error':     '#FF4040',
    'drc_warn':      '#FFA040',
    'grid_color':    '#1E1E38',
    'minimap_border':'#E8A020',
    'minimap_vp':    '#E8A02060',
}

_LIGHT = {
    'window':        '#F0F0F5',
    'window_text':   '#1A1A2E',
    'base':          '#FFFFFF',
    'alt_base':      '#E8E8F0',
    'text':          '#1A1A2E',
    'button':        '#E0E0EA',
    'button_text':   '#1A1A2E',
    'highlight':     '#2060C0',
    'highlight_text':'#FFFFFF',
    'tooltip_base':  '#FFFFF0',
    'tooltip_text':  '#1A1A2E',
    'canvas_bg':     '#E8E8F5',
    'toolbar_bg':    '#D8D8E8',
    'toolbar_border':'#2060C0',
    'panel_bg':      '#EBEBF5',
    'panel_border':  '#C0C0D0',
    'accent':        '#2060C0',
    'accent2':       '#C04020',
    'highlight_net': '#FF8000',
    'measure_color': '#008040',
    'drc_error':     '#CC0000',
    'drc_warn':      '#CC6600',
    'grid_color':    '#D0D0E0',
    'minimap_border':'#2060C0',
    'minimap_vp':    '#2060C060',
}

_HIGH_CONTRAST = {
    'window':        '#000000',
    'window_text':   '#FFFFFF',
    'base':          '#000000',
    'alt_base':      '#0A0A0A',
    'text':          '#FFFFFF',
    'button':        '#000000',
    'button_text':   '#FFFFFF',
    'highlight':     '#FFFF00',
    'highlight_text':'#000000',
    'tooltip_base':  '#000000',
    'tooltip_text':  '#FFFFFF',
    'canvas_bg':     '#000000',
    'toolbar_bg':    '#000000',
    'toolbar_border':'#FFFF00',
    'panel_bg':      '#000000',
    'panel_border':  '#FFFFFF',
    'accent':        '#FFFF00',
    'accent2':       '#00FFFF',
    'highlight_net': '#FFFF00',
    'measure_color': '#00FF00',
    'drc_error':     '#FF0000',
    'drc_warn':      '#FF8000',
    'grid_color':    '#1A1A1A',
    'minimap_border':'#FFFF00',
    'minimap_vp':    '#FFFF0050',
}

_MAPS = {'dark': _DARK, 'light': _LIGHT, 'high_contrast': _HIGH_CONTRAST}


class Theme:
    def __init__(self, name: str = 'dark'):
        self.name = name if name in THEMES else 'dark'
        self._c = _MAPS[self.name]

    def c(self, key: str) -> QColor:
        return QColor(self._c.get(key, '#FF00FF'))

    def hex(self, key: str) -> str:
        return self._c.get(key, '#FF00FF')

    def apply_palette(self, app: QApplication):
        p = QPalette()
        def sc(role, key):
            p.setColor(role, self.c(key))
        R = QPalette.ColorRole
        sc(R.Window,          'window')
        sc(R.WindowText,      'window_text')
        sc(R.Base,            'base')
        sc(R.AlternateBase,   'alt_base')
        sc(R.Text,            'window_text')
        sc(R.BrightText,      'window_text')
        sc(R.Button,          'button')
        sc(R.ButtonText,      'button_text')
        sc(R.Highlight,       'highlight')
        sc(R.HighlightedText, 'highlight_text')
        sc(R.ToolTipBase,     'tooltip_base')
        sc(R.ToolTipText,     'tooltip_text')
        app.setPalette(p)

    def main_stylesheet(self) -> str:
        c = self._c
        return f"""
QMainWindow, QDialog {{
    background: {c['window']};
}}
QToolBar {{
    background: {c['toolbar_bg']};
    border-bottom: 1px solid {c['toolbar_border']};
    spacing: 3px;
    padding: 2px 6px;
}}
QToolBar QToolButton, QToolBar QPushButton {{
    background: transparent;
    color: {c['window_text']};
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px 10px;
    font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    font-size: 11px;
}}
QToolBar QToolButton:hover, QToolBar QPushButton:hover {{
    background: {c['accent']};
    color: {c['window']};
    border-color: {c['accent']};
}}
QToolBar QToolButton:checked, QToolBar QPushButton:checked {{
    background: {c['accent']};
    color: {c['window']};
}}
QToolBar QToolButton:pressed, QToolBar QPushButton:pressed {{
    background: {c['accent2']};
}}
QMenuBar {{
    background: {c['toolbar_bg']};
    color: {c['window_text']};
    border-bottom: 1px solid {c['panel_border']};
}}
QMenuBar::item:selected {{
    background: {c['accent']};
    color: {c['window']};
}}
QMenu {{
    background: {c['panel_bg']};
    color: {c['window_text']};
    border: 1px solid {c['panel_border']};
}}
QMenu::item:selected {{
    background: {c['accent']};
    color: {c['window']};
}}
QStatusBar {{
    background: {c['toolbar_bg']};
    color: {c['window_text']};
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 11px;
    border-top: 1px solid {c['panel_border']};
}}
QSplitter::handle {{
    background: {c['panel_border']};
}}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical   {{ height: 1px; }}
QScrollBar:vertical {{
    background: {c['panel_bg']};
    width: 8px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {c['panel_border']};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {c['panel_bg']};
    height: 8px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: {c['panel_border']};
    border-radius: 4px;
    min-width: 20px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QToolTip {{
    background: {c['tooltip_base']};
    color: {c['tooltip_text']};
    border: 1px solid {c['accent']};
    font-size: 11px;
    padding: 4px 8px;
}}
QTabWidget::pane {{
    background: {c['panel_bg']};
    border: 1px solid {c['panel_border']};
}}
QTabBar::tab {{
    background: {c['alt_base']};
    color: {c['window_text']};
    padding: 5px 12px;
    border: 1px solid {c['panel_border']};
    border-bottom: none;
    font-size: 11px;
}}
QTabBar::tab:selected {{
    background: {c['panel_bg']};
    color: {c['accent']};
    border-bottom: 2px solid {c['accent']};
}}
QDialog {{
    background: {c['panel_bg']};
}}
QTextEdit, QPlainTextEdit {{
    background: {c['base']};
    color: {c['window_text']};
    border: 1px solid {c['panel_border']};
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 11px;
}}
QLineEdit {{
    background: {c['base']};
    color: {c['window_text']};
    border: 1px solid {c['panel_border']};
    border-radius: 3px;
    padding: 3px 6px;
}}
QComboBox {{
    background: {c['button']};
    color: {c['window_text']};
    border: 1px solid {c['panel_border']};
    border-radius: 3px;
    padding: 3px 6px;
}}
QGroupBox {{
    color: {c['accent']};
    border: 1px solid {c['panel_border']};
    border-radius: 4px;
    margin-top: 8px;
    font-size: 11px;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}
QCheckBox {{
    color: {c['window_text']};
    spacing: 6px;
    font-size: 11px;
}}
QCheckBox:hover {{
    color: {c['accent']};
}}
QPushButton {{
    background: {c['button']};
    color: {c['window_text']};
    border: 1px solid {c['panel_border']};
    border-radius: 4px;
    padding: 5px 14px;
    font-size: 11px;
}}
QPushButton:hover {{
    background: {c['accent']};
    color: {c['window']};
    border-color: {c['accent']};
}}
QPushButton:pressed {{
    background: {c['accent2']};
}}
QLabel {{
    color: {c['window_text']};
    font-size: 11px;
}}
QProgressBar {{
    background: {c['base']};
    border: 1px solid {c['panel_border']};
    border-radius: 4px;
    text-align: center;
    color: {c['window_text']};
    font-size: 11px;
}}
QProgressBar::chunk {{
    background: {c['accent']};
    border-radius: 3px;
}}
"""

    def layer_panel_stylesheet(self) -> str:
        c = self._c
        return f"""
QWidget {{ background: {c['panel_bg']}; color: {c['window_text']};
           font-family: 'Segoe UI', Arial, sans-serif; font-size: 11px; }}
QLabel#hdr {{ font-size: 12px; font-weight: bold; color: {c['accent']};
              padding: 6px 8px 4px 8px;
              border-bottom: 1px solid {c['accent']}; }}
QLabel#sub {{ font-size: 10px; color: {c['window_text']}; opacity: 0.6;
              padding: 2px 8px 4px 8px; }}
QScrollArea {{ border: none; background: {c['panel_bg']}; }}
"""
