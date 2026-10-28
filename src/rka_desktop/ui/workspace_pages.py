"""Workflow pages for the instrument-console navigation shell."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
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

        self.steps = QTabWidget()
        layout.addWidget(self.steps)

        sample, body = card("1 · 试样与配方")
        form = QFormLayout()
        self.recipe_label = QLabel("请从顶部工具栏选择配方")
        self.sample_name = QLineEdit()
        self.sample_name.setPlaceholderText("例如：球团矿 A-19")
        self.mass = QDoubleSpinBox()
        self.mass.setRange(0, 300)
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
        sample_step = QWidget()
        sample_layout = QVBoxLayout(sample_step)
        sample_layout.addWidget(sample)
        sample_layout.addStretch()
        self.steps.addTab(sample_step, "01 样品与配方")

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
        check_step = QWidget()
        check_layout = QVBoxLayout(check_step)
        check_layout.addWidget(check_card)
        check_layout.addStretch()
        self.steps.addTab(check_step, "02 设备与现场")

        summary_step = QWidget()
        summary_layout = QVBoxLayout(summary_step)
        summary_card, summary_body = card("3 · 复核与启动")
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setMinimumHeight(92)
        self.summary.setAlignment(Qt.AlignmentFlag.AlignTop)
        summary_body.addWidget(self.summary)
        summary_layout.addWidget(summary_card)
        summary_layout.addStretch()
        self.steps.addTab(summary_step, "03 复核与启动")

        actions = QHBoxLayout()
        self.btn_previous = QPushButton("上一步")
        self.btn_next = QPushButton("下一步")
        self.btn_start = QPushButton("确认并启动实验")
        self.btn_start.setObjectName("primary")
        actions.addWidget(self.btn_previous)
        actions.addWidget(self.btn_next)
        actions.addStretch()
        actions.addWidget(self.btn_start)
        layout.addLayout(actions)
        layout.addStretch()
        self.btn_previous.clicked.connect(lambda: self.steps.setCurrentIndex(self.steps.currentIndex() - 1))
        self.btn_next.clicked.connect(lambda: self.steps.setCurrentIndex(self.steps.currentIndex() + 1))
        self.steps.currentChanged.connect(self._refresh_step)
        self._refresh_step()

    def _refresh_step(self) -> None:
        index = self.steps.currentIndex()
        self.btn_previous.setEnabled(index > 0)
        self.btn_next.setEnabled(index < 2)
        self.btn_start.setVisible(index == 2)
        if index == 2:
            checked = sum(check.isChecked() for check in self.checks)
            self.summary.setText(
                f"配方：{self.recipe_label.text()}\n"
                f"试样：{self.sample_name.text().strip() or '未填写'} · {self.mass.value():.3f} g\n"
                f"操作员：{self.operator.text().strip() or '未填写'}\n"
                f"现场确认：{checked} / {len(self.checks)} 项"
            )

    def missing_fields(self) -> list[str]:
        missing = []
        if not self.sample_name.text().strip(): missing.append("试样名称")
        if self.mass.value() <= 0: missing.append("初始质量")
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
        self.sections = QTabWidget()
        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        self.experiment_table = QTableWidget(0, 4)
        self.experiment_table.setHorizontalHeaderLabels(("实验 ID", "样品 / 实验名称", "状态", "报告状态"))
        self.experiment_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.experiment_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.experiment_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.experiment_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        list_layout.addWidget(self.experiment_table)
        frame, body = card("生成实验记录报告")
        explanation = QLabel(
            "先从上方选择实验。HTML/PDF 报告包含实验信息、全部原始采样和报警，"
            "标注待复核状态；还原度 Excel 报告需先在数据分析页计算。"
        )
        explanation.setWordWrap(True)
        body.addWidget(explanation)
        row = QHBoxLayout()
        self.btn_generate_html = QPushButton("生成 HTML 报告")
        self.btn_generate_html.setObjectName("primary")
        self.btn_generate_pdf = QPushButton("生成 PDF 报告")
        self.btn_analysis = QPushButton("前往数据分析")
        self.btn_report = QPushButton("导出 Excel 分析报告")
        row.addWidget(self.btn_generate_html)
        row.addWidget(self.btn_generate_pdf)
        row.addWidget(self.btn_analysis)
        row.addWidget(self.btn_report)
        row.addStretch()
        body.addLayout(row)
        list_layout.addWidget(frame)
        frame, body = card("原始数据")
        body.addWidget(QLabel("在历史实验中选择记录后，可导出 CSV 或 Excel 测量数据。"))
        self.btn_history = QPushButton("前往历史实验")
        body.addWidget(self.btn_history, alignment=Qt.AlignmentFlag.AlignLeft)
        list_layout.addWidget(frame)

        preview_page = QWidget()
        preview_layout = QVBoxLayout(preview_page)
        preview, preview_body = card("报告结构预览")
        self.preview_text = QLabel("请先在报告列表选择一条实验记录。")
        self.preview_text.setTextFormat(Qt.TextFormat.PlainText)
        self.preview_text.setWordWrap(True)
        preview_body.addWidget(self.preview_text)
        preview_layout.addWidget(preview)
        preview_layout.addStretch()

        fields_page = QWidget()
        fields_layout = QVBoxLayout(fields_page)
        fields, fields_body = card("字段与审签")
        details = QLabel(
            "HTML/PDF 技术记录包含实验身份、试样参数、原始采样和报警。"
            "Excel 分析报告包含还原度数据与曲线。启动时配方快照、设备身份、"
            "数据质量判据、计算规则版本和审核签署尚待业务与方法验证。"
        )
        details.setWordWrap(True)
        fields_body.addWidget(details)
        fields_layout.addWidget(fields)
        fields_layout.addStretch()
        self.sections.addTab(list_page, "报告列表")
        self.sections.addTab(preview_page, "报告预览")
        self.sections.addTab(fields_page, "字段与审签")
        layout.addWidget(self.sections)

    def set_experiments(self, experiments: list[dict[str, object]]) -> None:
        selected_id = self.selected_experiment_id()
        self.experiment_table.blockSignals(True)
        self.experiment_table.setRowCount(len(experiments))
        selected_row = 0 if experiments else -1
        for row, experiment in enumerate(experiments):
            values = (
                experiment.get("id"), experiment.get("name"), experiment.get("status"),
                "可生成技术记录",
            )
            for col, value in enumerate(values):
                self.experiment_table.setItem(row, col, QTableWidgetItem(str(value or "--")))
            if experiment.get("id") == selected_id:
                selected_row = row
        if selected_row >= 0:
            self.experiment_table.selectRow(selected_row)
        self.experiment_table.blockSignals(False)

    def selected_experiment_id(self) -> int | None:
        item = self.experiment_table.item(self.experiment_table.currentRow(), 0)
        return int(item.text()) if item is not None else None

    def set_preview(self, detail: dict[str, object] | None, sample_count: int, alarm_count: int) -> None:
        if detail is None:
            self.preview_text.setText("请先在报告列表选择一条实验记录。")
            self.btn_generate_html.setEnabled(False)
            self.btn_generate_pdf.setEnabled(False)
            return
        self.btn_generate_html.setEnabled(True)
        self.btn_generate_pdf.setEnabled(True)
        status = str(detail.get("status") or "未知")
        caveat = "实验尚未正常完成，报告将标记数据可能不完整。" if status != "FINISHED" else "结果仍需人工复核。"
        self.preview_text.setText(
            f"实验 #{detail.get('id')} · {detail.get('name') or '未命名'}\n"
            f"状态：{status} · 采样：{sample_count} 条 · 报警：{alarm_count} 条\n"
            f"初始质量：{detail.get('initial_mass_g') or '未登记'} g · "
            f"TFe：{detail.get('tfe_pct') or '未登记'} % · FeO：{detail.get('feo_pct') if detail.get('feo_pct') is not None else '未登记'} %\n\n"
            f"{caveat} 生成的 HTML/PDF 为技术记录，不包含正式方法符合性结论或审核签署。"
        )


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
            ("04 · 结果", "历史实验中核对采样与报警；报告中心生成 HTML/PDF 技术记录。还原度 Excel 报告需先在数据分析页计算。"),
            ("设备能力说明", "当前控制后端支持 N₂、H₂、CO。原型中的 Ar、CO₂、CH₄、O₂ 与气体策略尚未完成真机映射与联锁验证。"),
        ):
            frame, body = card(heading)
            line = QLabel(description)
            line.setWordWrap(True)
            body.addWidget(line)
            layout.addWidget(frame)
        layout.addStretch()
