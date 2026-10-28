"""Instrument-console theme for the RKA desktop application."""

from __future__ import annotations

import qdarktheme
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QPushButton

# Instrument-console palette shared by navigation and charts.
ACCENT = "#0369A1"
ACCENT_HOVER = "#075985"
ACCENT_PRESSED = "#0C4A6E"
SURFACE = "#FFFFFF"
WINDOW = "#EEF2F7"
BORDER = "#E2E8F0"
TEXT = "#1E293B"
MUTED = "#64748B"
HEADER_BG = "#0F2942"     # deep navy header
SUCCESS = "#16A34A"
DANGER = "#DC2626"


def apply_theme(app: QApplication, mode: str = "light") -> None:
    """Apply the base theme + brand overrides + a clean font to the application."""
    try:
        base = qdarktheme.load_stylesheet(mode, custom_colors={"primary": ACCENT})
    except TypeError:
        # older/newer signature without custom_colors
        base = qdarktheme.load_stylesheet(mode)
    dark = mode == "dark"
    canvas = "#0b0f15" if dark else "#f2f5f9"
    surface = "#151a24" if dark else "#ffffff"
    sidebar = "#10141d" if dark else "#e9eef5"
    ink = "#e8edf6" if dark else "#18202f"
    muted = "#9aa8ba" if dark else "#617084"
    line = "#2c3544" if dark else "#d9e1eb"
    accent = "#38bdf8" if dark else ACCENT
    qss = f"""
    QWidget#centralRoot {{ background: {canvas}; }}
    QFrame#sidebar {{ background: {sidebar}; border-right: 1px solid {line}; }}
    QFrame#sidebar QLabel {{ background: transparent; }}
    QLabel#sideBrand {{ color: {accent}; font-size: 19px; font-weight: 800; }}
    QLabel#sideSub {{ color: {muted}; font-size: 11px; padding-left: 26px; }}
    QLabel#navGroup {{ color: {muted}; font-size: 11px; font-weight: 700; padding: 9px 9px 4px; }}
    QLabel#sideMode {{ color: {accent}; padding: 10px; }}
    QPushButton#navItem {{ text-align: left; color: {muted}; border: 0; border-radius: 8px;
                          padding: 8px 10px; background: transparent; font-size: 13px; }}
    QPushButton#navItem:hover {{ background: {line}; color: {ink}; }}
    QPushButton#navItem:checked {{ color: {accent}; background: {"#173044" if dark else "#dbeefa"}; font-weight: 700; }}
    QFrame#appHeader {{ background: {surface}; border-bottom: 1px solid {line}; }}
    QFrame#appHeader QLabel {{ background: transparent; }}
    QLabel#appTitle {{ color: {ink}; font-size: 15px; font-weight: 700; }}
    QLabel#appSubtitle, QLabel#appVersion {{ color: {muted}; font-size: 11px; }}
    QLabel#runtimeState {{ color: {accent}; font-size: 12px; font-weight: 700; padding: 5px 10px; }}
    QLabel#pageHeading {{ color: {ink}; font-size: 23px; font-weight: 750; }}
    QLabel#pageDescription {{ color: {muted}; font-size: 12px; }}
    QFrame#workspaceCard, QFrame#card, QFrame#metricTile {{ background: {surface}; border: 1px solid {line}; border-radius: 10px; }}
    QFrame#workspaceCard QLabel, QFrame#card QLabel, QFrame#metricTile QLabel {{ background: transparent; }}
    QLabel#cardHeading, QLabel#cardTitle {{ color: {ink}; font-size: 14px; font-weight: 700; }}
    QLabel#overviewMetric {{ color: {ink}; font-size: 28px; font-weight: 750; }}
    QLabel#runState {{ color: {accent}; font-size: 16px; font-weight: 700; }}
    QLabel#metricLabel {{ color: {muted}; font-size: 12px; }}
    QLabel#metricValue {{ color: {ink}; font-size: 23px; font-weight: 700; }}
    QLabel#metricUnit {{ color: {muted}; font-size: 13px; }}
    QGroupBox {{ border: 1px solid {line}; border-radius: 9px; margin-top: 16px;
                 padding: 14px 12px 12px; background: {surface}; }}
    QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 14px;
                        padding: 2px 6px; color: {ink}; font-weight: 700; }}
    QTabWidget::pane {{ border: 1px solid {line}; border-radius: 8px; background: {surface}; }}
    QTabBar::tab {{ padding: 9px 18px; color: {muted}; border: 0; }}
    QTabBar::tab:selected {{ color: {accent}; border-bottom: 2px solid {accent}; font-weight: 700; }}
    QPushButton {{ border-radius: 7px; padding: 7px 13px; }}
    QPushButton#primary {{ background: {ACCENT if not dark else '#0284c7'}; color: white; border: 0; font-weight: 700; }}
    QPushButton#primary:hover {{ background: {ACCENT_HOVER if not dark else '#0369a1'}; }}
    QPushButton#danger {{ background: {DANGER}; color: white; border: 0; font-weight: 700; }}
    QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{ border-radius: 7px; min-height: 22px; padding: 4px 8px; }}
    QTableWidget {{ border: 1px solid {line}; border-radius: 8px; gridline-color: {line}; }}
    QHeaderView::section {{ background: {sidebar}; color: {muted}; padding: 7px 8px;
                           border: 0; border-right: 1px solid {line}; border-bottom: 1px solid {line}; font-weight: 600; }}
    QTableWidget::item {{ padding: 4px 6px; }}
    QStatusBar, QStatusBar QLabel {{ color: {muted}; }}
    """
    app.setStyleSheet(base + qss)

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
