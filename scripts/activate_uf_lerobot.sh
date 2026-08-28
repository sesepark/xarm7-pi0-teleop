#!/usr/bin/env bash
# 이 파일은 "실행"이 아니라 source로 불러야 현재 터미널에 환경이 적용됩니다.
# 사용법: source scripts/activate_uf_lerobot.sh

if ! command -v conda >/dev/null 2>&1; then
  echo "[실패] conda를 찾지 못했습니다. 새 터미널을 열고 다시 시도하세요."
  return 1 2>/dev/null || exit 1
fi

# conda activate는 현재 셸에 적용되어야 하므로 conda의 셸 초기화 코드를 불러옵니다.
eval "$(conda shell.bash hook)"
conda activate uf_lerobot

# 다른 프로젝트가 ~/.local에 설치한 Python 패키지를 우연히 가져오지 않도록 막습니다.
# 이렇게 해야 uf_lerobot 안에 설치된 패키지만 사용하므로 재현성이 좋아집니다.
export PYTHONNOUSERSITE=1

echo "[완료] uf_lerobot 환경을 활성화했습니다."
echo "[다음] python scripts/doctor.py 를 실행해 로봇을 움직이지 않는 진단을 하세요."
