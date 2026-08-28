# 팀원 COSS GPU 방식으로 OpenPI π0 full fine-tuning 실행하기

이 문서는 팀원이 사용하는 `coss_agpu -g=1 -i=<Docker 이미지>` 방식에 맞춘 OpenPI π0
**full fine-tuning** 절차다. VS Code는 필요 없으며 SSH 터미널과 tmux만 사용한다.

> 중요: π0 full fine-tuning은 단일 GPU VRAM이 70GB를 초과해야 한다. A6000 48GB는
> full fine-tuning 대상이 아니며 LoRA를 사용해야 한다. 80GB A100/H100을 받지 못하면
> 아래 full 학습 명령은 시작하지 않는다.

## 1. 로봇 PC에서 서버로 프로젝트 보내기

로컬 OpenPI 가상환경(`openpi/.venv`)은 약 9GB이므로 보내지 않는다. 서버 컨테이너 안에서
새로 만든다. 이전에 서버의 `rsync` 실행 권한 오류가 있었으므로, 아래처럼 `tar + scp`를
쓴다. `<계정>`, `<서버주소>`, `<서버홈>`만 실제 값으로 바꾼다.

```bash
cd ~/pi0_sehwan
tar -czf /tmp/pi0_sehwan_for_server.tar.gz \
  --exclude='./openpi/.venv' \
  --exclude='./**/__pycache__' \
  --exclude='./logs' \
  --exclude='./checkpoints' \
  .

scp /tmp/pi0_sehwan_for_server.tar.gz \
  <계정>@<서버주소>:<서버홈>/
```

서버에 접속한 뒤 압축을 푼다.

```bash
ssh <계정>@<서버주소>
mkdir -p <서버홈>/pi0_sehwan
tar -xzf <서버홈>/pi0_sehwan_for_server.tar.gz -C <서버홈>/pi0_sehwan
```

## 2. tmux와 팀원 방식 GPU 컨테이너 진입

```bash
tmux new -s pi0_full
cd <서버홈>/pi0_sehwan
coss_agpu -g=1 -i=pytorch/pytorch:2.1.0-cuda12.1-cudnn8-runtime
```

컨테이너 안에서도 프로젝트가 보이는지 확인한다.

```bash
cd <서버홈>/pi0_sehwan
pwd
ls scripts/run_openpi_full_train.sh
nvidia-smi
```

`nvidia-smi`의 GPU 한 장이 **80GB A100/H100급**이어야 다음으로 진행한다. 48GB라면
`exit`로 컨테이너를 나와 LoRA 절차를 사용한다.

`pytorch:2.1.0-cuda12.1` 이미지를 사용하므로 이 컨테이너 안에서는 `module load cuda11.8`을
추가로 실행하지 않는다. CUDA 11.8 모듈과 CUDA 12.1 컨테이너를 섞으면 라이브러리 충돌이
날 수 있다.

## 3. OpenPI 환경 만들기 (처음 한 번만)

```bash
export PATH="$HOME/.local/bin:$PATH"
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

cd <서버홈>/pi0_sehwan/openpi
GIT_LFS_SKIP_SMUDGE=1 uv sync
GIT_LFS_SKIP_SMUDGE=1 uv pip install -e .
```

학습 체크포인트 다운로드 캐시와 JAX GPU 사용량을 고정한다.

```bash
mkdir -p <서버홈>/.cache/openpi
export OPENPI_DATA_HOME=<서버홈>/.cache/openpi
export XLA_PYTHON_CLIENT_MEM_FRACTION=0.9
```

## 4. 10 step smoke test

데이터 로딩, 정규화 통계, base checkpoint 다운로드, GPU 메모리, 체크포인트 저장이 되는지만
확인한다. 실제 full 학습은 아직 시작하지 않는다.

```bash
cd <서버홈>/pi0_sehwan
./scripts/run_openpi_full_train.sh smoke xarm7_full_smoke
```

성공하면 아래에 결과가 생긴다.

```text
checkpoints/pi0_xarm7_full/xarm7_full_smoke/
```

## 5. full fine-tuning 시작

smoke가 끝난 뒤 실행한다. 현재 설정은 3,000 step, batch size 8, 손목 RGB 1대와 xArm 7관절
및 기본 그리퍼 action 1개를 사용한다.

```bash
cd <서버홈>/pi0_sehwan
./scripts/run_openpi_full_train.sh train xarm7_red_block_full_v1
```

학습 화면을 두고 SSH를 끊어도 된다. tmux에서 빠져나오는 키는 `Ctrl+B`를 누른 뒤 `D`다.

재접속:

```bash
ssh <계정>@<서버주소>
tmux attach -t pi0_full
```

GPU 사용량은 같은 tmux 안의 새 pane 또는 별도 tmux 세션에서 본다.

```bash
nvidia-smi -l 2
```

## 6. 중단 뒤 재개

학습 프로세스가 실제로 종료됐고 동일 실험의 마지막 체크포인트부터 이어갈 때만 사용한다.

```bash
cd <서버홈>/pi0_sehwan
export OPENPI_DATA_HOME=<서버홈>/.cache/openpi
export XLA_PYTHON_CLIENT_MEM_FRACTION=0.9
./scripts/run_openpi_full_train.sh resume xarm7_red_block_full_v1
```

`train`은 같은 실험 이름 결과를 덮어쓸 수 있으므로, 새 실험을 만들려면 다른 이름을 쓴다.

```bash
./scripts/run_openpi_full_train.sh train xarm7_red_block_full_v2
```

## 7. 자주 막히는 지점

| 현상 | 의미와 조치 |
|---|---|
| `full fine-tuning 요구량에 못 미칩니다` | 48GB 등 VRAM 부족이다. full은 하지 말고 LoRA로 전환한다. |
| `uv: command not found` | 위의 `curl ... uv/install.sh`를 실행한 뒤 `export PATH=...`를 다시 한다. |
| base checkpoint 다운로드 실패 | 컨테이너에서 인터넷/Google Storage 접근이 되는지 확인하고 `OPENPI_DATA_HOME` 캐시 경로 권한을 확인한다. |
| CUDA 라이브러리 충돌 | CUDA 12.1 PyTorch 컨테이너 안에서 `module load cuda11.8`을 하지 않는다. |
| GPU OOM | `XLA_PYTHON_CLIENT_MEM_FRACTION=0.9`가 설정됐는지 확인한다. 그래도 OOM이면 해당 GPU는 full 조건이 아니다. |

팀원의 GPT 실험용 Docker build/push 명령은 OpenPI 학습에 필요 없다. 여기서는 연구실이 제공하는
PyTorch CUDA 12.1 이미지 안에 OpenPI `uv` 환경을 만들고, 프로젝트 폴더와 데이터셋을 그대로
마운트해 사용하는 방식이다.
