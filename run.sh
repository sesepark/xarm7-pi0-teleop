#!/usr/bin/env bash
# 사용법:
#   ./run.sh teleop [joint|endpoint]  # 검증을 통과한 경우에만 실제 텔레옵 실행
#                                     # joint: GELLO 관절값 그대로 추종(기본)
#                                     # endpoint: GELLO TCP만 추종, 관절 궤적은 xArm planning
#   ./run.sh gello-axis 1 1  # GELLO J1의 +1 후보 부호를 저속으로 시험
#   ./run.sh gello-detect     # 움직인 GELLO 물리 관절의 Dynamixel ID 확인
#   ./run.sh gello-gripper    # GELLO/xArm 기본 그리퍼 방향을 소폭으로 시험
#   ./run.sh camera-preview   # 손목 RealSense 화면만 미리보기 (로봇은 움직이지 않음)
#   ./run.sh record [joint|endpoint]  # 안전 검증 뒤 손목 카메라 포함 데이터 수집 시작
#   ./run.sh record-resume <세션yaml> # 기존 세션에 이어서 데이터 수집 (덮어쓰기 아님)
#   ./run.sh init-position    # 고정 초기 관절 자세로 8°/s 복귀
#   ./run.sh recover-c31      # 충돌/과전류(C31) 해제 후 초기 자세로 복귀
#   ./run.sh recover-c19      # 그리퍼/끝단 통신 오류(C19) 해제. 팔·그리퍼 미동작
#   ./run.sh recover-c1       # 비상정지(C1) 해제·모터 재활성화 후 초기 자세 복귀
#   ./run.sh replay <데이터셋경로> <시연번호> # 저장한 성공 시연을 원본 1배속으로 재생
#   ./run.sh dataset-merge    # session_004/005를 OpenPI 학습용 데이터셋으로 안전 병합
#   ./run.sh stop teleop  # 이 프로젝트가 기록한 텔레옵 프로세스만 정리
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$PROJECT_ROOT/runtime"
LOG_DIR="$PROJECT_ROOT/logs/teleop"
PID_FILE="$RUNTIME_DIR/teleop.pid"
CONFIG_FILE="$PROJECT_ROOT/config/xarm7_gello_teleop.yaml"
RECORD_CONFIG_FILE="$PROJECT_ROOT/config/xarm7_gello_wrist_record.yaml"
CONFIG_FILE_ENDPOINT="$PROJECT_ROOT/config/xarm7_gello_teleop_endpoint.yaml"
RECORD_CONFIG_FILE_ENDPOINT="$PROJECT_ROOT/config/xarm7_gello_wrist_record_endpoint.yaml"
CONFIG_FILE_WEBXR="$PROJECT_ROOT/config/xarm7_webxr_teleop.yaml"
RECORD_CONFIG_FILE_WEBXR="$PROJECT_ROOT/config/xarm7_webxr_wrist_record.yaml"

# teleop/record의 두 번째 인자(joint|endpoint|webxr)를 검사해 사용할 설정을 정한다.
select_tracking_config() {
    local tracking="${1:-joint}"
    local joint_config="$2"
    local endpoint_config="$3"
    local webxr_config="$4"
    case "$tracking" in
        joint) echo "$joint_config" ;;
        endpoint) echo "$endpoint_config" ;;
        webxr) echo "$webxr_config" ;;
        *)
            echo "[오류] 리더/추적 모드는 joint, endpoint 또는 webxr여야 합니다: $tracking" >&2
            return 2
            ;;
  esac
}

stop_teleop() {
  if [[ ! -f "$PID_FILE" ]]; then
    echo "[정보] 이 프로젝트가 기록한 텔레옵 프로세스가 없습니다."
    return 0
  fi
  local pid
  pid="$(<"$PID_FILE")"
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "[정보] 이전 PID 파일은 남아 있었지만 프로세스는 이미 종료됐습니다."
    return 0
  fi
  local command
  command="$(ps -p "$pid" -o args=)"
  if [[ "$command" != *"uf-robot-teleop"* && "$command" != *"$PROJECT_ROOT"* ]]; then
    echo "[중단] PID $pid 는 이 프로젝트의 텔레옵으로 확인되지 않아 종료하지 않습니다."
    echo "       현재 명령: $command"
    return 1
  fi
  echo "[정보] 이 프로젝트가 시작한 텔레옵(PID $pid)에 종료 신호를 보냅니다."
  kill -INT "$pid"
  rm -f "$PID_FILE"
}

