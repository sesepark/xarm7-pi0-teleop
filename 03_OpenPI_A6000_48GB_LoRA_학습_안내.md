# xArm7 π0 LoRA 학습: A6000 48GB 서버 실행 안내

이 문서는 기존 full fine-tuning 데이터셋과 설정을 보존한 채, A6000 48GB 한 장에서
π0 LoRA fine-tuning을 실행하는 절차다. VS Code Remote-SSH의 서버 터미널 또는 일반
SSH 터미널에서 실행할 수 있다.

## 1. 무엇이 달라졌는가

- 보존: `pi0_xarm7_full`, 원본 session_004/005, curated 데이터셋은 수정하지 않는다.
- 새 설정: `pi0_xarm7_lora_48gb`
- 동일: 손목 RGB, 8차원 state/action, 작업 문장, 정규화 방식
- 변경: base π0 가중치는 동결하고 LoRA adapter만 학습한다.

OpenPI 공식 단일 GPU 요구량은 full tuning이 70GB 초과, LoRA가 22.5GB 초과다.
A6000 48GB는 LoRA 조건을 충족한다.

## 2. 서버 GPU 환경 진입

서버에 접속한 뒤 tmux를 시작한다.

```bash
tmux new -s pi0_xarm
```

이미 세션이 있으면 다음을 쓴다.

```bash
tmux attach -t pi0_xarm
```

GPU를 한 장 요청하고, GPU/Singularity 환경 안에서 CUDA를 불러온다.

```bash
coss_a6gpu -g=1
module load cuda11.8
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
```

`NVIDIA RTX A6000, 49140 MiB`처럼 약 48GB가 표시되면 다음 단계로 진행한다.

## 3. 서버 OpenPI 환경 준비

프로젝트와 `data/curated/xarm7_red_block_black_line_v1` 폴더가 서버의
`~/pi0_sehwan`에 복사되어 있어야 한다. 서버의 rsync 실행 권한 오류가 있으면
VS Code Remote-SSH 파일 탐색기로 프로젝트를 복사하거나, 연구실 서버 관리자에게
`/usr/bin/rsync` 실행 권한을 문의한다.

```bash
cd ~/pi0_sehwan/openpi
GIT_LFS_SKIP_SMUDGE=1 uv sync
GIT_LFS_SKIP_SMUDGE=1 uv pip install -e .
cd ..
```

## 4. 10-step smoke test

먼저 GPU, base checkpoint 다운로드, 데이터 로딩, 정규화, LoRA 학습, 체크포인트 저장을
한 번에 확인한다.

```bash
cd ~/pi0_sehwan
./scripts/run_openpi_lora_train.sh smoke xarm7_lora_smoke
```

정상 종료 후 결과는 다음에 저장된다.

```text
checkpoints/pi0_xarm7_lora_48gb/xarm7_lora_smoke/
```

## 5. 실제 3,000-step LoRA 학습

smoke가 성공했을 때만 실행한다.

```bash
cd ~/pi0_sehwan
./scripts/run_openpi_lora_train.sh train xarm7_red_block_lora_v1
```

같은 실험 이름으로 다시 `train`을 실행하면 기존 결과를 덮어쓴다. 별도 실험은 이름을
바꾼다.

```bash
./scripts/run_openpi_lora_train.sh train xarm7_red_block_lora_v2
```

중단된 학습을 마지막 checkpoint부터 이어갈 때는 `resume`을 쓴다.

```bash
./scripts/run_openpi_lora_train.sh resume xarm7_red_block_lora_v1
```

## 6. 예상 시간과 실제 시간 계산

첫 실행은 base checkpoint 다운로드, JAX 컴파일, 전체 정규화 통계 계산 때문에 오래 걸린다.
A6000 48GB에서 일반적인 예상 범위는 다음과 같다.

- 처음 smoke 10 step: 약 10~30분
- 이후 3,000 step: 약 1.5~4시간

서버 환경·파일시스템·checkpoint 다운로드 속도에 따라 달라진다. 10-step smoke의 대부분은
base checkpoint 다운로드·JAX 컴파일·정규화 통계 계산 시간이며, 실제 3,000 step의 시간은
smoke 시간에 단순 비례하지 않는다. 초기 컴파일/다운로드는 첫 실행에만 발생한다.

## 7. 연결이 끊겼을 때

tmux에서 실행했으므로 SSH가 끊겨도 학습은 계속된다. 다시 접속해 다음을 실행한다.

```bash
tmux attach -t pi0_xarm
```
