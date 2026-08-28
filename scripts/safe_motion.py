#!/usr/bin/env python3
"""검토된 안전 자세로만 xArm을 저속 이동시키는 도구.

기본 실행은 상태를 읽기만 하고 절대 움직이지 않는다. 실제 이동은 다음 3중
안전장치를 모두 통과해야 한다.

1. --execute 옵션
2. --config로 지정한 설정 파일
3. 터미널에서 목표 이름을 직접 다시 입력하는 확인 절차

safe_motion.yaml은 아직 만들지 않았다. 실제 테이블/카메라/그리퍼 배치를 보고
사용자와 함께 안전 자세를 합의한 뒤에 작성한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def read_status(robot_ip: str) -> int:
    """어떤 모션 명령도 보내지 않고 현재 상태만 출력한다."""
    from xarm.wrapper import XArmAPI

    arm = XArmAPI(robot_ip, do_not_open=True)
    arm.connect()
    if not arm.connected:
        print(f"[실패] xArm 연결 실패: {robot_ip}")
        return 1
    try:
        print(f"[정보] 로봇 IP: {robot_ip}, 축 수: {arm.axis}, mode={arm.mode}")
        print(f"[정보] 오류/경고: {arm.get_err_warn_code()}")
        print(f"[정보] 관절값(rad): {arm.get_servo_angle(is_radian=True)}")
        print(f"[정보] TCP(mm, rad): {arm.get_position(is_radian=True)}")
        print("[안전] 상태 확인만 수행했습니다. 로봇은 움직이지 않았습니다.")
        return 0
    finally:
        arm.disconnect()


def load_target(config_path: Path, target_name: str) -> dict:
    """안전 자세 파일에서 하나의 joint-space 목표만 읽는다."""
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML이 필요합니다. uf_lerobot 환경을 활성화하세요.") from exc

    if not config_path.is_file():
        raise RuntimeError(
            f"설정 파일이 없습니다: {config_path}\n"
            "아직 안전 자세를 합의하지 않았습니다. --execute를 사용하지 마세요."
        )
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    targets = data.get("targets", {})
    target = targets.get(target_name)
    if not isinstance(target, dict):
        raise RuntimeError(f"'{target_name}' 목표를 찾지 못했습니다.")
    joints_deg = target.get("joints_deg")
    if not isinstance(joints_deg, list) or len(joints_deg) != 7:
        raise RuntimeError("joints_deg는 xArm7의 관절각 7개(도 단위)여야 합니다.")
    return target


def execute_joint_motion(robot_ip: str, target_name: str, target: dict) -> int:
    """의도적으로 매우 보수적인 속도로, 합의된 한 관절 자세만 실행한다."""
    from xarm.wrapper import XArmAPI

    joints_deg = target["joints_deg"]
    speed_deg_s = float(target.get("speed_deg_s", 5.0))
    if not 0 < speed_deg_s <= 10.0:
        raise RuntimeError("초기 안전 시험의 speed_deg_s는 0보다 크고 10 deg/s 이하여야 합니다.")

    print("\n[중요] 다음 목표로 실제 로봇을 움직입니다.")
    print(f"  목표 이름: {target_name}")
    print(f"  관절각(도): {joints_deg}")
    print(f"  속도: {speed_deg_s} deg/s")
    print("  실행 전 사람과 장애물이 로봇 작업영역 밖에 있는지 확인하세요.")
    answer = input(f"실행하려면 목표 이름 '{target_name}'을 정확히 입력하세요: ").strip()
    if answer != target_name:
        print("[취소] 확인 문자열이 일치하지 않아 모션을 실행하지 않았습니다.")
        return 2

    arm = XArmAPI(robot_ip)
    try:
        if not arm.connected:
            raise RuntimeError("xArm 연결에 실패했습니다.")
        _, err_warn = arm.get_err_warn_code()
        if err_warn != [0, 0]:
            raise RuntimeError(f"로봇 오류/경고가 있어 실행을 거부합니다: {err_warn}")

        # 아래 세 호출은 여기서만 실제 로봇 상태를 바꾼다.
        arm.motion_enable(enable=True)
        arm.set_mode(0)
        arm.set_state(0)
        result = arm.set_servo_angle(angle=joints_deg, speed=speed_deg_s, is_radian=False, wait=True)
        if result != 0:
            raise RuntimeError(f"xArm이 모션 명령을 거부했습니다. 반환 코드: {result}")
        print("[완료] 목표 자세 도착을 기다린 뒤 명령이 완료되었습니다.")
        return 0
    finally:
        arm.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(description="xArm7 상태 확인 및 검토된 저속 모션")
    parser.add_argument("--robot-ip", default="192.168.0.240", help="xArm IP 주소")
    parser.add_argument("--execute", action="store_true", help="실제 모션 실행을 명시적으로 허용")
    parser.add_argument("--config", type=Path, help="검토된 안전 자세 YAML 파일")
    parser.add_argument("--target", help="YAML 안의 목표 자세 이름")
    args = parser.parse_args()

    if not args.execute:
        return read_status(args.robot_ip)
    if args.config is None or not args.target:
        parser.error("실제 모션에는 --execute --config 파일 --target 이름이 모두 필요합니다.")
    try:
        target = load_target(args.config, args.target)
        return execute_joint_motion(args.robot_ip, args.target, target)
    except RuntimeError as exc:
        print(f"[실패] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