if [[ "${1:-}" == "stop" && "${2:-}" == "teleop" ]]; then
  stop_teleop
  exit 0
fi

if [[ "${1:-}" == "recover-c31" ]]; then
  echo "============================================================"
  echo "xArm C31 충돌/과전류 안전 복구"
  echo "실행 중인 이 프로젝트의 텔레옵은 먼저 종료합니다."
  echo "============================================================"
  stop_teleop || exit 1
  unset PYTHONPATH AMENT_PREFIX_PATH ROS_DISTRO ROS_VERSION
  export PYTHONNOUSERSITE=1
  export PYTHONUNBUFFERED=1
  eval "$(conda shell.bash hook)"
  conda activate uf_lerobot
  python "$PROJECT_ROOT/scripts/recover_c31.py" --config "$CONFIG_FILE"
  exit $?
fi

if [[ "${1:-}" == "recover-c1" ]]; then
  echo "============================================================"
  echo "xArm C1 비상정지 안전 복구"
  echo "실행 중인 이 프로젝트의 텔레옵은 먼저 종료합니다."
  echo "============================================================"
  stop_teleop || exit 1
  unset PYTHONPATH AMENT_PREFIX_PATH ROS_DISTRO ROS_VERSION
  export PYTHONNOUSERSITE=1
  export PYTHONUNBUFFERED=1
  eval "$(conda shell.bash hook)"
  conda activate uf_lerobot
  python "$PROJECT_ROOT/scripts/recover_c1.py" --config "$CONFIG_FILE"
  exit $?
fi

if [[ "${1:-}" == "recover-c19" ]]; then
  echo "============================================================"
  echo "xArm C19 그리퍼/끝단 통신 안전 복구"
  echo "실행 중인 이 프로젝트의 텔레옵은 먼저 종료합니다."
  echo "============================================================"
  stop_teleop || exit 1
  unset PYTHONPATH AMENT_PREFIX_PATH ROS_DISTRO ROS_VERSION
  export PYTHONNOUSERSITE=1
  export PYTHONUNBUFFERED=1
  eval "$(conda shell.bash hook)"
  conda activate uf_lerobot
  python "$PROJECT_ROOT/scripts/recover_c19.py" --config "$CONFIG_FILE"
  exit $?
fi

if [[ "${1:-}" == "replay" ]]; then
  dataset_path="${2:-}"
  episode_index="${3:-}"
  if [[ -z "$dataset_path" || ! "$episode_index" =~ ^[0-9]+$ ]]; then
    echo "사용법: ./run.sh replay <data/아래_데이터셋_경로> <시연번호>"
    echo "예시: ./run.sh replay data/2026-07-30/session_005 0"
    exit 2
  fi
  echo "============================================================"
  echo "xArm7 저장 성공 시연 1배속 재생"
  echo "데이터의 관절·그리퍼 action을 실제 로봇에 보내는 명령입니다."
  echo "============================================================"
  stop_teleop || exit 1
  unset PYTHONPATH AMENT_PREFIX_PATH ROS_DISTRO ROS_VERSION
  export PYTHONNOUSERSITE=1
  export PYTHONUNBUFFERED=1
  eval "$(conda shell.bash hook)"
  conda activate uf_lerobot
  python "$PROJECT_ROOT/scripts/replay_episode.py" \
    --dataset "$dataset_path" \
    --episode "$episode_index" \
    --execute
  exit $?
fi

if [[ "${1:-}" == "dataset-merge" ]]; then
  echo "============================================================"
  echo "xArm7 OpenPI 학습용 데이터셋 병합"
  echo "원본 session_004/005는 읽기만 하며 절대 수정하지 않습니다."
  echo "============================================================"
  openpi_python="$PROJECT_ROOT/openpi/.venv/bin/python"
  if [[ ! -x "$openpi_python" ]]; then
    echo "❌ OpenPI 가상환경이 없습니다: $openpi_python"
    exit 1
  fi
  "$openpi_python" "$PROJECT_ROOT/scripts/merge_xarm_datasets.py" \
    --sources "$PROJECT_ROOT/data/2026-07-30/session_004" "$PROJECT_ROOT/data/2026-07-30/session_005" \
    --output "$PROJECT_ROOT/data/curated/xarm7_red_block_black_line_v1"
  exit $?
fi

