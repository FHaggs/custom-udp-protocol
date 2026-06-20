from __future__ import annotations

from pathlib import Path
import threading
import time

import pytest

from rtp.peer import RtpReceiver, RtpSender
from rtp.protocol import ProtocolMode


@pytest.mark.parametrize(
    ("mode", "window"),
    [
        (ProtocolMode.STOP_AND_WAIT, 1),
        (ProtocolMode.GO_BACK_N, 4),
        (ProtocolMode.SELECTIVE_REPEAT, 4),
    ],
)
def test_end_to_end_transfer(mode: ProtocolMode, window: int, tmp_path: Path) -> None:
    base_port = 21000 + int(time.time() * 1000) % 20000
    source_path = tmp_path / "source.bin"
    output_path = tmp_path / "received.bin"
    source_bytes = b"networking-test-" * 80
    source_path.write_bytes(source_bytes)

    receiver = RtpReceiver(
        bind_host="127.0.0.1",
        port=base_port,
        mode=mode,
        window=window,
        output_path=output_path,
    )
    sender = RtpSender(
        bind_host="127.0.0.2",
        peer_host="127.0.0.1",
        port=base_port,
        mode=mode,
        window=window,
        input_path=source_path,
    )

    receiver_thread = threading.Thread(target=receiver.run, daemon=True)
    receiver_thread.start()
    time.sleep(0.05)
    sender.run()
    receiver_thread.join(timeout=5)

    assert not receiver_thread.is_alive()
    assert output_path.read_bytes() == source_bytes