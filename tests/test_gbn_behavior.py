from __future__ import annotations

from pathlib import Path

from rtp.peer import RtpReceiver, Session
from rtp.protocol import Header, Packet, build_control_packet
import rtp.peer as peer_module


def test_gbn_old_duplicate_produces_cumulative_ack(monkeypatch, tmp_path: Path) -> None:
    receiver = RtpReceiver(
        bind_host="127.0.0.1",
        port=9000,
        mode=peer_module.ProtocolMode.GO_BACK_N,
        window=4,
        output_path=tmp_path / "received.bin",
    )
    session = Session(peer=("127.0.0.1", 9999), window=4)

    inbound_packets = [
        (Packet(header=Header(seq=index, length=1), payload=b"x"), session.peer)
        for index in range(6)
    ]
    inbound_packets.extend(
        [
            (Packet(header=Header(seq=0, length=1), payload=b"x"), session.peer),
            (build_control_packet(fin=True), session.peer),
        ]
    )
    packet_iter = iter(inbound_packets)
    sent_controls: list[Packet] = []

    def fake_receive_packet(_socket: object) -> tuple[Packet | None, tuple[str, int]]:
        return next(packet_iter)

    def fake_send_packet(_socket: object, packet: Packet, _address: tuple[str, int]) -> None:
        sent_controls.append(packet)

    monkeypatch.setattr(peer_module, "receive_packet", fake_receive_packet)
    monkeypatch.setattr(receiver, "_send_packet", fake_send_packet)

    payload = receiver._receive_go_back_n(object(), session)

    assert payload == b"x" * 6
    duplicate_response = sent_controls[6]
    assert duplicate_response.header.ack_flag is True
    assert duplicate_response.header.nack is False
    assert duplicate_response.header.ack == 5