from __future__ import annotations

from dataclasses import replace

from rtp.protocol import HEADER_SIZE, Header, Packet, build_data_packets, seq_in_window


def test_header_roundtrip() -> None:
    header = Header(seq=123, syn=True, ack=77, ack_flag=True, length=42, crc32=0xDEADBEEF)
    assert Header.unpack(header.pack()) == header
    assert len(header.pack()) == HEADER_SIZE


def test_packet_crc_rejects_corruption() -> None:
    packet = Packet(header=Header(seq=1, length=4), payload=b"test")
    raw = bytearray(packet.to_bytes())
    raw[-1] ^= 0xFF
    assert Packet.parse(bytes(raw)) is None


def test_build_data_packets_adds_zero_length_terminator() -> None:
    packets = build_data_packets(b"a" * 510)
    assert [packet.header.length for packet in packets] == [255, 255, 0]


def test_build_data_packets_keeps_short_last_payload() -> None:
    packets = build_data_packets(b"a" * 300)
    assert [packet.header.length for packet in packets] == [255, 45]


def test_sequence_window_wraps_correctly() -> None:
    assert seq_in_window(0, 16383, 2)
    assert not seq_in_window(2, 16383, 2)