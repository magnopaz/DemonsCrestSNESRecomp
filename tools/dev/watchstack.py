#!/usr/bin/env python3
"""Collect recomp call stacks that reach a watched function.

The framework's debug server (only in a -DSNESRECOMP_ENABLE_TRACE=ON build)
has a one-shot function watch: arm a function name, and the first time it runs
the server snapshots the registers and the recompiled call stack. Re-arming
clears it. That is enough to find who calls the VRAM upload funnel without
touching any code.

Usage: watchstack.py <watch_name> [--port 4477] [--samples 40] [--interval 0.35]
Prints each distinct stack with a hit count.
"""
import argparse
import json
import socket
import time
from collections import Counter


class Client:
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        self.buf = b""

    def send(self, line):
        self.sock.sendall((line + "\n").encode())

    def recv_json(self):
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError("server closed")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        try:
            return json.loads(line.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return {"raw": line.decode("utf-8", "replace")[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("watch")
    ap.add_argument("--port", type=int, default=4477)
    ap.add_argument("--samples", type=int, default=40)
    ap.add_argument("--interval", type=float, default=0.35)
    a = ap.parse_args()
    c = Client(a.port)
    print("ping:", c.send("ping") or c.recv_json())
    stacks = Counter()
    seen_pc = Counter()
    got = 0
    for _ in range(a.samples):
        c.send("func_watch_arm %s" % a.watch)
        c.recv_json()
        time.sleep(a.interval)
        c.send("func_watch_get")
        r = c.recv_json()
        if r.get("captured"):
            got += 1
            stack = tuple(r.get("stack") or [])
            stacks[stack] += 1
            seen_pc[(r.get("pc24"), r.get("A"), r.get("X"), r.get("frame"))] += 1
    print("captured %d/%d samples\n" % (got, a.samples))
    for stack, n in stacks.most_common():
        print("  x%-3d %s" % (n, " <- ".join(stack) if stack else "(no stack)"))
    if seen_pc:
        print("\nsample registers (pc24, A, X, frame):")
        for k, n in seen_pc.most_common(8):
            print("  x%-3d %s" % (n, k))


if __name__ == "__main__":
    main()
