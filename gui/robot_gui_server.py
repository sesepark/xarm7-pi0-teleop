#!/usr/bin/env python3
"""xArm7 + GELLO 시연용 로컬 제어판 서버.

이 서버는 127.0.0.1에서만 열리며, 로봇 제어 로직을 새로 구현하지 않는다.
검증을 마친 run.sh / verify.sh / recover_c31.py를 자식 프로세스로 실행하고,
웹 화면에는 상태·안전 확인·로그·제한된 제어 버튼만 제공한다.

중요한 안전 원칙
----------------
* 웹 화면에는 임의 쉘 명령 입력창을 만들지 않는다.
* 한 번에 텔레옵/녹화/카메라/복귀 중 하나만 실행한다.
* 텔레옵과 녹화 전환 시 기존 모드를 멈추고 초기 자세로 복귀한 다음 실행한다.
* C31 이외의 오류를 자동으로 해제하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import pty
import re
import signal
import struct
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from collections import deque
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
DATA_ROOT = PROJECT_ROOT / "data"
RUN_SCRIPT = PROJECT_ROOT / "run.sh"
DOCTOR_SCRIPT = PROJECT_ROOT / "scripts" / "run_doctor.sh"
KEY_SENDER = Path(__file__).resolve().parent / "send_record_key.py"
CAMERA_CONFIG = PROJECT_ROOT / "config" / "cameras.yaml"
CAMERA_WORKER = PROJECT_ROOT / "scripts" / "camera_stream_worker.py"
RECORD_GUI_DIR = PROJECT_ROOT / "runtime" / "record_gui"
UF_PYTHON = Path.home() / "miniconda3" / "envs" / "uf_lerobot" / "bin" / "python"
MINICONDA_BIN = Path.home() / "miniconda3" / "bin"
MINICONDA_CONDABIN = Path.home() / "miniconda3" / "condabin"
GUI_CLIENT_TTL_S = 15.0
GUI_STARTUP_GRACE_S = 90.0


def load_camera_configs() -> dict[str, dict[str, object]]:
    data = yaml.safe_load(CAMERA_CONFIG.read_text(encoding="utf-8")) or {}
    cameras = data.get("cameras") or {}
    if not isinstance(cameras, dict):
        raise ValueError("config/cameras.yaml의 cameras 항목이 올바르지 않습니다.")
    return {str(name): dict(config) for name, config in cameras.items()}


def record_gui_status() -> dict[str, object]:
    path = RECORD_GUI_DIR / "status.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(data.get("updated_at", 0)) > 5:
            data["phase"] = "stale"
        return data
    except (OSError, ValueError, json.JSONDecodeError):
        return {"phase": "inactive", "saved_episodes": 0, "discarded_episodes": 0}


def gui_runtime_env() -> dict[str, str]:
    """앱 아이콘으로 실행했을 때도 conda를 찾을 수 있는 자식 환경을 만든다.

    Ubuntu 앱 실행기는 ~/.bashrc를 읽지 않는 경우가 많다. 그러면 터미널에서는
    정상인 conda 명령이 GUI 자식 프로세스에서는 PATH에 없어 doctor·카메라 등이
    실패한다. 현재 사용자의 Miniconda 경로만 앞에 추가하고 DISPLAY 등 데스크톱
    관련 기존 환경변수는 그대로 보존한다.
    """
    env = os.environ.copy()
    extra = [str(path) for path in (MINICONDA_BIN, MINICONDA_CONDABIN) if path.is_dir()]
    env["PATH"] = ":".join([*extra, env.get("PATH", "")])
    return env


def replay_catalog() -> list[dict[str, object]]:
    """GUI에서 선택할 이 프로젝트의 성공 시연 세션만 읽기 전용으로 나열한다."""
    datasets: list[dict[str, object]] = []
    if not DATA_ROOT.is_dir():
        return datasets
    for info_path in sorted(DATA_ROOT.glob("*/session_*/meta/info.json")):
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
            dataset_path = info_path.parent.parent
            if info.get("robot_type") != "UFACTORY Robot":
                continue
            total_episodes = int(info.get("total_episodes", 0))
            fps = int(info.get("fps", 0))
            if total_episodes <= 0 or fps != 30:
                continue
            features = info.get("features") or {}
            state = features.get("observation.state") or {}
            state_shape = state.get("shape") or []
            tracking = "endpoint" if state_shape == [14] else "joint"
            datasets.append(
                {
                    "key": str(dataset_path.relative_to(PROJECT_ROOT)),
                    "label": (
                        f"{dataset_path.parent.name} / {dataset_path.name} "
                        f"({total_episodes}개 성공 시연 · "
                        f"{'Endpoint' if tracking == 'endpoint' else '관절'} 추적)"
                    ),
                    "episodes": total_episodes,
                    "tracking": tracking,
                }
            )
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return datasets

def record_resume_catalog() -> list[dict[str, object]]:
    """이어서 녹화할 수 있는 세션을 읽기 전용으로 나열한다.

    조건: data/날짜/session_NNN에 유효한 meta/info.json이 있고, 같은 이름의
    runtime/record_sessions YAML(당시 녹화 설정)이 남아 있어야 한다.
    """
    sessions: list[dict[str, object]] = []
    if not DATA_ROOT.is_dir():
        return sessions
    for info_path in sorted(DATA_ROOT.glob("*/session_*/meta/info.json")):
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
            dataset_path = info_path.parent.parent
            if info.get("robot_type") != "UFACTORY Robot" or int(info.get("fps", 0)) != 30:
                continue
            session_yaml = (
                PROJECT_ROOT / "runtime" / "record_sessions"
                / dataset_path.parent.name / f"{dataset_path.name}.yaml"
            )
            if not session_yaml.is_file():
                continue
            state_shape = ((info.get("features") or {}).get("observation.state") or {}).get("shape") or []
            tracking = "endpoint" if state_shape == [14] else "joint"
            episodes = int(info.get("total_episodes", 0))
            sessions.append(
                {
                    "key": str(dataset_path.relative_to(PROJECT_ROOT)),
                    "yaml": str(session_yaml),
                    "label": (
                        f"{dataset_path.parent.name} / {dataset_path.name} "
                        f"({episodes}개 저장 · {'Endpoint' if tracking == 'endpoint' else '관절'} 추적)"
                    ),
                    "episodes": episodes,
                    "tracking": tracking,
                }
            )
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    sessions.reverse()  # 최신 세션이 위로 오게 한다.
    return sessions


# C31만 기존 recover_c31.py로 안전 복구한다. 나머지는 설명만 보여 주고 자동 해제하지 않는다.
ERROR_GUIDE = {
    1: {
        "title": "C1: 비상 정지 버튼",
        "detail": "비상 정지 버튼이 눌려 모터 전원이 차단된 상태입니다.",
        "recovery": "원인 확인 후 버튼을 물리적으로 해제하면 C1 안전 복구를 실행할 수 있습니다. 오류 해제·모터 재활성화·초기 자세 복귀를 단계별로 승인합니다.",
        "recoverable": True,
    },
    2: {
        "title": "C2: 비상 IO 입력",
        "detail": "외부 안전 입력(IO)이 비상 정지 상태를 알리고 있습니다.",
        "recovery": "외부 안전장치·배선·스위치를 확인한 뒤 안전 입력을 복구하세요. 원인을 모른 채 모션을 재시작하지 마세요.",
        "recoverable": False,
    },
    3: {
        "title": "C3: 3상 비상 정지",
        "detail": "컨트롤러의 3상 비상 정지 신호가 감지되었습니다.",
        "recovery": "전원·비상정지 회로를 점검하고 담당자에게 확인받은 뒤 xArm 웹 UI에서 복구하세요.",
        "recoverable": False,
    },
    10: {
        "title": "C10: 서보 모터 오류",
        "detail": "하나 이상의 관절 서보에서 오류가 보고되었습니다.",
        "recovery": "팔을 움직이지 말고 오류 상세 화면에서 관절 번호와 서보 코드를 확인하세요. 걸림·과열·케이블을 먼저 점검합니다.",
        "recoverable": False,
    },
    **{
        code: {
            "title": f"C{code}: J{code - 10} 서보 모터 오류",
            "detail": f"xArm J{code - 10} 관절의 서보에서 오류가 보고되었습니다.",
            "recovery": f"J{code - 10} 주변 장애물·케이블·과열을 확인하고, 로봇을 억지로 움직이지 마세요. xArm 웹 UI의 상세 코드를 확인한 뒤 담당자에게 보고하세요.",
            "recoverable": False,
        }
        for code in range(11, 18)
    },
    18: {
        "title": "C18: 힘/토크 센서 통신 오류",
        "detail": "FT 센서와 컨트롤러의 통신이 끊겼습니다.",
        "recovery": "손목 센서·케이블·전원을 확인하고 연결이 안정된 뒤 doctor를 다시 실행하세요.",
        "recoverable": False,
    },
    19: {
        "title": "C19: 그리퍼/끝단 통신 오류",
        "detail": "그리퍼 등 끝단 모듈과의 RS-485 통신이 끊겼습니다. 케이블 접촉 불량 또는 baud rate 문제가 흔한 원인입니다.",
        "recovery": "C19 안전 복구를 실행할 수 있습니다. 케이블 점검 후 통신만 복구하며 팔과 그리퍼는 움직이지 않습니다.",
        "recoverable": True,
    },
    21: {
        "title": "C21: 운동학 계산 오류",
        "detail": "로봇 자세를 계산하는 과정에서 오류가 발생했습니다.",
        "recovery": "현재 자세와 목표 자세가 xArm 작업영역 안인지 확인하고, 문제가 반복되면 목표를 더 안전한 위치로 바꾸세요.",
        "recoverable": False,
    },
    22: {
        "title": "C22: 자기 충돌",
        "detail": "로봇의 링크끼리 충돌할 수 있는 자세가 감지되었습니다.",
        "recovery": "모션을 중지하고 로봇을 안전한 초기 자세로 이동할 수 있는지 확인하세요. 좁은 경로와 손목 카메라 간섭을 점검합니다.",
        "recoverable": False,
    },
    23: {
        "title": "C23: 관절 각도 제한",
        "detail": "관절이 허용 각도 범위를 벗어나려 했습니다.",
        "recovery": "어느 관절인지 확인하고 목표 자세를 취소하세요. 초기 자세 복귀도 주변을 확인한 뒤 수동으로 승인합니다.",
        "recoverable": False,
    },
    24: {
        "title": "C24: 속도 제한 초과",
        "detail": "관절 또는 TCP 속도가 설정된 제한을 넘었습니다.",
        "recovery": "텔레옵 속도와 목표 간격을 낮추고, 급격한 리더 움직임을 피하세요. 원인 확인 전 자동 재시작하지 않습니다.",
        "recoverable": False,
    },
    25: {
        "title": "C25: 모션 계획 오류",
        "detail": "계획한 경로를 안전하게 만들 수 없습니다.",
        "recovery": "목표를 더 가까운 안전 위치로 바꾸고 장애물·작업영역을 확인하세요.",
        "recoverable": False,
    },
    26: {
        "title": "C26: 실시간 제어 오류",
        "detail": "컨트롤러의 Linux 실시간 처리에서 오류가 발생했습니다.",
        "recovery": "현재 모드를 중지하고 네트워크·컨트롤러 상태를 확인한 뒤 xArm을 재시작하세요. 반복되면 담당자에게 로그를 전달합니다.",
        "recoverable": False,
    },
    27: {
        "title": "C27: 명령 응답 오류",
        "detail": "컨트롤러가 명령에 정상 응답하지 않았습니다.",
        "recovery": "네트워크와 로봇 전원을 확인하고 모드를 재실행하기 전에 doctor를 통과시키세요.",
        "recoverable": False,
    },
    28: {
        "title": "C28: 엔드 모듈 통신 오류",
        "detail": "끝단 모듈 응답에 문제가 있습니다.",
        "recovery": "그리퍼·센서·케이블을 확인하고, 팔 모션은 정지한 상태로 점검하세요.",
        "recoverable": False,
    },
    30: {
        "title": "C30: 피드백 속도 오류",
        "detail": "실제 관절 속도 피드백이 비정상입니다.",
        "recovery": "모션을 멈추고 속도 설정과 관절 걸림 여부를 확인하세요.",
        "recoverable": False,
    },
    **{
        code: {
            "title": f"C{code}: 힘/토크 센서 오류",
            "detail": "힘/토크 센서의 영점, 측정값 또는 통신 상태에 문제가 있습니다.",
            "recovery": "팔을 멈추고 손목 센서가 눌리거나 케이블이 당겨지지 않았는지 확인하세요. 반복되면 센서 영점과 연결을 담당자에게 점검받습니다.",
            "recoverable": False,
        }
        for code in range(50, 54)
    },
    31: {
        "title": "C31: 충돌 또는 비정상 전류",
        "detail": "물체 충돌, 케이블 걸림, 그리퍼/손목 카메라 간섭을 먼저 확인해야 합니다.",
        "recovery": "C31 안전 복구를 실행할 수 있습니다. 장애물을 제거한 뒤 두 번 확인합니다.",
        "recoverable": True,
    },
    32: {
        "title": "C32: 원호 계산 오류",
        "detail": "원호 또는 곡선 경로 계산에 실패했습니다.",
        "recovery": "직선에 가까운 단순한 목표로 다시 시험하고 작업영역을 확인하세요.",
        "recoverable": False,
    },
    33: {
        "title": "C33: GPIO 오류",
        "detail": "컨트롤러 GPIO 신호 또는 설정에 문제가 있습니다.",
        "recovery": "외부 IO 장치와 배선을 확인하고, 관련 장치를 사용하지 않는 모드로도 재현되는지 담당자와 확인하세요.",
        "recoverable": False,
    },
    34: {
        "title": "C34: 기록 시간 초과",
        "detail": "컨트롤러의 기록 또는 명령 처리 시간이 초과되었습니다.",
        "recovery": "현재 모드를 종료하고 네트워크·저장장치 상태를 확인한 뒤 다시 시도하세요.",
        "recoverable": False,
    },
    35: {
        "title": "C35: 안전 경계 초과",
        "detail": "설정된 작업영역/안전 경계를 벗어나려 했습니다.",
        "recovery": "사람과 물체를 작업영역 밖으로 치우고 목표·초기 자세가 경계 안인지 확인하세요.",
        "recoverable": False,
    },
    36: {
        "title": "C36: 지연 명령 한도 초과",
        "detail": "처리되지 않은 지연 명령이 한도를 넘었습니다.",
        "recovery": "모드를 중지하고 입력 속도·명령 빈도를 낮춘 뒤 다시 시작하세요.",
        "recoverable": False,
    },
    37: {
        "title": "C37: 비정상 수동 움직임",
        "detail": "수동 안내 또는 외력 움직임이 비정상으로 감지되었습니다.",
        "recovery": "팔을 놓고 주변 걸림을 확인한 뒤 현재 모드를 종료하세요. 반복되면 안전 설정을 점검합니다.",
        "recoverable": False,
    },
    38: {
        "title": "C38: 비정상 관절 각도",
        "detail": "관절 각도 피드백이 예상 범위를 벗어났습니다.",
        "recovery": "팔을 억지로 움직이지 말고 해당 관절과 엔코더 케이블을 점검하세요.",
        "recoverable": False,
    },
    39: {
        "title": "C39: 전원 보드 통신 오류",
        "detail": "전원 보드와 컨트롤러의 통신 오류입니다.",
        "recovery": "모드를 종료하고 전원·케이블을 확인하세요. 반복되면 전원 재인가와 담당자 점검이 필요합니다.",
        "recoverable": False,
    },
    40: {
        "title": "C40: 역기구학(IK) 해 없음",
        "detail": "요청한 TCP 자세를 만들 수 있는 관절 조합을 찾지 못했습니다.",
        "recovery": "목표 자세를 작업영역 안의 더 단순한 자세로 바꾸고 손목 방향을 완화하세요.",
        "recoverable": False,
    },
    110: {
        "title": "C110: 보드 통신 오류",
        "detail": "컨트롤러 내부 보드 통신이 불안정합니다.",
        "recovery": "모드를 종료하고 전원·통신 케이블을 확인한 뒤 재시작하세요. 반복되면 로그와 함께 담당자에게 보고합니다.",
        "recoverable": False,
    },
    111: {
        "title": "C111: 보드 통신 오류",
        "detail": "컨트롤러 내부 보드 통신이 불안정합니다.",
        "recovery": "모드를 종료하고 전원·통신 케이블을 확인한 뒤 재시작하세요. 반복되면 로그와 함께 담당자에게 보고합니다.",
        "recoverable": False,
    },
    **{
        code: {
            "title": f"C{code}: 힘/토크 센서 상세 오류",
            "detail": "xArm 공식 오류 표에 정의된 힘/토크 센서 계열 오류입니다.",
            "recovery": "팔을 멈추고 손목 센서·케이블·전원을 확인하세요. 상세 원인은 xArm 웹 UI와 공식 오류 표를 확인합니다.",
            "recoverable": False,
        }
        for code in range(64, 74)
    },
}


@dataclass
class LogLine:
    number: int
    timestamp: str
    text: str


class LogBook:
    """브라우저가 폴링하는 최근 로그. 파일 로그를 대체하지는 않는다."""

    def __init__(self) -> None:
        self._lines: deque[LogLine] = deque(maxlen=3000)
        self._number = 0
        self._lock = threading.Lock()

    def add(self, text: str) -> None:
        clean = text.rstrip("\r\n")
        if not clean:
            return
        with self._lock:
            self._number += 1
            self._lines.append(LogLine(self._number, time.strftime("%H:%M:%S"), clean))

    def after(self, number: int) -> list[dict[str, object]]:
        with self._lock:
            return [line.__dict__ for line in self._lines if line.number > number]

    def latest_number(self) -> int:
        with self._lock:
            return self._number


class ManagedProcess:
    """PTY에 연결한 자식 프로세스.

    run.sh 내부의 start/return/Enter 입력은 PTY로 보내고, 표준 출력은 GUI 로그에
    그대로 보인다. 일반 shell을 노출하는 대신 고정된 명령만 실행한다.
    """

    def __init__(self, name: str, command: list[str], log: LogBook) -> None:
        self.name = name
        self.command = command
        self.log = log
        self.master_fd, slave_fd = pty.openpty()
        self.process = subprocess.Popen(
            command,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=PROJECT_ROOT,
            env=gui_runtime_env(),
            preexec_fn=os.setsid,
            close_fds=True,
        )
        os.close(slave_fd)
        self._reader = threading.Thread(target=self._read_output, daemon=True)
        self._reader.start()
        self.log.add(f"[GUI] {name} 실행: {' '.join(command)}")

    @property
    def pid(self) -> int:
        return self.process.pid

    def poll(self) -> int | None:
        return self.process.poll()

    def write(self, text: str) -> None:
        if self.poll() is not None:
            return
        try:
            os.write(self.master_fd, text.encode("utf-8"))
        except OSError:
            pass

    def stop(self) -> None:
        if self.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self.process.pid), signal.SIGINT)
        except ProcessLookupError:
            return

    def wait(self, timeout: float | None = None) -> int:
        return self.process.wait(timeout=timeout)

    def _read_output(self) -> None:
        pending = ""
        try:
            while True:
                try:
                    chunk = os.read(self.master_fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                pending += chunk.decode("utf-8", errors="replace")
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    self.log.add(line)
        finally:
            if pending:
                self.log.add(pending)
            try:
                os.close(self.master_fd)
            except OSError:
                pass


class CameraStream:
    """카메라 워커 한 개와 최신 JPEG 프레임을 관리한다."""

    def __init__(self, name: str, config: dict[str, object], log: LogBook):
        self.name = name
        self.config = config
        self.log = log
        self.process: subprocess.Popen[bytes] | None = None
        self.frame: bytes | None = None
        self.frame_number = 0
        self.last_frame_at = 0.0
        self.error: str | None = None
        self._condition = threading.Condition()

    def start(self) -> tuple[bool, str]:
        with self._condition:
            if self.process is not None and self.process.poll() is None:
                return True, f"{self.config.get('label', self.name)}가 이미 실행 중입니다."
            command = [
                str(UF_PYTHON), str(CAMERA_WORKER),
                "--name", self.name,
                "--serial", str(self.config["serial_number"]),
                "--width", str(self.config.get("width", 640)),
                "--height", str(self.config.get("height", 480)),
                "--fps", str(self.config.get("fps", 30)),
                "--rotation", str(self.config.get("rotation", 0)),
            ]
            try:
                self.process = subprocess.Popen(
                    command, cwd=PROJECT_ROOT, env=gui_runtime_env(),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    start_new_session=True,
                )
            except Exception as exc:
                self.error = str(exc)
                return False, f"카메라 워커 시작 실패: {exc}"
            self.frame = None
            self.error = None
            threading.Thread(target=self._read_frames, daemon=True).start()
            threading.Thread(target=self._read_errors, daemon=True).start()
            label = str(self.config.get("label", self.name))
            self.log.add(f"[GUI 카메라] {label} 연결을 시작합니다.")
            return True, f"{label} 프리뷰를 시작했습니다."

    def stop(self) -> None:
        with self._condition:
            process = self.process
        if process is not None and process.poll() is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGINT)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    process.kill()
            except OSError:
                pass
        with self._condition:
            self.process = None
            self.frame = None
            self._condition.notify_all()

    def wait_frame(self, after: int, timeout: float = 2.0) -> tuple[int, bytes | None]:
        with self._condition:
            if self.frame_number <= after:
                self._condition.wait(timeout)
            return self.frame_number, self.frame

    def snapshot(self) -> dict[str, object]:
        with self._condition:
            running = self.process is not None and self.process.poll() is None
            age = time.monotonic() - self.last_frame_at if self.last_frame_at else None
            return {
                "name": self.name,
                "label": self.config.get("label", self.name),
                "serial": self.config.get("serial_number"),
                "width": self.config.get("width"),
                "height": self.config.get("height"),
                "fps": self.config.get("fps"),
                "running": running,
                "receiving": running and age is not None and age < 3.0,
                "error": self.error,
            }

    def _read_exactly(self, size: int) -> bytes | None:
        process = self.process
        if process is None or process.stdout is None:
            return None
        chunks = bytearray()
        while len(chunks) < size:
            chunk = process.stdout.read(size - len(chunks))
            if not chunk:
                return None
            chunks.extend(chunk)
        return bytes(chunks)

    def _read_frames(self) -> None:
        while True:
            header = self._read_exactly(4)
            if header is None:
                break
            length = struct.unpack("!I", header)[0]
            if length <= 0 or length > 10_000_000:
                self.error = "잘못된 카메라 프레임을 받았습니다."
                break
            frame = self._read_exactly(length)
            if frame is None:
                break
            with self._condition:
                self.frame = frame
                self.frame_number += 1
                self.last_frame_at = time.monotonic()
                self._condition.notify_all()
        with self._condition:
            self._condition.notify_all()

    def _read_errors(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        for raw in iter(process.stderr.readline, b""):
            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            self.log.add(text)
            if "[카메라 오류]" in text:
                with self._condition:
                    self.error = text.split(":", 1)[-1].strip()
                    self._condition.notify_all()


class CameraManager:
    def __init__(self, log: LogBook):
        self.log = log
        try:
            configs = load_camera_configs()
            self.streams = {name: CameraStream(name, cfg, log) for name, cfg in configs.items()}
        except Exception as exc:
            self.streams = {}
            self.log.add(f"❌ [GUI 카메라] 설정을 읽지 못했습니다: {exc}")

    def start(self, name: str) -> tuple[bool, str]:
        stream = self.streams.get(name)
        if stream is None:
            return False, "등록되지 않은 카메라입니다."
        return stream.start()

    def start_all(self) -> None:
        for stream in self.streams.values():
            stream.start()

    def stop(self, name: str) -> tuple[bool, str]:
        stream = self.streams.get(name)
        if stream is None:
            return False, "등록되지 않은 카메라입니다."
        stream.stop()
        return True, f"{stream.config.get('label', name)} 프리뷰를 중지했습니다."

    def stop_all(self) -> None:
        for stream in self.streams.values():
            stream.stop()

    def snapshot(self) -> dict[str, object]:
        return {name: stream.snapshot() for name, stream in self.streams.items()}


class RobotController:
    """GUI의 단일 모드·안전 전환 상태 관리자."""

    def __init__(self) -> None:
        self.log = LogBook()
        self._lock = threading.RLock()
        self._active: ManagedProcess | None = None
        self._mode = "idle"
        self._phase = "대기"
        self._last_error: dict[str, object] | None = None
        self._record_ready = False
        self._c31_stage = "idle"
        self._c19_stage = "idle"
        self._c1_stage = "idle"
        self.cameras = CameraManager(self.log)
        self.log.add("[GUI] pi0 xArm7 제어판 준비 완료. 아직 로봇에 명령을 보내지 않았습니다.")

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            active = self._active
            if active and active.poll() is not None:
                self.log.add(f"[GUI] {active.name} 프로세스 종료 (코드 {active.poll()})")
                self._active = None
                if self._mode not in {"transition", "c31", "c19", "c1"}:
                    self._mode = "idle"
                    self._phase = "대기"
            return {
                "mode": self._mode,
                "phase": self._phase,
                "active": active.name if active and active.poll() is None else None,
                "pid": active.pid if active and active.poll() is None else None,
                "last_error": self._last_error,
                "record_ready": self._record_ready,
                "c31_stage": self._c31_stage,
                "c19_stage": self._c19_stage,
                "c1_stage": self._c1_stage,
                "log_cursor": self.log.latest_number(),
            "project_root": str(PROJECT_ROOT),
            "cameras": self.cameras.snapshot(),
            "record": record_gui_status() if self._mode == "record" else {"phase": "inactive"},
        }

    def _set_error_from_log(self, text: str) -> None:
        # xArm 로그는 보통 C31처럼 출력하지만, SDK/드라이버에 따라
        # "error code 31" 또는 "오류: C31" 형태로도 나올 수 있습니다.
        matches = re.findall(
            r"(?:오류\s*C|\bC|(?:오류|error|code)\s*[:#]?\s*C?)(\d{1,3})\b",
            text,
            flags=re.IGNORECASE,
        )
        if not matches:
            return
        code = int(matches[-1])
        guide = ERROR_GUIDE.get(
            code,
            {
                "title": f"C{code}: xArm 오류 감지",
                "detail": "이 코드의 자동 복구는 GUI에서 지원하지 않습니다.",
                "recovery": "로봇 웹 UI와 공식 xArm 오류 표를 확인한 뒤, 원인을 제거하고 상태를 다시 진단하세요.",
                "recoverable": False,
            },
        )
        self._last_error = {"code": code, **guide}

    def _launch(self, name: str, command: list[str]) -> ManagedProcess:
        process = ManagedProcess(name, command, self.log)
        self._active = process
        self._record_ready = False
        return process

    def _run_and_wait(self, name: str, command: list[str], inputs: list[str] | None = None, timeout: float = 180.0) -> int:
        process = self._launch(name, command)
        for item in inputs or []:
            process.write(item)
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.log.add(f"❌ [GUI] {name} 시간이 너무 오래 걸려 자동 중단합니다.")
            process.stop()
            return -1

    def _stop_active(self) -> None:
        with self._lock:
            process = self._active
            record_graceful = (
                process is not None
                and process.poll() is None
                and process.name == "record"
                and self._record_ready
            )
        if process is None or process.poll() is not None:
            return

        # 실행 중인 녹화는 SIGINT 전에 ESC로 정상 종료를 먼저 시도한다.
        # LeRobot이 데이터셋을 스스로 마무리하도록 하기 위함이다.
        if record_graceful and UF_PYTHON.is_file():
            self.log.add("[GUI] 녹화 프로그램에 ESC를 보내 정상 종료를 시도합니다.")
            try:
                subprocess.run(
                    [str(UF_PYTHON), str(KEY_SENDER), "esc"],
                    cwd=PROJECT_ROOT,
                    env=gui_runtime_env(),
                    text=True,
                    capture_output=True,
                    timeout=8,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.log.add("[GUI] ESC 정상 종료가 확인되지 않아 기존 종료 절차로 전환합니다.")
        if process.poll() is not None:
            with self._lock:
                if self._active is process:
                    self._active = None
            self.log.add("[GUI] 녹화 프로그램이 정상 종료됐습니다.")
            return

        self.log.add(f"[GUI] 기존 모드({process.name})를 안전하게 종료합니다.")
        # 텔레옵은 run.sh가 기록한 PID를 통해 먼저 종료한다.
        if process.name == "teleop":
            result = subprocess.run(
                [str(RUN_SCRIPT), "stop", "teleop"],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=15,
            )
            for line in (result.stdout + result.stderr).splitlines():
                self.log.add(line)

        process.stop()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.log.add("❌ [GUI] 기존 프로세스가 20초 안에 끝나지 않았습니다. 추가 동작을 막습니다.")
            raise RuntimeError("기존 모드를 안전하게 종료하지 못했습니다.")
        with self._lock:
            if self._active is process:
                self._active = None

    def start_doctor(self) -> tuple[bool, str]:
        with self._lock:
            if self._active is not None and self._active.poll() is None:
                return False, "실행 중인 모드가 있습니다. 먼저 중지하세요."
            self._mode = "doctor"
            self._phase = "읽기 전용 환경 진단 중"

        def worker() -> None:
            code = self._run_and_wait("doctor", [str(DOCTOR_SCRIPT)], timeout=90)
            with self._lock:
                self._active = None
                self._mode = "idle"
                self._phase = "진단 완료" if code == 0 else "진단 실패: 로그 확인"

        threading.Thread(target=worker, daemon=True).start()
        return True, "환경 진단을 시작했습니다. 로봇은 움직이지 않습니다."

    def request_mode(self, target: str, tracking: str = "joint", episode_time: int = 20) -> tuple[bool, str]:
        if target not in {"teleop", "record", "init"}:
            return False, "지원하지 않는 기능입니다."
        if tracking not in {"joint", "endpoint"}:
            return False, "추적 모드는 joint 또는 endpoint여야 합니다."
        if not 5 <= episode_time <= 300:
            return False, "에피소드 시간은 5~300초 사이여야 합니다."
        tracking_label = "관절값 추적" if tracking == "joint" else "Endpoint 추적"
        with self._lock:
            if self._mode in {"transition", "c31", "c19", "c1"}:
                return False, "현재 안전 전환 또는 복구가 진행 중입니다. 완료될 때까지 기다리세요."
            self._mode = "transition"
            self._phase = f"{target} 전환 준비"

        def worker() -> None:
            try:
                self._stop_active()
                if target == "record":
                    self.cameras.stop_all()
                    self.log.add("[GUI 카메라] 데이터 녹화를 위해 UI 프리뷰를 중지했습니다.")
                if target in {"teleop", "record"}:
                    # 사용자가 화면에서 안전 확인을 했으므로, 기존 init_position의
                # start 입력을 전달한다. 내부 3초 카운트다운은 그대로 유지한다.
                    with self._lock:
                        self._phase = "초기 자세 복귀 중 (8°/s)"
                    init_code = self._run_and_wait(
                        "init-position", [str(RUN_SCRIPT), "init-position"], ["start\n"], timeout=180
                    )
                    if init_code != 0:
                        raise RuntimeError("초기 자세 복귀가 완료되지 않아 다음 모드를 시작하지 않습니다.")

                with self._lock:
                    self._phase = f"{target} 실행 중"
                command = {
                    "teleop": [str(RUN_SCRIPT), "teleop", tracking],
                    "record": [str(RUN_SCRIPT), "record", tracking, str(episode_time)],
                    "init": [str(RUN_SCRIPT), "init-position"],
                }[target]
                process = self._launch(target, command)
                if target in {"teleop", "record", "init"}:
                    # GUI의 안전 확인 버튼은 각 기존 명령의 start 입력과 동등하다.
                    process.write("start\n")
                with self._lock:
                    self._mode = target
                    self._phase = {
                        "teleop": f"텔레옵({tracking_label}) 초기화/실행 중",
                        "record": f"녹화({tracking_label}) 준비 중: Space 또는 녹화 시작 버튼을 누르세요",
                        "init": "초기 자세 복귀 중",
                    }[target]
                # 텔레옵에서는 UI 프리뷰를 자동으로 열지 않는다. 두 RealSense
                # (각 640x480@30fps)를 동시에 브라우저로 전송하면 제어판 렌더러가
                # 멈춰 heartbeat까지 끊길 수 있다. 필요한 카메라는 화면의 수동
                # 프리뷰 버튼으로 하나씩 연다.

                # 초기 자세 복귀는 완료되면 자동으로 idle 상태가 된다.
                if target == "init":
                    code = process.wait()
                    with self._lock:
                        if self._active is process:
                            self._active = None
                            self._mode = "idle"
                            self._phase = "대기" if code == 0 else "실행 실패: 로그 확인"
            except Exception as exc:
                self.log.add(f"❌ [GUI] 모드 전환 실패: {exc}")
                self._set_error_from_log(str(exc))
                with self._lock:
                    self._active = None
                    self._mode = "idle"
                    self._phase = "전환 실패: 로그 확인"

        threading.Thread(target=worker, daemon=True).start()
        return True, "작업영역 확인 후 자동 전환을 시작했습니다. 기존 안전 카운트다운이 표시됩니다."

    def request_record_resume(self, session_key: str) -> tuple[bool, str]:
        """드롭다운에서 고른 기존 세션에 이어서 녹화를 시작한다.

        세션 경로는 API 입력을 그대로 신뢰하지 않고 현재 catalog 항목만 받는다.
        해당 세션이 만들어질 때 저장된 runtime YAML을 그대로 쓰므로 추적 모드
        (관절/endpoint)도 그 세션과 자동으로 같아진다.
        """
        selected = next((item for item in record_resume_catalog() if item["key"] == session_key), None)
        if selected is None:
            return False, "선택한 세션을 찾지 못했습니다. 목록을 새로고침하세요."
        with self._lock:
            if self._mode in {"transition", "c31", "c19", "c1"}:
                return False, "현재 안전 전환 또는 복구가 진행 중입니다. 완료될 때까지 기다리세요."
            self._mode = "transition"
            self._phase = "세션 이어서 수집 준비"

        def worker() -> None:
            try:
                self._stop_active()
                self.cameras.stop_all()
                self.log.add("[GUI 카메라] 데이터 녹화를 위해 UI 프리뷰를 중지했습니다.")
                with self._lock:
                    self._phase = "초기 자세 복귀 중 (8°/s)"
                init_code = self._run_and_wait(
                    "init-position", [str(RUN_SCRIPT), "init-position"], ["start\n"], timeout=180
                )
                if init_code != 0:
                    raise RuntimeError("초기 자세 복귀가 완료되지 않아 수집을 시작하지 않습니다.")
                process = self._launch(
                    "record", [str(RUN_SCRIPT), "record-resume", str(selected["yaml"])]
                )
                process.write("start\n")
                with self._lock:
                    self._mode = "record"
                    self._phase = (
                        f"{selected['key']} 이어서 수집 준비 중: "
                        "Space 또는 녹화 시작 버튼을 누르세요"
                    )
            except Exception as exc:
                self.log.add(f"❌ [GUI] 세션 이어서 수집 시작 실패: {exc}")
                self._set_error_from_log(str(exc))
                with self._lock:
                    self._active = None
                    self._mode = "idle"
                    self._phase = "이어서 수집 실패: 로그 확인"

        threading.Thread(target=worker, daemon=True).start()
        return True, f"{selected['key']} 세션에 이어서 수집을 준비합니다. 기존 에피소드는 유지됩니다."

    def request_replay(self, dataset_key: str, episode_index: int) -> tuple[bool, str]:
        """GUI에서 선택한 성공 시연을 1배속으로 재생한다.

        데이터 경로는 API 입력을 그대로 신뢰하지 않고 현재 catalog에 있는 항목만
        받는다. 실제 관절/그리퍼 시작 상태 검사는 replay_episode.py가 수행한다.
        """
        selected = next((item for item in replay_catalog() if item["key"] == dataset_key), None)
        if selected is None:
            return False, "선택한 데이터 수집 세션을 찾지 못했습니다. 목록을 새로고침하세요."
        total_episodes = int(selected["episodes"])
        if episode_index < 0 or episode_index >= total_episodes:
            return False, f"시연 번호는 0부터 {total_episodes - 1} 사이여야 합니다."
        with self._lock:
            if self._mode in {"transition", "c31", "c19", "c1"}:
                return False, "현재 안전 전환 또는 복구가 진행 중입니다. 완료될 때까지 기다리세요."
            self._mode = "transition"
            self._phase = "성공 시연 재생 준비"

        def worker() -> None:
            try:
                self._stop_active()
                with self._lock:
                    self._phase = "선택 시연 사전 검사 중"
                process = self._launch(
                    "replay",
                    [str(RUN_SCRIPT), "replay", dataset_key, str(episode_index)],
                )
                # GUI 안전 확인 체크는 replay_episode.py의 start 확인과 동등하다.
                process.write("start\n")
                with self._lock:
                    self._mode = "replay"
                    self._phase = "선택 시연 시작 자세·오류 검사 중"
            except Exception as exc:
                self.log.add(f"❌ [GUI] 성공 시연 재생 준비 실패: {exc}")
                with self._lock:
                    self._active = None
                    self._mode = "idle"
                    self._phase = "재생 준비 실패: 로그 확인"

        threading.Thread(target=worker, daemon=True).start()
        return True, "선택한 성공 시연의 사전 검사를 시작했습니다. 통과하면 3초 뒤 원본 1배속으로 재생됩니다."

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            if self._active is None or self._active.poll() is not None:
                return False, "현재 실행 중인 제어 모드가 없습니다."
            self._phase = "현재 모드 종료 중"

        def worker() -> None:
            try:
                self._stop_active()
                with self._lock:
                    self._mode = "idle"
                    self._phase = "대기"
                    self._c31_stage = "idle"
                    self._c19_stage = "idle"
                    self._c1_stage = "idle"
            except Exception as exc:
                self.log.add(f"❌ [GUI] 중지 실패: {exc}")
                with self._lock:
                    self._phase = "중지 실패: 로그 확인"

        threading.Thread(target=worker, daemon=True).start()
        return True, "현재 모드 종료를 요청했습니다."

    def shutdown(self) -> None:
        """GUI 창이 모두 닫혔을 때 남은 로봇 프로세스를 정리한다.

        가상환경은 각 run.sh 자식 프로세스 안에서만 활성화되므로, 이 메서드는
        실행 중인 자식 프로세스를 종료하면 환경까지 함께 정리된다.
        """
        self.log.add("[GUI] 열려 있는 제어판 창이 없어 현재 모드를 종료합니다.")
        self.cameras.stop_all()
        try:
            self._stop_active()
        except Exception as exc:
            self.log.add(f"❌ [GUI] 창 종료 중 프로세스 정리 실패: {exc}")
        finally:
            with self._lock:
                self._active = None
                self._mode = "idle"
                self._phase = "GUI 종료"
                self._record_ready = False
                self._c31_stage = "idle"
                self._c19_stage = "idle"
                self._c1_stage = "idle"

    def send_record_key(self, key: str) -> tuple[bool, str]:
        if key not in {"space", "right", "left", "esc"}:
            return False, "지원하지 않는 녹화 입력입니다."
        with self._lock:
            if self._mode != "record" or self._active is None or self._active.poll() is not None:
                return False, "녹화 프로그램이 실행 중일 때만 이 버튼을 사용할 수 있습니다."
            if not self._record_ready:
                return False, "녹화 프로그램이 아직 키 입력을 받을 준비가 되지 않았습니다. 로그에 Space 안내가 나온 뒤 누르세요."

        if not UF_PYTHON.is_file():
            return False, f"uf_lerobot Python을 찾지 못했습니다: {UF_PYTHON}"
        try:
            # GUI 버튼 명령은 녹화 브리지가 읽는 로컬 파일로 전달한다. 브리지는
            # LeRobot의 기존 키 처리 함수에 연결하므로 데스크톱 포커스에 의존하지 않는다.
            result = subprocess.run(
                [str(UF_PYTHON), str(KEY_SENDER), key],
                cwd=PROJECT_ROOT,
                env=gui_runtime_env(),
                text=True,
                capture_output=True,
                timeout=8,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, "키 입력 전송 시간이 초과됐습니다. 무선 키보드를 사용하세요."
        if result.returncode != 0:
            detail = (result.stdout + result.stderr).strip()
            self.log.add(f"❌ [GUI] 녹화 키 전송 실패: {detail}")
            return False, "GUI 키 전송에 실패했습니다. 무선 키보드를 사용하세요."
        label = {"space": "Space: 녹화 시작", "right": "→: 성공 저장", "left": "←: 실패 폐기", "esc": "ESC: 전체 종료"}[key]
        self.log.add(f"[GUI 입력] {label}")
        return True, label

    def begin_c31(self) -> tuple[bool, str]:
        with self._lock:
            if self._mode == "transition":
                return False, "모드 전환이 끝난 뒤 C31 복구를 실행하세요."
            if self._mode in {"c31", "c19", "c1"}:
                return False, "이미 복구 절차가 진행 중입니다. 화면의 현재 단계 안내를 따르세요."
            self._mode = "c31"
            self._phase = "C31 진단 중"
            self._c31_stage = "diagnosing"

        def worker() -> None:
            try:
                self._stop_active()
                process = self._launch("recover-c31", [str(RUN_SCRIPT), "recover-c31"])
                code = process.wait()
                with self._lock:
                    if self._active is process:
                        self._active = None
                    self._mode = "idle"
                    self._phase = "대기" if code == 0 else "C31 복구 중단/실패: 로그 확인"
                    self._c31_stage = "idle"
            except Exception as exc:
                self.log.add(f"❌ [GUI] C31 복구 시작 실패: {exc}")
                with self._lock:
                    self._active = None
                    self._mode = "idle"
                    self._phase = "C31 복구 실패: 로그 확인"
                    self._c31_stage = "idle"

        threading.Thread(target=worker, daemon=True).start()
        return True, "C31인지 읽기 전용으로 확인합니다. 아직 로봇을 움직이지 않습니다."

    def c31_continue(self, stage: str) -> tuple[bool, str]:
        with self._lock:
            process = self._active
            if self._mode != "c31" or process is None or process.poll() is not None:
                return False, "진행 중인 C31 복구가 없습니다."
            if stage == "clear":
                if self._c31_stage != "clear":
                    return False, "아직 장애물 제거 확인 단계가 아닙니다. C31 진단 결과가 로그에 나온 뒤 누르세요."
                process.write("\n")
                self._c31_stage = "clearing"
                self._phase = "C31 오류 해제 및 안전 상태 확인 중"
                return True, "장애물 제거 확인을 전달했습니다. 오류 해제 결과를 확인 중입니다."
            if stage == "return":
                if self._c31_stage != "return":
                    return False, "아직 초기 자세 복귀 승인 단계가 아닙니다. C31 해제 완료 로그를 먼저 확인하세요."
                process.write("return\n")
                self._c31_stage = "returning"
                self._phase = "초기 자세 복귀 중 (8°/s)"
                return True, "초기 자세 복귀 승인과 3초 안전 대기를 시작했습니다."
        return False, "지원하지 않는 C31 단계입니다."

    def begin_c1(self) -> tuple[bool, str]:
        with self._lock:
            if self._mode == "transition":
                return False, "모드 전환이 끝난 뒤 C1 복구를 실행하세요."
            if self._mode in {"c31", "c19", "c1"}:
                return False, "이미 복구 절차가 진행 중입니다. 화면의 현재 단계 안내를 따르세요."
            self._mode = "c1"
            self._phase = "C1 진단 중"
            self._c1_stage = "diagnosing"

        def worker() -> None:
            try:
                self._stop_active()
                process = self._launch("recover-c1", [str(RUN_SCRIPT), "recover-c1"])
                code = process.wait()
                with self._lock:
                    if self._active is process:
                        self._active = None
                    self._mode = "idle"
                    self._phase = "대기" if code == 0 else "C1 복구 중단/실패: 로그 확인"
                    self._c1_stage = "idle"
            except Exception as exc:
                self.log.add(f"❌ [GUI] C1 복구 시작 실패: {exc}")
                with self._lock:
                    self._active = None
                    self._mode = "idle"
                    self._phase = "C1 복구 실패: 로그 확인"
                    self._c1_stage = "idle"

        threading.Thread(target=worker, daemon=True).start()
        return True, "C1인지 읽기 전용으로 확인합니다. 아직 로봇을 움직이지 않습니다."

    def c1_continue(self, stage: str) -> tuple[bool, str]:
        with self._lock:
            process = self._active
            if self._mode != "c1" or process is None or process.poll() is not None:
                return False, "진행 중인 C1 복구가 없습니다."
            if stage == "release":
                if self._c1_stage != "release":
                    return False, "아직 비상정지 해제 확인 단계가 아닙니다. C1 진단 결과가 로그에 나온 뒤 누르세요."
                process.write("\n")
                self._c1_stage = "enabling"
                self._phase = "C1 해제·모터 재활성화 중 (팔 미이동)"
                return True, "비상정지 해제 확인을 전달했습니다. 모터 재활성화 결과를 확인 중입니다."
            if stage == "return":
                if self._c1_stage != "return":
                    return False, "아직 초기 자세 복귀 승인 단계가 아닙니다. 모터 재활성화 완료 로그를 먼저 확인하세요."
                process.write("return\n")
                self._c1_stage = "returning"
                self._phase = "초기 자세 복귀 중 (8°/s)"
                return True, "초기 자세 복귀 승인과 3초 안전 대기를 시작했습니다."
        return False, "지원하지 않는 C1 단계입니다."

    def begin_c19(self) -> tuple[bool, str]:
        with self._lock:
            if self._mode == "transition":
                return False, "모드 전환이 끝난 뒤 C19 복구를 실행하세요."
            if self._mode in {"c31", "c19", "c1"}:
                return False, "이미 복구 절차가 진행 중입니다. 화면의 현재 단계 안내를 따르세요."
            self._mode = "c19"
            self._phase = "C19 진단 중"
            self._c19_stage = "diagnosing"

        def worker() -> None:
            try:
                self._stop_active()
                process = self._launch("recover-c19", [str(RUN_SCRIPT), "recover-c19"])
                code = process.wait()
                with self._lock:
                    if self._active is process:
                        self._active = None
                    self._mode = "idle"
                    self._phase = "대기" if code == 0 else "C19 복구 중단/실패: 로그 확인"
                    self._c19_stage = "idle"
            except Exception as exc:
                self.log.add(f"❌ [GUI] C19 복구 시작 실패: {exc}")
                with self._lock:
                    self._active = None
                    self._mode = "idle"
                    self._phase = "C19 복구 실패: 로그 확인"
                    self._c19_stage = "idle"

        threading.Thread(target=worker, daemon=True).start()
        return True, "C19인지 읽기 전용으로 확인합니다. 팔과 그리퍼는 움직이지 않습니다."

    def c19_continue(self) -> tuple[bool, str]:
        with self._lock:
            process = self._active
            if self._mode != "c19" or process is None or process.poll() is not None:
                return False, "진행 중인 C19 복구가 없습니다."
            if self._c19_stage != "check":
                return False, "아직 케이블 점검 확인 단계가 아닙니다. C19 진단 결과가 로그에 나온 뒤 누르세요."
            process.write("\n")
            self._c19_stage = "recovering"
            self._phase = "C19 해제·그리퍼 통신 복구 중 (팔·그리퍼 미동작)"
            return True, "케이블 점검 확인을 전달했습니다. 통신 복구 결과를 확인 중입니다."

    def observe_log(self, text: str) -> None:
        self._set_error_from_log(text)
        # LeRobot이 실제로 키보드 안내를 출력한 뒤에만 GUI의 녹화 버튼을 허용한다.
        # 준비 전 입력이 사라져 "버튼이 안 된다"고 느껴지는 문제를 막는다.
        with self._lock:
            if self._mode == "record" and ("[ESC] 전체 종료" in text or "녹화 시작" in text and "성공 저장" in text):
                self._record_ready = True
                self._phase = "녹화 준비 완료: Space 또는 녹화 시작 버튼을 누르세요"
            if self._mode == "c31":
                if "[GUI 단계] 장애물 제거 확인 대기" in text:
                    self._c31_stage = "clear"
                    self._phase = "장애물·케이블 제거 뒤 ‘장애물 제거 완료’를 누르세요"
                elif "[GUI 단계] 초기 자세 복귀 승인 대기" in text:
                    self._c31_stage = "return"
                    self._phase = "C31 해제 완료: 작업영역 확인 뒤 ‘초기 자세 복귀 승인’을 누르세요"
            if self._mode == "c19" and "[GUI 단계] 케이블 점검 확인 대기" in text:
                self._c19_stage = "check"
                self._phase = "그리퍼/카메라 케이블 점검 뒤 ‘케이블 점검 완료’를 누르세요"
            if self._mode == "c1":
                if "[GUI 단계] 비상정지 해제 확인 대기" in text:
                    self._c1_stage = "release"
                    self._phase = "비상 정지 버튼을 물리적으로 해제한 뒤 ‘비상정지 해제 완료’를 누르세요"
                elif "[GUI 단계] 초기 자세 복귀 승인 대기" in text:
                    self._c1_stage = "return"
                    self._phase = "모터 재활성화 완료: 작업영역 확인 뒤 ‘초기 자세 복귀 승인’을 누르세요"


CONTROLLER = RobotController()


def add_log_and_watch(text: str) -> None:
    CONTROLLER.log.add(text)
    CONTROLLER.observe_log(text)


# LogBook.add를 감싸 오류 코드를 실시간으로 감지한다.
_original_add = CONTROLLER.log.add


def _watched_add(text: str) -> None:
    _original_add(text)
    CONTROLLER.observe_log(text)


CONTROLLER.log.add = _watched_add  # type: ignore[method-assign]


class GuiClientTracker:
    """브라우저 제어판이 열려 있는지 가볍게 추적한다.

    웹 서버만 남으면 다음 앱 실행이 포트 충돌로 실패하므로, 마지막 제어판 창이
    닫힌 뒤 일정 시간 동안 heartbeat가 없으면 실행 중인 자식 프로세스와 서버를
    함께 종료한다. 네트워크 순간 지연을 고려해 15초의 여유를 둔다.
    """

    def __init__(self) -> None:
        self._started_at = time.monotonic()
        self._clients: dict[str, float] = {}
        self._seen_client = False
        self._lock = threading.Lock()

    def heartbeat(self, client_id: str) -> None:
        if not client_id or len(client_id) > 128:
            return
        with self._lock:
            self._seen_client = True
            self._clients[client_id] = time.monotonic()

    def should_shutdown(self) -> bool:
        now = time.monotonic()
        with self._lock:
            self._clients = {
                client_id: seen_at
                for client_id, seen_at in self._clients.items()
                if now - seen_at <= GUI_CLIENT_TTL_S
            }
            # 브라우저가 아예 열리지 못한 경우에도 서버가 영구히 남지 않게 한다.
            if not self._seen_client:
                return now - self._started_at > GUI_STARTUP_GRACE_S
            return not self._clients


CLIENTS = GuiClientTracker()
SERVER: ThreadingHTTPServer | None = None
SERVER_PORT = 8765
SERVER_SHUTDOWN_STARTED = threading.Event()

# 재시작 헬퍼: 옛 서버가 포트를 놓을 때까지 기다렸다가 새 서버를 시작한다.
# 옛 서버 프로세스와 분리(setsid)되어 실행되므로 옛 서버가 죽어도 살아남는다.
RESTARTER_CODE = """
import os, socket, sys, time
port = int(sys.argv[1])
server_script = sys.argv[2]
deadline = time.time() + 30
while time.time() < deadline:
    probe = socket.socket()
    probe.settimeout(0.5)
    try:
        probe.connect(("127.0.0.1", port))
        probe.close()
        time.sleep(0.4)
    except OSError:
        probe.close()
        break
