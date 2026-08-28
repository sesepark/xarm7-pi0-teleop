#!/usr/bin/env python3
"""GUI 버튼 명령을 실행 중인 LeRobot 녹화 브리지에 전달한다."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


KEYS = {"space", "right", "left", "esc"}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTROL_PATH = PROJECT_ROOT / "runtime" / "record_gui" / "control.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("key", choices=sorted(KEYS))
    args = parser.parse_args()
    CONTROL_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONTROL_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"key": args.key, "requested_at": time.time()}),
        encoding="utf-8",
    )
    os.replace(temporary, CONTROL_PATH)
    print(f"GUI 녹화 명령 전달 완료: {args.key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
