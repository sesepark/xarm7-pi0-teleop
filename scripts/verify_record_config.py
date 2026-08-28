#!/usr/bin/env python3
"""데이터 수집 설정의 파일·카메라·저장 경로 규칙을 읽기 전용으로 검사한다."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


EXPECTED_TASK = "Pick up the red rectangular block and move it to the right side of the black line in the center."


def main() -> int:
    parser = argparse.ArgumentParser(description="xArm7 데이터 수집 설정 검사")
    parser.add_argument("--config", type=Path, required=True, help="기록 설정 YAML 파일")
    parser.add_argument("--project-root", type=Path, required=True, help="pi0_sehwan 경로")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="기존 세션에 이어서 녹화하는 경우: 데이터셋 경로가 이미 존재해야 하며 덮어쓰기가 아니다.",
    )
    args = parser.parse_args()

    failed = False

    def ok(message: str) -> None:
        print(f"✅ [OK] {message}")

    def fail(message: str) -> None:
        nonlocal failed
        failed = True
        print(f"❌ [FAIL] {message}")

    if not args.config.is_file():
        fail(f"기록 설정 파일이 없습니다: {args.config}")
        return 1
    data = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    robot = data.get("robot", {})
    dataset = data.get("dataset", {})
    # cameras는 robot(uf::robot) 설정의 하위 항목입니다. 최상위에서 읽으면
    # 정상 설정을 "카메라 없음"으로 잘못 판정합니다.
    cameras = robot.get("cameras", {}) if isinstance(robot, dict) else {}
    wrist = cameras.get("wrist", {}) if isinstance(cameras, dict) else {}
    front = cameras.get("front", {}) if isinstance(cameras, dict) else {}

    if dataset.get("single_task") == EXPECTED_TASK:
        ok("작업 문장이 빨간 직사각형 물체와 중앙 검은 선의 오른쪽을 정확히 지정합니다.")
    else:
        fail(f"single_task는 다음 문장과 같아야 합니다: {EXPECTED_TASK}")

    configured_root = Path(str(dataset.get("root", ""))).expanduser().resolve()
    template_paths = {
        args.project_root.resolve() / "config/xarm7_gello_wrist_record.yaml",
        args.project_root.resolve() / "config/xarm7_gello_wrist_record_endpoint.yaml",
        args.project_root.resolve() / "config/xarm7_webxr_wrist_record.yaml",
    }
    is_template = args.config.resolve() in template_paths
    root_relative = configured_root.relative_to(args.project_root.resolve() / "data") if configured_root.is_relative_to(args.project_root.resolve() / "data") else None
    valid_session_path = (
        root_relative is not None
        and len(root_relative.parts) == 2
        and len(root_relative.parts[0]) == 10
        and root_relative.parts[0][4] == "-"
        and root_relative.parts[0][7] == "-"
        and root_relative.parts[1].startswith("session_")
        and root_relative.parts[1][8:].isdigit()
    )
    if valid_session_path:
        ok(f"데이터셋 저장 위치: {configured_root}")
    elif is_template:
        ok("기록 원본 설정입니다. ./run.sh record가 날짜별 session_NNN 경로로 자동 교체합니다.")
    else:
        fail("데이터셋은 프로젝트 내부 data/YYYY-MM-DD/session_NNN 경로여야 합니다. " f"현재: {configured_root}")

    if args.resume:
        if (configured_root / "meta" / "info.json").is_file():
            ok("이어서 녹화할 기존 세션을 확인했습니다. 새 에피소드는 뒤에 추가됩니다.")
        else:
            fail(f"이어서 녹화할 세션이 없거나 형식이 아닙니다: {configured_root}")
    elif configured_root.exists() and not is_template:
        fail(
            "첫 기록용 데이터셋 경로가 이미 존재합니다. 기존 데이터를 덮어쓰지 않도록 "
            "새 버전 경로를 정하거나, 세션 이어서 녹화(resume)를 사용해야 합니다."
        )
    elif not is_template:
        ok("첫 기록용 데이터셋 경로가 비어 있어 기존 데이터를 덮어쓰지 않습니다.")

    episode_time = dataset.get("episode_time_s")
    if dataset.get("fps") == 30 and isinstance(episode_time, int) and 5 <= episode_time <= 300 and dataset.get("num_episodes") == 30:
        ok(f"실제 수집 설정: 30 fps, 에피소드당 최대 {episode_time}초, 성공 시연 30개")
    else:
        fail("실제 수집은 fps=30, episode_time_s=5~300 정수, num_episodes=30이어야 합니다.")

    if dataset.get("video") is True and data.get("video_codec") == "h264" and dataset.get("push_to_hub") is False:
        ok("영상은 H.264로 로컬 저장하며 Hugging Face 업로드는 비활성화됐습니다.")
    else:
        fail("첫 수집은 video=true, video_codec=h264, push_to_hub=false여야 합니다.")

    expected_camera = {
        "type": "intelrealsense",
        "serial_number_or_name": "348522072411",
        "width": 640,
        "height": 480,
        "fps": 30,
        "color_mode": "rgb",
        "use_depth": False,
        "rotation": 0,
    }
    wrong_camera = [key for key, value in expected_camera.items() if wrist.get(key) != value]
    if not wrong_camera:
        ok("손목 D435i RGB 카메라 설정이 검증된 프로필과 일치합니다.")
    else:
        fail(f"손목 카메라 설정이 다릅니다: {', '.join(wrong_camera)}")

    expected_front = {**expected_camera, "serial_number_or_name": "348522072232"}
    wrong_front = [key for key, value in expected_front.items() if front.get(key) != value]
    if not wrong_front:
        ok("전면 D435i RGB 카메라 설정이 검증된 프로필과 일치합니다.")
    else:
        fail(f"전면 카메라 설정이 다릅니다: {', '.join(wrong_front)}")

    countdown = data.get("start_countdown_s")
    if countdown == 2.0:
        ok("에피소드별 시작 전 2초 안전 대기 설정 확인")
    elif args.resume and isinstance(countdown, (int, float)) and 0 < float(countdown) <= 3.0:
        # 기존 세션 YAML은 변경된 최대 3초 범위의 값을 갖는다. 이어서
        # 녹화할 때는 세션 생성 당시 설정을 존중한다.
        ok(f"이 세션이 만들어질 때의 시작 대기 {countdown}초를 그대로 사용합니다.")
    else:
        fail("start_countdown_s는 2.0초여야 합니다.")

    if data.get("return_to_start_velocity") == 8.0:
        ok("성공 저장/실패 폐기 판정 후 자동 초기 자세 복귀 속도: 8°/s")
    else:
        fail("return_to_start_velocity는 8.0°/s여야 합니다.")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
