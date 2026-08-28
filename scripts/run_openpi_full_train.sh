#!/usr/bin/env bash
# 서버의 tmux + GPU 노드 안에서 실행하는 π0 full fine-tuning 래퍼.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENPI_PYTHON="$PROJECT_ROOT/openpi/.venv/bin/python"
MODE="${1:-train}"
EXP_NAME="${2:-xarm7_red_block_full_v1}"
# ``uv pip install -e .``를 생략한 서버에서도, 이 프로젝트 안에서 수정한
# xArm7 전용 OpenPI 설정을 반드시 사용하도록 경로를 명시한다.
export PYTHONPATH="$PROJECT_ROOT/openpi/src${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -x "$OPENPI_PYTHON" ]]; then
  echo "❌ OpenPI 가상환경이 없습니다: $OPENPI_PYTHON"
  echo "   서버에서 먼저: cd openpi && GIT_LFS_SKIP_SMUDGE=1 uv sync"
  exit 1
fi

if [[ ! -d "$PROJECT_ROOT/data/curated/xarm7_red_block_black_line_v1" ]]; then
  echo "❌ 병합 데이터셋이 없습니다. 먼저 ./run.sh dataset-merge 를 실행하세요."
  exit 1
fi

"$OPENPI_PYTHON" "$PROJECT_ROOT/scripts/check_openpi_full_gpu.py"

case "$MODE" in
  smoke)
    # 데이터 로딩·정규화·GPU 메모리·체크포인트만 빠르게 확인하는 10 step 검사다.
    STEPS=10
    TRAIN_FLAGS=(--overwrite)
    ;;
  train)
    STEPS=3000
    TRAIN_FLAGS=(--overwrite)
    ;;
  resume)
    STEPS=3000
    TRAIN_FLAGS=(--resume)
    ;;
  *)
    echo "사용법: ./scripts/run_openpi_full_train.sh smoke|train|resume [실험이름]"
    exit 2
    ;;
esac

echo "============================================================"
echo "OpenPI π0 xArm7 full fine-tuning 시작"
echo "모드: $MODE / step: $STEPS / 실험: $EXP_NAME"
echo "W&B는 비활성화되어 있으며 체크포인트는 checkpoints에 저장됩니다."
echo "============================================================"
cd "$PROJECT_ROOT"
"$OPENPI_PYTHON" "$PROJECT_ROOT/openpi/scripts/compute_norm_stats.py" --config-name=pi0_xarm7_full
"$OPENPI_PYTHON" "$PROJECT_ROOT/openpi/scripts/train.py" pi0_xarm7_full \
  --exp-name="$EXP_NAME" \
  --num-train-steps="$STEPS" \
  "${TRAIN_FLAGS[@]}"
