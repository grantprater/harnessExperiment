"""Small process-tree bootstrap; the supervisor assigns it before releasing it."""

from __future__ import annotations

import json
import subprocess
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("bootstrap expects one JSON command argument", file=sys.stderr)
        return 2
    command = json.loads(sys.argv[1])
    if not isinstance(command, list) or not command or not all(
        isinstance(part, str) for part in command
    ):
        print("bootstrap command must be a non-empty string list", file=sys.stderr)
        return 2
    if sys.stdin.buffer.read(1) != b"R":
        print("bootstrap was not released by its supervisor", file=sys.stderr)
        return 3
    try:
        completed = subprocess.run(command, check=False)
    except OSError as exc:
        print(f"could not start command: {exc}", file=sys.stderr)
        return 127
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
