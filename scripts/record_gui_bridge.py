#!/usr/bin/env python3
"""녹화가 이미 읽은 두 카메라 프레임과 상태를 로컬 GUI에 공유한다."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot_robot_ufactory.scripts import uf_lerobot_record

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / "runtime" / "record_gui"
STATUS_PATH = RUNTIME_DIR / "status.json"
CONTROL_PATH = RUNTIME_DIR / "control.json"
STATE: dict[str, object] = {
    "phase": "starting", "episode_started_at": None, "episode_time_s": None,
    "saved_episodes": 0, "discarded_episodes": 0, "frames": {},
}
LAST_FRAME_WRITE = 0.0
SAVING_EPISODE = False


def atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def publish_state(**updates: object) -> None:
    STATE.update(updates)
    STATE["updated_at"] = time.time()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write(STATUS_PATH, json.dumps(STATE, ensure_ascii=False).encode("utf-8"))


def publish_frames(observation: dict) -> None:
    global LAST_FRAME_WRITE
    now = time.monotonic()
    if now - LAST_FRAME_WRITE < 0.1:  # UI 복사본은 최대 10fps
        return
    written: dict[str, float] = dict(STATE.get("frames", {}))
    for name in ("wrist", "front"):
        frame = next(
            (value for key, value in observation.items() if key == name or key.endswith(f".{name}")),
            None,
        )
        if not isinstance(frame, np.ndarray) or frame.ndim != 3:
            continue
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        ok, encoded = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            atomic_write(RUNTIME_DIR / f"{name}.jpg", encoded.tobytes())
            written[name] = time.time()
    LAST_FRAME_WRITE = now
    if written:
        publish_state(frames=written)


ORIGINAL_RECORD_LOOP = uf_lerobot_record.record_loop
ORIGINAL_INIT_KEYBOARD_LISTENER = uf_lerobot_record.init_keyboard_listener


def bridged_init_keyboard_listener(*args, **kwargs):
    """GUI 파일 명령도 LeRobot의 기존 키 처리 함수로 전달한다."""
    listener, events = ORIGINAL_INIT_KEYBOARD_LISTENER(*args, **kwargs)
    on_press = kwargs.get("on_press")
    on_release = kwargs.get("on_release")
    if on_press is None and len(args) >= 2:
        on_press = args[1]
    if on_release is None and len(args) >= 3:
        on_release = args[2]

    def consume_controls():
        from pynput.keyboard import Key

        key_map = {"space": Key.space, "right": Key.right, "left": Key.left, "esc": Key.esc}
        while True:
            try:
                payload = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
                CONTROL_PATH.unlink(missing_ok=True)
                requested_key = key_map.get(str(payload.get("key", "")))
                if requested_key is None or on_press is None:
                    continue
                on_press(requested_key)
                # Space는 LeRobot의 대기 루프가 감지할 수 있도록 짧게 유지한다.
                if on_release is not None:
                    time.sleep(0.12)
                    on_release(requested_key)
            except FileNotFoundError:
                time.sleep(0.05)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                print(f"[GUI 입력] 명령 처리 실패: {exc}")
                CONTROL_PATH.unlink(missing_ok=True)
                time.sleep(0.05)

    threading.Thread(target=consume_controls, daemon=True, name="gui-record-controls").start()
    return listener, events


def bridged_record_loop(*args, **kwargs):
    dataset = kwargs.get("dataset")
    duration = kwargs.get("control_time_s")
    previous_callback = kwargs.get("frame_callback")
    publish_state(
        phase="recording",
        episode_started_at=time.time(),
        episode_time_s=duration,
        saved_episodes=int(dataset.num_episodes) if dataset is not None else STATE.get("saved_episodes", 0),
    )

    def frame_callback(frame):
        publish_frames(frame)
        return previous_callback(frame) if previous_callback is not None else frame

    kwargs["frame_callback"] = frame_callback
    try:
        return ORIGINAL_RECORD_LOOP(*args, **kwargs)
    finally:
        publish_state(phase="decision", episode_started_at=None)


ORIGINAL_SAVE_EPISODE = LeRobotDataset.save_episode
ORIGINAL_CLEAR_EPISODE = LeRobotDataset.clear_episode_buffer


def bridged_save_episode(self, *args, **kwargs):
    global SAVING_EPISODE
    SAVING_EPISODE = True
    try:
        result = ORIGINAL_SAVE_EPISODE(self, *args, **kwargs)
    finally:
        SAVING_EPISODE = False
    publish_state(phase="ready", saved_episodes=int(self.num_episodes), episode_started_at=None)
    return result


def bridged_clear_episode(self, *args, **kwargs):
    result = ORIGINAL_CLEAR_EPISODE(self, *args, **kwargs)
    if not SAVING_EPISODE:
        publish_state(
            phase="ready", discarded_episodes=int(STATE.get("discarded_episodes", 0)) + 1,
            episode_started_at=None,
        )
    return result


def main() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    CONTROL_PATH.unlink(missing_ok=True)
    for path in RUNTIME_DIR.glob("*.jpg"):
        path.unlink(missing_ok=True)
    publish_state(phase="starting")
    uf_lerobot_record.record_loop = bridged_record_loop
    uf_lerobot_record.init_keyboard_listener = bridged_init_keyboard_listener
    LeRobotDataset.save_episode = bridged_save_episode
    LeRobotDataset.clear_episode_buffer = bridged_clear_episode
    try:
        uf_lerobot_record.main()
    finally:
        publish_state(phase="stopped", episode_started_at=None)


if __name__ == "__main__":
    main()
