#!/usr/bin/env python3
"""텔레옵 설정 파일이 현재 xArm 상태와 맞는지 읽기 전용으로 검사한다."""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import yaml


def fail(message: str) -> None:
    print(f"❌ [FAIL] {message}")


def ok(message: str) -> None:
    print(f"✅ [OK] {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="xArm7/GELLO 텔레옵 설정의 읽기 전용 검사")
    parser.add_argument("--config", type=Path, required=True, help="텔레옵 YAML 설정 파일")
    parser.add_argument("--safety-state", type=Path, required=True, help="텔레옵 안전 검증 상태 파일")
    parser.add_argument("--max-start-error-deg", type=float, default=2.0, help="시작 자세 허용 오차")
    parser.add_argument(
        "--allow-start-pose-mismatch",
        action="store_true",
        help="기록 시작 시 자동 복귀를 허용합니다. 자세 차이는 FAIL 대신 WARN으로 표시합니다.",
    )
    args = parser.parse_args()

    if not args.config.is_file():
        fail(f"설정 파일이 없습니다: {args.config}")
        return 1
    data = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    if not args.safety_state.is_file():
        fail(f"안전 검증 상태 파일이 없습니다: {args.safety_state}")
        return 1
    safety_state = yaml.safe_load(args.safety_state.read_text(encoding="utf-8")) or {}
    robot = data.get("robot", {})
    teleop = data.get("teleop", {})
    robot_joints = robot.get("start_joints")
    gello_joints = teleop.get("start_joints")
    signs = teleop.get("joint_signs")
    failed = False

    if not isinstance(robot_joints, list) or len(robot_joints) != 7:
        fail("robot.start_joints는 관절각 7개여야 합니다.")
        failed = True
    else:
        ok(f"robot.start_joints 형식 확인: {robot_joints}")

    if robot_joints != gello_joints:
        fail("robot.start_joints와 teleop.start_joints가 다릅니다. 초기 급이동을 막기 위해 같아야 합니다.")
        failed = True
    else:
        ok("xArm과 GELLO의 시작 관절값이 같습니다.")

    if not isinstance(signs, list) or len(signs) != 7 or any(sign not in (-1, 1) for sign in signs):
        fail("teleop.joint_signs는 7개의 +1 또는 -1이어야 합니다.")
        failed = True
    else:
        ok(f"GELLO 관절 부호 형식 확인: {signs}")

    if robot.get("gripper_type") != 1:
        fail("현재 장비는 기본 xArm Gripper이므로 gripper_type은 1이어야 합니다.")
        failed = True
    else:
        ok("기본 xArm Gripper 설정 확인")

    tracking_mode = teleop.get("tracking_mode", "joint")
    if tracking_mode == "endpoint":
        # endpoint(TCP) 추적 모드: cartesian 제어 공간과 검토된 속도/관측 설정 검사.
        if robot.get("control_space") == "cartesian":
            ok("endpoint 추적: robot.control_space=cartesian (mode 7 온라인 planning)")
        else:
            fail("endpoint 추적 모드는 robot.control_space가 cartesian이어야 합니다.")
            failed = True
        if robot.get("cartesian_obs_include_joints") is True:
            ok("cartesian 모드에서도 관절값 J1~J7을 관측에 포함합니다 (pi0 스키마 유지).")
        else:
            fail("endpoint 모드는 cartesian_obs_include_joints: true여야 합니다.")
            failed = True
        if robot.get("max_linear_velocity") == 720 and robot.get("initial_sync_linear_velocity") == 20.0:
            ok("정상 TCP 추종 속도: 720mm/s (120°/s 환산 수준, 시작 후 첫 3초는 20mm/s)")
        else:
            fail(
                "endpoint 추종 속도는 검토한 max_linear_velocity=720, "
                f"initial_sync_linear_velocity=20.0이어야 합니다. 현재: "
                f"{robot.get('max_linear_velocity')!r}, {robot.get('initial_sync_linear_velocity')!r}"
            )
            failed = True
        tcp_offset = teleop.get("tcp_offset")
        if isinstance(tcp_offset, list) and len(tcp_offset) == 6:
            ok(f"teleop.tcp_offset 형식 확인: {tcp_offset}")
        else:
            fail("teleop.tcp_offset은 [x, y, z(mm), roll, pitch, yaw(°)] 6개 값이어야 합니다.")
            failed = True
        fk_ip = teleop.get("robot_ip", "")
        if fk_ip == robot.get("robot_ip"):
            ok("컨트롤러 FK 사용: 공장 캘리브레이션이 포함된 FK로 endpoint를 계산합니다.")
        elif not fk_ip:
            print("⚠️ [WARN] teleop.robot_ip가 비어 있어 로컬 공칭 FK를 씁니다. 수 mm 모델 오차가 생깁니다.")
        else:
            fail(f"teleop.robot_ip({fk_ip!r})가 robot.robot_ip({robot.get('robot_ip')!r})와 다릅니다.")
            failed = True
        smoothing = teleop.get("endpoint_smoothing_alpha", 1.0)
        if isinstance(smoothing, (int, float)) and 0 < float(smoothing) <= 1.0:
            ok(f"endpoint 목표 스무딩 α={smoothing} (1=끔)")
        else:
            fail(f"endpoint_smoothing_alpha는 0보다 크고 1 이하여야 합니다: {smoothing!r}")
            failed = True
    elif tracking_mode == "joint":
        # 일반 추종 속도만 검사합니다. 시작 직후 3초의 저속 구간(3°/s)은 별도 설정입니다.
        tracking_velocity = robot.get("max_joint_velocity")
        if tracking_velocity == 120:
            ok("정상 텔레옵 추종 속도: 120°/s (시작 후 첫 3초는 3°/s)")
        else:
            fail(
                "정상 텔레옵 추종 속도는 검토한 120°/s여야 합니다. "
                f"현재 값: {tracking_velocity!r}"
            )
            failed = True
    else:
        fail(f"teleop.tracking_mode는 joint 또는 endpoint여야 합니다: {tracking_mode!r}")
        failed = True

    # 이 아래부터는 getter만 사용하는 읽기 전용 xArm 검사입니다.
    try:
        from xarm.wrapper import XArmAPI

        arm = XArmAPI(robot.get("robot_ip", "192.168.0.240"), do_not_open=True)
        arm.connect()
        try:
            code, current_rad = arm.get_servo_angle(is_radian=True)
            if code != 0:
                fail(f"현재 관절값 읽기 실패: 반환 코드 {code}")
                failed = True
            elif isinstance(robot_joints, list) and len(robot_joints) == 7:
                current_deg = [math.degrees(value) for value in current_rad]
                errors = [abs(now - expected) for now, expected in zip(current_deg, robot_joints)]
                largest = max(errors)
                if largest <= args.max_start_error_deg:
                    ok(
                        f"현재 xArm 자세가 기록된 안전 시작 자세와 일치합니다. "
                        f"최대 오차 {largest:.3f}° (허용값 {args.max_start_error_deg:.3f}°)"
                    )
                else:
                    message = (
                        f"현재 xArm 자세가 안전 시작 자세에서 최대 {largest:.3f}° 벗어났습니다. "
                "start 확인과 3초 대기 후 3°/s로 안전 시작 자세에 자동 복귀합니다."
                    )
                    if args.allow_start_pose_mismatch:
                        print(f"⚠️ [WARN] {message}")
                    else:
                        fail(message)
                        failed = True

            if tracking_mode == "endpoint":
                # 컨트롤러의 실제 TCP offset과 config의 tcp_offset이 같아야
                # endpoint delta 매핑에서 방향 변화 시 오차가 없다.
                # 주의: arm.tcp_offset은 컨트롤러의 주기 report에서 채워지는
                # 값이라 connect 직후에는 초기값 [0]*6이 읽힐 수 있다(레이스).
                # 첫 report가 도착할 때까지 최대 3초 기다린다.
                controller_offset = list(arm.tcp_offset)  # [x,y,z(mm), roll,pitch,yaw(°)]
                wait_deadline = time.monotonic() + 3.0
                while (
                    all(abs(value) < 1e-9 for value in controller_offset)
                    and time.monotonic() < wait_deadline
                ):
                    time.sleep(0.2)
                    controller_offset = list(arm.tcp_offset)
                if all(abs(value) < 1e-9 for value in controller_offset):
                    print(
                        "⚠️ [WARN] 컨트롤러 TCP offset이 3초 후에도 [0]*6입니다. "
                        "실제로 offset이 0이면 xArm Studio에서 그리퍼 TCP(z=172mm)를 "
                        "설정해야 합니다."
                    )
                config_offset = teleop.get("tcp_offset") or []
                if len(config_offset) == 6 and len(controller_offset) == 6:
                    gaps = [abs(a - b) for a, b in zip(controller_offset, config_offset)]
                    if max(gaps[:3]) <= 1.0 and max(gaps[3:]) <= 1.0:
                        ok(f"컨트롤러 TCP offset과 config tcp_offset 일치: {controller_offset}")
                    else:
                        fail(
                            f"컨트롤러 TCP offset {controller_offset}과 config tcp_offset "
                            f"{config_offset}이 다릅니다. config를 컨트롤러 값에 맞추세요."
                        )
                        failed = True
        finally:
            arm.disconnect()
    except Exception as exc:
        fail(f"xArm 읽기 전용 검사 실패: {type(exc).__name__}: {exc}")
        failed = True

    if safety_state.get("arm_joint_signs_verified") is True:
        ok("GELLO 팔 관절 J1~J7 부호 검증 완료 표시가 있습니다.")
    else:
        fail("GELLO 팔 관절 J1~J7 부호 검증 완료 표시가 없습니다.")
        failed = True

    if safety_state.get("gripper_mapping_verified") is not True:
        fail(
            "GELLO 그리퍼 방향/영점이 아직 검증되지 않았습니다. "
            "./run.sh gello-gripper를 완료한 뒤에만 전체 텔레옵을 허용합니다."
        )
        failed = True

    if safety_state.get("gello_mapping_verified") is True:
        ok("GELLO 관절 부호/영점 검증 완료 표시가 있습니다.")
    else:
        fail(
            "GELLO 관절 부호/영점이 아직 검증되지 않았습니다. "
            "2단계에서 각 축을 확인한 뒤에만 gello_mapping_verified를 true로 바꿉니다."
        )
        failed = True

    relative_checks = {
        "relative_alignment_enabled": True,
        "leader_stability_duration_s": 0.5,
        "leader_stability_max_delta_deg": 1.0,
        "first_action_max_delta_deg": 1.0,
    }
    if tracking_mode == "endpoint":
        relative_checks.update(
            {
                "first_action_max_delta_mm": 5.0,
                "first_action_max_delta_rot_deg": 2.0,
                "max_frame_jump_mm": 150.0,
            }
        )
    wrong_relative = [
        key for key, expected in relative_checks.items()
        if teleop.get(key) != expected
    ]
    if not wrong_relative:
        ok("에피소드별 상대 영점 및 리더/첫 action 안전 조건 확인")
    else:
        fail(
            "상대 영점 안전 설정이 다릅니다: "
            + ", ".join(wrong_relative)
        )
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
