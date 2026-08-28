#!/usr/bin/env python3
"""GELLO 그리퍼와 기본 xArm Gripper의 방향을 아주 작게 검증한다.

이 파일은 전체 텔레옵이 아니다. 팔 관절 명령은 전혀 보내지 않는다.

공식 UFACTORY GELLO 구현은 텔레옵을 시작한 순간의 GELLO 그리퍼를 "열림"으로
잡고, 엔코더 값이 약 42도 *감소*한 위치를 "닫힘"으로 사용한다. 이 시험은
그 전제가 현재 GELLO에서도 맞는지 먼저 읽기 전용으로 검사한다.

전제가 맞고 사용자가 ASCII 확인 문자열 test를 입력한 경우에만, 빈 xArm
기본 그리퍼를 현재 위치에서 50 펄스(전체 800의 6.25%) 닫았다가 원래
위치로 복귀한다. 팔 관절은 움직이지 않는다.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

import yaml


MIN_CLOSE_DELTA_DEG = 3.0
MAX_CLOSE_DELTA_DEG = 30.0
GRIPPER_TEST_STEP = 50
GRIPPER_SPEED = 500
XARM_GRIPPER_CLOSED = 0
XARM_GRIPPER_OPEN = 800


def wrapped_delta_deg(current: float, baseline: float) -> float:
    """360도 경계에서도 작은 변화량의 방향을 보존한다."""
    return math.degrees((current - baseline + math.pi) % (2 * math.pi) - math.pi)


def load_config(path: Path) -> tuple[dict, dict]:
    if not path.is_file():
        raise RuntimeError(f"설정 파일이 없습니다: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    robot, teleop = data.get("robot", {}), data.get("teleop", {})
    if robot.get("gripper_type") != 1:
        raise RuntimeError("이 시험은 기본 xArm Gripper(gripper_type: 1) 전용입니다.")
    if not isinstance(teleop.get("gripper_id"), int) or teleop["gripper_id"] < 0:
        raise RuntimeError("teleop.gripper_id가 올바르게 설정되지 않았습니다.")
    return robot, teleop


def read_gello_gripper_rad(teleop: dict) -> float:
    """GELLO 그리퍼 엔코더만 읽는다. 토크와 목표 위치는 바꾸지 않는다."""
    from gello.dynamixel.driver import DynamixelDriver

    driver = DynamixelDriver([teleop["gripper_id"]], port=teleop["port"], baudrate=57600)
    try:
        value = None
        for _ in range(10):
            value = driver.get_joints()
        if value is None or len(value) != 1:
            raise RuntimeError("GELLO 그리퍼 엔코더를 읽지 못했습니다.")
        return float(value[0])
    finally:
        driver.close()


def move_xarm_gripper_once(robot_ip: str) -> tuple[int, int]:
    """그리퍼만 소폭 닫고 항상 출발 위치로 되돌린다."""
    from xarm.wrapper import XArmAPI

    arm = XArmAPI(robot_ip)
    original_position: int | None = None
    try:
        if not arm.connected:
            raise RuntimeError("xArm 연결에 실패했습니다.")
        _, err_warn = arm.get_err_warn_code()
        if err_warn != [0, 0]:
            raise RuntimeError(f"xArm 오류/경고가 있어 그리퍼 시험을 거부합니다: {err_warn}")
        code, position = arm.get_gripper_position()
        if code != 0:
            raise RuntimeError(f"현재 xArm 그리퍼 위치 읽기 실패: 반환 코드 {code}")
        original_position = int(position)
        target = max(XARM_GRIPPER_CLOSED, original_position - GRIPPER_TEST_STEP)
        if target == original_position:
            raise RuntimeError("현재 그리퍼가 이미 완전히 닫혀 있어 안전한 닫힘 시험을 할 수 없습니다.")

        # 아래 네 줄 중 set_gripper_position만 실제 그리퍼 모션 명령이다.
        for description, result in (
            ("그리퍼 활성화", arm.set_gripper_enable(True)),
            ("그리퍼 위치 제어 모드 설정", arm.set_gripper_mode(0)),
            ("그리퍼 저속 설정", arm.set_gripper_speed(GRIPPER_SPEED)),
        ):
            if result != 0:
                raise RuntimeError(f"{description} 실패: 반환 코드 {result}")
        result = arm.set_gripper_position(target, wait=True, timeout=10)
        if result != 0:
            raise RuntimeError(f"그리퍼 소폭 닫힘 명령 실패: 반환 코드 {result}")
        print(f"✅ xArm 그리퍼를 {original_position} → {target}으로 소폭 닫았습니다.")
        input("눈으로 닫힘을 확인한 뒤, 원래 위치로 복귀하려면 Enter를 누르세요: ")
        result = arm.set_gripper_position(original_position, wait=True, timeout=10)
        if result != 0:
            raise RuntimeError(f"그리퍼 원위치 복귀 실패: 반환 코드 {result}")
        print(f"✅ xArm 그리퍼가 원래 위치 {original_position}으로 복귀했습니다.")
        return original_position, target
    except KeyboardInterrupt:
        # 팔 관절 정지 명령은 보내지 않는다. 그리퍼가 아직 동작 중이라면 정지만 요청한다.
        stop = getattr(arm, "set_gripper_stop", None)
        if callable(stop):
            stop()
        print("\n[중단] Ctrl+C가 감지되어 그리퍼 정지를 요청했습니다.")
        raise
    finally:
        arm.disconnect()


def save_log(log_dir: Path, payload: dict) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"gello_gripper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[기록] 시험 값 저장: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="GELLO/xArm 기본 그리퍼 방향 시험")
    parser.add_argument("--config", type=Path, required=True, help="xArm7/GELLO 설정 YAML")
    parser.add_argument("--log-dir", type=Path, required=True, help="시험 로그 저장 폴더")
    args = parser.parse_args()
    robot, teleop = load_config(args.config)

    print("=" * 72)
    print("GELLO 그리퍼 → xArm 기본 그리퍼 방향 시험")
    print("팔 관절은 절대로 움직이지 않습니다.")
    print("먼저 GELLO 그리퍼를 눈으로 완전히 열린 상태로 놓으세요.")
    print("그 다음 손으로 3°~30° 정도 '닫는 방향'으로만 움직입니다.")
    print("=" * 72)
    input("GELLO 그리퍼가 열린 상태이면 Enter를 누르세요. 취소: Ctrl+C: ")
    baseline = read_gello_gripper_rad(teleop)
    print("✅ 열린 GELLO 그리퍼 기준값을 읽었습니다. 이제 닫는 방향으로 3°~30° 움직이세요.")
    input("움직인 뒤 Enter를 누르세요. 취소: Ctrl+C: ")
    moved = read_gello_gripper_rad(teleop)
    delta = wrapped_delta_deg(moved, baseline)
    print(f"GELLO 그리퍼 엔코더 변화량: {delta:+.3f}°")

    if not MIN_CLOSE_DELTA_DEG <= abs(delta) <= MAX_CLOSE_DELTA_DEG:
        raise RuntimeError(
            f"변화량이 {delta:+.3f}°입니다. 허용 범위는 "
            f"{MIN_CLOSE_DELTA_DEG}°~{MAX_CLOSE_DELTA_DEG}°입니다. 다시 시도하세요."
        )
    if delta > 0:
        raise RuntimeError(
            "GELLO를 닫았는데 엔코더 값이 증가했습니다. 공식 UFACTORY 코드가 기대하는 "
            "'닫힘 = 엔코더 감소'와 반대입니다. xArm 그리퍼는 움직이지 않았습니다. "
            "이 경우 그리퍼 변환 설정을 별도로 결정해야 합니다."
        )

    print("✅ 공식 UFACTORY 그리퍼 변환의 방향 전제가 현재 GELLO와 일치합니다.")
    print(f"이제 빈 xArm 그리퍼만 {GRIPPER_TEST_STEP}/800 펄스, 속도 {GRIPPER_SPEED}으로 닫았다가 복귀합니다.")
    answer = input("실제 그리퍼 시험을 실행하려면 'test'를 입력하세요: ").strip()
    if answer != "test":
        print("[취소] 확인 문자열이 일치하지 않아 xArm 그리퍼를 움직이지 않았습니다.")
        return 2
    original, target = move_xarm_gripper_once(robot["robot_ip"])
    save_log(args.log_dir, {
        "time": datetime.now().isoformat(timespec="seconds"),
        "gello_gripper_id": teleop["gripper_id"],
        "gello_close_delta_deg": delta,
        "xarm_original_position": original,
        "xarm_test_closed_position": target,
        "xarm_gripper_motion_only": True,
    })
    print("\n다음 판단:")
    print("- GELLO를 닫을 때 xArm 그리퍼도 위 시험처럼 닫히는 논리라면: 사용자에게 결과를 알려주세요.")
    print("- GELLO를 닫았는데 시험 전제와 다르거나 이상하면: 전체 텔레옵을 시작하지 말고 결과를 알려주세요.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"❌ 그리퍼 시험 중단: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
