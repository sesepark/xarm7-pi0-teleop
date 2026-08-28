#!/usr/bin/env bash
# 사용법: ./verify.sh teleop
#
# 실행 전에 필요한 환경만 읽기 전용으로 점검한다. 어떤 모션 명령도 보내지 않는다.
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-}"
# teleop/record 모드의 선택적 설정 파일 경로 (endpoint 추적 모드 등)
CONFIG_OVERRIDE="${2:-}"

if [[ "$MODE" != "teleop" && "$MODE" != "gello" && "$MODE" != "camera" && "$MODE" != "record" && "$MODE" != "record-resume" ]]; then
  echo "사용법: ./verify.sh teleop | ./verify.sh gello | ./verify.sh camera | ./verify.sh record | ./verify.sh record-resume <세션yaml>"
  echo "현재 지원하는 검증 대상: teleop, gello, camera, record, record-resume"
  exit 2
fi

echo "============================================================"
echo "xArm7 + GELLO 사전 검증 (읽기 전용)"
echo "xArm과 GELLO를 움직이지 않습니다."
echo "============================================================"

# ROS가 전역으로 주입한 Python 경로를 제거해 텔레옵 전용 환경만 사용합니다.
unset PYTHONPATH AMENT_PREFIX_PATH ROS_DISTRO ROS_VERSION
export PYTHONNOUSERSITE=1
eval "$(conda shell.bash hook)"
conda activate uf_lerobot

# WebXR is an alternative leader, so its validation intentionally does not
# require the GELLO serial port or GELLO mapping flags. The xArm checks below
# remain read-only and camera/record validation is unchanged.
if [[ -n "$CONFIG_OVERRIDE" && -f "$CONFIG_OVERRIDE" ]] && \
   grep -q 'type:[[:space:]]*uf::webxr_teleop' "$CONFIG_OVERRIDE"; then
    webxr_status=0
    python "$PROJECT_ROOT/scripts/verify_webxr_setup.py" \
        --config "$CONFIG_OVERRIDE" --check-robot || webxr_status=$?

    if [[ "$MODE" == "record" || "$MODE" == "record-resume" ]]; then
        camera_status=0
        record_config_status=0
        python "$PROJECT_ROOT/scripts/check_wrist_camera.py" \
            --config "$PROJECT_ROOT/config/cameras.yaml" --camera wrist || camera_status=$?
        python "$PROJECT_ROOT/scripts/check_wrist_camera.py" \
            --config "$PROJECT_ROOT/config/cameras.yaml" --camera front || camera_status=$?
        resume_flag=()
        if [[ "$MODE" == "record-resume" ]]; then
            resume_flag=(--resume)
        fi
        python "$PROJECT_ROOT/scripts/verify_record_config.py" \
            --config "$CONFIG_OVERRIDE" \
            --project-root "$PROJECT_ROOT" \
            "${resume_flag[@]}" || record_config_status=$?
        if [[ "$webxr_status" -eq 0 && "$camera_status" -eq 0 && "$record_config_status" -eq 0 ]]; then
            echo "✅ WebXR 데이터 수집 조건을 모두 통과했습니다. 로봇 모션 명령은 보내지 않았습니다."
            exit 0
        fi
        echo "❌ WebXR 데이터 수집을 시작하지 않았습니다. 위 FAIL을 해결하세요."
        exit 1
    fi

    if [[ "$webxr_status" -eq 0 ]]; then
        echo "✅ WebXR 텔레옵 실행 조건을 모두 통과했습니다."
        exit 0
    fi
    echo "❌ WebXR 텔레옵을 시작하지 않았습니다. 위 FAIL을 해결하세요."
    exit 1
fi

doctor_status=0
config_status=0
python "$PROJECT_ROOT/scripts/doctor.py" || doctor_status=$?

if [[ "$MODE" == "gello" ]]; then
  gello_status=0
  python "$PROJECT_ROOT/scripts/read_gello.py" \
    --config "$PROJECT_ROOT/config/xarm7_gello_teleop.yaml" || gello_status=$?
  echo "------------------------------------------------------------"
  if [[ "$doctor_status" -eq 0 && "$gello_status" -eq 0 ]]; then
    echo "✅ GELLO 읽기 전용 검증을 통과했습니다."
    exit 0
  fi
  echo "❌ GELLO 읽기 전용 검증에 실패했습니다. 위 FAIL 항목을 해결하세요."
  exit 1
