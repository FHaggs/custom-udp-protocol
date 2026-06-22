from __future__ import annotations

from pathlib import Path
import socket
import threading
import time

import pytest

import rtp.peer as peer_module
from rtp.peer import RtpReceiver, RtpSender, create_sender_socket
from rtp.protocol import Header, Packet, ProtocolMode, build_control_packet


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
        bind_host="127.0.0.1",
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


def test_sender_uses_p_plus_one_for_roundtrip_control() -> None:
    base_port = 24000 + int(time.time() * 1000) % 10000

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver_socket:
        receiver_socket.bind(("127.0.0.1", base_port))
        receiver_socket.settimeout(1.0)

        with create_sender_socket("127.0.0.1", base_port, 1.0) as sender_socket:
            sender_socket.sendto(
                build_control_packet(syn=True, length=4).to_bytes(),
                ("127.0.0.1", base_port),
            )

            _, sender_address = receiver_socket.recvfrom(4096)

            receiver_socket.sendto(
                build_control_packet(ack=0, ack_flag=True).to_bytes(),
                sender_address,
            )

            raw_response, response_address = sender_socket.recvfrom(4096)

    response_packet = Packet.parse(raw_response)

    assert sender_address[1] == base_port + 1
    assert response_address[1] == base_port
    assert response_packet is not None
    assert response_packet.header.ack_flag is True


def test_sender_repeats_final_ack_on_duplicate_syn_ack(monkeypatch, tmp_path: Path) -> None:
    sender = RtpSender(
        bind_host="127.0.0.1",
        peer_host="127.0.0.1",
        port=9000,
        mode=ProtocolMode.STOP_AND_WAIT,
        window=1,
        input_path=tmp_path / "source.bin",
    )
    peer = ("127.0.0.1", 9000)
    duplicate_syn_ack = Packet(header=Header(syn=True, ack_flag=True, length=1))
    data_ack = Packet(header=Header(ack=0, ack_flag=True))
    inbound_packets = iter([(duplicate_syn_ack, peer), (data_ack, peer)])
    sent_controls: list[Packet] = []

    class FakeSocket:
        def settimeout(self, _timeout: float) -> None:
            return None

    def fake_receive_packet(_socket: object) -> tuple[Packet | None, tuple[str, int]]:
        return next(inbound_packets)

    def fake_send_packet(_socket: object, packet: Packet, _address: tuple[str, int]) -> None:
        sent_controls.append(packet)

    monkeypatch.setattr(peer_module, "receive_packet", fake_receive_packet)
    monkeypatch.setattr(sender, "_send_packet", fake_send_packet)

    response = sender._wait_for_control(
        FakeSocket(),
        lambda packet, address: address == peer and packet.header.ack_flag and not packet.header.syn,
        peer=peer,
    )

    assert response == data_ack
    assert len(sent_controls) == 1
    assert sent_controls[0].header.ack_flag is True
    assert sent_controls[0].header.syn is False
    assert sent_controls[0].header.fin is False


def test_sender_saw_does_not_treat_duplicate_syn_ack_as_data_ack(monkeypatch, tmp_path: Path) -> None:
    sender = RtpSender(
        bind_host="127.0.0.1",
        peer_host="127.0.0.1",
        port=9000,
        mode=ProtocolMode.STOP_AND_WAIT,
        window=1,
        input_path=tmp_path / "source.bin",
    )
    session = peer_module.Session(peer=("127.0.0.1", 9000), window=1)
    packet = Packet(header=Header(seq=0, length=1), payload=b"a")
    duplicate_syn_ack = Packet(header=Header(syn=True, ack_flag=True, length=1))
    real_ack = Packet(header=Header(ack=0, ack_flag=True))
    inbound_packets = iter([(duplicate_syn_ack, session.peer), (real_ack, session.peer)])
    sent_packets: list[Packet] = []

    class FakeSocket:
        def settimeout(self, _timeout: float) -> None:
            return None

    def fake_receive_packet(_socket: object) -> tuple[Packet | None, tuple[str, int]]:
        return next(inbound_packets)

    def fake_send_packet(_socket: object, outbound_packet: Packet, _address: tuple[str, int]) -> None:
        sent_packets.append(outbound_packet)

    monkeypatch.setattr(peer_module, "receive_packet", fake_receive_packet)
    monkeypatch.setattr(sender, "_send_packet", fake_send_packet)

    sender._send_stop_and_wait(FakeSocket(), session, [packet])

    assert [outbound.header.seq for outbound in sent_packets if outbound.header.length == 1] == [0]
    control_packets = [outbound for outbound in sent_packets if outbound.header.ack_flag]
    assert len(control_packets) == 1
    assert control_packets[0].header.syn is False
    assert control_packets[0].header.ack == 0


