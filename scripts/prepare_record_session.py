#!/usr/bin/env python3
"""날짜/세션 번호가 겹치지 않는 데이터 수집 설정 파일을 만든다.

기존 데이터셋은 절대 수정하거나 삭제하지 않는다. 이 스크립트를 한 번 실행할 때마다
새 세션 번호를 예약해, 중단된 실행과 다음 실행도 서로 충돌하지 않게 한다.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser(description="날짜별 데이터 수집 세션 설정 만들기")
    parser.add_argument("--template", type=Path, required=True, help="기록 설정 원본 YAML")
    parser.add_argument("--project-root", type=Path, required=True, help="pi0_sehwan 경로")
    parser.add_argument("--episode-time", type=int, help="에피소드 녹화 제한 시간(초)")
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not args.template.is_file():
        raise SystemExit(f"기록 설정 원본이 없습니다: {args.template}")
    data = yaml.safe_load(args.template.read_text(encoding="utf-8")) or {}

    date_text = datetime.now().astimezone().strftime("%Y-%m-%d")
    data_date_dir = project_root / "data" / date_text
    runtime_date_dir = project_root / "runtime" / "record_sessions" / date_text
    pattern = re.compile(r"session_(\d{3})$")
    used_numbers: set[int] = set()
    for parent in (data_date_dir, runtime_date_dir):
        if parent.is_dir():
            for child in parent.iterdir():
                match = pattern.fullmatch(child.name)
                if match:
                    used_numbers.add(int(match.group(1)))
                # runtime 설정 파일 이름은 session_001.yaml 형태다.
                if child.is_file() and child.suffix == ".yaml":
                    match = pattern.fullmatch(child.stem)
                    if match:
                        used_numbers.add(int(match.group(1)))

    session_number = 1
    while session_number in used_numbers:
        session_number += 1
    session_name = f"session_{session_number:03d}"
    root = data_date_dir / session_name
    runtime_config = runtime_date_dir / f"{session_name}.yaml"
    if root.exists() or runtime_config.exists():
        raise SystemExit("새 세션 경로 충돌을 감지했습니다. 다시 실행하세요.")

    dataset = data.setdefault("dataset", {})
    if args.episode_time is not None:
        if not 5 <= args.episode_time <= 300:
            raise SystemExit("에피소드 시간은 5~300초 사이여야 합니다.")
        dataset["episode_time_s"] = args.episode_time
    dataset["root"] = str(root)
    # 서버/허브에 올릴 때도 작업 내용을 혼동하지 않도록 템플릿의 repo_id에
    # 날짜/세션을 붙인다. endpoint 템플릿이면 repo_id에 endpoint가 남아
    # 세션 종류를 구분할 수 있다. 실제 로컬 저장 경로는 위의
    # data/YYYY-MM-DD/session_NNN 입니다.
    template_repo_id = str(
        dataset.get("repo_id")
        or "pi0_sehwan/xarm7_gello_wrist_red_block_black_line_right_v1"
    )
    dataset["repo_id"] = (
        f"{template_repo_id}_{date_text.replace('-', '_')}_{session_name}"
    )
    data_date_dir.mkdir(parents=True, exist_ok=True)
    runtime_date_dir.mkdir(parents=True, exist_ok=True)
    runtime_config.write_text(
        "# run.sh가 자동 생성한 날짜별 데이터 수집 세션 설정입니다.\n"
        "# 기존 세션과 데이터는 덮어쓰지 않습니다.\n\n"
        + yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    # run.sh가 안전하게 받을 수 있도록 경로만 한 줄로 출력한다.
    print(runtime_config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
