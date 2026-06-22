from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import socket
import time
from typing import Callable

from rtp.protocol import (
    ProtocolMode,
    TIMEOUT_SECONDS,
    Packet,
    build_control_packet,
    build_data_packets,
    seq_add,
    seq_in_window,
    seq_is_recent,
    seq_prev,
)

SocketAddress = tuple[str, int]
LOGGER = logging.getLogger("rtp")


@dataclass(slots=True)
class TransferStats:
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float = 0.0
    bytes_transferred: int = 0
    datagrams_sent: int = 0
    datagrams_received: int = 0
    retransmissions: int = 0

    def finish(self) -> None:
        self.finished_at = time.monotonic()

    @property
    def duration(self) -> float:
        end_time = self.finished_at or time.monotonic()
        return max(end_time - self.started_at, 0.0)

    @property
    def throughput_bytes_per_second(self) -> float:
        if self.duration == 0:
            return 0.0
        return self.bytes_transferred / self.duration

    def to_dict(self) -> dict[str, float | int]:
        return {
            "bytes_transferred": self.bytes_transferred,
            "datagrams_sent": self.datagrams_sent,
            "datagrams_received": self.datagrams_received,
            "retransmissions": self.retransmissions,
            "duration_seconds": self.duration,
            "throughput_bytes_per_second": self.throughput_bytes_per_second,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


@dataclass(frozen=True, slots=True)
class Session:
    peer: SocketAddress
    window: int


class ProtocolError(RuntimeError):
    pass


def create_bound_socket(bind_host: str, port: int, timeout: float | None) -> socket.socket:
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_socket.bind((bind_host, port))
    if timeout is not None:
        udp_socket.settimeout(timeout)
    return udp_socket


def create_sender_socket(bind_host: str, timeout: float) -> socket.socket:
    sender_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sender_socket.bind((bind_host, 0))
    sender_socket.settimeout(timeout)
    return sender_socket


def receive_packet(udp_socket: socket.socket) -> tuple[Packet | None, SocketAddress]:
    data, address = udp_socket.recvfrom(4096)
    return Packet.parse(data), address


class RtpSender:
    def __init__(
        self,
        *,
        bind_host: str,
        peer_host: str,
        port: int,
        mode: ProtocolMode,
        window: int,
        input_path: Path,
    ) -> None:
        self.bind_host = bind_host
        self.peer_host = peer_host
        self.port = port
        self.mode = mode
        self.window = window
        self.input_path = input_path
        self.stats = TransferStats()
        self._last_progress_log = 0.0

    def run(self) -> TransferStats:
        payload = self.input_path.read_bytes()
        packets = build_data_packets(payload)
        self.stats.bytes_transferred = len(payload)
        LOGGER.info(
            "sender_start mode=%s window=%s bytes=%s packets=%s peer=%s:%s",
            self.mode.value,
            self.window,
            len(payload),
            len(packets),
            self.peer_host,
            self.port,
        )

        sender_socket = create_sender_socket(self.bind_host, TIMEOUT_SECONDS)
        with sender_socket:
            session = self._establish_session(sender_socket)
            if self.mode is ProtocolMode.STOP_AND_WAIT:
                self._send_stop_and_wait(sender_socket, session, packets)
            elif self.mode is ProtocolMode.GO_BACK_N:
                self._send_go_back_n(sender_socket, session, packets)
            else:
                self._send_selective_repeat(sender_socket, session, packets)
            self._close_session(sender_socket, session)

        self.stats.finish()
        LOGGER.info("sender_complete stats=%s", self.stats.to_json())
        return self.stats

    def _establish_session(self, data_socket: socket.socket) -> Session:
        peer = (self.peer_host, self.port)
        syn_packet = build_control_packet(syn=True, length=self.window)

        while True:
            LOGGER.info("sender_handshake syn proposed_window=%s peer=%s:%s", self.window, peer[0], peer[1])
            self._send_packet(data_socket, syn_packet, peer)
            response = self._wait_for_control(
                data_socket,
                lambda packet, address: (
                    address == peer
                    and packet.header.syn
                    and packet.header.ack_flag
                    and not packet.header.nack
                    and not packet.header.fin
                ),
                peer=peer,
            )
            if response is None:
                LOGGER.warning("sender_handshake timeout waiting_for=syn_ack")
                self.stats.retransmissions += 1
                continue
            window = max(1, min(self.window, response.header.length))
            ack_packet = build_control_packet(ack=0, ack_flag=True)
            self._send_packet(data_socket, ack_packet, peer)
            LOGGER.info("sender_handshake established negotiated_window=%s", window)
            return Session(peer=peer, window=window)

    def _close_session(
        self,
        data_socket: socket.socket,
        session: Session,
    ) -> None:
        fin_packet = build_control_packet(fin=True)
        while True:
            LOGGER.info("sender_close send_fin")
            self._send_packet(data_socket, fin_packet, session.peer)
            response = self._wait_for_control(
                data_socket,
                lambda packet, address: (
                    address == session.peer
                    and packet.header.fin
                    and packet.header.ack_flag
                ),
                peer=session.peer,
            )
            if response is not None:
                LOGGER.info("sender_close fin_ack_received")
                return
            LOGGER.warning("sender_close timeout waiting_for=fin_ack")
            self.stats.retransmissions += 1

    def _send_stop_and_wait(
        self,
        data_socket: socket.socket,
        session: Session,
        packets: list[Packet],
    ) -> None:
        for packet in packets:
            while True:
                self._send_packet(data_socket, packet, session.peer)
                response = self._wait_for_control(
                    data_socket,
                    lambda control, address: (
                        self._is_data_phase_control(control, address, session.peer)
                        and control.header.ack_flag
                        and not control.header.nack
                        and control.header.ack == packet.header.seq
                    ),
                    peer=session.peer,
                )
                if response is not None:
                    self._maybe_log_sender_progress("saw", packet.header.seq + 1, len(packets), packet.header.seq + 1, packet.header.seq + 1)
                    break
                LOGGER.warning("sender_saw timeout seq=%s retransmitting", packet.header.seq)
                self.stats.retransmissions += 1

    def _send_go_back_n(
        self,
        data_socket: socket.socket,
        session: Session,
        packets: list[Packet],
    ) -> None:
        base = 0
        next_to_send = 0

        while base < len(packets):
            while next_to_send < len(packets) and next_to_send - base < session.window:
                self._send_packet(data_socket, packets[next_to_send], session.peer)
                next_to_send += 1
            self._maybe_log_sender_progress("gbn", base, len(packets), base, next_to_send)

            response = self._wait_for_control(
                data_socket,
                lambda packet, address: self._is_data_phase_control(packet, address, session.peer),
                peer=session.peer,
            )
            
            if response is None:
                LOGGER.warning("sender_gbn timeout base=%s next=%s retransmit_from=%s", base, next_to_send, base)
                self._retransmit_range(data_socket, session.peer, packets, base, next_to_send)
                continue

            if response.header.nack:
                missing_index = self._find_index(packets, base, next_to_send, response.header.ack)
                if missing_index is not None:
                    LOGGER.info("sender_gbn nack ack=%s missing_index=%s base=%s next=%s", response.header.ack, missing_index, base, next_to_send)
                    self._retransmit_range(data_socket, session.peer, packets, missing_index, next_to_send)
                else:
                    LOGGER.warning("sender_gbn nack_outside_window ack=%s base=%s next=%s retransmit_from_base", response.header.ack, base, next_to_send)
                    self._retransmit_range(data_socket, session.peer, packets, base, next_to_send)
                continue

            if not response.header.ack_flag:
                continue

            acked_index = self._find_index(packets, base, next_to_send, response.header.ack)
            if acked_index is not None:
                base = acked_index + 1
                self._maybe_log_sender_progress("gbn", base, len(packets), base, next_to_send)

    def _send_selective_repeat(
        self,
        data_socket: socket.socket,
        session: Session,
        packets: list[Packet],
    ) -> None:
        base = 0
        next_to_send = 0
        acked = [False] * len(packets)
        last_sent_at = [0.0] * len(packets)

        def send_index(index: int, *, retransmission: bool = False) -> None:
            self._send_packet(data_socket, packets[index], session.peer)
            last_sent_at[index] = time.monotonic()
            if retransmission:
                self.stats.retransmissions += 1

        while base < len(packets):
            while next_to_send < len(packets) and next_to_send - base < session.window:
                send_index(next_to_send)
                next_to_send += 1
            self._maybe_log_sender_progress("sr", base, len(packets), base, next_to_send)

            deadline = self._earliest_deadline(base, next_to_send, acked, last_sent_at)
            response = self._wait_for_control(
                data_socket,
                lambda packet, address: self._is_data_phase_control(packet, address, session.peer),
                deadline,
                peer=session.peer,
            )
            current_time = time.monotonic()

            if response is not None:
                if response.header.nack:
                    missing_index = self._find_index(packets, base, next_to_send, response.header.ack)
                    if missing_index is not None and not acked[missing_index]:
                        LOGGER.info("sender_sr nack ack=%s missing_index=%s base=%s next=%s", response.header.ack, missing_index, base, next_to_send)
                        send_index(missing_index, retransmission=True)
                elif response.header.ack_flag:
                    acked_index = self._find_index(packets, base, next_to_send, response.header.ack)
                    if acked_index is not None:
                        acked[acked_index] = True
                        self._maybe_log_sender_progress("sr", acked_index + 1, len(packets), base, next_to_send)

            for index in range(base, next_to_send):
                if acked[index]:
                    continue
                if current_time - last_sent_at[index] >= TIMEOUT_SECONDS:
                    LOGGER.warning("sender_sr timeout index=%s base=%s next=%s", index, base, next_to_send)
                    send_index(index, retransmission=True)

            while base < len(packets) and acked[base]:
                base += 1

    def _maybe_log_sender_progress(
        self,
        mode_name: str,
        completed_packets: int,
        total_packets: int,
        base: int,
        next_to_send: int,
    ) -> None:
        now = time.monotonic()
        if completed_packets == total_packets or now - self._last_progress_log >= 1.0:
            LOGGER.info(
                "sender_progress mode=%s completed_packets=%s total_packets=%s base=%s next=%s retransmissions=%s",
                mode_name,
                completed_packets,
                total_packets,
                base,
                next_to_send,
                self.stats.retransmissions,
            )
            self._last_progress_log = now

    def _earliest_deadline(
        self,
        base: int,
        next_to_send: int,
        acked: list[bool],
        last_sent_at: list[float],
    ) -> float:
        deadlines = [
            last_sent_at[index] + TIMEOUT_SECONDS
            for index in range(base, next_to_send)
            if not acked[index]
        ]
        if not deadlines:
            return time.monotonic() + TIMEOUT_SECONDS
        return min(deadlines)

    def _retransmit_range(
        self,
        data_socket: socket.socket,
        peer_data: SocketAddress,
        packets: list[Packet],
        start: int,
        end: int,
    ) -> None:
        for index in range(start, end):
            self._send_packet(data_socket, packets[index], peer_data)
            self.stats.retransmissions += 1

    def _find_index(
        self,
        packets: list[Packet],
        start: int,
        end: int,
        seq: int,
    ) -> int | None:
        for index in range(start, end):
            if packets[index].header.seq == seq:
                return index
        return None

    def _send_packet(self, udp_socket: socket.socket, packet: Packet, address: SocketAddress) -> None:
        udp_socket.sendto(packet.to_bytes(), address)
        self.stats.datagrams_sent += 1

    def _is_data_phase_control(self, packet: Packet, address: SocketAddress, peer: SocketAddress) -> bool:
        return (
            address == peer
            and not packet.header.syn
            and not packet.header.fin
        )

    def _wait_for_control(
        self,
        udp_socket: socket.socket,
        predicate: Callable[[Packet, SocketAddress], bool],
        deadline: float | None = None,
        peer: SocketAddress | None = None,
    ) -> Packet | None:
        until = deadline if deadline is not None else time.monotonic() + TIMEOUT_SECONDS
        while True:
            remaining = until - time.monotonic()
            if remaining <= 0:
                return None
            udp_socket.settimeout(remaining)
            try:
                packet, address = receive_packet(udp_socket)
            except TimeoutError:
                return None
            if packet is None:
                continue
            self.stats.datagrams_received += 1
            if predicate(packet, address):
                return packet
            if self._should_repeat_final_ack(packet, address, peer):
                self._send_packet(udp_socket, build_control_packet(ack=0, ack_flag=True), address)

    def _should_repeat_final_ack(
        self,
        packet: Packet,
        address: SocketAddress,
        peer: SocketAddress | None,
    ) -> bool:
        return (
            peer is not None
            and address == peer
            and packet.header.syn
            and packet.header.ack_flag
            and not packet.header.nack
            and not packet.header.fin
        )


class RtpReceiver:
    def __init__(
        self,
        *,
        bind_host: str,
        port: int,
        mode: ProtocolMode,
        window: int,
        output_path: Path,
    ) -> None:
        self.bind_host = bind_host
        self.port = port
        self.mode = mode
        self.window = window
        self.output_path = output_path
        self.stats = TransferStats()
        self._last_progress_log = 0.0

    def run(self) -> TransferStats:
        LOGGER.info(
            "receiver_start mode=%s window=%s bind=%s:%s output=%s",
            self.mode.value,
            self.window,
            self.bind_host,
            self.port,
            self.output_path,
        )
        with create_bound_socket(self.bind_host, self.port, None) as data_socket:
            session = self._accept_session(data_socket)
            payload = self._receive_stream(data_socket, session)
            self.output_path.write_bytes(payload)
            self.stats.bytes_transferred = len(payload)
        self.stats.finish()
        LOGGER.info("receiver_complete stats=%s", self.stats.to_json())
        return self.stats

    def _accept_session(self, data_socket: socket.socket) -> Session:
        while True:
            packet, address = receive_packet(data_socket)
            if packet is None:
                continue
            self.stats.datagrams_received += 1
            if not packet.header.syn or packet.header.ack_flag or packet.header.fin:
                continue

            proposed_window = max(1, min(self.window, packet.header.length))
            syn_ack = build_control_packet(syn=True, ack=0, ack_flag=True, length=self.window)
            LOGGER.info("receiver_handshake syn_received proposed_window=%s peer=%s:%s", proposed_window, address[0], address[1])

            while True:
                self._send_packet(data_socket, syn_ack, address)
                data_socket.settimeout(TIMEOUT_SECONDS)
                try:
                    response, response_address = receive_packet(data_socket)
                except socket.timeout:
                    LOGGER.warning("receiver_handshake timeout waiting_for=final_ack")
                    self.stats.retransmissions += 1
                    continue
                finally:
                    data_socket.settimeout(None)

                if response is None:
                    continue
                self.stats.datagrams_received += 1
                if response_address != address:
                    continue
                if response.header.syn and not response.header.ack_flag:
                    self.stats.retransmissions += 1
                    continue
                if response.header.ack_flag and not response.header.syn and not response.header.fin:
                    LOGGER.info("receiver_handshake established negotiated_window=%s", proposed_window)
                    return Session(peer=address, window=proposed_window)

    def _receive_stream(self, data_socket: socket.socket, session: Session) -> bytes:
        if self.mode is ProtocolMode.STOP_AND_WAIT:
            return self._receive_stop_and_wait(data_socket, session)
        if self.mode is ProtocolMode.GO_BACK_N:
            return self._receive_go_back_n(data_socket, session)
        return self._receive_selective_repeat(data_socket, session)

    def _is_data_packet(self, packet: Packet) -> bool:
        return (
            not packet.header.syn
            and not packet.header.fin
            and not packet.header.ack_flag
            and not packet.header.nack
        )

    def _receive_stop_and_wait(self, data_socket: socket.socket, session: Session) -> bytes:
        expected = 0
        assembled = bytearray()

        while True:
            packet, address = receive_packet(data_socket)
            if address != session.peer or packet is None:
                continue
            self.stats.datagrams_received += 1

            if packet.header.fin:
                LOGGER.info("receiver_close fin_received")
                self._send_packet(data_socket, build_control_packet(fin=True, ack=0, ack_flag=True), session.peer)
                return bytes(assembled)

            if not self._is_data_packet(packet):
                continue

            seq = packet.header.seq
            if seq == expected:
                assembled.extend(packet.payload)
                self._send_packet(data_socket, build_control_packet(ack=seq, ack_flag=True), session.peer)
                expected = seq_add(expected, 1)
                self._maybe_log_receiver_progress("saw", expected, len(assembled))
                continue

            if seq == seq_prev(expected):
                self._send_packet(data_socket, build_control_packet(ack=seq, ack_flag=True), session.peer)

    def _receive_go_back_n(self, data_socket: socket.socket, session: Session) -> bytes:
        expected = 0
        assembled = bytearray()

        while True:
            packet, address = receive_packet(data_socket)
            if address != session.peer or packet is None:
                continue
            self.stats.datagrams_received += 1

            if packet.header.fin:
                LOGGER.info("receiver_close fin_received")
                self._send_packet(data_socket, build_control_packet(fin=True, ack=0, ack_flag=True), session.peer)
                return bytes(assembled)

            if not self._is_data_packet(packet):
                continue

            seq = packet.header.seq
            if seq == expected:
                assembled.extend(packet.payload)
                self._send_packet(data_socket, build_control_packet(ack=seq, ack_flag=True), session.peer)
                expected = seq_add(expected, 1)
                self._maybe_log_receiver_progress("gbn", expected, len(assembled))
                continue

            if seq_in_window(seq, expected, session.window):
                LOGGER.info("receiver_gbn out_of_order seq=%s expected=%s send_nack", seq, expected)
                self._send_packet(
                    data_socket,
                    build_control_packet(ack=expected, ack_flag=True, nack=True),
                    session.peer,
                )
                continue

            if seq_is_recent(seq, expected, expected if expected < session.window else session.window):
                LOGGER.info("receiver_gbn duplicate seq=%s expected=%s resend_ack=%s", seq, expected, seq_prev(expected))
                self._send_packet(
                    data_socket,
                    build_control_packet(ack=seq_prev(expected), ack_flag=True),
                    session.peer,
                )
                continue

            self._send_packet(
                data_socket,
                build_control_packet(ack=seq_prev(expected), ack_flag=True),
                session.peer,
            )

    def _receive_selective_repeat(self, data_socket: socket.socket, session: Session) -> bytes:
        base = 0
        buffered: dict[int, bytes] = {}
        assembled = bytearray()

        while True:
            packet, address = receive_packet(data_socket)
            if address != session.peer or packet is None:
                continue
            self.stats.datagrams_received += 1

            if packet.header.fin:
                LOGGER.info("receiver_close fin_received")
                self._send_packet(data_socket, build_control_packet(fin=True, ack=0, ack_flag=True), session.peer)
                return bytes(assembled)

            if not self._is_data_packet(packet):
                continue

            seq = packet.header.seq
            if seq_in_window(seq, base, session.window):
                if seq not in buffered:
                    buffered[seq] = packet.payload
                self._send_packet(data_socket, build_control_packet(ack=seq, ack_flag=True), session.peer)
                if seq != base:
                    self._send_packet(
                        data_socket,
                        build_control_packet(ack=base, ack_flag=True, nack=True),
                        session.peer,
                    )
                while base in buffered:
                    assembled.extend(buffered.pop(base))
                    base = seq_add(base, 1)
                self._maybe_log_receiver_progress("sr", base, len(assembled))
                continue

            if seq_is_recent(seq, base, session.window):
                self._send_packet(data_socket, build_control_packet(ack=seq, ack_flag=True), session.peer)
                continue

            self._send_packet(
                data_socket,
                build_control_packet(ack=base, ack_flag=True, nack=True),
                session.peer,
            )

    def _maybe_log_receiver_progress(self, mode_name: str, delivered_packets: int, assembled_bytes: int) -> None:
        now = time.monotonic()
        if delivered_packets == 0:
            return
        if delivered_packets % 8 == 0 or now - self._last_progress_log >= 1.0:
            LOGGER.info(
                "receiver_progress mode=%s delivered_packets=%s assembled_bytes=%s retransmissions=%s",
                mode_name,
                delivered_packets,
                assembled_bytes,
                self.stats.retransmissions,
            )
            self._last_progress_log = now

    def _send_packet(self, udp_socket: socket.socket, packet: Packet, address: SocketAddress) -> None:
        udp_socket.sendto(packet.to_bytes(), address)
        self.stats.datagrams_sent += 1