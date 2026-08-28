#!/usr/bin/env bash
# 재부팅 후 가장 먼저 실행하는 읽기 전용 점검 명령입니다.
# 사용법: bash scripts/run_doctor.sh
set -euo pipefail

eval "$(conda shell.bash hook)"
conda activate uf_lerobot
export PYTHONNOUSERSITE=1
python scripts/doctor.py "$@"
