from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import socket
import time

from rtp.protocol import (
    MAX_PAYLOAD_SIZE,
    ProtocolMode,
    TIMEOUT_SECONDS,
    Packet,
    build_control_packet,
    build_data_packets,
    seq_add,
    seq_distance,
    seq_in_window,
    seq_is_recent,
    seq_prev,
)

SocketAddress = tuple[str, int]


@dataclass(slots=True)
class TransferStats:
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float = 0.0
    datagrams_sent: int = 0
    datagrams_received: int = 0
    retransmissions: int = 0

    def finish(self) -> None:
        self.finished_at = time.monotonic()

    @property
    def duration(self) -> float:
        end_time = self.finished_at or time.monotonic()
        return max(end_time - self.started_at, 0.0)


@dataclass(frozen=True, slots=True)
class Session:
    peer_data: SocketAddress
    peer_control: SocketAddress
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


def create_sender_socket_pair(bind_host: str, timeout: float) -> tuple[socket.socket, socket.socket]:
    while True:
        data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        data_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        data_socket.bind((bind_host, 0))
        data_socket.settimeout(timeout)
        data_port = int(data_socket.getsockname()[1])

        if data_port >= 65535:
            data_socket.close()
            continue

        try:
            control_socket = create_bound_socket(bind_host, data_port + 1, timeout)
        except OSError:
            data_socket.close()
            continue

        return data_socket, control_socket


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

    def run(self) -> TransferStats:
        payload = self.input_path.read_bytes()
        packets = build_data_packets(payload)

        data_socket, control_socket = create_sender_socket_pair(self.bind_host, TIMEOUT_SECONDS)
        with data_socket, control_socket:
            session = self._establish_session(data_socket)
            if self.mode is ProtocolMode.STOP_AND_WAIT:
                self._send_stop_and_wait(data_socket, control_socket, session, packets)
            elif self.mode is ProtocolMode.GO_BACK_N:
                self._send_go_back_n(data_socket, control_socket, session, packets)
            else:
                self._send_selective_repeat(data_socket, control_socket, session, packets)
            self._close_session(data_socket, control_socket, session)

        self.stats.finish()
        return self.stats

    def _establish_session(self, data_socket: socket.socket) -> Session:
        peer_data = (self.peer_host, self.port)
        syn_packet = build_control_packet(syn=True, length=self.window)

        while True:
            self._send_packet(data_socket, syn_packet, peer_data)
            response = self._wait_for_control(
                data_socket,
                lambda packet, address: (
                    address == peer_data
                    and packet.header.syn
                    and packet.header.ack_flag
                    and not packet.header.nack
                    and not packet.header.fin
                ),
            )
            if response is None:
                self.stats.retransmissions += 1
                continue
            window = max(1, min(self.window, response.header.length))
            ack_packet = build_control_packet(ack=0, ack_flag=True)
            self._send_packet(data_socket, ack_packet, peer_data)
            return Session(peer_data=peer_data, peer_control=(self.peer_host, self.port + 1), window=window)

    def _close_session(
        self,
        data_socket: socket.socket,
        control_socket: socket.socket,
        session: Session,
    ) -> None:
        fin_packet = build_control_packet(fin=True)
        while True:
            self._send_packet(data_socket, fin_packet, session.peer_data)
            response = self._wait_for_control(
                control_socket,
                lambda packet, address: (
                    address == session.peer_data
                    and packet.header.fin
                    and packet.header.ack_flag
                ),
            )
            if response is not None:
                return
            self.stats.retransmissions += 1

    def _send_stop_and_wait(
        self,
        data_socket: socket.socket,
        control_socket: socket.socket,
        session: Session,
        packets: list[Packet],
    ) -> None:
        for packet in packets:
            while True:
                self._send_packet(data_socket, packet, session.peer_data)
                response = self._wait_for_control(
                    control_socket,
                    lambda control, address: (
                            address == session.peer_data
                        and control.header.ack_flag
                        and not control.header.nack
                        and control.header.ack == packet.header.seq
                    ),
                )
                if response is not None:
                    break
                self.stats.retransmissions += 1

    def _send_go_back_n(
        self,
        data_socket: socket.socket,
        control_socket: socket.socket,
        session: Session,
        packets: list[Packet],
    ) -> None:
        base = 0
        next_to_send = 0

        while base < len(packets):
            while next_to_send < len(packets) and next_to_send - base < session.window:
                self._send_packet(data_socket, packets[next_to_send], session.peer_data)
                next_to_send += 1

            response = self._wait_for_control(control_socket, lambda _packet, address: address == session.peer_data)
            
            if response is None:
                self._retransmit_range(data_socket, session.peer_data, packets, base, next_to_send)
                continue

            if response.header.nack:
                missing_index = self._find_index(packets, base, next_to_send, response.header.ack)
                if missing_index is not None:
                    self._retransmit_range(data_socket, session.peer_data, packets, missing_index, next_to_send)
                continue

            if not response.header.ack_flag:
                continue

            acked_index = self._find_index(packets, base, next_to_send, response.header.ack)
            if acked_index is not None:
                base = acked_index + 1

    def _send_selective_repeat(
        self,
        data_socket: socket.socket,
        control_socket: socket.socket,
        session: Session,
        packets: list[Packet],
    ) -> None:
        base = 0
        next_to_send = 0
        acked = [False] * len(packets)
        last_sent_at = [0.0] * len(packets)

        def send_index(index: int, *, retransmission: bool = False) -> None:
            self._send_packet(data_socket, packets[index], session.peer_data)
            last_sent_at[index] = time.monotonic()
            if retransmission:
                self.stats.retransmissions += 1

        while base < len(packets):
            while next_to_send < len(packets) and next_to_send - base < session.window:
                send_index(next_to_send)
                next_to_send += 1

            deadline = self._earliest_deadline(base, next_to_send, acked, last_sent_at)
            response = self._wait_for_control(control_socket, lambda _packet, address: address == session.peer_data, deadline)
            current_time = time.monotonic()

            if response is not None:
                if response.header.ack_flag:
                    acked_index = self._find_index(packets, base, next_to_send, response.header.ack)
                    if acked_index is not None:
                        acked[acked_index] = True
                if response.header.nack:
                    missing_index = self._find_index(packets, base, next_to_send, response.header.ack)
                    if missing_index is not None and not acked[missing_index]:
                        send_index(missing_index, retransmission=True)

            for index in range(base, next_to_send):
                if acked[index]:
                    continue
                if current_time - last_sent_at[index] >= TIMEOUT_SECONDS:
                    send_index(index, retransmission=True)

            while base < len(packets) and acked[base]:
                base += 1

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

    def _wait_for_control(
        self,
        udp_socket: socket.socket,
        predicate: callable[[Packet, SocketAddress], bool],
        deadline: float | None = None,
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
            except socket.timeout:
                return None
            if packet is None:
                continue
            self.stats.datagrams_received += 1
            if predicate(packet, address):
                return packet


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

    def run(self) -> TransferStats:
        with create_bound_socket(self.bind_host, self.port, None) as data_socket:
            session = self._accept_session(data_socket)
            payload = self._receive_stream(data_socket, session)
            self.output_path.write_bytes(payload)
        self.stats.finish()
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

            while True:
                self._send_packet(data_socket, syn_ack, address)
                data_socket.settimeout(TIMEOUT_SECONDS)
                try:
                    response, response_address = receive_packet(data_socket)
                except socket.timeout:
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
                    return Session(
                        peer_data=address,
                        peer_control=(address[0], address[1] + 1),
                        window=proposed_window,
                    )

    def _receive_stream(self, data_socket: socket.socket, session: Session) -> bytes:
        if self.mode is ProtocolMode.STOP_AND_WAIT:
            return self._receive_stop_and_wait(data_socket, session)
        if self.mode is ProtocolMode.GO_BACK_N:
            return self._receive_go_back_n(data_socket, session)
        return self._receive_selective_repeat(data_socket, session)

    def _receive_stop_and_wait(self, data_socket: socket.socket, session: Session) -> bytes:
        expected = 0
        assembled = bytearray()

        while True:
            packet, address = receive_packet(data_socket)
            if address != session.peer_data or packet is None:
                continue
            self.stats.datagrams_received += 1

            if packet.header.fin:
                self._send_packet(data_socket, build_control_packet(fin=True, ack=0, ack_flag=True), session.peer_control)
                return bytes(assembled)

            seq = packet.header.seq
            if seq == expected:
                assembled.extend(packet.payload)
                self._send_packet(data_socket, build_control_packet(ack=seq, ack_flag=True), session.peer_control)
                expected = seq_add(expected, 1)
                continue

            if seq == seq_prev(expected):
                self._send_packet(data_socket, build_control_packet(ack=seq, ack_flag=True), session.peer_control)

    def _receive_go_back_n(self, data_socket: socket.socket, session: Session) -> bytes:
        expected = 0
        assembled = bytearray()

        while True:
            packet, address = receive_packet(data_socket)
            if address != session.peer_data or packet is None:
                continue
            self.stats.datagrams_received += 1

            if packet.header.fin:
                self._send_packet(data_socket, build_control_packet(fin=True, ack=0, ack_flag=True), session.peer_control)
                return bytes(assembled)

            seq = packet.header.seq
            if seq == expected:
                assembled.extend(packet.payload)
                self._send_packet(data_socket, build_control_packet(ack=seq, ack_flag=True), session.peer_control)
                expected = seq_add(expected, 1)
                continue

            if seq_is_recent(seq, expected, session.window):
                self._send_packet(
                    data_socket,
                    build_control_packet(ack=seq_prev(expected), ack_flag=True),
                    session.peer_control,
                )
                continue

            self._send_packet(
                data_socket,
                build_control_packet(ack=expected, ack_flag=True, nack=True),
                session.peer_control,
            )

    def _receive_selective_repeat(self, data_socket: socket.socket, session: Session) -> bytes:
        base = 0
        buffered: dict[int, bytes] = {}
        assembled = bytearray()

        while True:
            packet, address = receive_packet(data_socket)
            if address != session.peer_data or packet is None:
                continue
            self.stats.datagrams_received += 1

            if packet.header.fin:
                self._send_packet(data_socket, build_control_packet(fin=True, ack=0, ack_flag=True), session.peer_control)
                return bytes(assembled)

            seq = packet.header.seq
            if seq_in_window(seq, base, session.window):
                if seq not in buffered:
                    buffered[seq] = packet.payload
                self._send_packet(data_socket, build_control_packet(ack=seq, ack_flag=True), session.peer_control)
                if seq != base:
                    self._send_packet(
                        data_socket,
                        build_control_packet(ack=base, ack_flag=True, nack=True),
                        session.peer_control,
                    )
                while base in buffered:
                    assembled.extend(buffered.pop(base))
                    base = seq_add(base, 1)
                continue

            if seq_is_recent(seq, base, session.window):
                self._send_packet(data_socket, build_control_packet(ack=seq, ack_flag=True), session.peer_control)
                continue

            self._send_packet(
                data_socket,
                build_control_packet(ack=base, ack_flag=True, nack=True),
                session.peer_control,
            )

    def _send_packet(self, udp_socket: socket.socket, packet: Packet, address: SocketAddress) -> None:
        udp_socket.sendto(packet.to_bytes(), address)
        self.stats.datagrams_sent += 1