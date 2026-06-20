from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import zlib

HEADER_SIZE = 9
MAX_PAYLOAD_SIZE = 255
MAX_SEQUENCE = 1 << 14
TIMEOUT_SECONDS = 0.1


class ProtocolMode(StrEnum):
    STOP_AND_WAIT = "saw"
    GO_BACK_N = "gbn"
    SELECTIVE_REPEAT = "sr"


@dataclass(frozen=True, slots=True)
class Header:
    seq: int = 0
    syn: bool = False
    fin: bool = False
    ack: int = 0
    ack_flag: bool = False
    nack: bool = False
    length: int = 0
    crc32: int = 0

    def pack(self) -> bytes:
        validate_header(self)
        value = (
            (self.seq & 0x3FFF) << 58
            | (int(self.syn) << 57)
            | (int(self.fin) << 56)
            | ((self.ack & 0x3FFF) << 42)
            | (int(self.ack_flag) << 41)
            | (int(self.nack) << 40)
            | ((self.length & 0xFF) << 32)
            | (self.crc32 & 0xFFFFFFFF)
        )
        return value.to_bytes(HEADER_SIZE, byteorder="big")

    @classmethod
    def unpack(cls, data: bytes) -> Header:
        if len(data) != HEADER_SIZE:
            raise ValueError("invalid RTP header size")
        value = int.from_bytes(data, byteorder="big")
        return cls(
            seq=(value >> 58) & 0x3FFF,
            syn=bool((value >> 57) & 0x1),
            fin=bool((value >> 56) & 0x1),
            ack=(value >> 42) & 0x3FFF,
            ack_flag=bool((value >> 41) & 0x1),
            nack=bool((value >> 40) & 0x1),
            length=(value >> 32) & 0xFF,
            crc32=value & 0xFFFFFFFF,
        )


@dataclass(frozen=True, slots=True)
class Packet:
    header: Header
    payload: bytes = b""

    def to_bytes(self) -> bytes:
        if self.header.syn:
            if self.payload:
                raise ValueError("handshake packets cannot carry payload")
        elif len(self.payload) != self.header.length:
            raise ValueError("payload length does not match header length")
        checksum_header = replace(self.header, crc32=0)
        checksum = zlib.crc32(checksum_header.pack() + self.payload) & 0xFFFFFFFF
        header = replace(self.header, crc32=checksum)
        return header.pack() + self.payload

    @classmethod
    def parse(cls, data: bytes) -> Packet | None:
        if len(data) < HEADER_SIZE:
            return None
        try:
            header = Header.unpack(data[:HEADER_SIZE])
        except ValueError:
            return None
        expected_payload_length = 0 if header.syn else header.length
        if len(data) != HEADER_SIZE + expected_payload_length:
            return None
        payload = data[HEADER_SIZE:]
        checksum_header = replace(header, crc32=0)
        checksum = zlib.crc32(checksum_header.pack() + payload) & 0xFFFFFFFF
        if checksum != header.crc32:
            return None
        return cls(header=header, payload=payload)


def validate_header(header: Header) -> None:
    if not 0 <= header.seq < MAX_SEQUENCE:
        raise ValueError("sequence number out of range")
    if not 0 <= header.ack < MAX_SEQUENCE:
        raise ValueError("acknowledgement number out of range")
    if not 0 <= header.length <= MAX_PAYLOAD_SIZE:
        raise ValueError("invalid payload length")
    if not 0 <= header.crc32 <= 0xFFFFFFFF:
        raise ValueError("invalid crc32 value")


def seq_add(seq: int, increment: int) -> int:
    return (seq + increment) % MAX_SEQUENCE


def seq_prev(seq: int) -> int:
    return (seq - 1) % MAX_SEQUENCE


def seq_distance(seq: int, start: int) -> int:
    return (seq - start) % MAX_SEQUENCE


def seq_in_window(seq: int, start: int, size: int) -> bool:
    return seq_distance(seq, start) < size


def seq_is_recent(seq: int, current: int, size: int) -> bool:
    distance = (current - seq) % MAX_SEQUENCE
    return 0 < distance <= size


def build_data_packets(data: bytes) -> list[Packet]:
    payloads = [data[index:index + MAX_PAYLOAD_SIZE] for index in range(0, len(data), MAX_PAYLOAD_SIZE)]
    if len(data) == 0 or len(data) % MAX_PAYLOAD_SIZE == 0:
        payloads.append(b"")
    return [
        Packet(
            header=Header(seq=seq_add(0, index), length=len(payload)),
            payload=payload,
        )
        for index, payload in enumerate(payloads)
    ]


def build_control_packet(
    *,
    seq: int = 0,
    syn: bool = False,
    fin: bool = False,
    ack: int = 0,
    ack_flag: bool = False,
    nack: bool = False,
    length: int = 0,
) -> Packet:
    return Packet(
        header=Header(
            seq=seq,
            syn=syn,
            fin=fin,
            ack=ack,
            ack_flag=ack_flag,
            nack=nack,
            length=length,
        )
    )