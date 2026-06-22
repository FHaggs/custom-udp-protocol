from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

from rtp.peer import RtpReceiver, RtpSender
from rtp.protocol import ProtocolMode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rtp",
        description="Reliable Transport Protocol over UDP",
    )
    parser.add_argument("--listen", action="store_true", help="run as receiver")
    parser.add_argument("--host", default="127.0.0.1", help="peer host for sender mode")
    parser.add_argument(
        "--bind-host",
        default="0.0.0.0",
        help="local host or interface used for bind operations",
    )
    parser.add_argument("--port", type=int, required=True, help="base UDP port")
    parser.add_argument(
        "--mode",
        type=ProtocolMode,
        choices=tuple(ProtocolMode),
        default=ProtocolMode.STOP_AND_WAIT,
        help="reliability mode",
    )
    parser.add_argument("--window", type=int, default=4, help="proposed window size")
    parser.add_argument("--input", help="input file for sender mode")
    parser.add_argument("--output", help="output file for receiver mode")
    parser.add_argument("--stats-json", help="write transfer metrics as JSON to this path")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
        help="application log level",
    )
    return parser


def write_stats(stats_path: str | None, stats_json: str) -> None:
    if stats_path is None:
        print(stats_json, file=sys.stderr)
        return
    Path(stats_path).write_text(stats_json + "\n", encoding="utf-8")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not 1 <= args.port <= 65534:
        parser.error("--port must be between 1 and 65534")
    if not 1 <= args.window <= 255:
        parser.error("--window must be between 1 and 255")

    if args.listen:
        if not args.output:
            parser.error("--output is required in receiver mode")
        receiver = RtpReceiver(
            bind_host=args.bind_host,
            port=args.port,
            mode=args.mode,
            window=args.window,
            output_path=Path(args.output),
        )
        stats = receiver.run()
        write_stats(args.stats_json, stats.to_json())
        return 0

    if not args.input:
        parser.error("--input is required in sender mode")

    sender = RtpSender(
        bind_host=args.bind_host,
        peer_host=args.host,
        port=args.port,
        mode=args.mode,
        window=args.window,
        input_path=Path(args.input),
    )
    stats = sender.run()
    write_stats(args.stats_json, stats.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())