if [[ "${1:-}" == "gello-detect" ]]; then
  echo "============================================================"
  echo "GELLO 물리 관절 ↔ Dynamixel ID 확인"
  echo "xArm에는 모션 명령을 보내지 않습니다. 상태만 읽기 전용으로 확인합니다."
  echo "============================================================"
  if ! "$PROJECT_ROOT/verify.sh" gello; then
    exit 1
  fi
  unset PYTHONPATH AMENT_PREFIX_PATH ROS_DISTRO ROS_VERSION
  export PYTHONNOUSERSITE=1
  eval "$(conda shell.bash hook)"
  conda activate uf_lerobot
  python "$PROJECT_ROOT/scripts/detect_gello_joint.py" --config "$CONFIG_FILE"
  exit $?
fi

if [[ "${1:-}" == "gello-axis" ]]; then
  axis="${2:-}"
  candidate_sign="${3:-}"
  if [[ ! "$axis" =~ ^[1-7]$ || ( "$candidate_sign" != "1" && "$candidate_sign" != "-1" ) ]]; then
    echo "사용법: ./run.sh gello-axis <관절번호 1~7> <후보부호 1 또는 -1>"
    echo "예시: ./run.sh gello-axis 1 1"
    exit 2
  fi
  echo "============================================================"
  echo "GELLO J${axis} 단일 축 방향 시험 준비"
  echo "사람은 GELLO 관절을 3°~30° 편하게 움직이고, xArm은 선택 관절만 1°, 3°/s로 움직입니다."
  echo "============================================================"
  if ! "$PROJECT_ROOT/verify.sh" gello; then
    exit 1
  fi
  unset PYTHONPATH AMENT_PREFIX_PATH ROS_DISTRO ROS_VERSION
  export PYTHONNOUSERSITE=1
  eval "$(conda shell.bash hook)"
  conda activate uf_lerobot
  python "$PROJECT_ROOT/scripts/test_gello_axis.py" \
    --config "$CONFIG_FILE" \
    --axis "$axis" \
    --candidate-sign "$candidate_sign" \
    --log-dir "$PROJECT_ROOT/logs/gello_axis"
  exit $?
fi

if [[ "${1:-}" == "gello-gripper" ]]; then
  echo "============================================================"
  echo "GELLO ↔ xArm 기본 그리퍼 방향 시험"
  echo "팔 관절에는 모션 명령을 보내지 않습니다. 빈 그리퍼만 50/800 펄스 시험합니다."
  echo "============================================================"
  if ! "$PROJECT_ROOT/verify.sh" gello; then
    exit 1
  fi
  unset PYTHONPATH AMENT_PREFIX_PATH ROS_DISTRO ROS_VERSION
  export PYTHONNOUSERSITE=1
  eval "$(conda shell.bash hook)"
  conda activate uf_lerobot
  python "$PROJECT_ROOT/scripts/test_gello_gripper.py" \
    --config "$CONFIG_FILE" \
    --log-dir "$PROJECT_ROOT/logs/gello_gripper"
  exit $?
fi

if [[ "${1:-}" == "camera-preview" ]]; then
  camera_name="${2:-wrist}"
  if [[ "$camera_name" != "wrist" && "$camera_name" != "front" ]]; then
    echo "사용법: ./run.sh camera-preview [wrist|front]"
    exit 2
  fi
  echo "============================================================"
  echo "${camera_name} RealSense D435i 화면 미리보기"
  echo "xArm과 GELLO에는 연결하거나 명령을 보내지 않습니다."
  echo "============================================================"
  unset PYTHONPATH AMENT_PREFIX_PATH ROS_DISTRO ROS_VERSION
  export PYTHONNOUSERSITE=1
  eval "$(conda shell.bash hook)"
  conda activate uf_lerobot
  python "$PROJECT_ROOT/scripts/check_wrist_camera.py" \
    --config "$PROJECT_ROOT/config/cameras.yaml" --camera "$camera_name" \
    --preview
  exit $?
fi

if [[ "${1:-}" == "init-position" ]]; then
  echo "============================================================"
  echo "xArm7 고정 초기 관절 자세 복구"
  echo "그리퍼는 움직이지 않습니다. 팔 관절만 8°/s로 복귀합니다."
  echo "============================================================"
  unset PYTHONPATH AMENT_PREFIX_PATH ROS_DISTRO ROS_VERSION
  export PYTHONNOUSERSITE=1
  eval "$(conda shell.bash hook)"
  conda activate uf_lerobot
  python "$PROJECT_ROOT/init_position.py" --execute
  exit $?
fi

