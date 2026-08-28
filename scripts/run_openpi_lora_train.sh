#!/usr/bin/env bash
# A6000 48GB 등 단일 GPU에서 실행하는 xArm7 π0 LoRA 학습 래퍼.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENPI_PYTHON="$PROJECT_ROOT/openpi/.venv/bin/python"
MODE="${1:-train}"
EXP_NAME="${2:-xarm7_red_block_lora_v1}"

# 서버에서 editable install을 아직 하지 않았어도 현재 프로젝트의 xArm 설정을 쓴다.
export PYTHONPATH="$PROJECT_ROOT/openpi/src${PYTHONPATH:+:$PYTHONPATH}"
# OpenPI 공식 학습 안내의 권장값이다. 이미 사용자가 지정했다면 그 값을 존중한다.
export XLA_PYTHON_CLIENT_MEM_FRACTION="${XLA_PYTHON_CLIENT_MEM_FRACTION:-0.9}"

if [[ ! -x "$OPENPI_PYTHON" ]]; then
  echo "❌ OpenPI 가상환경이 없습니다: $OPENPI_PYTHON"
  echo "   서버에서 먼저: cd openpi && GIT_LFS_SKIP_SMUDGE=1 uv sync"
  exit 1
fi

if [[ ! -d "$PROJECT_ROOT/data/curated/xarm7_red_block_black_line_v1" ]]; then
  echo "❌ 병합 데이터셋이 없습니다. data/curated 폴더를 서버로 복사했는지 확인하세요."
  exit 1
fi

case "$MODE" in
  smoke)
    # smoke는 학습 품질 측정이 아니라 GPU/데이터/forward-backward/저장이
    # 실제로 되는지만 빠르게 확인하는 절차다. 마지막 step은 train.py가
    # 항상 저장하므로 10 step도 checkpoint 저장까지 검증한다.
    STEPS=10
    TRAIN_FLAGS=(--overwrite --log-interval=1 --save-interval=10)
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
    echo "사용법: ./scripts/run_openpi_lora_train.sh smoke|train|resume [실험이름]"
    exit 2
    ;;
esac

"$OPENPI_PYTHON" "$PROJECT_ROOT/scripts/check_openpi_lora_gpu.py"

echo "============================================================"
echo "OpenPI π0 xArm7 LoRA fine-tuning 시작"
echo "모드: $MODE / step: $STEPS / 실험: $EXP_NAME"
echo "배치: 8 / GPU 메모리 예약 비율: $XLA_PYTHON_CLIENT_MEM_FRACTION"
echo "W&B는 비활성화되어 있으며 체크포인트는 checkpoints에 저장됩니다."
echo "============================================================"

cd "$PROJECT_ROOT"
"$OPENPI_PYTHON" "$PROJECT_ROOT/openpi/scripts/compute_norm_stats.py" --config-name=pi0_xarm7_lora_48gb
"$OPENPI_PYTHON" "$PROJECT_ROOT/openpi/scripts/train.py" pi0_xarm7_lora_48gb \
  --exp-name="$EXP_NAME" \
  --num-train-steps="$STEPS" \
  "${TRAIN_FLAGS[@]}"
