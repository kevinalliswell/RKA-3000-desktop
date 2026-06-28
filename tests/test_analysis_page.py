import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from rka_desktop.ui.analysis_page import AnalysisPage


class _FakeRepo:
    def __init__(self, measurements):
        self._measurements = measurements
        self.saved = None

    def list_experiments(self, limit=200):
        return [{"id": 1, "name": "exp-1", "status": "FINISHED"}]

    def get_experiment_detail(self, experiment_id):
        return {"id": experiment_id, "initial_mass_g": 50.0, "tfe_pct": 60.0, "feo_pct": 0.0}

    def fetch_measurements(self, experiment_id):
        return self._measurements

    def set_sample_params(self, experiment_id, initial_mass_g, tfe_pct, feo_pct):
        self.saved = (experiment_id, initial_mass_g, tfe_pct, feo_pct)


def _app():
    return QApplication.instance() or QApplication([])


def test_compute_renders_indices_from_measurements():
    _app()
    # 0/60/120 s, losing 6.45 then 12.9 g of a 50 g, 60% TFe sample -> R = 0/50/100 %
    measurements = [
        {"sampled_at": "2026-06-28T10:00:00", "weight_g": 50.0},
        {"sampled_at": "2026-06-28T10:01:00", "weight_g": 43.55},
        {"sampled_at": "2026-06-28T10:02:00", "weight_g": 37.1},
    ]
    page = AnalysisPage(_FakeRepo(measurements))
    page.refresh_experiments()
    result = page.compute()

    assert result is not None
    assert abs(result.final_degree_pct - 100.0) < 1e-6
    assert "100.00" in page.lbl_final.text()
    assert "1.20" in page.lbl_t60.text()  # t60 = 1.2 min


def test_save_params_delegates_to_repo():
    _app()
    repo = _FakeRepo([])
    page = AnalysisPage(repo)
    page.refresh_experiments()
    page.spin_m0.setValue(48.0)
    page.spin_tfe.setValue(62.0)
    page.spin_feo.setValue(3.0)
    page._save_params()
    assert repo.saved == (1, 48.0, 62.0, 3.0)


def test_compute_without_measurements_sets_status():
    _app()
    page = AnalysisPage(_FakeRepo([]))
    page.refresh_experiments()
    assert page.compute() is None
    assert "没有可用" in page.lbl_status.text()