time.sleep(0.5)
os.execv(sys.executable, [sys.executable, server_script, "--port", str(port)])
"""


def restart_server() -> None:
    """새 서버를 준비시킨 뒤 현재 서버를 종료한다."""
    log_path = PROJECT_ROOT / "logs" / "gui_server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab") as log_file:
        subprocess.Popen(
            [
                "/usr/bin/python3",
                "-c",
                RESTARTER_CODE,
                str(SERVER_PORT),
                str(Path(__file__).resolve()),
            ],
            cwd=PROJECT_ROOT,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
            close_fds=True,
        )
    request_server_shutdown("사용자가 GUI 서버 재시작을 요청했습니다.")


def request_server_shutdown(reason: str) -> None:
    """HTTP 요청 처리 스레드와 분리해 안전하게 서버를 닫는다."""
    if SERVER_SHUTDOWN_STARTED.is_set():
        return
    SERVER_SHUTDOWN_STARTED.set()

    def worker() -> None:
        add_log_and_watch(f"[GUI] 종료 요청: {reason}")
        CONTROLLER.shutdown()
        if SERVER is not None:
            SERVER.shutdown()

    threading.Thread(target=worker, daemon=True).start()


def watch_gui_clients() -> None:
    while not SERVER_SHUTDOWN_STARTED.wait(2.0):
        if CLIENTS.should_shutdown():
            request_server_shutdown("제어판 창이 닫혀 heartbeat가 끊겼습니다.")
            return


class GuiRequestHandler(BaseHTTPRequestHandler):
    server_version = "Pi0XArmGui/1.0"

    def log_message(self, format: str, *args: object) -> None:
        # HTTP access log는 화면의 로봇 로그를 흐리지 않도록 기록하지 않는다.
        return

    def _local_client(self) -> bool:
        return self.client_address[0] in {"127.0.0.1", "::1"}

    def _send_json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 100_000:
            return {}
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            return value if isinstance(value, dict) else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def do_GET(self) -> None:  # noqa: N802
        if not self._local_client():
            self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "message": "로컬 PC에서만 사용할 수 있습니다."})
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/status":
            self._send_json(HTTPStatus.OK, {"ok": True, "data": CONTROLLER.snapshot()})
            return
        if parsed.path == "/api/heartbeat":
            query = urllib.parse.parse_qs(parsed.query)
            CLIENTS.heartbeat(str(query.get("client", [""])[0]))
            self._send_json(HTTPStatus.OK, {"ok": True})
            return
        if parsed.path == "/api/logs":
            query = urllib.parse.parse_qs(parsed.query)
            try:
                after = int(query.get("after", ["0"])[0])
            except ValueError:
                after = 0
            self._send_json(HTTPStatus.OK, {"ok": True, "lines": CONTROLLER.log.after(after)})
            return
        if parsed.path == "/api/replay/catalog":
            self._send_json(HTTPStatus.OK, {"ok": True, "datasets": replay_catalog()})
            return
        if parsed.path == "/api/record/catalog":
            self._send_json(HTTPStatus.OK, {"ok": True, "sessions": record_resume_catalog()})
            return
        if parsed.path.startswith("/api/camera/stream/"):
            name = parsed.path.rsplit("/", 1)[-1]
            stream = CONTROLLER.cameras.streams.get(name)
            if stream is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            frame_number = 0
            try:
                while not SERVER_SHUTDOWN_STARTED.is_set():
                    frame_number, frame = stream.wait_frame(frame_number)
                    if frame is None:
                        if stream.process is None or stream.process.poll() is not None:
                            break
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if parsed.path.startswith("/api/record/frame/"):
            name = parsed.path.rsplit("/", 1)[-1]
            if name not in {"wrist", "front"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            path = RECORD_GUI_DIR / f"{name}.jpg"
            if not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        if not self._local_client():
            self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "message": "로컬 PC에서만 사용할 수 있습니다."})
            return
        payload = self._read_json()
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/doctor":
            ok, message = CONTROLLER.start_doctor()
        elif path == "/api/mode":
            try:
                episode_time = int(payload.get("episode_time", 20))
            except (TypeError, ValueError):
                episode_time = 0
            ok, message = CONTROLLER.request_mode(
                str(payload.get("target", "")),
                str(payload.get("tracking", "joint")),
                episode_time,
            )
        elif path == "/api/camera/start":
            ok, message = CONTROLLER.cameras.start(str(payload.get("camera", "")))
        elif path == "/api/camera/stop":
            ok, message = CONTROLLER.cameras.stop(str(payload.get("camera", "")))
        elif path == "/api/stop":
            ok, message = CONTROLLER.stop()
        elif path == "/api/record-key":
            ok, message = CONTROLLER.send_record_key(str(payload.get("key", "")))
        elif path == "/api/record/resume":
            ok, message = CONTROLLER.request_record_resume(str(payload.get("session", "")))
        elif path == "/api/replay":
            try:
                episode = int(payload.get("episode", -1))
            except (TypeError, ValueError):
                episode = -1
            ok, message = CONTROLLER.request_replay(str(payload.get("dataset", "")), episode)
        elif path == "/api/c31/start":
            ok, message = CONTROLLER.begin_c31()
        elif path == "/api/c31/continue":
            ok, message = CONTROLLER.c31_continue(str(payload.get("stage", "")))
        elif path == "/api/c19/start":
            ok, message = CONTROLLER.begin_c19()
        elif path == "/api/c19/continue":
            ok, message = CONTROLLER.c19_continue()
        elif path == "/api/c1/start":
            ok, message = CONTROLLER.begin_c1()
        elif path == "/api/c1/continue":
            ok, message = CONTROLLER.c1_continue(str(payload.get("stage", "")))
        elif path == "/api/restart":
            # 실행 중인 로봇 모드를 정리하고 GUI 서버 프로세스를 새로 시작한다.
            restart_server()
            ok, message = True, "GUI 서버를 재시작합니다. 잠시 후 화면이 자동으로 다시 연결됩니다."
        elif path == "/api/shutdown":
            # launch script가 종료될 때 호출한다. 외부 명령 입력을 허용하지 않고,
            # 현재 프로젝트가 시작한 프로세스만 종료한다.
            request_server_shutdown("실행기 종료")
            ok, message = True, "GUI 종료와 현재 모드 정리를 시작했습니다."
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "없는 기능입니다."})
            return
        self._send_json(HTTPStatus.OK if ok else HTTPStatus.CONFLICT, {"ok": ok, "message": message, "data": CONTROLLER.snapshot()})

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        candidate = (STATIC_ROOT / relative).resolve()
        if STATIC_ROOT not in candidate.parents and candidate != STATIC_ROOT:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        mime = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".png": "image/png",
        }.get(candidate.suffix, "application/octet-stream")
        data = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="pi0 xArm7 로컬 GUI 제어판")
    parser.add_argument("--port", type=int, default=8765, help="로컬 웹 포트")
    parser.add_argument("--open-browser", action="store_true", help="시작 뒤 기본 브라우저 열기")
    args = parser.parse_args()

    if not RUN_SCRIPT.is_file() or not DOCTOR_SCRIPT.is_file():
        raise SystemExit("필수 프로젝트 파일을 찾지 못했습니다. pi0_sehwan 폴더 구조를 확인하세요.")
    global SERVER, SERVER_PORT
    SERVER_PORT = args.port
    server = ThreadingHTTPServer(("127.0.0.1", args.port), GuiRequestHandler)
    SERVER = server

    def handle_shutdown_signal(signum: int, _frame: object) -> None:
        request_server_shutdown(f"운영체제 종료 신호({signum})")

    # 앱 실행기나 사용자가 GUI 프로세스를 종료해도 자식 로봇 모드를 같은 방식으로
    # 정리한다. 이전에는 SIGINT/SIGTERM 상황에서 서버만 남을 수 있었다.
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    url = f"http://127.0.0.1:{args.port}"
    add_log_and_watch(f"[GUI] 로컬 제어판 주소: {url}")
    print(f"pi0 xArm7 GUI가 실행되었습니다: {url}")
    print("제어판 창을 닫으면 실행 중인 현재 모드와 GUI 서버가 함께 정리됩니다.")
    if args.open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    threading.Thread(target=watch_gui_clients, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGUI 서버를 종료합니다.")
    finally:
        # Ctrl+C로 종료한 경우도 동일하게 현재 프로젝트의 자식 프로세스를 정리한다.
        CONTROLLER.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