def test_receiver_ignores_ack_only_control_during_data_phase(monkeypatch, tmp_path: Path) -> None:
    receiver = RtpReceiver(
        bind_host="127.0.0.1",
        port=9000,
        mode=ProtocolMode.STOP_AND_WAIT,
        window=1,
        output_path=tmp_path / "received.bin",
    )
    session = peer_module.Session(peer=("127.0.0.1", 9999), window=1)
    inbound_packets = iter(
        [
            (Packet(header=Header(ack=0, ack_flag=True)), session.peer),
            (Packet(header=Header(seq=0, length=1), payload=b"a"), session.peer),
            (peer_module.build_control_packet(fin=True), session.peer),
        ]
    )
    sent_controls: list[Packet] = []

    def fake_receive_packet(_socket: object) -> tuple[Packet | None, tuple[str, int]]:
        return next(inbound_packets)

    def fake_send_packet(_socket: object, packet: Packet, _address: tuple[str, int]) -> None:
        sent_controls.append(packet)

    monkeypatch.setattr(peer_module, "receive_packet", fake_receive_packet)
    monkeypatch.setattr(receiver, "_send_packet", fake_send_packet)

    payload = receiver._receive_stop_and_wait(object(), session)

    assert payload == b"a"
    assert [packet.header.ack for packet in sent_controls if packet.header.ack_flag and not packet.header.fin] == [0]


def test_sender_sr_retransmits_missing_packet_on_nack_without_acknowledging_it(monkeypatch, tmp_path: Path) -> None:
    sender = RtpSender(
        bind_host="127.0.0.1",
        peer_host="127.0.0.1",
        port=9000,
        mode=ProtocolMode.SELECTIVE_REPEAT,
        window=4,
        input_path=tmp_path / "source.bin",
    )
    session = peer_module.Session(peer=("127.0.0.1", 9000), window=4)
    packets = [
        Packet(header=Header(seq=seq, length=1), payload=b"x")
        for seq in range(37, 41)
    ]
    inbound_packets = iter(
        [
            (Packet(header=Header(ack=37, ack_flag=True, nack=True)), session.peer),
            (Packet(header=Header(ack=37, ack_flag=True)), session.peer),
            (Packet(header=Header(ack=38, ack_flag=True)), session.peer),
            (Packet(header=Header(ack=39, ack_flag=True)), session.peer),
            (Packet(header=Header(ack=40, ack_flag=True)), session.peer),
        ]
    )
    sent_packets: list[Packet] = []

    class FakeSocket:
        def settimeout(self, _timeout: float) -> None:
            return None

    def fake_receive_packet(_socket: object) -> tuple[Packet | None, tuple[str, int]]:
        return next(inbound_packets)

    def fake_send_packet(_socket: object, outbound_packet: Packet, _address: tuple[str, int]) -> None:
        sent_packets.append(outbound_packet)

    monkeypatch.setattr(peer_module, "receive_packet", fake_receive_packet)
    monkeypatch.setattr(sender, "_send_packet", fake_send_packet)

    sender._send_selective_repeat(FakeSocket(), session, packets)

    assert [packet.header.seq for packet in sent_packets] == [37, 38, 39, 40, 37]