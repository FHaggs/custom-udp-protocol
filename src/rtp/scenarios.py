from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from rtp.protocol import MAX_PAYLOAD_SIZE, ProtocolMode


class ScenarioKind(StrEnum):
    LATENCY = "latency"
    LOSS = "loss"
    REORDER = "reorder"


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    code: str
    kind: ScenarioKind
    value: int


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    mode: ProtocolMode
    windows: tuple[int, ...]
    scenario_set: str
    results_dir: Path
    input_path: Path | None
    payload_bytes: int
    base_port: int
    receiver_host: str
    sender_bind_host: str
    receiver_bind_host: str
    tx_namespace: str | None
    rx_namespace: str | None
    tx_interface: str | None
    rx_interface: str | None
    impair_side: str
    capture_pcap: bool
    timeout_seconds: float


LATENCY_SCENARIOS: tuple[ScenarioDefinition, ...] = (
    ScenarioDefinition("L0", ScenarioKind.LATENCY, 0),
    ScenarioDefinition("L1", ScenarioKind.LATENCY, 50),
    ScenarioDefinition("L2", ScenarioKind.LATENCY, 100),
    ScenarioDefinition("L3", ScenarioKind.LATENCY, 150),
)

LOSS_SCENARIOS: tuple[ScenarioDefinition, ...] = (
    ScenarioDefinition("P0", ScenarioKind.LOSS, 0),
    ScenarioDefinition("P1", ScenarioKind.LOSS, 1),
    ScenarioDefinition("P2", ScenarioKind.LOSS, 5),
    ScenarioDefinition("P3", ScenarioKind.LOSS, 10),
    ScenarioDefinition("P4", ScenarioKind.LOSS, 25),
)

