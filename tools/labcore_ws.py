# -*- coding: utf-8 -*-
"""labCORE 的 WebSocket 控制通道 —— 最小可用客戶端。

背景
────
labCORE 是一台跑 Linux 的盒子,透過「HEAD acoustics USBLAN Adapter」
掛成一張 USB 網卡,固定在 10.254.0.2。它開了三個服務:

    22    SSH
    8080  韌體更新網頁(SWUpdate)
    8081  WebSocket++/0.8.2   ← RC_labCORE.exe 用的控制通道

ACQUA 的 COM 介面(137 個主題)完全沒有硬體相關的 API,SQL 也只記
「哪個 MMD 需要哪組硬體設定」而不能設定硬體。所以要用程式碰麥克風
供電/極化電壓,這個 WebSocket 是唯一看起來可行的入口。

為什麼自己刻而不裝 websocket-client
──────────────────────────────────
這台機器的 Python 環境是量測用的,不想為了探路多塞相依套件。
RFC 6455 的客戶端握手加解框其實很短,自己寫反而好控制。

安全預設
────────
**預設只連線與監聽,不送任何東西。** 這台是真的量測硬體,
送錯指令可能改到通道供電 —— 那會讓之後的量測數據靜靜地變成錯的。
要送必須明確加 --send。

用法
────
    python tools/labcore_ws.py                    連上去聽 10 秒
    python tools/labcore_ws.py --seconds 30       聽久一點
    python tools/labcore_ws.py --send '<xml/>'    送一則(需自行確認安全)
"""
from __future__ import annotations

import argparse
import base64
import os
import socket
import struct
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

HOST, PORT = "10.254.0.2", 8081


class WS:
    """夠用就好的 RFC 6455 客戶端:握手、收框、送文字框。"""

    def __init__(self, host=HOST, port=PORT, path="/", origin=None,
                 protocol=None, timeout=6.0):
        self.host, self.port, self.path = host, port, path
        self.origin, self.protocol, self.timeout = origin, protocol, timeout
        self.sock = None
        self.handshake = ""

    # ── 連線 ─────────────────────────────────────
    def connect(self):
        key = base64.b64encode(os.urandom(16)).decode()
        lines = [
            "GET %s HTTP/1.1" % self.path,
            "Host: %s:%d" % (self.host, self.port),
            "Upgrade: websocket",
            "Connection: Upgrade",
            "Sec-WebSocket-Key: %s" % key,
            "Sec-WebSocket-Version: 13",
        ]
        if self.origin:
            lines.append("Origin: %s" % self.origin)
        if self.protocol:
            lines.append("Sec-WebSocket-Protocol: %s" % self.protocol)
        req = "\r\n".join(lines) + "\r\n\r\n"

        self.sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock.sendall(req.encode())

        # 讀完整個 header 區塊才動手 —— 之後的 body 是框資料,不能吃掉
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise IOError("握手時連線就被關了")
            buf += chunk
        head, rest = buf.split(b"\r\n\r\n", 1)
        self.handshake = head.decode("latin-1")
        self._buf = rest
        if "101" not in self.handshake.split("\r\n")[0]:
            raise IOError("升級被拒:\n%s" % self.handshake)
        return self

    # ── 收 ───────────────────────────────────────
    def _need(self, n):
        while len(self._buf) < n:
            self.sock.settimeout(self.timeout)
            chunk = self.sock.recv(65536)
            if not chunk:
                raise IOError("連線關閉")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def recv(self):
        """回 (opcode, payload)。伺服器送來的框不會遮罩。"""
        b0, b1 = self._need(2)
        op = b0 & 0x0F
        ln = b1 & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", self._need(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", self._need(8))[0]
        mask = self._need(4) if (b1 & 0x80) else None
        data = self._need(ln) if ln else b""
        if mask:
            data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
        return op, data

    # ── 送 ───────────────────────────────────────
    def send(self, text, opcode=0x1):
        """客戶端送出的框**必須**遮罩,否則伺服器會直接斷線。"""
        payload = text.encode("utf-8") if isinstance(text, str) else text
        frame = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            frame.append(0x80 | n)
        elif n < (1 << 16):
            frame.append(0x80 | 126)
            frame += struct.pack(">H", n)
        else:
            frame.append(0x80 | 127)
            frame += struct.pack(">Q", n)
        mask = os.urandom(4)
        frame += mask
        frame += bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
        self.sock.sendall(bytes(frame))

    def close(self):
        try:
            self.send(b"", 0x8)
            self.sock.close()
        except Exception:                                   # noqa: BLE001
            pass


OPNAME = {0x0: "cont", 0x1: "text", 0x2: "binary",
          0x8: "close", 0x9: "ping", 0xA: "pong"}


def listen(ws, seconds):
    """聽一段時間,把收到的東西照原樣印出來。"""
    end = time.time() + seconds
    got = 0
    while time.time() < end:
        ws.sock.settimeout(max(0.4, end - time.time()))
        try:
            op, data = ws.recv()
        except socket.timeout:
            continue
        except Exception as exc:                            # noqa: BLE001
            print("  [斷] %s" % str(exc)[:70])
            break
        got += 1
        if op == 0x9:                                       # ping 要回 pong
            ws.send(data, 0xA)
            print("  <ping> 已回 pong")
            continue
        try:
            body = data.decode("utf-8")
        except UnicodeDecodeError:
            body = repr(data[:220])
        print("  [%s %d bytes] %s" % (OPNAME.get(op, op), len(data), body[:900]))
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--path", default="/")
    ap.add_argument("--protocol", default=None, help="Sec-WebSocket-Protocol")
    ap.add_argument("--seconds", type=float, default=10)
    ap.add_argument("--send", default=None,
                    help="要送出的字串。**會改到真硬體,自行確認安全**")
    args = ap.parse_args()

    print("連 ws://%s:%d%s" % (args.host, args.port, args.path))
    ws = WS(args.host, args.port, args.path, protocol=args.protocol).connect()
    print("握手成功:")
    for line in args.handshake.split("\r\n") if False else ws.handshake.split("\r\n"):
        if line.strip():
            print("   " + line)
    print()

    if args.send:
        print("送出 %d bytes" % len(args.send))
        ws.send(args.send)

    print("監聽 %.0f 秒..." % args.seconds)
    n = listen(ws, args.seconds)
    print("\n收到 %d 個框" % n)
    ws.close()


if __name__ == "__main__":
    main()
