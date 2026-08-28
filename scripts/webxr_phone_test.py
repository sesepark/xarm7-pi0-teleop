#!/usr/bin/env python3
"""Run only the WebXR HTTPS server; never connects to or commands xArm."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import yaml
from lerobot_robot_ufactory.teleoperators.webxr_teleop import (
    WebXRTeleop,
    WebXRTeleopConfig,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phone-only WebXR tracking test (no robot)"
    )
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    data = yaml.safe_load(args.config.read_text(encoding="utf-8"))["teleop"].copy()
    data.pop("type", None)
    teleop = WebXRTeleop(WebXRTeleopConfig(**data))
    teleop.connect()
    print("[안전] 이 명령은 xArm에 연결하지 않고 로봇 명령도 보내지 않습니다.")
    print("휴대폰에서 START WEBXR 후 MOVE를 눌러 pose/fps 입력만 확인하세요.")
    try:
        previous = None
        while True:
            status = teleop.get_phone_status()
            summary = (
                status["connected"],
                status["sequence"],
                status["move"],
                status["gripper_closed"],
                round(status["fps"], 1),
            )
            if summary != previous:
                age = status["sample_age_ms"]
                age_text = "-" if age is None else f"{age:.0f}ms"
                print(
                    f"phone={summary[0]} seq={summary[1]} age={age_text} "
                    f"move={summary[2]} gripper_closed={summary[3]} fps={summary[4]}",
                    flush=True,
                )
                previous = summary
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n[종료] phone-only WebXR test")
    finally:
        teleop.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
