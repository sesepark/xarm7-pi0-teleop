#!/usr/bin/env python3
"""xArm7 원본 LeRobot v3 세션들을 최신 OpenPI용 LeRobot 데이터셋으로 병합한다.

원본 세션은 절대 수정하지 않는다. 현재 수집기(LeRobot 0.4)가 만든 v3 형식은
최신 OpenPI가 사용하는 LeRobot 형식과 메타데이터 구조가 달라, 단순 파일 복사가
아닌 안전한 재기록이 필요하다. 이 도구는 action/state/작업 문장/손목 RGB 프레임을
에피소드 단위로 읽어 새로운 최신 형식 데이터셋으로 기록한다.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq
from lerobot.common.datasets.lerobot_dataset import LeRobotDataset


TASK = "Pick up the red rectangular block and move it to the right side of the black line in the center."
FEATURES = {
    "observation.state": {"dtype": "float32", "shape": (8,), "names": None},
    "action": {"dtype": "float32", "shape": (8,), "names": None},
    "observation.images.wrist": {
        "dtype": "video",
        "shape": (480, 640, 3),
        "names": ["height", "width", "channels"],
    },
}


def source_video_path(root: Path) -> Path:
    videos = sorted(root.glob("videos/observation.images.wrist/**/*.mp4"))
    if len(videos) != 1:
        raise RuntimeError(f"손목 영상은 정확히 한 파일이어야 합니다: {root} (발견 {len(videos)}개)")
    return videos[0]


def episode_to_joint_schema(episode_rows: list[dict], source: Path) -> list[tuple[np.ndarray, np.ndarray]]:
    """세션 형식별로 (state 8, action 8) 프레임 목록을 만든다.

    * 관절 추적 세션: state/action 모두 8차원 → 그대로 사용.
    * endpoint 추적 세션: state 14차원([J1..J7, pose 6, gripper]), action 7차원(pose).
      pi0 학습 스키마(절대 관절 8차원)를 유지하기 위해 state에서 관절+그리퍼를
      추출하고, action은 "다음 프레임에 실제로 도달한 관절값"으로 재구성한다.
      (마지막 프레임의 action은 자기 자신의 관절값이다.)
    """
    states = [row["observation.state"] for row in episode_rows]
    actions = [row["action"] for row in episode_rows]
    n_state, n_action = len(states[0]), len(actions[0])
    if n_state == 8 and n_action == 8:
        return [
            (np.asarray(s, dtype=np.float32), np.asarray(a, dtype=np.float32))
            for s, a in zip(states, actions)
        ]
    if n_state == 14 and n_action == 7:
        joints = [
            np.asarray([s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[13]], dtype=np.float32)
            for s in states
        ]
        return [
            (joints[t], joints[t + 1] if t + 1 < len(joints) else joints[t])
            for t in range(len(joints))
        ]
    raise RuntimeError(
        f"지원하지 않는 세션 형식입니다 (state {n_state}차원, action {n_action}차원): {source}"
    )


def load_source(root: Path):
    info_path = root / "meta" / "info.json"
    data_path = root / "data" / "chunk-000" / "file-000.parquet"
    if not info_path.is_file() or not data_path.is_file():
        raise RuntimeError(f"정상적인 원본 세션이 아닙니다: {root}")
    info = json.loads(info_path.read_text(encoding="utf-8"))
    if info.get("fps") != 30:
        raise RuntimeError(f"원본 fps는 30이어야 합니다: {root}")
    frame_table = pq.read_table(data_path, columns=["action", "observation.state", "episode_index"])
    rows = frame_table.to_pylist()
    if len(rows) != info.get("total_frames"):
        raise RuntimeError(f"프레임 수가 meta와 다릅니다: {root}")
    return info, rows, source_video_path(root)


def main() -> int:
    parser = argparse.ArgumentParser(description="xArm7 세션을 OpenPI용 최신 LeRobot 데이터셋으로 병합")
    parser.add_argument("--sources", type=Path, nargs="+", required=True, help="원본 session 폴더들")
    parser.add_argument("--output", type=Path, required=True, help="새 curated 데이터셋 폴더")
    parser.add_argument("--repo-id", default="pi0_sehwan/xarm7_red_block_black_line_v1", help="학습용 LeRobot repo id")
    args = parser.parse_args()

    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"[중단] 출력 폴더가 이미 존재합니다. 원본/결과를 덮어쓰지 않습니다: {output}")
    if not args.sources:
        raise SystemExit("[중단] 원본 세션이 없습니다.")

    for source in args.sources:
        if not source.is_dir():
            raise SystemExit(f"[중단] 원본 세션 폴더가 없습니다: {source}")

    print("=" * 72)
    print("xArm7 OpenPI 학습용 데이터셋 병합")
    print("원본 세션은 읽기만 하며 수정·삭제하지 않습니다.")
    print("=" * 72)
    dataset = LeRobotDataset.create(
        repo_id=args.repo_id,
        root=output,
        fps=30,
        robot_type="xArm7 + GELLO",
        features=FEATURES,
        use_videos=True,
        image_writer_threads=4,
    )
    manifest: dict[str, object] = {"repo_id": args.repo_id, "task": TASK, "sources": [], "episodes": []}

    try:
        output_episode = 0
        for source in args.sources:
            source = source.resolve()
            info, rows, video_path = load_source(source)
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                raise RuntimeError(f"원본 영상을 열 수 없습니다: {video_path}")
            session_type = "endpoint" if len(rows[0]["observation.state"]) == 14 else "joint"
            print(
                f"[원본] {source.name}: 성공 에피소드 {info['total_episodes']}개, "
                f"프레임 {len(rows)}개 ({session_type} 추적 세션)"
            )
            if session_type == "endpoint":
                print("  → endpoint 세션: action을 다음 프레임의 실제 관절값으로 재구성해 8차원 스키마로 변환합니다.")
            offset = 0
            try:
                for source_episode in range(int(info["total_episodes"])):
                    episode_rows: list[dict] = []
                    while offset < len(rows) and int(rows[offset]["episode_index"]) == source_episode:
                        episode_rows.append(rows[offset])
                        offset += 1
                    if not episode_rows:
                        raise RuntimeError(f"원본 에피소드 {source_episode} 프레임을 찾지 못했습니다: {source}")

                    joint_frames = episode_to_joint_schema(episode_rows, source)
                    for frame_number, (state8, action8) in enumerate(joint_frames):
                        ok, bgr = cap.read()
                        if not ok:
                            raise RuntimeError(f"원본 영상 프레임 부족: {source}, episode {source_episode}, frame {frame_number}")
                        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                        if rgb.shape != (480, 640, 3):
                            raise RuntimeError(f"예상과 다른 영상 크기 {rgb.shape}: {source}")
                        dataset.add_frame(
                            {
                                "observation.state": state8,
                                "action": action8,
                                "observation.images.wrist": rgb,
                                "task": TASK,
                            }
                        )
                    dataset.save_episode()
                    manifest["episodes"].append(
                        {
                            "output_episode": output_episode,
                            "source_session": source.name,
                            "source_episode": source_episode,
                            "frames": len(episode_rows),
                        }
                    )
                    output_episode += 1
                    print(f"  ✅ {source.name} episode {source_episode} → curated episode {output_episode - 1}")
            finally:
                cap.release()
            if offset != len(rows):
                raise RuntimeError(f"원본 프레임 경계 해석 실패: {source}")
            manifest["sources"].append({"path": str(source), "tracking": session_type})
    except Exception:
        # 새 결과물만 삭제한다. 원본 source에는 절대 손대지 않는다.
        if output.exists():
            shutil.rmtree(output)
        raise

    manifest["total_episodes"] = dataset.meta.total_episodes
    manifest["total_frames"] = dataset.meta.total_frames
    (output / "pi0_sehwan_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("=" * 72)
    print(f"✅ 병합 완료: 성공 에피소드 {dataset.meta.total_episodes}개, 프레임 {dataset.meta.total_frames}개")
    print(f"결과: {output}")
    print("다음: OpenPI 정규화 통계 계산 후 full fine-tuning smoke test를 실행하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
