"""Central design system: a professional theme layered on pyqtdarktheme.

We use pyqtdarktheme as a consistent, well-tested foundation (handles every edge
widget — scrollbars, menus, tooltips, spin buttons) and layer a focused set of
brand overrides on top for identity: an accent color, primary action buttons,
card-style group boxes, an accented tab strip, and comfortable spacing.
"""

from __future__ import annotations

import qdarktheme
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QPushButton

# Brand palette (Tailwind-inspired, calm and professional for instrument software)
ACCENT = "#2563EB"        # blue-600
ACCENT_HOVER = "#1D4ED8"  # blue-700
ACCENT_PRESSED = "#1E40AF"  # blue-800
SURFACE = "#FFFFFF"
WINDOW = "#EEF2F7"
BORDER = "#E2E8F0"
TEXT = "#1E293B"
MUTED = "#64748B"
HEADER_BG = "#0F2942"     # deep navy header
SUCCESS = "#16A34A"
DANGER = "#DC2626"

_EXTRA_QSS = f"""
/* ---- window & surfaces ---- */
QWidget#centralRoot {{ background: {WINDOW}; }}

/* ---- app header ---- */
QFrame#appHeader {{
    background: {HEADER_BG};
    border: none;
}}
QFrame#appHeader QLabel {{ background: transparent; }}
QLabel#appTitle {{ color: #FFFFFF; font-size: 16px; font-weight: 700; }}
QLabel#appSubtitle {{ color: #9FB3C8; font-size: 12px; }}
QLabel#appVersion {{
    color: #DCE6F2; font-size: 12px; font-weight: 700;
    background: rgba(255,255,255,0.10); border-radius: 10px; padding: 3px 10px;
}}

/* ---- tabs ---- */
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; top: -1px; background: {SURFACE}; }}
QTabBar::tab {{
    padding: 9px 20px; margin-right: 2px; color: {MUTED};
    font-size: 13px; border: none; background: transparent;
}}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{
    color: {ACCENT}; font-weight: 700;
    border-bottom: 2px solid {ACCENT};
}}

/* ---- group boxes as cards ---- */
QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 10px;
    margin-top: 16px; padding: 14px 12px 12px 12px; background: {SURFACE};
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left; left: 14px;
    padding: 2px 6px; color: {TEXT}; font-weight: 700;
}}

/* ---- buttons ---- */
QPushButton {{ border-radius: 7px; padding: 7px 16px; }}
QPushButton#primary {{
    background: {ACCENT}; color: #FFFFFF; font-weight: 600; border: none;
}}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton#primary:disabled {{ background: #93B4F0; color: #EAF1FF; }}
QPushButton#danger {{ background: {DANGER}; color: #FFFFFF; font-weight: 600; border: none; }}
QPushButton#danger:hover {{ background: #B91C1C; }}

/* ---- inputs ---- */
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{
    border-radius: 7px; padding: 5px 9px; min-height: 20px;
}}

/* ---- tables ---- */
QTableWidget {{ border: 1px solid {BORDER}; border-radius: 8px; gridline-color: #EDF1F6; }}
QHeaderView::section {{
    background: #F1F5F9; color: {MUTED}; padding: 7px 8px;
    border: none; border-right: 1px solid {BORDER}; border-bottom: 1px solid {BORDER};
    font-weight: 600;
}}
QTableWidget::item {{ padding: 4px 6px; }}

/* ---- status bar ---- */
QStatusBar {{ color: {MUTED}; }}
QStatusBar QLabel {{ color: {MUTED}; }}

/* ---- components: card ---- */
QFrame#card {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
}}
QLabel#cardTitle {{ color: {TEXT}; font-size: 14px; font-weight: 700; }}

/* ---- components: metric tile ---- */
QFrame#metricTile {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
}}
QFrame#metricTile:hover {{ border: 1px solid #C7D2FE; }}
QLabel#metricLabel {{ color: {MUTED}; font-size: 12px; background: transparent; }}
QLabel#metricValue {{ color: {TEXT}; font-size: 23px; font-weight: 700; background: transparent; }}
QLabel#metricUnit {{ color: {MUTED}; font-size: 13px; padding-bottom: 3px; background: transparent; }}
QLabel#metricIcon {{ background: transparent; }}
"""


def apply_theme(app: QApplication, mode: str = "light") -> None:
    """Apply the base theme + brand overrides + a clean font to the application."""
    try:
        base = qdarktheme.load_stylesheet(mode, custom_colors={"primary": ACCENT})
    except TypeError:
        # older/newer signature without custom_colors
        base = qdarktheme.load_stylesheet(mode)
    app.setStyleSheet(base + _EXTRA_QSS)

    font = QFont()
    # macOS: PingFang SC; Windows: Microsoft YaHei; fall back to the default sans.
    for family in ("PingFang SC", "Microsoft YaHei", "Segoe UI", "Helvetica Neue"):
        font.setFamily(family)
        if QFont(family).exactMatch():
            break
    font.setPointSize(13)
    app.setFont(font)


def make_primary(button: QPushButton) -> QPushButton:
    """Mark a button as the primary (accent) action."""
    button.setObjectName("primary")
    return button


def make_danger(button: QPushButton) -> QPushButton:
    button.setObjectName("danger")
    return button


# --- chart styling (lazy QtCharts imports so theme stays import-safe) ---

def accent_pen(color: str = ACCENT, width: int = 2):
    from PySide6.QtGui import QColor, QPen

    pen = QPen(QColor(color))
    pen.setWidth(width)
    pen.setCosmetic(True)
    return pen


def style_chart(chart) -> None:
    from PySide6.QtCharts import QChart
    from PySide6.QtCore import QMargins
    from PySide6.QtGui import QColor, QFont

    chart.setBackgroundVisible(False)
    chart.setMargins(QMargins(8, 6, 12, 6))
    chart.setTheme(QChart.ChartTheme.ChartThemeLight)
    chart.legend().setVisible(False)
    title_font = QFont()
    title_font.setPointSize(12)
    title_font.setBold(True)
    chart.setTitleFont(title_font)
    chart.setTitleBrush(QColor(TEXT))
    chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)


def style_axis(axis, *, label_format: str | None = None, ticks: int | None = None) -> None:
    from PySide6.QtGui import QColor, QFont

    labels_font = QFont()
    labels_font.setPointSize(10)
    axis.setLabelsFont(labels_font)
    axis.setLabelsColor(QColor(MUTED))
    title_font = QFont()
    title_font.setPointSize(10)
    title_font.setBold(True)
    axis.setTitleFont(title_font)
    axis.setTitleBrush(QColor(MUTED))
    if hasattr(axis, "setGridLineColor"):
        axis.setGridLineColor(QColor("#EDF1F6"))
    if hasattr(axis, "setLinePenColor"):
        axis.setLinePenColor(QColor(BORDER))
    if label_format is not None and hasattr(axis, "setLabelFormat"):
        axis.setLabelFormat(label_format)
    if ticks is not None and hasattr(axis, "setTickCount"):
        axis.setTickCount(ticks)


def style_chart_view(view) -> None:
    from PySide6.QtGui import QPainter

    view.setRenderHint(QPainter.RenderHint.Antialiasing)
