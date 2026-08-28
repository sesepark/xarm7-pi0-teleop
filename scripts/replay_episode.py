#!/usr/bin/env python3
"""LeRobot 성공 시연 한 개를 xArm7에서 원래 30fps로 재생한다.

이 도구는 추론이나 텔레옵이 아니라 이미 저장된 ``action``을 그대로 보낸다.
따라서 반드시 다음을 확인한 뒤에만 움직인다.

* 선택한 데이터셋이 이 프로젝트의 data/ 폴더 안에 있는가
* xArm 오류/경고가 0인가
* 현재 7개 관절각이 해당 시연의 첫 action과 각각 2° 이내인가
* 기본 xArm 그리퍼도 첫 action(열림/닫힘)과 충분히 일치하는가
* 사용자의 start 확인과 3초 안전 대기가 끝났는가

기본 실행은 데이터를 읽고 검사할 내용만 출력한다. 실제 재생에는 --execute와
start 확인이 모두 필요하다.
"""

from __future__ import annotations

import argparse
import json
import math
import signal
import sys
import time
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = (PROJECT_ROOT / "data").resolve()
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "xarm7_gello_teleop.yaml"
FPS = 30.0
JOINT_START_TOLERANCE_DEG = 2.0
GRIPPER_START_TOLERANCE_NORM = 0.10
GRIPPER_OPEN_POSITION = 800
GRIPPER_CLOSE_POSITION = 0
GRIPPER_SPEED = 5000
GRIPPER_UPDATE_STEP = 3


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def resolve_dataset(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    require(path != DATA_ROOT and DATA_ROOT in path.parents, "데이터셋은 pi0_sehwan/data/ 폴더 안에서만 선택할 수 있습니다.")
    require((path / "meta" / "info.json").is_file(), f"LeRobot info.json을 찾지 못했습니다: {path}")
    return path


def load_robot_replay_config(config_path: Path) -> tuple[str, float]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    robot = config.get("robot", {})
    robot_ip = robot.get("robot_ip")
    require(isinstance(robot_ip, str) and robot_ip, "robot.robot_ip를 읽지 못했습니다.")
    max_joint_velocity = robot.get("max_joint_velocity")
    require(
        isinstance(max_joint_velocity, (int, float)) and 0 < float(max_joint_velocity) <= 180,
        "robot.max_joint_velocity는 0보다 크고 180°/s 이하여야 합니다.",
    )
    return robot_ip, float(max_joint_velocity)


def load_episode_actions(dataset_path: Path, episode_index: int) -> tuple[list[list[float]], float]:
    """재생할 관절 궤적(J1~J7 + gripper, 8차원)을 만든다.

    * 관절 추적 세션(action 8차원): 저장된 action을 그대로 쓴다.
    * endpoint 추적 세션(action 7차원 pose, state 14차원): action은 TCP pose라
      이 재생기로 직접 보낼 수 없다. 대신 관측 state에 기록된 "실제로 움직인
      관절값"([0:7]) + gripper([13])를 관절 궤적으로 재구성해 동일하게 재생한다.
    """
    info = json.loads((dataset_path / "meta" / "info.json").read_text(encoding="utf-8"))
    require(info.get("robot_type") == "UFACTORY Robot", "UFACTORY Robot 형식의 데이터셋만 재생할 수 있습니다.")
    require(int(info.get("fps", 0)) == int(FPS), f"이 재생기는 {int(FPS)}fps 데이터셋만 지원합니다.")
    features = info.get("features") or {}
    action_shape = (features.get("action") or {}).get("shape")
    state_shape = (features.get("observation.state") or {}).get("shape")
    if action_shape == [8]:
        endpoint_session = False
    elif action_shape == [7] and state_shape == [14]:
        endpoint_session = True
        print("[안내] endpoint 추적 세션입니다. 관측된 실제 관절값으로 재생 궤적을 만듭니다.")
    else:
        require(False, f"지원하지 않는 데이터 형식입니다 (action {action_shape}, state {state_shape}).")

    parquet_files = sorted((dataset_path / "data").glob("chunk-*/*.parquet"))
    require(parquet_files, "action parquet 파일을 찾지 못했습니다.")
    actions: list[list[float]] = []
    for parquet_file in parquet_files:
        table = pq.read_table(
            parquet_file, columns=["action", "observation.state", "episode_index", "timestamp"]
        )
        for row in table.to_pylist():
            if int(row["episode_index"]) != episode_index:
                continue
            if endpoint_session:
                state = row["observation.state"]
                require(isinstance(state, list) and len(state) == 14, "state 행의 길이가 14가 아닙니다.")
                actions.append([float(state[k]) for k in range(7)] + [float(state[13])])
            else:
                action = row["action"]
                require(isinstance(action, list) and len(action) == 8, "action 행의 길이가 8이 아닙니다.")
                actions.append([float(value) for value in action])

    require(actions, f"선택한 성공 시연 번호 {episode_index}의 action을 찾지 못했습니다.")
    return actions, float(info["fps"])


def gripper_norm_to_position(value: float) -> int:
    clipped = min(1.0, max(0.0, float(value)))
    return int(round(GRIPPER_OPEN_POSITION + clipped * (GRIPPER_CLOSE_POSITION - GRIPPER_OPEN_POSITION)))


def gripper_position_to_norm(value: float) -> float:
    clipped = min(GRIPPER_OPEN_POSITION, max(GRIPPER_CLOSE_POSITION, float(value)))
    return (GRIPPER_OPEN_POSITION - clipped) / (GRIPPER_OPEN_POSITION - GRIPPER_CLOSE_POSITION)


def describe_episode(actions: list[list[float]], fps: float) -> None:
    first = actions[0]
    joint_ranges = [
        math.degrees(max(frame[index] for frame in actions) - min(frame[index] for frame in actions))
        for index in range(7)
    ]
    print("=" * 72)
    print("xArm7 저장 시연 재생 사전 검사")
    print("데이터의 7개 관절 action과 기본 그리퍼 action을 원본 1배속으로 보냅니다.")
    print("=" * 72)
    print(f"프레임 수: {len(actions)} / 길이: {len(actions) / fps:.2f}초 / 속도: {fps:.0f}fps (1배속)")
    print(f"첫 관절 action(°): {[round(math.degrees(value), 3) for value in first[:7]]}")
    print(f"첫 그리퍼 action: {first[7]:.3f} (실제 위치 약 {gripper_norm_to_position(first[7])}/800)")
    print(f"관절별 전체 이동 범위(°): {[round(value, 2) for value in joint_ranges]}")


def check_start_state(arm: Any, first_action: list[float]) -> None:
    code, err_warn = arm.get_err_warn_code()
    require(code == 0 and list(err_warn[:2]) == [0, 0], f"로봇 오류/경고가 있어 재생을 거부합니다: {err_warn}")
    code, current = arm.get_servo_angle(is_radian=True)
    require(code == 0, f"현재 관절값 읽기 실패: xArm SDK 반환 코드 {code}")
    deltas_deg = [math.degrees(abs(now - target)) for now, target in zip(current[:7], first_action[:7])]
    max_delta = max(deltas_deg)
    print(f"현재-첫프레임 관절 오차(°): {[round(value, 3) for value in deltas_deg]}")
    require(
        max_delta <= JOINT_START_TOLERANCE_DEG,
        f"현재 관절값이 시연 첫 프레임에서 최대 {max_delta:.3f}° 벗어났습니다. "
        f"허용값은 {JOINT_START_TOLERANCE_DEG:.1f}°입니다. 초기 자세를 맞춘 뒤 다시 실행하세요.",
    )
    code, gripper_position = arm.get_gripper_position()
    require(code == 0, f"현재 그리퍼 위치 읽기 실패: xArm SDK 반환 코드 {code}")
    current_gripper = gripper_position_to_norm(gripper_position)
    gripper_delta = abs(current_gripper - first_action[7])
    print(f"현재-첫프레임 그리퍼 오차: {gripper_delta:.3f}")
    require(
        gripper_delta <= GRIPPER_START_TOLERANCE_NORM,
        "현재 그리퍼가 시연 첫 프레임과 다릅니다. 물체를 놓고 그리퍼를 첫 상태에 맞춘 뒤 다시 실행하세요.",
    )


def configure_for_replay(arm: Any) -> None:
    for label, result in (
        ("모터 활성화", arm.motion_enable(enable=True)),
        ("관절 온라인 계획 모드(6) 설정", arm.set_mode(6)),
        ("로봇 ready 상태 설정", arm.set_state(0)),
        ("그리퍼 활성화", arm.set_gripper_enable(True)),
        ("그리퍼 위치 제어 모드 설정", arm.set_gripper_mode(0)),
        ("그리퍼 속도 설정", arm.set_gripper_speed(GRIPPER_SPEED)),
    ):
        require(result == 0, f"{label} 실패: xArm SDK 반환 코드 {result}")
    time.sleep(0.2)


def safe_stop(arm: Any) -> None:
    try:
        arm.set_state(4)
        stop_gripper = getattr(arm, "set_gripper_stop", None)
        if callable(stop_gripper):
            stop_gripper()
        arm.set_mode(0)
    except Exception:
        pass


def replay(arm: Any, actions: list[list[float]], fps: float, joint_velocity_deg_s: float) -> None:
    period_s = 1.0 / fps
    joint_velocity_rad_s = math.radians(joint_velocity_deg_s)
    last_gripper_position: int | None = None
    started_at = time.monotonic()
    next_error_check = started_at
    total = len(actions)
    for frame_index, action in enumerate(actions):
        deadline = started_at + frame_index * period_s
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

        now = time.monotonic()
        if now >= next_error_check:
            code, err_warn = arm.get_err_warn_code()
            require(code == 0 and list(err_warn[:2]) == [0, 0], f"재생 중 xArm 오류/경고 감지: {err_warn}")
            next_error_check = now + 0.2

        code = arm.set_servo_angle(
            angle=action[:7], speed=joint_velocity_rad_s, is_radian=True, wait=False
        )
        require(code == 0, f"재생 프레임 {frame_index} 관절 명령 실패: xArm SDK 반환 코드 {code}")

        gripper_position = gripper_norm_to_position(action[7])
        if last_gripper_position is None or abs(gripper_position - last_gripper_position) >= GRIPPER_UPDATE_STEP:
            code = arm.set_gripper_position(gripper_position, wait=False, speed=GRIPPER_SPEED)
            require(code == 0, f"재생 프레임 {frame_index} 그리퍼 명령 실패: xArm SDK 반환 코드 {code}")
            last_gripper_position = gripper_position

        if frame_index == 0 or (frame_index + 1) % max(1, int(fps * 2)) == 0 or frame_index + 1 == total:
            print(f"[재생] {frame_index + 1}/{total} 프레임", flush=True)


def countdown() -> None:
    print("[대기] 3초 뒤 선택한 성공 시연을 원본 1배속으로 재생합니다.")
    for remaining in (3, 2, 1):
        print(f"[대기] {remaining}초...", flush=True)
        time.sleep(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="xArm7 저장 성공 시연 재생")
    parser.add_argument("--dataset", required=True, help="pi0_sehwan/data 아래 LeRobot 데이터셋 경로")
    parser.add_argument("--episode", type=int, required=True, help="재생할 성공 시연 번호(0부터 시작)")
    parser.add_argument("--execute", action="store_true", help="실제 로봇 재생을 명시적으로 허용")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="xArm IP 설정 YAML")
    args = parser.parse_args()

    arm = None
    try:
        dataset_path = resolve_dataset(args.dataset)
        require(args.episode >= 0, "시연 번호는 0 이상이어야 합니다.")
        actions, fps = load_episode_actions(dataset_path, args.episode)
        describe_episode(actions, fps)
        print(f"데이터셋: {dataset_path}")
        if not args.execute:
            print("[안전] 데이터 검사만 수행했습니다. 실제 재생에는 --execute가 필요합니다.")
            return 0

        from xarm.wrapper import XArmAPI

        robot_ip, joint_velocity_deg_s = load_robot_replay_config(args.config)
        arm = XArmAPI(robot_ip)
        require(arm.connected, f"xArm 연결 실패: {robot_ip}")
        check_start_state(arm, actions[0])
        print("[주의] 이제 선택한 성공 시연을 실제 xArm에서 1배속으로 재생합니다.")
        print("       사람·물체·케이블이 작업영역 밖에 있는지 확인하세요.")
        answer = input("재생을 시작하려면 'start'를 입력하세요: ").strip()
        if answer != "start":
            print("[취소] 확인 문자열이 일치하지 않아 재생하지 않았습니다.")
            return 2
        countdown()
        # 3초 대기 중 사람이 자세를 바꾸거나 오류가 새로 생긴 경우를 다시 차단한다.
        check_start_state(arm, actions[0])
        configure_for_replay(arm)
        print("[재생 시작] Ctrl+C 또는 GUI 현재 모드 중지로 즉시 재생을 중단할 수 있습니다.")
        replay(arm, actions, fps, joint_velocity_deg_s)
        safe_stop(arm)
        print("✅ [완료] 선택한 성공 시연의 1배속 재생이 끝났습니다. 현재 자세를 유지한 채 제어를 멈췄습니다.")
        return 0
    except KeyboardInterrupt:
        if arm is not None:
            safe_stop(arm)
        print("\n[중지] 재생 중지 요청을 받아 xArm 상태 4와 그리퍼 정지를 요청했습니다.")
        return 130
    except RuntimeError as exc:
        if arm is not None:
            safe_stop(arm)
        print(f"❌ [실패] {exc}")
        return 1
    finally:
        if arm is not None:
            arm.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
