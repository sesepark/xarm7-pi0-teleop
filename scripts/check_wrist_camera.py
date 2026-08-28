#!/usr/bin/env python3
"""손목 RealSense D435i의 LeRobot 호환성을 확인하고 필요하면 화면을 보여준다.

이 스크립트는 카메라 USB만 사용한다. xArm, GELLO에 연결하거나 로봇 모션 명령을
보내지 않는다. 따라서 텔레옵과 분리하여 카메라 문제만 안전하게 찾을 수 있다.

사용법:
    ./verify.sh camera          # 30프레임을 읽어 실제 동작 여부 확인
    ./run.sh camera-preview     # 실시간 화면 확인 (q 또는 ESC로 종료)
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2
import yaml


def load_config(path: Path, camera_name: str | None = None) -> dict:
    """초보자가 설정 실수를 바로 알 수 있도록 필수 항목을 검사한다."""
    if not path.is_file():
        raise ValueError(f"카메라 설정 파일이 없습니다: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    camera = data.get("camera")
    if camera is None and isinstance(data.get("cameras"), dict):
        if not camera_name:
            raise ValueError("여러 카메라 설정에서는 --camera 이름이 필요합니다.")
        selected = data["cameras"].get(camera_name)
        if isinstance(selected, dict):
            camera = {**selected, "name": camera_name}
    if not isinstance(camera, dict):
        raise ValueError("camera: 항목을 읽지 못했습니다.")

    required = ("name", "serial_number", "width", "height", "fps", "color_mode")
    missing = [key for key in required if key not in camera]
    if missing:
        raise ValueError(f"카메라 설정의 필수 항목이 없습니다: {', '.join(missing)}")
    if camera.get("type") != "intelrealsense":
        raise ValueError("현재는 type: intelrealsense 만 지원합니다.")
    if camera["color_mode"] != "rgb":
        raise ValueError("pi0 첫 시연 설정은 color_mode: rgb 여야 합니다.")
    return camera


def make_camera(camera_cfg: dict):
    """향후 데이터 수집에도 쓸 LeRobot RealSense 클래스로 실제 연결한다."""
    from lerobot.cameras import ColorMode, Cv2Rotation
    from lerobot.cameras.realsense import RealSenseCamera, RealSenseCameraConfig

    rotations = {
        0: Cv2Rotation.NO_ROTATION,
        90: Cv2Rotation.ROTATE_90,
        180: Cv2Rotation.ROTATE_180,
        -90: Cv2Rotation.ROTATE_270,
    }
    rotation_degrees = camera_cfg.get("rotation_degrees", 0)
    if rotation_degrees not in rotations:
        raise ValueError("rotation_degrees는 0, 90, 180, -90 중 하나여야 합니다.")

    config = RealSenseCameraConfig(
        serial_number_or_name=str(camera_cfg["serial_number"]),
        fps=int(camera_cfg["fps"]),
        width=int(camera_cfg["width"]),
        height=int(camera_cfg["height"]),
        color_mode=ColorMode.RGB,
        use_depth=bool(camera_cfg.get("use_depth", False)),
        rotation=rotations[rotation_degrees],
    )
    return RealSenseCamera(config)


def print_header(camera_cfg: dict, preview: bool) -> None:
    print("=" * 72)
    print("손목 RealSense D435i 검사 (카메라만 사용, 로봇은 움직이지 않음)")
    print(f"카메라 이름: {camera_cfg['name']}")
    print(f"시리얼 번호: {camera_cfg['serial_number']}")
    print(f"요청 프로필: {camera_cfg['width']}x{camera_cfg['height']} / {camera_cfg['fps']} fps / RGB")
    print("모드: 화면 미리보기" if preview else "모드: 프레임 읽기 검증")
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description="손목 RealSense D435i 검사")
    parser.add_argument("--config", type=Path, required=True, help="카메라 설정 YAML 경로")
    parser.add_argument("--camera", help="cameras YAML에서 검사할 카메라 이름")
    parser.add_argument("--preview", action="store_true", help="실시간 RGB 화면을 표시합니다")
    parser.add_argument("--frames", type=int, default=30, help="검증 시 읽을 프레임 수")
    args = parser.parse_args()

    try:
        camera_cfg = load_config(args.config, args.camera)
        print_header(camera_cfg, args.preview)
        camera = make_camera(camera_cfg)
        camera.connect()
    except Exception as exc:
        print(f"❌ 카메라 연결 실패: {type(exc).__name__}: {exc}")
        print("   USB 케이블/전원, 시리얼 번호, 다른 프로그램의 카메라 사용 여부를 확인하세요.")
        return 1

    try:
        if args.preview:
            print("✅ 카메라 연결 성공. 화면 창에서 손목 장착 방향과 시야를 확인하세요.")
            print("   q 또는 ESC: 종료 / 이 창을 닫아도 종료됩니다.")
            while True:
                # LeRobot은 RGB 배열을 반환한다. OpenCV 화면 표시는 BGR 순서가 필요하다.
                frame_rgb = camera.read()
                frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                cv2.putText(
                    frame_bgr,
                    "wrist / RGB / q or ESC: exit",
                    (12, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )
                cv2.imshow("pi0 wrist camera preview", frame_bgr)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27) or cv2.getWindowProperty("pi0 wrist camera preview", cv2.WND_PROP_VISIBLE) < 1:
                    break
            print("[종료] 카메라 미리보기를 종료했습니다.")
            return 0

        frame_count = max(1, args.frames)
        start = time.monotonic()
        last_frame = None
        for _ in range(frame_count):
            last_frame = camera.read()
        elapsed = time.monotonic() - start
        if last_frame is None:
            raise RuntimeError("프레임을 받지 못했습니다.")
        expected_shape = (int(camera_cfg["height"]), int(camera_cfg["width"]), 3)
        actual_shape = tuple(last_frame.shape)
        if actual_shape != expected_shape:
            raise RuntimeError(f"프레임 크기가 다릅니다. 기대={expected_shape}, 실제={actual_shape}")
        measured_fps = frame_count / elapsed if elapsed > 0 else 0.0
        print("✅ LeRobot RealSense 연결과 RGB 프레임 읽기를 확인했습니다.")
        print(f"   실제 프레임 크기: {actual_shape[1]}x{actual_shape[0]} RGB")
        print(f"   {frame_count}프레임 읽기 시간: {elapsed:.2f}초 (측정 {measured_fps:.1f} fps)")
        print("   참고: 이 측정값은 USB/PC 상태를 포함한 간단한 건강 검사이며, 녹화 성능의 보증값은 아닙니다.")
        return 0
    except Exception as exc:
        print(f"❌ 카메라 프레임 읽기 실패: {type(exc).__name__}: {exc}")
        return 1
    finally:
        camera.disconnect()
        if args.preview:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    raise SystemExit(main())
