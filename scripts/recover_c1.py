#!/usr/bin/env python3
"""xArm C1(비상 정지 버튼) 전용의 대화형 안전 복구 도구.

이 도구는 C1만 처리한다. 충돌(C31), 통신(C19), 서보 오류 같은 다른 오류는
원인이 전혀 다르므로 절대 자동 해제하지 않는다.

중요: 비상 정지 버튼은 소프트웨어로 해제할 수 없다. 사용자가 버튼을 물리적으로
돌려서(풀어서) 해제한 뒤에만 이 절차가 진행된다.

실행 순서:
1. 오류 코드가 정말 C1인지 읽기 전용으로 확인한다.
2. 사용자가 비상정지 원인을 확인하고 버튼을 물리적으로 해제했다는 확인을 기다린다.
3. 오류를 해제하고 모터를 다시 활성화한다(motion_enable → mode 0 → state 0).
   버튼이 아직 눌려 있으면 오류가 남으므로 여기서 안전하게 중단한다.
4. 사용자의 두 번째 확인 뒤에만, 검증된 초기 관절 자세로 8°/s 복귀한다.

그리퍼에는 어떤 명령도 보내지 않으며, 텔레옵을 자동 재시작하지 않는다.
"""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import yaml


C1 = 1
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "xarm7_gello_teleop.yaml"


