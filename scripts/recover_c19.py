#!/usr/bin/env python3
"""xArm C19(끝단 모듈/그리퍼 통신 오류) 전용의 대화형 안전 복구 도구.

이 도구는 C19만 처리한다. 충돌(C31), 서보 오류, 비상정지 같은 다른 오류는
원인이 전혀 다르므로 절대 자동 해제하지 않는다.

공식 근거 (xArm User Manual, 오류 처리 표):
  C19 "Gripper Communication Error" — 그리퍼 장착 상태와 baud rate 설정을
  확인하고, 해결되지 않으면 컨트롤 박스의 비상 정지 버튼으로 재시작한다.

이 프로젝트에서 C19의 흔한 원인:
  * 손목 커넥터/그리퍼 케이블의 접촉 불량 (텔레옵 중 손목 회전으로 당겨짐)
  * tool RS-485 baud rate가 기본 xArm Gripper 값(2,000,000)에서 벗어남
  * 손목 카메라 USB 케이블이 그리퍼 케이블을 누르거나 당김

실행 순서:
1. 오류 코드가 정말 C19인지 읽기 전용으로 확인한다.
2. 사용자가 그리퍼/카메라 케이블 상태를 점검했다는 확인을 기다린다.
3. 오류를 해제하고, tool baud rate 자동 교정과 함께 그리퍼 통신만 복구한다.
4. 그리퍼 위치를 '읽기'로 통신을 검증한다. 이 과정에서 팔과 그리퍼는
   전혀 움직이지 않는다(물체를 잡고 있어도 떨어뜨리지 않는다).

복구 후에도 C19가 곧바로 재발하면 케이블/하드웨어 문제이므로, 공식 절차대로
비상 정지 버튼 재시작 또는 담당자 점검을 안내하고 종료한다.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import yaml


C19 = 19
XARM_GRIPPER_BAUD = 2_000_000  # 기본 xArm Gripper의 tool RS-485 baud rate
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "xarm7_gello_teleop.yaml"


def load_robot_ip(config_path: Path) -> str:
    if not config_path.is_file():
        raise RuntimeError(f"설정 파일이 없습니다: {config_path}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    robot = config.get("robot", {})
    robot_ip = robot.get("robot_ip")
    if not isinstance(robot_ip, str) or not robot_ip:
        raise RuntimeError("robot.robot_ip를 읽지 못했습니다.")
    if robot.get("gripper_type") != 1:
        raise RuntimeError(
            "이 복구 도구는 기본 xArm Gripper(gripper_type=1) 전용입니다. "
            f"현재 설정: {robot.get('gripper_type')!r}"
        )
    return robot_ip


def read_error(arm) -> tuple[int, int]:
    """오류/경고 코드만 읽는다. 어떤 상태 변경도 하지 않는다."""
    code, err_warn = arm.get_err_warn_code()
    if code != 0 or not isinstance(err_warn, (list, tuple)) or len(err_warn) < 2:
        raise RuntimeError(f"xArm 오류 코드 읽기 실패: SDK 반환값 {code}, {err_warn}")
    return int(err_warn[0]), int(err_warn[1])


def require_success(code: int, action: str) -> None:
    if code != 0:
        raise RuntimeError(f"{action} 실패: xArm SDK 반환 코드 {code}")


def main() -> int:
    parser = argparse.ArgumentParser(description="xArm C19 그리퍼/끝단 통신 안전 복구")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="텔레옵 설정 YAML")
    args = parser.parse_args()

    try:
        robot_ip = load_robot_ip(args.config)
        from xarm.wrapper import XArmAPI

        # 1. 첫 연결은 오직 C19 판정용이다.
        arm = XArmAPI(robot_ip, do_not_open=True)
        arm.connect()
        try:
            if not arm.connected:
                raise RuntimeError(f"xArm 연결 실패: {robot_ip}")
            error_code, warning_code = read_error(arm)
            print("=" * 72)
            print("xArm C19 그리퍼/끝단 통신 복구")
            print("이 도구는 C19만 처리하며, 팔과 그리퍼를 움직이지 않습니다.")
            print("=" * 72)
            print(f"[진단] 컨트롤러 오류 코드: {error_code}, 경고 코드: {warning_code}")
            print(f"[진단] 로봇 상태: state={arm.state}, mode={arm.mode}")
            if error_code != C19:
                if error_code == 0:
                    print("[중단] 현재 C19 오류가 없습니다. 안전상 아무 동작도 하지 않습니다.")
                    return 2
                print(
                    f"[중단] 현재 오류는 C19가 아닌 C{error_code}입니다. "
                    "충돌(C31)은 C31 복구를, 그 밖의 오류는 원인 확인 후 doctor를 사용하세요."
                )
                return 2
        finally:
            arm.disconnect()

        print("\n[1/3] 그리퍼/케이블 상태를 먼저 점검하세요. 로봇은 아직 움직이지 않습니다.")
        print("  - 손목의 그리퍼 커넥터가 단단히 꽂혀 있는지 확인하세요.")
        print("  - 그리퍼 케이블이 꺾이거나 손목 카메라 케이블에 눌리지 않았는지 확인하세요.")
        print("  - 케이블을 다시 꽂았다면 커넥터가 끝까지 잠겼는지 확인하세요.")
        print("[GUI 단계] 케이블 점검 확인 대기")
        input("점검이 끝났으면 Enter를 누르세요 (아직 아무 명령도 보내지 않습니다): ")

        # 2. 점검 뒤에도 C19인지 재확인한 다음에만 해제한다.
        arm = XArmAPI(robot_ip)
        try:
            if not arm.connected:
                raise RuntimeError(f"xArm 연결 실패: {robot_ip}")
            error_code, warning_code = read_error(arm)
            if error_code != C19:
                raise RuntimeError(
                    f"오류 상태가 C19에서 바뀌었습니다(C{error_code}, 경고 {warning_code}). "
                    "안전상 자동 해제를 중단합니다."
                )

            print("[2/3] C19 오류를 해제하고 그리퍼 통신을 복구합니다. 팔은 움직이지 않습니다.")
            require_success(arm.clean_error(), "C19 오류 해제")
            time.sleep(0.5)
            error_code, warning_code = read_error(arm)
            if error_code != 0:
                raise RuntimeError(
                    f"오류 해제 뒤에도 코드가 남아 있습니다: 오류 C{error_code}, 경고 {warning_code}. "
                    "케이블 접촉을 다시 확인하고, 반복되면 공식 절차대로 비상 정지 버튼으로 "
                    "컨트롤 박스를 재시작하세요."
                )
            print("✅ [확인] C19 오류가 해제됐습니다.")

            # tool RS-485 baud rate 확인. 기본 xArm Gripper는 2,000,000이어야 한다.
            code, baud = arm.get_tgpio_modbus_baudrate()
            if code == 0:
                print(f"[진단] tool RS-485 baud rate: {baud}")
                if int(baud) != XARM_GRIPPER_BAUD:
                    print(f"[복구] baud rate를 기본 xArm Gripper 값 {XARM_GRIPPER_BAUD}으로 되돌립니다.")
                    require_success(arm.set_tgpio_modbus_baudrate(XARM_GRIPPER_BAUD), "baud rate 복구")
                    time.sleep(0.3)
            else:
                print(f"⚠️ [경고] baud rate 읽기 실패(코드 {code}). 그리퍼 재활성화로 계속합니다.")

            # SDK의 baud 자동 점검/교정을 켠 상태로 그리퍼 통신만 재활성화한다.
            # 위치 명령은 보내지 않으므로 그리퍼는 물리적으로 움직이지 않는다.
            arm._arm._baud_checkset = True
            try:
                enable_code = arm.set_gripper_enable(True)
                if enable_code != 0:
                    recheck_error, _ = read_error(arm)
                    if recheck_error == C19:
                        raise RuntimeError(
                            "그리퍼 재활성화 순간 C19가 즉시 재발했습니다. 소프트웨어로는 "
                            "복구할 수 없는 물리 계층 문제입니다. 다음을 순서대로 점검하세요:\n"
                            "  1) 손목의 그리퍼 커넥터를 뽑았다가 딸깍 소리가 나도록 다시 꽂기\n"
                            "  2) 그리퍼 케이블의 꺾임/손상, 손목 카메라 케이블과의 간섭 확인\n"
                            "  3) 컨트롤 박스 비상 정지 버튼으로 로봇 재시작(공식 권장 절차)\n"
                            "  4) 반복되면 케이블 교체 또는 담당자 점검"
                        )
                    require_success(enable_code, "그리퍼 활성화")
                require_success(arm.set_gripper_mode(0), "그리퍼 위치 제어 모드 설정")
                code, gripper_err = arm.get_gripper_err_code()
                if code == 0 and int(gripper_err) != 0:
                    print(f"[복구] 그리퍼 자체 오류 코드 {gripper_err}를 해제합니다.")
                    require_success(arm.clean_gripper_error(), "그리퍼 오류 해제")
                    time.sleep(0.3)
            finally:
                arm._arm._baud_checkset = False

            # 3. 통신 검증: 그리퍼 위치 '읽기'만으로 확인한다.
            print("[3/3] 그리퍼 통신을 읽기 전용으로 검증합니다.")
            code, position = arm.get_gripper_position()
            if code != 0 or position is None:
                raise RuntimeError(
                    f"그리퍼 위치 읽기 실패(코드 {code}). 케이블/커넥터 문제일 가능성이 큽니다. "
                    "공식 절차대로 비상 정지 버튼으로 컨트롤 박스를 재시작하거나 담당자에게 "
                    "점검을 요청하세요."
                )
            print(f"✅ [확인] 그리퍼 응답 정상 (현재 위치 {position}/800, 이동 명령은 보내지 않았습니다).")

            # C19가 곧바로 재발하는지 잠시 관찰한다.
            time.sleep(1.0)
            error_code, warning_code = read_error(arm)
            if error_code != 0:
                raise RuntimeError(
                    f"복구 직후 오류가 재발했습니다: C{error_code}. 통신 하드웨어 문제이므로 "
                    "자동 복구를 반복하지 않습니다. 케이블 교체 또는 비상 정지 재시작이 필요합니다."
                )

            print("✅ [완료] C19 복구가 끝났습니다. 팔과 그리퍼는 움직이지 않았습니다.")
            print("[다음] 텔레옵/녹화는 자동 재개되지 않습니다. 필요하면 초기 자세 복귀 후 다시 시작하세요.")
            print("[참고] C19가 반복되면: 그리퍼 케이블 교체, 손목 카메라 케이블 정리, 비상 정지 재시작 순으로 점검하세요.")
            return 0
        finally:
            arm.disconnect()
    except RuntimeError as exc:
        print(f"❌ [실패] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
