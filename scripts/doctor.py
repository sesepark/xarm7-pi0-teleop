#!/usr/bin/env python3
"""pi0/xArm7 시연 환경의 읽기 전용 건강 진단.

이 스크립트는 모션 명령, 모드 변경, 오류 해제, 그리퍼 명령을 보내지 않는다.
확인하는 것은 Python 패키지, USB 권한, 카메라 인식, GPU, 네트워크와 xArm의
현재 상태뿐이다.
"""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROBOT_IP = "192.168.0.240"
GELLO_PORT = Path("/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTATZQHL-if00-port0")
EXPECTED_CAMERA_SERIAL = "348522072411"


@dataclass
class CheckResult:
    name: str
    status: str  # OK, WARN, FAIL
    detail: str
    solution: str = ""


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def command_output(command: list[str], timeout: int = 10) -> tuple[bool, str]:
    """외부 명령을 실행하되, 실패해도 doctor 전체는 계속 진행한다."""
    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return completed.returncode == 0, completed.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def check_python_and_packages() -> list[CheckResult]:
    results: list[CheckResult] = []
    version = sys.version_info
    python_ok = (version.major, version.minor) == (3, 10)
    results.append(
        CheckResult(
            "Python 3.10",
            "OK" if python_ok else "FAIL",
            f"현재 Python: {version.major}.{version.minor}.{version.micro}",
            "" if python_ok else "source scripts/activate_uf_lerobot.sh 후 다시 실행하세요.",
        )
    )

    required = {
        "xarm-python-sdk": "xArm 제어 SDK",
        "lerobot": "데이터 수집 프레임워크",
        "gello": "GELLO 관절값 드라이버",
        "dynamixel-sdk": "Dynamixel 통신 라이브러리",
        "pyrealsense2": "RealSense Python 카메라 드라이버",
    }
    for package, description in required.items():
        version_text = package_version(package)
        results.append(
            CheckResult(
                description,
                "OK" if version_text else "FAIL",
                f"{package} {version_text}" if version_text else f"{package} 미설치",
                "환경 설치가 끝나지 않았습니다. 안내 문서의 설치 단계를 확인하세요." if not version_text else "",
            )
        )
    return results


def check_gello_port() -> CheckResult:
    if not GELLO_PORT.exists():
        return CheckResult(
            "GELLO USB",
            "FAIL",
            f"장치 경로가 없습니다: {GELLO_PORT}",
            "GELLO USB와 전원을 확인한 뒤 다시 연결하세요.",
        )
    readable = os.access(GELLO_PORT, os.R_OK)
    writable = os.access(GELLO_PORT, os.W_OK)
    if readable and writable:
        return CheckResult("GELLO USB 권한", "OK", f"읽기/쓰기 가능: {GELLO_PORT}")
    return CheckResult(
        "GELLO USB 권한",
        "FAIL",
        f"장치는 보이지만 접근 권한이 없습니다: {GELLO_PORT}",
        "sudo usermod -aG dialout $USER 실행 후 Ubuntu에서 로그아웃/로그인하세요.",
    )


def check_camera() -> CheckResult:
    if shutil.which("rs-enumerate-devices") is None:
        return CheckResult(
            "RealSense D435i",
            "WARN",
            "rs-enumerate-devices 명령이 없습니다.",
            "RealSense 도구 또는 ROS RealSense 패키지 설치 상태를 확인하세요.",
        )
    ok, output = command_output(["rs-enumerate-devices", "-s"])
    if ok and EXPECTED_CAMERA_SERIAL in output:
        return CheckResult("RealSense D435i", "OK", f"예상 serial {EXPECTED_CAMERA_SERIAL} 인식")
    return CheckResult(
        "RealSense D435i",
        "FAIL",
        "예상 serial을 찾지 못했습니다.",
        "USB 연결, 전원, camera serial을 확인하세요.",
    )


def check_gpu() -> CheckResult:
    if shutil.which("nvidia-smi") is None:
        return CheckResult("NVIDIA GPU", "WARN", "nvidia-smi 명령이 없습니다.")
    ok, output = command_output(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], timeout=10
    )
    return CheckResult("NVIDIA GPU", "OK" if ok else "WARN", output or "GPU 정보를 읽지 못했습니다.")


def can_connect(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_robot_network() -> CheckResult:
    web_ok = can_connect(ROBOT_IP, 18333)
    motion_port_ok = can_connect(ROBOT_IP, 30001)
    if web_ok and motion_port_ok:
        return CheckResult("xArm 네트워크", "OK", f"{ROBOT_IP}: 웹 UI와 제어 포트 연결 가능")
    return CheckResult(
        "xArm 네트워크",
        "FAIL",
        f"웹 UI={web_ok}, 제어 포트={motion_port_ok}",
        "로봇과 PC가 같은 유선 네트워크(192.168.0.x)에 있는지 확인하세요.",
    )


def check_robot_read_only() -> CheckResult:
    """SDK 연결 후 getter만 호출한다. motion_enable/set_mode/set_state는 호출하지 않는다."""
    try:
        from xarm.wrapper import XArmAPI

        arm = XArmAPI(ROBOT_IP, do_not_open=True)
        arm.connect()
        if not arm.connected:
            return CheckResult("xArm 읽기 전용 상태", "FAIL", "SDK 연결에 실패했습니다.")
        _, err_warn = arm.get_err_warn_code()
        _, joints = arm.get_servo_angle(is_radian=True)
        _, pose = arm.get_position(is_radian=True)
        arm.disconnect()
        status = "OK" if err_warn == [0, 0] else "WARN"
        return CheckResult(
            "xArm 읽기 전용 상태",
            status,
            f"오류/경고={err_warn}, 관절(rad)={['%.3f' % value for value in joints]}, TCP(mm,rad)={['%.3f' % value for value in pose]}",
            "오류/경고가 0이 아니면 로봇 웹 UI에서 원인을 먼저 확인하세요." if status != "OK" else "",
        )
    except Exception as exc:  # 장치/SDK 오류도 사람이 읽을 수 있게 보여준다.
        return CheckResult(
            "xArm 읽기 전용 상태",
            "FAIL",
            f"상태 읽기 실패: {type(exc).__name__}: {exc}",
            "xarm-python-sdk와 로봇 네트워크를 확인하세요.",
        )


def print_result(result: CheckResult) -> None:
    icon = {"OK": "✅", "WARN": "⚠️", "FAIL": "❌"}[result.status]
    print(f"{icon} [{result.status}] {result.name}: {result.detail}")
    if result.solution:
        print(f"    해결 방법: {result.solution}")


def main() -> int:
    print("=" * 72)
    print("pi0/xArm7 시작 전 doctor 진단 (읽기 전용, 로봇을 움직이지 않음)")
    print("=" * 72)
    checks = [
        *check_python_and_packages(),
        check_gello_port(),
        check_camera(),
        check_gpu(),
        check_robot_network(),
        check_robot_read_only(),
    ]
    for result in checks:
        print_result(result)
    failures = sum(result.status == "FAIL" for result in checks)
    warnings = sum(result.status == "WARN" for result in checks)
    print("-" * 72)
    print(f"결과: 실패 {failures}개, 경고 {warnings}개")
    print("FAIL이 0개여야 GELLO/카메라/로봇을 함께 사용하는 다음 단계로 진행합니다.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
