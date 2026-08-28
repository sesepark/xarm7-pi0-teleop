#!/usr/bin/env python3
"""GELLO 관절값을 읽기 전용으로 확인하는 도구.

이 코드는 xArm 네트워크에 연결하지 않는다. Dynamixel 모터의 현재 encoder 값만 읽고
토크 설정, 목표 위치 명령, xArm 명령을 보내지 않는다.

사용법:
    ./verify.sh gello
    # 또는
    python scripts/read_gello.py --config config/xarm7_gello_teleop.yaml
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser(description="GELLO 관절값 읽기 전용 검사")
    parser.add_argument("--config", type=Path, required=True, help="GELLO 설정 YAML 파일")
    parser.add_argument("--samples", type=int, default=10, help="통신 안정화를 위해 읽을 횟수")
    args = parser.parse_args()

    if not args.config.is_file():
        print(f"❌ 설정 파일이 없습니다: {args.config}")
        return 1
    data = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    teleop = data.get("teleop", {})
    port = teleop.get("port")
    joint_ids = teleop.get("joint_ids")
    gripper_id = teleop.get("gripper_id", -1)
    if not isinstance(port, str) or not isinstance(joint_ids, list) or len(joint_ids) != 7:
        print("❌ teleop.port와 teleop.joint_ids(7개)를 설정 파일에서 읽지 못했습니다.")
        return 1

    motor_ids = list(joint_ids)
    if isinstance(gripper_id, int) and gripper_id >= 0:
        motor_ids.append(gripper_id)

    print("=" * 72)
    print("GELLO 읽기 전용 통신 검사")
    print("이 작업은 xArm에 연결하지 않으며, 모터 목표 위치/토크를 변경하지 않습니다.")
    print(f"USB 포트: {port}")
    print(f"읽을 Dynamixel ID: {motor_ids}")
    print("=" * 72)

    try:
        # UFACTORY의 GELLO 텔레옵 구현과 같은 읽기 드라이버를 사용합니다.
        from gello.dynamixel.driver import DynamixelDriver

        driver = DynamixelDriver(motor_ids, port=port, baudrate=57600)
        try:
            current = None
            for _ in range(max(1, args.samples)):
                current = driver.get_joints()
            if current is None or len(current) != len(motor_ids):
                raise RuntimeError("예상한 모터 수만큼 관절값을 받지 못했습니다.")
        finally:
            # 통신 포트만 닫습니다. 모터 설정을 되돌리거나 바꾸는 명령은 없습니다.
            driver.close()
    except Exception as exc:
        print(f"❌ GELLO 읽기 실패: {type(exc).__name__}: {exc}")
        print("   USB 권한, 케이블, GELLO 전원, Dynamixel ID 1~8을 확인하세요.")
        return 1

    print("✅ GELLO 관절값을 정상적으로 읽었습니다.")
    print("\n현재 GELLO 값 (이 값 자체는 아직 xArm 관절각으로 확정 변환되지 않았습니다):")
    labels = [f"J{i + 1}" for i in range(7)] + (["그리퍼"] if len(motor_ids) == 8 else [])
    for label, motor_id, value_rad in zip(labels, motor_ids, current):
        print(f"  {label}  | Dynamixel ID {motor_id} | {value_rad:+.5f} rad | {math.degrees(value_rad):+.2f}°")
    print("\n다음 단계: 각 축을 한 번에 하나씩 아주 작게 움직여 관절 부호를 검증합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
