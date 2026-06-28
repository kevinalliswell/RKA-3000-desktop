from openpyxl import load_workbook

from rka_desktop.analysis.reduction_kinetics import SampleParams, compute_reduction
from rka_desktop.reporting.report_service import ReportService


def _result():
    params = SampleParams(initial_mass_g=50.0, tfe_pct=60.0, feo_pct=0.0)
    series = [(0.0, 50.0), (60.0, 43.55), (120.0, 37.1)]
    return compute_reduction(series, params)


def test_generates_excel_report_with_sheets_and_chart(tmp_path):
    experiment = {
        "id": 7,
        "name": "exp-7",
        "status": "FINISHED",
        "initial_mass_g": 50.0,
        "tfe_pct": 60.0,
        "feo_pct": 0.0,
    }
    out = tmp_path / "report.xlsx"
    ReportService().generate_excel_report(experiment, _result(), out)

    assert out.exists()
    wb = load_workbook(out)
    assert set(wb.sheetnames) == {"报告", "数据"}

    report = wb["报告"]
    # indices written to the summary sheet
    labels = {report[f"A{i}"].value for i in range(3, 13)}
    assert "终态还原度 (%)" in labels
    assert "40% 还原速率 (%/min)" in labels

    data = wb["数据"]
    assert data["A1"].value == "时间 (min)"
    assert data.max_row == 4  # header + 3 points
    # a chart was embedded
    assert len(data._charts) == 1


def test_report_handles_single_point_without_chart(tmp_path):
    params = SampleParams(initial_mass_g=50.0, tfe_pct=60.0, feo_pct=0.0)
    result = compute_reduction([(0.0, 50.0)], params)
    experiment = {"id": 1, "name": "x", "status": "RUNNING"}
    out = tmp_path / "r.xlsx"
    ReportService().generate_excel_report(experiment, result, out)
    wb = load_workbook(out)
    assert len(wb["数据"]._charts) == 0  # not enough points for a chart
