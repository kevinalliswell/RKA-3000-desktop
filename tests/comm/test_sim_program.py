"""The simulated temperature controller runs a downloaded program curve and reports its segment."""

from rka_desktop.infrastructure.comm.adapters.sim_adapters import SimTemperatureAdapter


def test_sim_program_runs_segments_and_turns_off_at_end():
    now = {"t": 0.0}
    sim = SimTemperatureAdapter(initial_c=25.0, approach=1.0, segment_seconds=1.0, clock=lambda: now["t"])
    for number, (sv, time_raw) in enumerate([(150.0, 0), (150.0, 10), (300.0, 20), (300.0, 10)], start=1):
        sim.write_program_segment(0, number, sv, time_raw)
    assert sim.read_program_segment() == 0  # not started
    sim.select_program_group(0)
    now["t"] = 5
    assert sim.read_program_segment() == 2 and sim.read_pv() == 150.0
    now["t"] = 20
    assert sim.read_program_segment() == 3 and sim.read_pv() == 225.0
    now["t"] = 35
    assert sim.read_program_segment() == 4 and sim.read_pv() == 300.0
    now["t"] = 45
    assert sim.read_program_segment() == 0 and sim.read_pv() == 25.0  # curve finished: output off