fi

if [[ "$MODE" == "camera" ]]; then
  camera_status=0
  python "$PROJECT_ROOT/scripts/check_wrist_camera.py" \
    --config "$PROJECT_ROOT/config/cameras.yaml" --camera wrist || camera_status=$?
  python "$PROJECT_ROOT/scripts/check_wrist_camera.py" \
    --config "$PROJECT_ROOT/config/cameras.yaml" --camera front || camera_status=$?
  echo "------------------------------------------------------------"
  if [[ "$camera_status" -eq 0 ]]; then
    echo "✅ 손목 카메라 검증을 통과했습니다. 이 과정에서는 로봇을 움직이지 않았습니다."
    exit 0
  fi
  echo "❌ 손목 카메라 검증에 실패했습니다. 위 오류를 해결한 뒤 다시 실행하세요."
  exit 1
fi

if [[ "$MODE" == "record" || "$MODE" == "record-resume" ]]; then
  record_config="${CONFIG_OVERRIDE:-$PROJECT_ROOT/config/xarm7_gello_wrist_record.yaml}"
  resume_flag=()
  if [[ "$MODE" == "record-resume" ]]; then
    resume_flag=(--resume)
  fi
  gello_status=0
  camera_status=0
  teleop_config_status=0
  record_config_status=0

  # GELLO의 실제 현재 관절값, 손목 카메라의 실제 프레임까지 확인한다.
  python "$PROJECT_ROOT/scripts/read_gello.py" --config "$record_config" || gello_status=$?
  python "$PROJECT_ROOT/scripts/check_wrist_camera.py" \
    --config "$PROJECT_ROOT/config/cameras.yaml" --camera wrist || camera_status=$?
  python "$PROJECT_ROOT/scripts/check_wrist_camera.py" \
    --config "$PROJECT_ROOT/config/cameras.yaml" --camera front || camera_status=$?
  # 현재 xArm 자세가 기록 시작 자세에서 2° 이내인지와 검증 완료 이력을 확인한다.
  python "$PROJECT_ROOT/scripts/verify_teleop_config.py" \
    --config "$record_config" \
    --safety-state "$PROJECT_ROOT/config/teleop_safety_state.yaml" \
    --allow-start-pose-mismatch || teleop_config_status=$?
  python "$PROJECT_ROOT/scripts/verify_record_config.py" \
    --config "$record_config" \
    --project-root "$PROJECT_ROOT" "${resume_flag[@]}" || record_config_status=$?

  echo "------------------------------------------------------------"
  if [[ "$doctor_status" -eq 0 && "$gello_status" -eq 0 && "$camera_status" -eq 0 && "$teleop_config_status" -eq 0 && "$record_config_status" -eq 0 ]]; then
    echo "✅ 데이터 수집 실행 조건을 모두 통과했습니다. 아직 로봇 모션 명령은 보내지 않았습니다."
    exit 0
  fi
  echo "❌ 데이터 수집을 시작하지 않았습니다. 위 FAIL 항목을 해결한 뒤 다시 실행하세요."
  exit 1
fi

teleop_config="${CONFIG_OVERRIDE:-$PROJECT_ROOT/config/xarm7_gello_teleop.yaml}"
python "$PROJECT_ROOT/scripts/verify_teleop_config.py" \
  --config "$teleop_config" \
  --safety-state "$PROJECT_ROOT/config/teleop_safety_state.yaml" || config_status=$?

echo "------------------------------------------------------------"
if [[ "$doctor_status" -eq 0 && "$config_status" -eq 0 ]]; then
  echo "✅ 텔레옵 실행 조건이 모두 통과했습니다."
  exit 0
fi

echo "❌ 텔레옵을 시작하지 않았습니다. 위 FAIL 항목을 해결한 뒤 다시 실행하세요."
exit 1