def load_recovery_target(config_path: Path) -> tuple[str, list[float], float]:
    """이미 검증한 텔레옵 시작 관절 자세와 복귀 속도만 읽는다."""
    if not config_path.is_file():
        raise RuntimeError(f"설정 파일이 없습니다: {config_path}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    robot = config.get("robot", {})
    robot_ip = robot.get("robot_ip")
    target = robot.get("start_joints")
    speed = robot.get("init_position_velocity")
    if not isinstance(robot_ip, str):
        raise RuntimeError("robot.robot_ip를 읽지 못했습니다.")
    if not isinstance(target, list) or len(target) != 7:
        raise RuntimeError("robot.start_joints는 관절각 7개여야 합니다.")
    if not isinstance(speed, (int, float)) or not 0 < float(speed) <= 10:
        raise RuntimeError("init_position_velocity는 0보다 크고 10°/s 이하여야 합니다.")
    return robot_ip, [float(value) for value in target], float(speed)


def read_error(arm) -> tuple[int, int]:
    """오류/경고 코드만 읽는다. 어떤 상태 변경도 하지 않는다."""
    code, err_warn = arm.get_err_warn_code()
    if code != 0 or not isinstance(err_warn, (list, tuple)) or len(err_warn) < 2:
        raise RuntimeError(f"xArm 오류 코드 읽기 실패: SDK 반환값 {code}, {err_warn}")
    return int(err_warn[0]), int(err_warn[1])


def require_success(code: int, action: str) -> None:
    if code != 0:
        raise RuntimeError(f"{action} 실패: xArm SDK 반환 코드 {code}")


def countdown() -> None:
    print("[대기] 3초 뒤 초기 자세 복귀를 시작합니다. 사람·물체·케이블을 마지막으로 확인하세요.")
    for remaining in (3, 2, 1):
        print(f"[대기] {remaining}초...")
        time.sleep(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="xArm C1 비상정지 안전 복구")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="텔레옵 설정 YAML")
    args = parser.parse_args()

    try:
        robot_ip, target, speed_deg_s = load_recovery_target(args.config)
        from xarm.wrapper import XArmAPI

        # 1. 첫 연결은 오직 C1 판정용이다.
        arm = XArmAPI(robot_ip, do_not_open=True)
        arm.connect()
        try:
            if not arm.connected:
                raise RuntimeError(f"xArm 연결 실패: {robot_ip}")
            error_code, warning_code = read_error(arm)
            print("=" * 72)
            print("xArm C1 비상정지 복구")
            print("이 도구는 C1만 처리하며, 아직 로봇을 움직이지 않았습니다.")
            print("=" * 72)
            print(f"[진단] 컨트롤러 오류 코드: {error_code}, 경고 코드: {warning_code}")
            print(f"[진단] 로봇 상태: state={arm.state}, mode={arm.mode}")
            if error_code != C1:
                if error_code == 0:
                    print("[중단] 현재 C1 오류가 없습니다. 안전상 아무 동작도 하지 않습니다.")
                    return 2
                print(
                    f"[중단] 현재 오류는 C1이 아닌 C{error_code}입니다. "
                    "충돌(C31)·그리퍼 통신(C19)은 각각의 복구 절차를, 그 밖의 오류는 doctor를 사용하세요."
                )
                return 2
        finally:
            arm.disconnect()

        print("\n[1/3] 비상정지 원인을 먼저 확인하고, 버튼을 물리적으로 해제하세요.")
        print("  - 왜 비상정지를 눌렀는지(충돌 위험, 오작동 등) 원인이 사라졌는지 확인하세요.")
        print("  - 컨트롤 박스의 비상 정지 버튼을 화살표 방향으로 돌려서 해제하세요.")
        print("  - 모터가 다시 켜질 때 팔이 약간 내려앉을 수 있습니다. 팔 아래에 손·물체를 두지 마세요.")
        print("[GUI 단계] 비상정지 해제 확인 대기")
        input("버튼을 해제했으면 Enter를 누르세요 (아직 로봇은 움직이지 않습니다): ")

        # 2. 사용자 확인 뒤 오류 해제와 모터 재활성화를 진행한다.
        arm = XArmAPI(robot_ip)
        try:
            if not arm.connected:
                raise RuntimeError(f"xArm 연결 실패: {robot_ip}")
            error_code, warning_code = read_error(arm)
            if error_code not in (0, C1):
                raise RuntimeError(
                    f"오류 상태가 C1에서 C{error_code}로 바뀌었습니다. "
                    "안전상 자동 해제를 중단합니다. 해당 오류의 절차를 따르세요."
                )

            print("[2/3] C1 오류를 해제하고 모터를 다시 활성화합니다. 이 단계는 팔을 이동시키지 않습니다.")
            require_success(arm.clean_error(), "C1 오류 해제")
            time.sleep(0.5)
            error_code, warning_code = read_error(arm)
            if error_code == C1:
                raise RuntimeError(
                    "오류 해제 뒤에도 C1이 남아 있습니다. 비상 정지 버튼이 아직 눌려(잠겨) "
                    "있을 가능성이 큽니다. 버튼을 화살표 방향으로 끝까지 돌려 해제한 뒤 다시 실행하세요."
                )
            if error_code != 0:
                raise RuntimeError(
                    f"오류 해제 뒤 다른 오류 C{error_code}가 나타났습니다. 해당 오류의 절차를 따르세요."
                )

            # 비상정지는 모터 전원을 끊으므로 반드시 재활성화가 필요하다.
            # 아래 호출들은 목표 위치를 주지 않으므로 팔을 이동시키지 않는다.
            require_success(arm.motion_enable(enable=True), "모터 활성화")
            require_success(arm.set_mode(0), "위치 제어 모드 설정")
            require_success(arm.set_state(0), "로봇 준비 상태 설정")
            time.sleep(0.5)
            error_code, warning_code = read_error(arm)
            if error_code != 0:
                raise RuntimeError(f"모터 재활성화 중 오류 발생: C{error_code}, 경고 {warning_code}")
            print("✅ [확인] C1이 해제되고 모터가 다시 켜졌습니다. 아직 이동 명령은 보내지 않았습니다.")

            code, current = arm.get_servo_angle(is_radian=False)
            require_success(code, "현재 관절값 읽기")
            current = [float(value) for value in current[:7]]
            largest_delta = max(abs(now - goal) for now, goal in zip(current, target))
            estimate = largest_delta / speed_deg_s
            print("\n[3/3] 이제 초기 자세로 실제 복귀할 수 있습니다.")
            print(f"  현재 관절각(°): {[round(value, 2) for value in current]}")
            print(f"  목표 관절각(°): {[round(value, 2) for value in target]}")
            print(f"  최대 관절 차이: {largest_delta:.2f}°")
            print(f"  복귀 속도: {speed_deg_s:.1f}°/s (최소 예상 약 {estimate:.1f}초)")
            print("[GUI 단계] 초기 자세 복귀 승인 대기")
            answer = input("작업영역이 비었음을 확인했고 초기 자세로 복귀하려면 'return'을 입력하세요: ").strip()
            if answer != "return":
                print("[취소] 초기 자세 복귀를 실행하지 않았습니다. C1 해제와 모터 활성화까지만 완료된 상태입니다.")
                return 2

            countdown()
            error_code, warning_code = read_error(arm)
            if error_code != 0:
                raise RuntimeError(f"대기 중 오류 발생: C{error_code}, 경고 {warning_code}")
            timeout_s = max(10.0, estimate + 10.0)
            print("[복귀 시작] 팔 관절만 초기 자세로 이동합니다. 그리퍼는 움직이지 않습니다.")
            require_success(
                arm.set_servo_angle(
                    angle=target,
                    speed=speed_deg_s,
                    is_radian=False,
                    wait=True,
                    timeout=timeout_s,
                ),
                "초기 자세 복귀",
            )
            print("✅ [완료] C1 복구와 초기 자세 복귀가 끝났습니다.")
            print("[다음] 텔레옵은 자동 재개되지 않습니다. 필요하면 ./run.sh teleop 을 새로 실행하세요.")
            return 0
        finally:
            arm.disconnect()
    except RuntimeError as exc:
        print(f"❌ [실패] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
