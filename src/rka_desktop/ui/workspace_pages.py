"""Workflow pages for the instrument-console navigation shell."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


def title(text: str, description: str) -> QWidget:
    block = QWidget()
    layout = QVBoxLayout(block)
    layout.setContentsMargins(0, 0, 0, 0)
    heading = QLabel(text)
    heading.setObjectName("pageHeading")
    sub = QLabel(description)
    sub.setObjectName("pageDescription")
    sub.setWordWrap(True)
    layout.addWidget(heading)
    layout.addWidget(sub)
    return block


def card(heading: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("workspaceCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 20)
    layout.setSpacing(12)
    label = QLabel(heading)
    label.setObjectName("cardHeading")
    layout.addWidget(label)
    return frame, layout


class OverviewPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.addWidget(title("实时总览", "实验状态、关键测量与待处理事项"))
        metrics = QGridLayout()
        metrics.setSpacing(14)
        self.values: dict[str, QLabel] = {}
        for index, (key, label, initial) in enumerate((
            ("temperature", "炉温", "-- ℃"),
            ("weight", "试样质量", "-- g"),
            ("pressure", "炉内压力", "-- MPa"),
            ("flow", "总气体流量", "-- L/min"),
        )):
            frame, body = card(label)
            value = QLabel(initial)
            value.setObjectName("overviewMetric")
            body.addWidget(value)
            self.values[key] = value
            metrics.addWidget(frame, index // 2, index % 2)
        layout.addLayout(metrics)
        status, body = card("当前实验")
        self.run_state = QLabel("待机 · 尚无运行中的实验")
        self.run_state.setObjectName("runState")
        body.addWidget(self.run_state)
        self.alarm_state = QLabel("报警与联锁状态将在设备采集后显示")
        self.alarm_state.setWordWrap(True)
        body.addWidget(self.alarm_state)
        actions = QHBoxLayout()
        self.btn_prepare = QPushButton("新建实验")
        self.btn_prepare.setObjectName("primary")
        self.btn_current = QPushButton("查看当前实验")
        self.btn_history = QPushButton("查看历史")
        for button in (self.btn_prepare, self.btn_current, self.btn_history):
            actions.addWidget(button)
        actions.addStretch()
        body.addLayout(actions)
        layout.addWidget(status)
        layout.addStretch()

    def update_snapshot(self, snapshot) -> None:
        self.values["temperature"].setText(f"{snapshot.temperature_c:.1f} ℃")
        self.values["weight"].setText(f"{snapshot.weight_g:.3f} g")
        self.values["pressure"].setText(f"{snapshot.pressure_mpa:.3f} MPa")
        self.values["flow"].setText(
            f"{snapshot.n2_lpm + snapshot.h2_lpm + snapshot.co_lpm:.2f} L/min"
        )
        self.alarm_state.setText(
            f"报警字 {snapshot.alarm_word:#06x} · 联锁字 {snapshot.interlock_word:#06x}"
        )


class PreflightPage(QWidget):
    """Operator worksheet. Checks are declarations, never device safety proof."""

    def __init__(self) -> None:
        super().__init__()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root = QWidget()
        scroll.setWidget(root)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(16)
        layout.addWidget(title("实验准备", "选择已保存配方、登记试样并记录现场检查"))

        sample, body = card("1 · 试样与配方")
        form = QFormLayout()
        self.recipe_label = QLabel("请从顶部工具栏选择配方")
        self.sample_name = QLineEdit()
        self.sample_name.setPlaceholderText("例如：球团矿 A-19")
        self.mass = QDoubleSpinBox()
        self.mass.setRange(0, 100000)
        self.mass.setDecimals(3)
        self.mass.setSuffix(" g")
        self.tfe = QDoubleSpinBox()
        self.tfe.setRange(0, 100)
        self.tfe.setDecimals(2)
        self.tfe.setSuffix(" %")
        self.feo = QDoubleSpinBox()
        self.feo.setRange(0, 100)
        self.feo.setDecimals(2)
        self.feo.setSuffix(" %")
        self.operator = QLineEdit()
        self.operator.setPlaceholderText("操作员姓名")
        for label, widget in (("实验配方", self.recipe_label), ("试样名称", self.sample_name),
                              ("初始质量 m₀", self.mass), ("TFe", self.tfe),
                              ("FeO", self.feo), ("操作员", self.operator)):
            form.addRow(label, widget)
        body.addLayout(form)
        layout.addWidget(sample)

        check_card, check_body = card("2 · 启动前现场确认")
        self.checks = []
        for text in ("通信端口与设备状态已检查", "温控与天平校准状态已确认",
                     "气源、管路与阀位已检查", "通风和尾气处理已确认",
                     "报警及联锁状态已确认", "实验配方及样品参数已复核"):
            check = QCheckBox(text)
            check_body.addWidget(check)
            self.checks.append(check)
        note = QLabel("人工勾选仅记录操作员确认；真实设备联锁仍由控制器判定。")
        note.setObjectName("pageDescription")
        note.setWordWrap(True)
        check_body.addWidget(note)
        layout.addWidget(check_card)
        self.btn_start = QPushButton("确认并启动实验")
        self.btn_start.setObjectName("primary")
        layout.addWidget(self.btn_start, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()

    def missing_fields(self) -> list[str]:
        missing = []
        if not self.sample_name.text().strip(): missing.append("试样名称")
        if self.mass.value() <= 0: missing.append("初始质量")
        if self.tfe.value() <= 0: missing.append("TFe")
        if not self.operator.text().strip(): missing.append("操作员")
        if not all(check.isChecked() for check in self.checks): missing.append("现场确认")
        return missing


class ReportsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.addWidget(title("报告中心", "从历史实验选择数据，完成分析后生成报告"))
        frame, body = card("实验结果导出")
        body.addWidget(QLabel("报告使用数据分析页当前选择的实验及已计算结果。"))
        row = QHBoxLayout()
        self.btn_analysis = QPushButton("前往数据分析")
        self.btn_report = QPushButton("生成 Excel 报告")
        self.btn_report.setObjectName("primary")
        row.addWidget(self.btn_analysis)
        row.addWidget(self.btn_report)
        row.addStretch()
        body.addLayout(row)
        layout.addWidget(frame)
        frame, body = card("原始数据")
        body.addWidget(QLabel("在历史实验中选择记录后，可导出 CSV 或 Excel 测量数据。"))
        self.btn_history = QPushButton("前往历史实验")
        body.addWidget(self.btn_history, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(frame)
        layout.addStretch()


class HelpPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(title("使用帮助", "RKA-3000 实验控制工作台操作路径"))
        for heading, description in (
            ("01 · 准备", "在实验配方页创建并保存步骤；在实验准备页登记试样、检查现场条件。"),
            ("02 · 运行", "连接设备并启动实验；当前实验页查看实时测量、阶段、报警和设备反馈。"),
            ("03 · 处置", "报警事件页确认报警及复位联锁。异常处置应遵循现场操作规程。"),
            ("04 · 结果", "历史实验中选择记录；数据分析页录入化学参数、计算还原度；报告中心导出。"),
            ("设备能力说明", "当前控制后端支持 N₂、H₂、CO。原型中的 Ar、CO₂、CH₄、O₂ 与气体策略尚未完成真机映射与联锁验证。"),
        ):
            frame, body = card(heading)
            line = QLabel(description)
            line.setWordWrap(True)
            body.addWidget(line)
            layout.addWidget(frame)
        layout.addStretch()
