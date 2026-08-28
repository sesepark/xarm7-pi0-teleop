#!/usr/bin/env python3
"""한 대의 RealSense RGB 영상을 길이 프레임 JPEG로 stdout에 전달한다.

GUI 서버의 시스템 Python에는 pyrealsense2가 없으므로 이 워커만
uf_lerobot 환경에서 실행한다. stdout은 바이너리 프로토콜 전용이며,
진단 메시지는 stderr로만 보낸다.
"""

from __future__ import annotations

import argparse
import struct
import sys

import cv2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--rotation", type=int, choices=(0, 90, 180, -90), default=0)
    parser.add_argument("--jpeg-quality", type=int, default=80)
    args = parser.parse_args()

    from lerobot.cameras import ColorMode, Cv2Rotation
    from lerobot.cameras.realsense import RealSenseCamera, RealSenseCameraConfig

    rotations = {
        0: Cv2Rotation.NO_ROTATION,
        90: Cv2Rotation.ROTATE_90,
        180: Cv2Rotation.ROTATE_180,
        -90: Cv2Rotation.ROTATE_270,
    }
    camera = RealSenseCamera(
        RealSenseCameraConfig(
            serial_number_or_name=args.serial,
            fps=args.fps,
            width=args.width,
            height=args.height,
            color_mode=ColorMode.RGB,
            use_depth=False,
            rotation=rotations[args.rotation],
        )
    )

    try:
        camera.connect()
        print(f"[카메라] {args.name} ({args.serial}) 연결 완료", file=sys.stderr, flush=True)
        while True:
            frame_rgb = camera.read()
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            ok, encoded = cv2.imencode(
                ".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality]
            )
            if not ok:
                continue
            payload = encoded.tobytes()
            sys.stdout.buffer.write(struct.pack("!I", len(payload)))
            sys.stdout.buffer.write(payload)
            sys.stdout.buffer.flush()
    except (BrokenPipeError, KeyboardInterrupt):
        return 0
    except Exception as exc:
        print(f"[카메라 오류] {args.name}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        try:
            camera.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
