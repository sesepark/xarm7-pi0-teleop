#!/usr/bin/env python3
"""사용자가 움직인 GELLO 물리 관절이 어떤 Dynamixel ID인지 찾는다.

xArm에는 연결하지 않는다. 사용자는 GELLO의 눈에 보이는 관절 하나를 편하게 3°~30° 정도
움직이면 된다. 프로그램이 encoder 변화량이 가장 큰 Dynamixel ID를 출력한다.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import yaml


def wrapped_delta_deg(current: float, baseline: float) -> float:
    """Dynamixel 각도가 360° 경계를 넘더라도 가장 작은 변화량으로 계산한다."""
    return math.degrees((current - baseline + math.pi) % (2 * math.pi) - math.pi)


def read_joints(port: str, ids: list[int]) -> list[float]:
    from gello.dynamixel.driver import DynamixelDriver

    driver = DynamixelDriver(ids, port=port, baudrate=57600)
    try:
        values = None
        for _ in range(10):
            values = driver.get_joints()
        if values is None or len(values) != len(ids):
            raise RuntimeError("GELLO 관절값을 모두 읽지 못했습니다.")
        return [float(value) for value in values]
    finally:
        driver.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="GELLO 물리 관절 ↔ Dynamixel ID 찾기")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    data = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    teleop = data.get("teleop", {})
    port = teleop.get("port")
    ids = teleop.get("joint_ids")
    if not isinstance(port, str) or not isinstance(ids, list) or len(ids) != 7:
        raise RuntimeError("GELLO port 또는 7개 joint_ids 설정을 읽지 못했습니다.")

    print("=" * 72)
    print("GELLO 물리 관절 찾기 (xArm은 움직이지 않음)")
    print("GELLO에서 알고 싶은 관절 하나만 3°~30° 정도 편하게 움직이세요.")
    print("=" * 72)
    baseline = read_joints(port, ids)
    input("움직이기 전 기준값을 읽었습니다. 관절 하나를 움직인 뒤 Enter를 누르세요: ")
    moved = read_joints(port, ids)
    deltas = [wrapped_delta_deg(now, before) for now, before in zip(moved, baseline)]
    changed_index = max(range(7), key=lambda index: abs(deltas[index]))
    largest = abs(deltas[changed_index])

    print("\nGELLO encoder 변화량:")
    for index, (motor_id, delta) in enumerate(zip(ids, deltas), start=1):
        marker = "  ← 가장 크게 움직인 관절" if index - 1 == changed_index else ""
        print(f"  설정 순서 {index} | Dynamixel ID {motor_id} | {delta:+.2f}°{marker}")
    if largest < 3.0:
        print("\n⚠️ 변화량이 너무 작습니다. 같은 관절을 조금 더 크게 움직여 다시 확인하세요.")
        return 1
    print(
        f"\n✅ 방금 움직인 물리 관절은 현재 설정 기준 Dynamixel ID {ids[changed_index]} "
        f"(설정 순서 {changed_index + 1})로 감지됐습니다."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"❌ GELLO 관절 찾기 실패: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
