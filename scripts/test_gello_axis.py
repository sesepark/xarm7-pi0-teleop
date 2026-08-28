#!/usr/bin/env python3
"""GELLO 한 축과 xArm 한 축의 방향을 매우 작게 시험한다.

이 도구는 일반 텔레옵이 아니다. 처음 joint_signs를 확정하기 위한 안전 시험이다.

안전 규칙:
  * 선택한 xArm 관절 하나만 움직인다.
  * GELLO는 사람이 편하게 3° 이상 움직여도 된다. 프로그램이 encoder 변화를 감지한다.
  * xArm 목표 변화량은 GELLO 변화량과 무관하게 항상 1.0°, 속도는 3.0°/s로 제한한다.
  * 그리퍼를 전혀 제어하지 않는다.
  * 시험 뒤 사용자의 Enter를 받은 후 기록된 안전 시작 자세로 돌아간다.

공식 UFACTORY GELLO 코드의 offset 원리와 같은 식을 사용한다.
    xArm 목표 변화량 = joint_sign × (GELLO 현재값 - GELLO 기준값)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml


MAX_LEADER_DELTA_DEG = 30.0
MIN_LEADER_DELTA_DEG = 3.0
OTHER_AXIS_TOLERANCE_DEG = 3.0
ROBOT_TEST_STEP_DEG = 1.0
SPEED_DEG_S = 3.0


def wrapped_delta_deg(current: float, baseline: float) -> float:
    """360° 경계를 넘어도 실제 작은 움직임의 부호/크기를 보존한다."""
    return math.degrees((current - baseline + math.pi) % (2 * math.pi) - math.pi)


def load_config(path: Path) -> tuple[dict, dict]:
    if not path.is_file():
        raise RuntimeError(f"설정 파일이 없습니다: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    robot = data.get("robot", {})
    teleop = data.get("teleop", {})
    if robot.get("robot_dof") != 7 or not isinstance(robot.get("start_joints"), list):
        raise RuntimeError("xArm7 robot.start_joints 설정을 읽지 못했습니다.")
    if not isinstance(teleop.get("joint_ids"), list) or len(teleop["joint_ids"]) != 7:
        raise RuntimeError("GELLO joint_ids 7개 설정을 읽지 못했습니다.")
    return robot, teleop


def get_gello_joints(teleop: dict) -> list[float]:
    """GELLO 값만 읽는다. 토크/목표 위치를 변경하지 않는다."""
    from gello.dynamixel.driver import DynamixelDriver

    ids = list(teleop["joint_ids"])
    driver = DynamixelDriver(ids, port=teleop["port"], baudrate=57600)
    try:
        values = None
        for _ in range(10):
            values = driver.get_joints()
        if values is None or len(values) != 7:
            raise RuntimeError("GELLO에서 7개 관절값을 읽지 못했습니다.")
        return [float(value) for value in values]
    finally:
        driver.close()


def get_xarm_joints_deg(robot_ip: str) -> list[float]:
    """xArm 관절값만 읽는다. 모션 명령은 보내지 않는다."""
    from xarm.wrapper import XArmAPI

    arm = XArmAPI(robot_ip, do_not_open=True)
    arm.connect()
    try:
        if not arm.connected:
            raise RuntimeError("xArm 연결에 실패했습니다.")
        _, err_warn = arm.get_err_warn_code()
        if err_warn != [0, 0]:
            raise RuntimeError(f"xArm 오류/경고가 있어 시험을 거부합니다: {err_warn}")
        code, joints_rad = arm.get_servo_angle(is_radian=True)
        if code != 0:
            raise RuntimeError(f"xArm 관절값 읽기 실패: 반환 코드 {code}")
        return [math.degrees(value) for value in joints_rad]
    finally:
        arm.disconnect()


def require_current_safe_pose(current_deg: list[float], safe_deg: list[float]) -> None:
    errors = [abs(now - expected) for now, expected in zip(current_deg, safe_deg)]
    largest = max(errors)
    if largest > 2.0:
        raise RuntimeError(
            f"현재 xArm이 기록된 안전 시작 자세에서 최대 {largest:.3f}° 벗어났습니다. "
            "먼저 안전 시작 자세로 복귀한 뒤에만 축 시험을 할 수 있습니다."
        )


def move_xarm_once(robot_ip: str, target_deg: list[float], safe_deg: list[float]) -> None:
    """선택 축의 작은 목표로 이동한 뒤, Enter 이후 안전 시작 자세로 복귀한다."""
    from xarm.wrapper import XArmAPI

    arm = XArmAPI(robot_ip)
    try:
        if not arm.connected:
            raise RuntimeError("xArm 연결에 실패했습니다.")
        _, err_warn = arm.get_err_warn_code()
        if err_warn != [0, 0]:
            raise RuntimeError(f"xArm 오류/경고가 있어 실행을 거부합니다: {err_warn}")

        speed_rad_s = math.radians(SPEED_DEG_S)
        # 여기부터 실제 로봇 모션이 발생한다. 그리퍼 관련 API는 호출하지 않는다.
        arm.motion_enable(enable=True)
        arm.set_mode(0)
        arm.set_state(0)
        result = arm.set_servo_angle(
            angle=[math.radians(value) for value in target_deg],
            speed=speed_rad_s,
            is_radian=True,
            wait=True,
        )
        if result != 0:
            raise RuntimeError(f"시험 모션이 거부되었습니다. 반환 코드: {result}")

        input("\n방향을 눈으로 확인하세요. 안전 시작 자세로 돌아가려면 Enter를 누르세요: ")
        result = arm.set_servo_angle(
            angle=[math.radians(value) for value in safe_deg],
            speed=speed_rad_s,
            is_radian=True,
            wait=True,
        )
        if result != 0:
            raise RuntimeError(f"안전 시작 자세 복귀가 거부되었습니다. 반환 코드: {result}")
        print("✅ 기록된 안전 시작 자세로 복귀했습니다.")
    except KeyboardInterrupt:
        # 사용자가 Ctrl+C를 눌렀다면 추가 모션을 중단한다.
        arm.set_state(4)
        print("\n[중단] Ctrl+C가 감지되어 xArm 정지 상태를 요청했습니다.")
        raise
    finally:
        arm.disconnect()


def save_log(log_dir: Path, payload: dict) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = log_dir / f"gello_axis_{payload['axis']}_{timestamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[기록] 시험 값 저장: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="GELLO/xArm 단일 관절 방향 시험")
    parser.add_argument("--config", type=Path, required=True, help="xArm7/GELLO 설정 YAML")
    parser.add_argument("--axis", type=int, required=True, choices=range(1, 8), help="시험할 관절 번호 (1~7)")
    parser.add_argument("--candidate-sign", type=int, required=True, choices=(-1, 1), help="이번 시험에서 적용할 부호")
    parser.add_argument("--log-dir", type=Path, required=True, help="시험 로그 저장 폴더")
    args = parser.parse_args()

    robot, teleop = load_config(args.config)
    safe_deg = [float(value) for value in robot["start_joints"]]
    axis_index = args.axis - 1

    print("=" * 72)
    print(f"GELLO J{args.axis} → xArm J{args.axis} 방향 시험")
    expected_motor_id = teleop["joint_ids"][axis_index]
    print("xArm은 선택 관절만 정확히 1.0°, 3.0°/s로 움직입니다. 그리퍼는 움직이지 않습니다.")
    print(f"이번 후보 부호: {args.candidate_sign:+d}")
    print(f"이번에 움직일 GELLO 물리 관절: 설정상 Dynamixel ID {expected_motor_id}에 해당하는 관절")
    print("=" * 72)

    current_robot_deg = get_xarm_joints_deg(robot["robot_ip"])
    require_current_safe_pose(current_robot_deg, safe_deg)
    baseline_gello = get_gello_joints(teleop)
    print("✅ 현재 xArm은 안전 시작 자세입니다.")
    print(f"✅ GELLO 기준값을 읽었습니다. 이제 해당 물리 관절을 3°~30° 정도 편하게 움직이세요.")
    input("GELLO를 움직인 뒤 Enter를 누르세요. 취소하려면 Ctrl+C: ")

    moved_gello = get_gello_joints(teleop)
    deltas_deg = [wrapped_delta_deg(now, baseline) for now, baseline in zip(moved_gello, baseline_gello)]
    selected_delta = deltas_deg[axis_index]
    other_deltas = [abs(delta) for index, delta in enumerate(deltas_deg) if index != axis_index]
    detected_index = max(range(7), key=lambda index: abs(deltas_deg[index]))
    detected_motor_id = teleop["joint_ids"][detected_index]

    if detected_motor_id != expected_motor_id:
        raise RuntimeError(
            f"이번에 가장 크게 움직인 GELLO 모터는 Dynamixel ID {detected_motor_id}입니다. "
            f"xArm J{args.axis}에 현재 연결된 것으로 설정한 ID {expected_motor_id}와 다릅니다. "
            "xArm은 움직이지 않았습니다. ./run.sh gello-detect로 물리 관절 ID부터 확인하세요."
        )
    if not MIN_LEADER_DELTA_DEG <= abs(selected_delta) <= MAX_LEADER_DELTA_DEG:
        raise RuntimeError(
            f"J{args.axis} 변화량이 {selected_delta:+.3f}°입니다. "
            f"시험 허용 범위는 {MIN_LEADER_DELTA_DEG}°~{MAX_LEADER_DELTA_DEG}°입니다. 다시 기준을 잡고 시도하세요."
        )
    largest_other = max(other_deltas)
    if largest_other > OTHER_AXIS_TOLERANCE_DEG:
        raise RuntimeError(
            f"선택하지 않은 GELLO 축도 최대 {largest_other:.3f}° 움직였습니다. "
            "다른 축을 고정한 뒤 다시 시도하세요."
        )

    target_deg = safe_deg.copy()
    # 사람이 GELLO를 크게 움직여도 xArm은 정해진 1°만 움직인다.
    target_deg[axis_index] += args.candidate_sign * math.copysign(ROBOT_TEST_STEP_DEG, selected_delta)
    robot_delta = target_deg[axis_index] - safe_deg[axis_index]
    print(f"\n예상 xArm 변화: J{args.axis} {robot_delta:+.3f}°")
    print(f"xArm 목표 관절각: {[round(value, 4) for value in target_deg]}")
    print("사람과 장애물이 작업영역 밖에 있는지 다시 확인하세요.")
    # 터미널 한글 입력 인코딩 문제를 피하기 위해 확인 문자열은 ASCII 영문만 사용한다.
    answer = input("실제 한 축 시험을 실행하려면 'test'를 입력하세요: ").strip()
    if answer != "test":
        print("[취소] 확인 문자열이 일치하지 않아 xArm을 움직이지 않았습니다.")
        return 2

    payload = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "axis": args.axis,
        "candidate_sign": args.candidate_sign,
        "detected_gello_motor_id": detected_motor_id,
        "gello_delta_deg": deltas_deg,
        "xarm_target_deg": target_deg,
        "xarm_selected_delta_deg": robot_delta,
    }
    move_xarm_once(robot["robot_ip"], target_deg, safe_deg)
    save_log(args.log_dir, payload)
    print("\n판정 방법:")
    print(f"- GELLO 물리 관절과 xArm J{args.axis} 움직임이 물리적으로 같은 방향이면: 부호 {args.candidate_sign:+d} 확정")
    print(f"- 반대 방향이면: 같은 시험을 candidate-sign {-args.candidate_sign:+d}로 다시 실행")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"❌ 축 시험 중단: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