REORDER_SCENARIOS: tuple[ScenarioDefinition, ...] = (
    ScenarioDefinition("R0", ScenarioKind.REORDER, 0),
    ScenarioDefinition("R1", ScenarioKind.REORDER, 10),
    ScenarioDefinition("R2", ScenarioKind.REORDER, 25),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rtp-scenarios",
        description="Run required RTP scenarios and collect metrics",
    )
    parser.add_argument("--mode", type=ProtocolMode, choices=tuple(ProtocolMode), required=True)
    parser.add_argument("--window", type=int, nargs="+", default=[4])
    parser.add_argument(
        "--scenario-set",
        choices=("required", "latency", "loss", "reorder", "all"),
        default="required",
    )
    parser.add_argument("--results-dir", type=Path, default=Path("results"))
    parser.add_argument("--input", type=Path, help="existing input file; if omitted, one is generated")
    parser.add_argument(
        "--payload-bytes",
        type=int,
        default=MAX_PAYLOAD_SIZE * 64,
        help="size of generated input when --input is omitted; default creates at least 64 packets",
    )
    parser.add_argument("--base-port", type=int, default=9000)
    parser.add_argument("--receiver-host", default="127.0.0.1")
    parser.add_argument("--sender-bind-host", default="127.0.0.1")
    parser.add_argument("--receiver-bind-host", default="127.0.0.1")
    parser.add_argument("--tx-namespace")
    parser.add_argument("--rx-namespace")
    parser.add_argument("--tx-interface")
    parser.add_argument("--rx-interface")
    parser.add_argument("--impair-side", choices=("sender", "receiver"), default="sender")
    parser.add_argument("--capture-pcap", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = RunnerConfig(
        mode=args.mode,
        windows=tuple(args.window),
        scenario_set=args.scenario_set,
        results_dir=args.results_dir,
        input_path=args.input,
        payload_bytes=args.payload_bytes,
        base_port=args.base_port,
        receiver_host=args.receiver_host,
        sender_bind_host=args.sender_bind_host,
        receiver_bind_host=args.receiver_bind_host,
        tx_namespace=args.tx_namespace,
        rx_namespace=args.rx_namespace,
        tx_interface=args.tx_interface,
        rx_interface=args.rx_interface,
        impair_side=args.impair_side,
        capture_pcap=args.capture_pcap,
        timeout_seconds=args.timeout_seconds,
    )
    summaries = run_matrix(config)
    write_csv(config.results_dir / "summary.csv", summaries)
    write_markdown(config.results_dir / "summary.md", summaries)
    print(json.dumps(summaries, indent=2, sort_keys=True))
    return 0


def run_matrix(config: RunnerConfig) -> list[dict[str, object]]:
    ensure_tools_available()
    config.results_dir.mkdir(parents=True, exist_ok=True)
    input_path = prepare_input_file(config)
    scenarios = expand_scenarios(config.mode, config.scenario_set)
    summaries: list[dict[str, object]] = []

    for window in config.windows:
        for scenario in scenarios:
            summaries.append(run_single_scenario(config, input_path, window, scenario))

    return summaries


def ensure_tools_available() -> None:
    for program in ("ip", "tc", "tcpdump"):
        if shutil.which(program) is None:
            raise RuntimeError(f"required tool not found: {program}")


def prepare_input_file(config: RunnerConfig) -> Path:
    if config.input_path is not None:
        return config.input_path
    generated = config.results_dir / "generated_input.bin"
    data = bytes(index % 251 for index in range(config.payload_bytes))
    generated.write_bytes(data)
    return generated


def expand_scenarios(mode: ProtocolMode, scenario_set: str) -> tuple[ScenarioDefinition, ...]:
    if scenario_set == "latency":
        return LATENCY_SCENARIOS
    if scenario_set == "loss":
        return LOSS_SCENARIOS
    if scenario_set == "reorder":
        return REORDER_SCENARIOS
    if scenario_set == "all":
        return LATENCY_SCENARIOS + LOSS_SCENARIOS + REORDER_SCENARIOS
    if mode is ProtocolMode.STOP_AND_WAIT:
        return LATENCY_SCENARIOS + LOSS_SCENARIOS
    return LATENCY_SCENARIOS + LOSS_SCENARIOS + REORDER_SCENARIOS


def run_single_scenario(
    config: RunnerConfig,
    input_path: Path,
    window: int,
    scenario: ScenarioDefinition,
) -> dict[str, object]:
    scenario_dir = config.results_dir / config.mode.value / f"window_{window}" / scenario.code
    scenario_dir.mkdir(parents=True, exist_ok=True)

    input_hash = sha256_file(input_path)
    output_path = scenario_dir / "received.bin"
    sender_stats_path = scenario_dir / "sender_stats.json"
    receiver_stats_path = scenario_dir / "receiver_stats.json"
    sender_log = scenario_dir / "sender.log"
    receiver_log = scenario_dir / "receiver.log"

    tcpdump_process: subprocess.Popen[bytes] | None = None
    receiver_process: subprocess.Popen[bytes] | None = None
    try:
        apply_netem(config, scenario)

        if config.capture_pcap:
            tcpdump_process = start_tcpdump(config, scenario_dir, window)

        receiver_command = build_rtp_command(
            listen=True,
            mode=config.mode,
            window=window,
            port=config.base_port,
            host=config.receiver_host,
            bind_host=config.receiver_bind_host,
            input_path=None,
            output_path=output_path,
            stats_path=receiver_stats_path,
        )
        sender_command = build_rtp_command(
            listen=False,
            mode=config.mode,
            window=window,
            port=config.base_port,
            host=config.receiver_host,
            bind_host=config.sender_bind_host,
            input_path=input_path,
            output_path=None,
            stats_path=sender_stats_path,
        )

        receiver_process = start_process(
            namespace=config.rx_namespace,
            command=receiver_command,
            log_path=receiver_log,
        )
        time.sleep(0.25)

        sender_result = run_command(
            namespace=config.tx_namespace,
            command=sender_command,
            log_path=sender_log,
            timeout_seconds=config.timeout_seconds,
        )
        if sender_result.returncode != 0:
            raise RuntimeError(f"sender failed for {scenario.code}: exit={sender_result.returncode}")

        if receiver_process.wait(timeout=config.timeout_seconds) != 0:
            raise RuntimeError(f"receiver failed for {scenario.code}: exit={receiver_process.returncode}")

        sender_stats = json.loads(sender_stats_path.read_text(encoding="utf-8"))
        receiver_stats = json.loads(receiver_stats_path.read_text(encoding="utf-8"))
        output_hash = sha256_file(output_path)

        summary = {
            "mode": config.mode.value,
            "window": window,
            "scenario": scenario.code,
            "scenario_kind": scenario.kind.value,
            "scenario_value": scenario.value,
            "input_bytes": input_path.stat().st_size,
            "input_sha256": input_hash,
            "output_sha256": output_hash,
            "hash_match": input_hash == output_hash,
            "sender": sender_stats,
            "receiver": receiver_stats,
            "capture_pcap": config.capture_pcap,
        }
        (scenario_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return summary
    finally:
        if receiver_process is not None and receiver_process.poll() is None:
            receiver_process.kill()
            receiver_process.wait()
        if tcpdump_process is not None and tcpdump_process.poll() is None:
            tcpdump_process.terminate()
            tcpdump_process.wait()
        clear_netem(config)


def build_rtp_command(
    *,
    listen: bool,
    mode: ProtocolMode,
    window: int,
    port: int,
    host: str,
    bind_host: str,
    input_path: Path | None,
    output_path: Path | None,
    stats_path: Path,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "rtp",
        "--bind-host",
        bind_host,
        "--port",
        str(port),
        "--mode",
        mode.value,
        "--window",
        str(window),
        "--stats-json",
        str(stats_path),
    ]
    if listen:
        command.extend(["--listen", "--output", str(output_path)])
    else:
        command.extend(["--host", host, "--input", str(input_path)])
    return command


def start_process(namespace: str | None, command: list[str], log_path: Path) -> subprocess.Popen[bytes]:
    log_handle = log_path.open("wb")
    wrapped = wrap_with_namespace(namespace, command)
    return subprocess.Popen(wrapped, stdout=log_handle, stderr=subprocess.STDOUT)


def run_command(
    *,
    namespace: str | None,
    command: list[str],
    log_path: Path,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[bytes]:
    wrapped = wrap_with_namespace(namespace, command)
    with log_path.open("wb") as log_handle:
        return subprocess.run(wrapped, stdout=log_handle, stderr=subprocess.STDOUT, timeout=timeout_seconds, check=False)


def wrap_with_namespace(namespace: str | None, command: list[str]) -> list[str]:
    if namespace is None:
        return command
    return ["ip", "netns", "exec", namespace, *command]


def apply_netem(config: RunnerConfig, scenario: ScenarioDefinition) -> None:
    interface = pick_impaired_interface(config)
    if interface is None:
        if scenario.value != 0:
            raise RuntimeError("non-zero impairment scenario requires --tx-interface or --rx-interface")
        return

    netem_args = build_netem_arguments(scenario)
    command = ["tc", "qdisc", "replace", "dev", interface, "root", "netem", *netem_args]
    subprocess.run(wrap_with_namespace(pick_impaired_namespace(config), command), check=True)


def clear_netem(config: RunnerConfig) -> None:
    interface = pick_impaired_interface(config)
    if interface is None:
        return
    command = ["tc", "qdisc", "del", "dev", interface, "root"]
    subprocess.run(wrap_with_namespace(pick_impaired_namespace(config), command), check=False)


def build_netem_arguments(scenario: ScenarioDefinition) -> list[str]:
    if scenario.kind is ScenarioKind.LATENCY:
        return ["delay", f"{scenario.value}ms"]
    if scenario.kind is ScenarioKind.LOSS:
        return ["loss", f"{scenario.value}%"]
    return ["delay", "20ms", "reorder", f"{scenario.value}%", "50%"]


def pick_impaired_namespace(config: RunnerConfig) -> str | None:
    return config.tx_namespace if config.impair_side == "sender" else config.rx_namespace


def pick_impaired_interface(config: RunnerConfig) -> str | None:
    return config.tx_interface if config.impair_side == "sender" else config.rx_interface


def start_tcpdump(config: RunnerConfig, scenario_dir: Path, window: int) -> subprocess.Popen[bytes]:
    pcap_path = scenario_dir / f"capture_window{window}.pcapng"
    namespace = pick_impaired_namespace(config)
    interface = pick_impaired_interface(config)
    if interface is None:
        raise RuntimeError("--capture-pcap requires an interface for the impaired side")
    command = [
        "tcpdump",
        "-i",
        interface,
        "-w",
        str(pcap_path),
        "udp",
        "and",
        "port",
        str(config.base_port),
    ]
    return subprocess.Popen(wrap_with_namespace(namespace, command), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, summaries: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "mode",
                "window",
                "scenario",
                "scenario_kind",
                "scenario_value",
                "input_bytes",
                "hash_match",
                "sender_duration_seconds",
                "sender_throughput_bytes_per_second",
                "sender_retransmissions",
                "receiver_duration_seconds",
                "receiver_retransmissions",
            ],
        )
        writer.writeheader()
        for summary in summaries:
            sender = summary["sender"]
            receiver = summary["receiver"]
            writer.writerow(
                {
                    "mode": summary["mode"],
                    "window": summary["window"],
                    "scenario": summary["scenario"],
                    "scenario_kind": summary["scenario_kind"],
                    "scenario_value": summary["scenario_value"],
                    "input_bytes": summary["input_bytes"],
                    "hash_match": summary["hash_match"],
                    "sender_duration_seconds": sender["duration_seconds"],
                    "sender_throughput_bytes_per_second": sender["throughput_bytes_per_second"],
                    "sender_retransmissions": sender["retransmissions"],
                    "receiver_duration_seconds": receiver["duration_seconds"],
                    "receiver_retransmissions": receiver["retransmissions"],
                }
            )


def write_markdown(path: Path, summaries: list[dict[str, object]]) -> None:
    lines = [
        "# Scenario Results",
        "",
        "| Mode | Window | Scenario | Kind | Value | Hash Match | Sender Throughput (B/s) | Sender Retransmissions | Sender Duration (s) |",
        "| --- | ---: | --- | --- | ---: | --- | ---: | ---: | ---: |",
    ]
    for summary in summaries:
        sender = summary["sender"]
        lines.append(
            "| {mode} | {window} | {scenario} | {kind} | {value} | {hash_match} | {throughput:.2f} | {retransmissions} | {duration:.6f} |".format(
                mode=summary["mode"],
                window=summary["window"],
                scenario=summary["scenario"],
                kind=summary["scenario_kind"],
                value=summary["scenario_value"],
                hash_match="yes" if summary["hash_match"] else "no",
                throughput=sender["throughput_bytes_per_second"],
                retransmissions=sender["retransmissions"],
                duration=sender["duration_seconds"],
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")