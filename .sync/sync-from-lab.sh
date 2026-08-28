#!/bin/zsh
# 연구실 PC(~/pi0_sehwan)의 변경을 이 저장소로 끌어와 커밋·푸시한다.
# 자동 스냅샷 커밋은 중립 신원으로 남긴다. 연구실 PC는 여러 사람이 같은 계정으로
# 쓰기 때문에, 남의 수정까지 내 이름으로 커밋되면 안 되기 때문이다.
set -euo pipefail

REPO="/Users/sehwan/Projects/xarm7-pi0-teleop"
REMOTE="xarm-lab"
SRC="pi0_sehwan/"
BOT_NAME="pi0-lab-sync"
BOT_EMAIL="pi0-lab-sync@users.noreply.github.com"

cd "$REPO"

# 연구실 PC가 안 켜져 있거나 Tailscale이 끊겼으면 조용히 종료한다.
if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "$REMOTE" true 2>/dev/null; then
  echo "$(date '+%F %T') 연구실 PC에 연결할 수 없음 — 건너뜀"
  exit 0
fi

git pull --ff-only -q origin main 2>/dev/null || true

rsync -a --delete \
  --exclude='.git/' --exclude='.sync/' \
  --exclude='README.md' --exclude='.gitignore' \
  --exclude='openpi/' --exclude='lerobot_robot_ufactory/' \
  --exclude='data/' --exclude='checkpoints/' --exclude='*.deb' \
  --exclude='runtime/' --exclude='logs/' --exclude='log/' \
  --exclude='build/' --exclude='install/' \
  --exclude='__pycache__/' --exclude='*.pyc' \
  --exclude='.ruff_cache/' --exclude='.pytest_cache/' --exclude='.serena/' \
  --exclude='*.key' --exclude='*.csr' --exclude='*.pem' \
  --exclude='package.json' --exclude='package-lock.json' \
  --exclude='test.py' --exclude='test2.py' \
  "$REMOTE:$SRC" "$REPO/"

git add -A
if git diff --cached --quiet; then
  echo "$(date '+%F %T') 변경 없음"
  exit 0
fi

SUMMARY=$(git diff --cached --shortstat)
git -c user.name="$BOT_NAME" -c user.email="$BOT_EMAIL" \
    commit -q -m "chore(sync): 연구실 PC 스냅샷 $(date '+%Y-%m-%d')" \
           -m "$SUMMARY" \
           -m "자동 동기화 커밋입니다. 연구실 PC의 ~/pi0_sehwan 상태를 그대로 반영하며,
누가 수정했는지 구분하지 않으므로 중립 신원으로 남깁니다."
git push -q origin main
echo "$(date '+%F %T') 동기화 완료 — $SUMMARY"