if [[ "${1:-}" == "webxr-setup" ]]; then
    "$PROJECT_ROOT/scripts/setup_webxr_tls.sh"
    unset PYTHONPATH AMENT_PREFIX_PATH ROS_DISTRO ROS_VERSION
    export PYTHONNOUSERSITE=1
    eval "$(conda shell.bash hook)"
    conda activate uf_lerobot
    python "$PROJECT_ROOT/scripts/verify_webxr_setup.py" --config "$CONFIG_FILE_WEBXR"
    exit $?
fi

if [[ "${1:-}" == "webxr-phone-test" ]]; then
    unset PYTHONPATH AMENT_PREFIX_PATH ROS_DISTRO ROS_VERSION
    export PYTHONNOUSERSITE=1
    export PYTHONUNBUFFERED=1
    eval "$(conda shell.bash hook)"
    conda activate uf_lerobot
    python "$PROJECT_ROOT/scripts/verify_webxr_setup.py" --config "$CONFIG_FILE_WEBXR"
    python "$PROJECT_ROOT/scripts/webxr_phone_test.py" --config "$CONFIG_FILE_WEBXR"
    exit $?
fi

if [[ "${1:-}" == "record-resume" ]]; then
  session_config="${2:-}"
  # 안전: runtime/record_sessions 아래의 세션 YAML만 허용한다.
  case "$(readlink -f "$session_config" 2>/dev/null)" in
    "$PROJECT_ROOT/runtime/record_sessions/"*.yaml) ;;
    *)
      echo "사용법: ./run.sh record-resume runtime/record_sessions/<날짜>/<세션>.yaml"
      exit 2
      ;;
  esac
  if [[ ! -f "$session_config" ]]; then
    echo "❌ 세션 설정 파일이 없습니다: $session_config"
    exit 1
  fi
  echo "============================================================"
  echo "xArm7 기존 세션 이어서 데이터 수집 (resume)"
  echo "세션 설정: $session_config"
  echo "기존 에피소드는 유지되고 새 에피소드가 뒤에 추가됩니다."
  echo "============================================================"
  if ! "$PROJECT_ROOT/verify.sh" record-resume "$session_config"; then
    exit 1
  fi

  echo ""
  echo "[최종 주의] 프로그램 초기화 시 기본 그리퍼가 열립니다. 사람과 물체가 작업영역 밖에 있는지 확인하세요."
  read -r -p "이어서 데이터 수집을 시작하려면 'start'를 입력하세요: " answer
  if [[ "$answer" != "start" ]]; then
    echo "[취소] 확인 문자열이 일치하지 않아 데이터 수집을 시작하지 않았습니다."
    exit 2
  fi
  echo "[대기] 2초 뒤 데이터 수집 프로그램을 엽니다."
  for remaining in 2 1; do
    echo "[대기] ${remaining}초..."
    sleep 1
  done

  unset PYTHONPATH AMENT_PREFIX_PATH ROS_DISTRO ROS_VERSION
  export PYTHONNOUSERSITE=1
  export PYTHONUNBUFFERED=1
  eval "$(conda shell.bash hook)"
  conda activate uf_lerobot
  echo "[안내] 프로그램이 열리면 Space로 각 에피소드를 시작합니다."
  echo "[안내] 녹화 후 →: 성공 저장 / ←: 실패 폐기 / ESC: 전체 수집 종료"
  python "$PROJECT_ROOT/scripts/record_gui_bridge.py" -r --config_path "$session_config"
  exit $?
fi

