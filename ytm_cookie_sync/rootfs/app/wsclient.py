"""Minimaler Websocket-Client und -Brücke ohne Fremdbibliotheken (RFC 6455)."""
from __future__ import annotations

import base64
import json
import os
import socket
import struct


class WSClosed(Exception):
    """Gegenstelle hat die Verbindung geschlossen."""


def _rx(sock: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise WSClosed("Verbindung geschlossen")
        data += chunk
    return data


def send_frame(sock: socket.socket, payload: bytes, opcode: int = 0x1, mask: bool = True) -> None:
    head = bytearray([0x80 | opcode])
    n = len(payload)
    mbit = 0x80 if mask else 0
    if n < 126:
        head.append(mbit | n)
    elif n < 65536:
        head.append(mbit | 126)
        head += struct.pack(">H", n)
    else:
        head.append(mbit | 127)
        head += struct.pack(">Q", n)
    if mask:
        key = os.urandom(4)
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
        sock.sendall(bytes(head) + key + payload)
    else:
        sock.sendall(bytes(head) + payload)


def recv_frame(sock: socket.socket) -> tuple[int, bytes]:
    """Liest eine vollständige Nachricht (inkl. Fortsetzungsframes). Liefert (opcode, daten)."""
    message = b""
    first_opcode = None
    while True:
        b1, b2 = _rx(sock, 2)
        fin = b1 & 0x80
        opcode = b1 & 0x0F
        masked = b2 & 0x80
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack(">H", _rx(sock, 2))[0]
        elif n == 127:
            n = struct.unpack(">Q", _rx(sock, 8))[0]
        key = _rx(sock, 4) if masked else None
        data = _rx(sock, n) if n else b""
        if key:
            data = bytes(b ^ key[i % 4] for i, b in enumerate(data))
        if opcode == 0x8:
            raise WSClosed("Close-Frame empfangen")
        if opcode == 0x9:  # Ping -> Pong
            send_frame(sock, data, opcode=0xA, mask=not masked)
            continue
        if opcode == 0xA:
            continue
        if first_opcode is None:
            first_opcode = opcode
        message += data
        if fin:
            return first_opcode, message


class WSClient:
    """Einfacher JSON-Websocket-Client (für Music Assistant und Chrome DevTools)."""

    def __init__(self, host: str, port: int, path: str, timeout: float = 60) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(1)
            if not chunk:
                raise WSClosed("Handshake abgebrochen")
            resp += chunk
        status = resp.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise ConnectionError(f"Websocket-Handshake fehlgeschlagen: {status.decode(errors='replace')}")

    def send_json(self, obj: dict) -> None:
        send_frame(self.sock, json.dumps(obj).encode())

    def recv_json(self) -> dict:
        _op, data = recv_frame(self.sock)
        return json.loads(data)

    def close(self) -> None:
        try:
            send_frame(self.sock, b"", opcode=0x8)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
