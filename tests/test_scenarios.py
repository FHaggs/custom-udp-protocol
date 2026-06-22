from __future__ import annotations

from pathlib import Path

from rtp.protocol import ProtocolMode
from rtp.scenarios import build_netem_arguments, expand_scenarios, prepare_input_file, RunnerConfig, ScenarioDefinition, ScenarioKind


def test_expand_required_for_saw_excludes_reorder() -> None:
    scenarios = expand_scenarios(ProtocolMode.STOP_AND_WAIT, "required")
    assert [scenario.code for scenario in scenarios] == ["L0", "L1", "L2", "L3", "P0", "P1", "P2", "P3", "P4"]


def test_expand_required_for_sr_includes_reorder() -> None:
    scenarios = expand_scenarios(ProtocolMode.SELECTIVE_REPEAT, "required")
    assert scenarios[-3:] == (
        ScenarioDefinition("R0", ScenarioKind.REORDER, 0),
        ScenarioDefinition("R1", ScenarioKind.REORDER, 10),
        ScenarioDefinition("R2", ScenarioKind.REORDER, 25),
    )


def test_reorder_netem_uses_base_delay() -> None:
    scenario = ScenarioDefinition("R1", ScenarioKind.REORDER, 10)
    assert build_netem_arguments(scenario) == ["delay", "20ms", "reorder", "10%", "50%"]


def test_prepare_input_file_generates_enough_bytes(tmp_path: Path) -> None:
    config = RunnerConfig(
        mode=ProtocolMode.GO_BACK_N,
        windows=(4, 16),
        scenario_set="required",
        results_dir=tmp_path,
        input_path=None,
        payload_bytes=255 * 64,
        base_port=9000,
        receiver_host="127.0.0.1",
        sender_bind_host="127.0.0.1",
        receiver_bind_host="127.0.0.1",
        tx_namespace=None,
        rx_namespace=None,
        tx_interface=None,
        rx_interface=None,
        impair_side="sender",
        capture_pcap=False,
        timeout_seconds=30.0,
    )
    input_path = prepare_input_file(config)
    assert input_path.exists()
    assert input_path.stat().st_size == 255 * 64