if [[ "${1:-}" == "record" ]]; then
  record_tracking="${2:-joint}"
  episode_time="${3:-20}"
  if [[ ! "$episode_time" =~ ^[0-9]+$ ]] || (( episode_time < 5 || episode_time > 300 )); then
    echo "에피소드 시간은 5~300초 사이의 정수여야 합니다."
    exit 2
  fi
    if ! RECORD_CONFIG_FILE="$(select_tracking_config "$record_tracking" "$RECORD_CONFIG_FILE" "$RECORD_CONFIG_FILE_ENDPOINT" "$RECORD_CONFIG_FILE_WEBXR")"; then
    exit 2
  fi
  echo "============================================================"
  echo "xArm7 + GELLO + 손목 카메라 데이터 수집 시작 준비 (추적 모드: $record_tracking)"
  echo "1) 읽기 전용 사전 검증을 합니다."
  echo "2) 검증 실패 시 데이터 수집과 로봇 모션을 시작하지 않습니다."
  echo "3) 첫 에피소드의 실제 시작은 이후 Space를 눌러야 합니다."
  echo "============================================================"
  # 실행할 때마다 날짜별 새 세션 설정을 만든다. 기존 데이터 폴더는 절대 재사용하거나
  # 덮어쓰지 않는다. 이 작업은 YAML 설정 파일만 만들며 로봇에는 연결하지 않는다.
  unset PYTHONPATH AMENT_PREFIX_PATH ROS_DISTRO ROS_VERSION
  export PYTHONNOUSERSITE=1
  eval "$(conda shell.bash hook)"
  conda activate uf_lerobot
  session_config="$(python "$PROJECT_ROOT/scripts/prepare_record_session.py" \
    --template "$RECORD_CONFIG_FILE" \
    --project-root "$PROJECT_ROOT" \
    --episode-time "$episode_time")"
  echo "[새 세션] 설정 파일: $session_config"
    if [[ "$record_tracking" == "webxr" ]]; then
        if ! conda run -n uf_lerobot python "$PROJECT_ROOT/scripts/verify_webxr_setup.py" \
            --config "$session_config" --check-robot; then
            exit 1
        fi
        if ! conda run -n uf_lerobot python "$PROJECT_ROOT/scripts/check_wrist_camera.py" \
            --config "$PROJECT_ROOT/config/cameras.yaml" --camera wrist; then
            exit 1
        fi
        if ! conda run -n uf_lerobot python "$PROJECT_ROOT/scripts/check_wrist_camera.py" \
            --config "$PROJECT_ROOT/config/cameras.yaml" --camera front; then
            exit 1
        fi
        if ! conda run -n uf_lerobot python "$PROJECT_ROOT/scripts/verify_record_config.py" \
            --config "$session_config" --project-root "$PROJECT_ROOT"; then
            exit 1
        fi
    elif ! "$PROJECT_ROOT/verify.sh" record "$session_config"; then
        exit 1
    fi

  echo ""
  echo "[기록 작업] 빨간색 직사각형 물체를 집어 중앙 검은 선의 오른쪽으로 옮기기"
  echo "[기록 설정] 최대 ${episode_time}초 × 성공 시연 30개 / 손목·전면 RGB 640x480@30fps"
  echo "[최종 주의] 프로그램 초기화 시 기본 그리퍼가 열립니다. 사람과 물체가 작업영역 밖에 있는지 확인하세요."
  read -r -p "데이터 수집 프로그램을 열려면 'start'를 입력하세요: " answer
  if [[ "$answer" != "start" ]]; then
    echo "[취소] 확인 문자열이 일치하지 않아 데이터 수집을 시작하지 않았습니다."
    exit 2
  fi

  echo "[대기] 2초 뒤 데이터 수집 프로그램을 엽니다. 이때도 아직 에피소드 녹화는 시작되지 않습니다."
  for remaining in 2 1; do
    echo "[대기] ${remaining}초..."
    sleep 1
  done

  unset PYTHONPATH AMENT_PREFIX_PATH ROS_DISTRO ROS_VERSION
  export PYTHONNOUSERSITE=1
  export PYTHONUNBUFFERED=1
  eval "$(conda shell.bash hook)"
  conda activate uf_lerobot
  echo "[안내] 프로그램이 열리면 Space로 각 에피소드를 시작합니다."
  echo "[안내] 녹화 후 →: 성공 저장 / ←: 실패 폐기 / ESC: 전체 수집 종료"
  python "$PROJECT_ROOT/scripts/record_gui_bridge.py" --config_path "$session_config"
  exit $?
fi

if [[ "${1:-}" != "teleop" ]]; then
  echo "사용법: ./run.sh teleop [joint|endpoint] | ./run.sh record [joint|endpoint] | ./run.sh record-resume <세션yaml> | ./run.sh init-position | ./run.sh recover-c31 | ./run.sh recover-c19 | ./run.sh recover-c1 | ./run.sh replay <데이터셋경로> <시연번호> | ./run.sh dataset-merge | ./run.sh gello-detect | ./run.sh gello-axis <1~7> <1|-1> | ./run.sh gello-gripper | ./run.sh camera-preview | ./run.sh stop teleop"
  exit 2
fi

teleop_tracking="${2:-joint}"
if ! CONFIG_FILE="$(select_tracking_config "$teleop_tracking" "$CONFIG_FILE" "$CONFIG_FILE_ENDPOINT" "$CONFIG_FILE_WEBXR")"; then
  exit 2
fi

# 이전 실행이 비정상 종료되어 남은 기록만 안전하게 정리합니다.
stop_teleop || exit 1

