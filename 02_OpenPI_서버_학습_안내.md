# xArm7 데이터로 OpenPI π0 full fine-tuning 하기

이 문서는 VS Code 없이 SSH 터미널과 tmux만으로 학습하는 절차입니다.
학습 중에는 로봇 PC에서 텔레옵이나 녹화를 실행하지 않습니다.

## 0. 준비된 데이터와 학습 방식

- 원본: `data/2026-07-30/session_004`, `session_005`
- 학습용 결과: `data/curated/xarm7_red_block_black_line_v1`
- 작업: 빨간 직사각형 물체를 집어 중앙 검은 선 오른쪽으로 옮기기
- 입력: 손목 RealSense RGB 1대 + xArm 관절 7개 + 그리퍼 1개
- 출력: 절대 xArm 관절 목표 7개 + 절대 그리퍼 값 1개
- 학습: π0 base checkpoint를 이용한 **full fine-tuning**

중요: OpenPI 공식 요구량상 full fine-tuning은 단일 GPU VRAM 70GB 초과가 필요합니다.
서버에서 80GB A100/H100 등 조건을 만족하는 GPU를 받아야 합니다. 이 프로젝트의
학습 명령은 조건이 부족하면 학습을 시작하지 않고 중단합니다.

## 1. 로봇 PC에서 병합 데이터셋 만들기

프로젝트 최상위 폴더에서 실행합니다.

```bash
cd ~/pi0_sehwan
./run.sh dataset-merge
```

이 명령은 원본 session_004와 session_005를 절대 수정하지 않고, 최신 OpenPI 호환
LeRobot 데이터셋을 아래에 새로 만듭니다.

```text
data/curated/xarm7_red_block_black_line_v1/
```

## 2. 서버 접속과 tmux

서버 주소와 계정은 연구실에서 받은 값을 사용합니다. 비밀번호를 명령어에 쓰지 말고,
SSH가 물어볼 때 직접 입력합니다.

```bash
ssh <서버계정>@<서버주소>
tmux new -s pi0_xarm
```

tmux 재접속 명령은 다음입니다.

```bash
tmux attach -t pi0_xarm
```

## 3. GPU 노드 할당과 확인

연구실 GPU 할당 명령을 실행하고 CUDA 모듈을 불러옵니다.

```bash
coss_a6gpu -g=1
module load cuda11.8
nvidia-smi
```

`nvidia-smi`에서 한 GPU의 메모리가 70GB를 넘어야 full fine-tuning을 진행합니다.
부족하면 여기서 멈추고 더 큰 GPU를 요청하세요.

## 4. 프로젝트와 데이터 전송

로봇 PC의 새 터미널에서 실행합니다. `<서버계정>`, `<서버주소>`, `<서버경로>`만
본인 환경에 맞게 바꿉니다.

```bash
rsync -avP --exclude='.venv' --exclude='__pycache__' \
  ~/pi0_sehwan/ <서버계정>@<서버주소>:<서버경로>/pi0_sehwan/
```

재전송할 때도 같은 명령을 쓰면 변경분만 복사합니다.

## 5. 서버 OpenPI 환경 설치

GPU 노드 안의 프로젝트 폴더에서 실행합니다.

```bash
cd <서버경로>/pi0_sehwan/openpi
GIT_LFS_SKIP_SMUDGE=1 uv sync
GIT_LFS_SKIP_SMUDGE=1 uv pip install -e .
cd ..
```

## 6. 10 step smoke test

먼저 데이터 로딩, 정규화 통계, GPU 메모리, 체크포인트 저장이 모두 되는지만 확인합니다.

```bash
cd <서버경로>/pi0_sehwan
./scripts/run_openpi_full_train.sh smoke xarm7_full_smoke
```

정상이라면 `checkpoints/pi0_xarm7_full/xarm7_full_smoke/`에 체크포인트가 생깁니다.

## 7. 임시 π0 full fine-tuning

smoke test가 끝난 뒤 실제 임시 학습을 실행합니다.

```bash
cd <서버경로>/pi0_sehwan
./scripts/run_openpi_full_train.sh train xarm7_red_block_full_v1
```

이 설정은 34개 성공 시연으로 3,000 step만 학습합니다. 이는 같은 배치·같은 시점에서
동작하는지 보는 임시 시연용이며, 물체 위치 변화에 대한 일반화 성능을 보장하지 않습니다.

## 8. 연결이 끊겼을 때

SSH가 끊겨도 tmux 안의 학습은 계속됩니다. 다시 접속한 뒤 다음을 실행합니다.

```bash
tmux attach -t pi0_xarm
```

학습 프로세스 자체가 중단됐고 마지막 체크포인트부터 이어서 하려면 다음을 실행합니다.
`resume`은 기존 실험 폴더를 덮어쓰지 않습니다.

```bash
cd ~/pi0_sehwan
./scripts/run_openpi_full_train.sh resume xarm7_red_block_full_v1
```

반대로 `train`은 같은 실험 이름의 기존 체크포인트를 새로 시작하기 위해 덮어씁니다.
실험 결과를 보존하려면 이름을 바꿔 실행하세요.

학습 종료 뒤에는 체크포인트와 학습 로그를 먼저 확인한 뒤, 별도 추론/로봇 제어 단계를
구현합니다. 학습 체크포인트를 바로 xArm에 연결해서 움직이지 않습니다.
