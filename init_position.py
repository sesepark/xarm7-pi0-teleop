#!/usr/bin/env python3
"""xArm7을 pi0 시연의 고정 초기 관절 자세로 안전하게 복귀시키는 도구.

기본 실행은 현재 관절값과 목표값만 읽는다. 실제 복귀에는 반드시 --execute와
터미널의 start 확인이 모두 필요하다. 이 도구는 팔 관절만 움직이며 그리퍼에는
어떤 명령도 보내지 않는다.

사용법:
    python init_position.py                 # 읽기 전용 상태 확인
    python init_position.py --execute       # 3°/s 초기 자세 복귀
    ./run.sh init-position                  # 위 실제 복귀의 쉬운 실행 명령
"""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "xarm7_gello_teleop.yaml"


def load_initial_position(config_path: Path) -> tuple[str, list[float], float]:
    """텔레옵과 동일한 단 하나의 기준 관절 자세를 읽는다."""
    if not config_path.is_file():
        raise RuntimeError(f"설정 파일이 없습니다: {config_path}")
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    robot = data.get("robot", {})
    robot_ip = robot.get("robot_ip")
    joints_deg = robot.get("start_joints")
    # 수동 초기 자세 복구는 텔레옵 시작 직후의 저속 추종과 목적이 다르므로,
    # 별도의 init_position_velocity를 쓴다.
    speed_deg_s = robot.get("init_position_velocity")
    if not isinstance(robot_ip, str):
        raise RuntimeError("robot.robot_ip를 읽지 못했습니다.")
    if not isinstance(joints_deg, list) or len(joints_deg) != 7:
        raise RuntimeError("robot.start_joints는 관절각 7개여야 합니다.")
    if not isinstance(speed_deg_s, (int, float)) or not 0 < speed_deg_s <= 10:
        raise RuntimeError("init_position_velocity는 0보다 크고 10°/s 이하여야 합니다.")
    return robot_ip, [float(value) for value in joints_deg], float(speed_deg_s)


def get_current_joints(robot_ip: str) -> tuple[list[float], list[int]]:
    """상태만 읽는다. 이 함수에서는 로봇 상태를 전혀 변경하지 않는다."""
    from xarm.wrapper import XArmAPI

    arm = XArmAPI(robot_ip, do_not_open=True)
    arm.connect()
    try:
        if not arm.connected:
            raise RuntimeError("xArm 연결에 실패했습니다.")
        code, joints = arm.get_servo_angle(is_radian=False)
        if code != 0:
            raise RuntimeError(f"현재 관절값 읽기 실패: xArm SDK 반환 코드 {code}")
        _, err_warn = arm.get_err_warn_code()
        return [float(value) for value in joints[:7]], list(err_warn)
    finally:
        arm.disconnect()


def print_comparison(current: list[float], target: list[float], speed_deg_s: float) -> float:
    errors = [abs(now - expected) for now, expected in zip(current, target)]
    largest = max(errors)
    estimate = largest / speed_deg_s
    print("=" * 72)
    print("xArm7 초기 관절 자세 복구")
    print("그리퍼는 움직이지 않으며, 팔 관절만 고정된 기준 자세로 복귀합니다.")
    print("=" * 72)
    print(f"목표 관절각(°): {[round(value, 4) for value in target]}")
    print(f"현재 관절각(°): {[round(value, 4) for value in current]}")
    print(f"최대 관절 차이: {largest:.3f}°")
    print(f"복귀 속도: {speed_deg_s:.1f}°/s (이론상 최소 약 {estimate:.1f}초)")
    return largest


def execute_restore(robot_ip: str, target: list[float], speed_deg_s: float) -> int:
    """명시적인 사용자 확인 뒤에만 고정된 목표 관절 자세로 이동한다."""
    current, err_warn = get_current_joints(robot_ip)
    largest = print_comparison(current, target, speed_deg_s)
    if err_warn != [0, 0]:
        print(f"❌ 로봇 오류/경고가 있어 복귀를 거부합니다: {err_warn}")
        return 1
    if largest <= 0.01:
        print("✅ 이미 초기 관절 자세와 일치합니다. 이동 명령을 보내지 않았습니다.")
        return 0

    print("\n[주의] 이 동작은 현재 자세에서 초기 관절 자세로 실제 이동합니다.")
    print("       사람·물체·케이블이 작업영역 밖에 있는지 확인하세요.")
    answer = input("3°/s로 초기 자세 복귀를 시작하려면 'start'를 입력하세요: ").strip()
    if answer != "start":
        print("[취소] 확인 문자열이 일치하지 않아 이동하지 않았습니다.")
        return 2
    print("[대기] 3초 뒤 초기 자세 복귀를 시작합니다.")
    for remaining in (3, 2, 1):
        print(f"[대기] {remaining}초...")
        time.sleep(1)

    from xarm.wrapper import XArmAPI

    arm = XArmAPI(robot_ip)
    try:
        if not arm.connected:
            raise RuntimeError("xArm 연결에 실패했습니다.")
        _, live_err_warn = arm.get_err_warn_code()
        if live_err_warn != [0, 0]:
            raise RuntimeError(f"대기 중 로봇 오류/경고가 발생했습니다: {live_err_warn}")

        # 팔 관절 모션에 필요한 최소한의 상태 전환만 수행한다.
        # 그리퍼 열기/닫기, TCP 좌표 이동, 목표값 자르기는 하지 않는다.
        arm.motion_enable(enable=True)
        arm.set_mode(0)
        arm.set_state(0)
        timeout_s = max(10.0, largest / speed_deg_s + 5.0)
        print("[복귀 시작] 초기 관절 자세로 저속 이동합니다.")
        code = arm.set_servo_angle(
            angle=target,
            speed=speed_deg_s,
            is_radian=False,
            wait=True,
            timeout=timeout_s,
        )
        if code != 0:
            raise RuntimeError(f"초기 자세 복귀 실패: xArm SDK 반환 코드 {code}")
        print("✅ [복귀 완료] 초기 관절 자세에 도착했습니다.")
        return 0
    finally:
        arm.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(description="xArm7 초기 관절 자세 복구")
    parser.add_argument("--execute", action="store_true", help="실제 초기 자세 복귀를 명시적으로 허용")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="텔레옵 설정 YAML 경로")
    args = parser.parse_args()
    try:
        robot_ip, target, speed_deg_s = load_initial_position(args.config)
        current, err_warn = get_current_joints(robot_ip)
        print_comparison(current, target, speed_deg_s)
        print(f"현재 로봇 오류/경고: {err_warn}")
        if not args.execute:
            print("[안전] 읽기 전용 확인만 수행했습니다. 실제 복귀에는 --execute가 필요합니다.")
            return 0
        return execute_restore(robot_ip, target, speed_deg_s)
    except RuntimeError as exc:
        print(f"❌ [실패] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