echo "============================================================"
echo "xArm7 + GELLO 텔레옵 시작 준비 (추적 모드: $teleop_tracking)"
echo "1) 지금부터 읽기 전용 사전 검증을 합니다."
echo "2) 검증 실패 시 로봇을 움직이지 않고 종료합니다."
echo "3) 통과 후에도 사용자의 최종 입력이 있어야 시작합니다."
echo "============================================================"
if [[ "$teleop_tracking" == "webxr" ]]; then
    if ! conda run -n uf_lerobot python "$PROJECT_ROOT/scripts/verify_webxr_setup.py" \
        --config "$CONFIG_FILE" --check-robot; then
        exit 1
    fi
elif ! "$PROJECT_ROOT/verify.sh" teleop "$CONFIG_FILE"; then
    exit 1
fi

echo ""
echo "[최종 주의] 텔레옵 시작 시 xArm 기본 그리퍼가 열리고, 로봇은 기록된 안전 시작 자세를 기준으로 동작합니다."
if [[ "$teleop_tracking" == "endpoint" ]]; then
    echo "[안전 시작] endpoint 추적: 처음 3초 동안 TCP 20mm/s로만 추종한 뒤 정상 속도 720mm/s(120°/s 환산 수준)로 전환됩니다."
    echo "[안전 시작] 관절 궤적은 xArm 컨트롤러의 온라인 planning(mode 7)이 결정합니다."
elif [[ "$teleop_tracking" == "webxr" ]]; then
    echo "[WebXR] 휴대폰 페이지를 먼저 연결하고 START WEBXR로 tracking을 시작하세요."
    echo "[WebXR] PC에서 Space를 눌러 arm한 뒤, 휴대폰 MOVE를 누르는 동안만 움직입니다."
    echo "[안전 시작] TCP 20mm/s에서 시작하며 정상 속도도 100mm/s로 제한됩니다."
else
  echo "[안전 시작] GELLO 입력은 처음 3초 동안 3°/s로만 추종한 뒤 정상 속도 120°/s로 전환됩니다."
fi
echo "[안전 시작] 목표를 잘라내지 않습니다. 시작 후 GELLO를 천천히 움직이세요."
echo "[최종 주의] 사람과 물체가 작업영역 밖에 있는지 확인하세요."
read -r -p "실제로 텔레옵을 시작하려면 'start'를 입력하세요: " answer
if [[ "$answer" != "start" ]]; then
  echo "[취소] 확인 문자열이 일치하지 않아 텔레옵을 시작하지 않았습니다."
  exit 2
fi

# start를 입력한 뒤에도 작업자가 마지막으로 사람/물체/케이블을 확인할 시간을 둡니다.
# 이 3초 동안에는 아직 uf-robot-teleop을 실행하지 않으므로 로봇 모션 명령이 없습니다.
echo "[대기] 3초 뒤 텔레옵을 시작합니다. 지금 작업영역을 마지막으로 확인하세요."
for remaining in 3 2 1; do
  echo "[대기] ${remaining}초..."
  sleep 1
done
echo "[시작 준비 완료] 이제 xArm/GELLO 텔레옵 프로세스를 시작합니다."
echo "[안내] 추가 Space 입력 없이 자동으로 추종을 시작합니다. 시작 후 Space는 일시정지/재개입니다."

mkdir -p "$RUNTIME_DIR" "$LOG_DIR"
timestamp="$(date +%Y%m%d_%H%M%S)"
log_file="$LOG_DIR/teleop_${timestamp}.log"
echo "$$" > "$PID_FILE"
cleanup() { rm -f "$PID_FILE"; }
trap cleanup EXIT INT TERM

unset PYTHONPATH AMENT_PREFIX_PATH ROS_DISTRO ROS_VERSION
export PYTHONNOUSERSITE=1
# Python 표준 출력을 즉시 로그에 기록합니다. 초기화가 멈춘 경우에도 마지막
# 성공 단계를 바로 확인할 수 있습니다.
export PYTHONUNBUFFERED=1
eval "$(conda shell.bash hook)"
conda activate uf_lerobot
echo "[시작] 로그 파일: $log_file"
echo "[종료] Ctrl+C 또는 ./run.sh stop teleop"

# 이 명령만 uf_lerobot 환경에서 실행된다. 현재 터미널의 다른 가상환경과 섞이지 않는다.
uf-robot-teleop --config_path "$CONFIG_FILE" 2>&1 | tee "$log_file"
