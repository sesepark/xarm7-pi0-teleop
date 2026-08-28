#!/usr/bin/env python3
"""Read-only validation for the local WebXR server setup."""

from __future__ import annotations

import argparse
import importlib.util
import ipaddress
import math
import socket
import ssl
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    finally:
        sock.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate WebXR dependencies, YAML and TLS"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--check-robot",
        action="store_true",
        help="Also connect read-only to xArm and validate error/start pose",
    )
    args = parser.parse_args()
    failed = False

    def ok(message: str) -> None:
        print(f"✅ [OK] {message}")

    def fail(message: str) -> None:
        nonlocal failed
        failed = True
        print(f"❌ [FAIL] {message}")

    for module in ("fastapi", "uvicorn", "websockets"):
        if importlib.util.find_spec(module):
            ok(f"Python dependency: {module}")
        else:
            fail(f"Python dependency missing: {module}")

    if not args.config.is_file():
        fail(f"Config does not exist: {args.config}")
        return 1
    data = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    robot = data.get("robot", {})
    teleop = data.get("teleop", {})
    if teleop.get("type") == "uf::webxr_teleop":
        ok("teleop.type is uf::webxr_teleop")
    else:
        fail(f"Unexpected teleop.type: {teleop.get('type')!r}")
    if robot.get("control_space") == "cartesian":
        ok("robot.control_space is cartesian")
    else:
        fail("WebXR requires robot.control_space: cartesian")
    if data.get("start_paused") is True or "dataset" in data:
        ok("Startup is operator-gated")
    else:
        fail("Teleop config must use start_paused: true")
    max_speed = float(robot.get("max_linear_velocity", 0))
    if 0 < max_speed <= 100:
        ok(f"Conservative initial TCP limit: {max_speed:.0f}mm/s")
    else:
        fail(f"Initial WebXR TCP limit must be 1..100mm/s, got {max_speed}")

    cert_path = Path(teleop.get("tls_certfile", "")).expanduser()
    key_path = Path(teleop.get("tls_keyfile", "")).expanduser()
    if not cert_path.is_file():
        fail(f"TLS certificate missing: {cert_path}")
    if not key_path.is_file():
        fail(f"TLS private key missing: {key_path}")
    if cert_path.is_file():
        cert = ssl._ssl._test_decode_cert(str(cert_path))
        expires = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc
        )
        if expires > datetime.now(timezone.utc):
            ok(f"TLS certificate valid until {expires.date().isoformat()}")
        else:
            fail(f"TLS certificate expired on {expires.date().isoformat()}")
        current_ip = local_ip()
        sans = {
            value
            for kind, value in cert.get("subjectAltName", ())
            if kind == "IP Address"
        }
        if current_ip in sans:
            ok(f"TLS SAN contains current LAN IP: {current_ip}")
        else:
            fail(
                f"TLS SAN does not contain current LAN IP {current_ip}; "
                "rerun ./scripts/setup_webxr_tls.sh"
            )
        for value in sans:
            ipaddress.ip_address(value)
    if cert_path.is_file() and key_path.is_file():
        cert_pub = subprocess.run(
            ["openssl", "x509", "-in", str(cert_path), "-pubkey", "-noout"],
            check=True,
            capture_output=True,
        ).stdout
        key_pub = subprocess.run(
            ["openssl", "pkey", "-in", str(key_path), "-pubout"],
            check=True,
            capture_output=True,
        ).stdout
        if cert_pub == key_pub:
            ok("TLS certificate and private key match")
        else:
            fail("TLS certificate and private key do not match")

    port = int(teleop.get("port", 8443))
    probe = socket.socket()
    try:
        probe.bind((teleop.get("host", "0.0.0.0"), port))
    except OSError as exc:
        fail(f"WebXR port {port} is unavailable: {exc}")
    else:
        ok(f"WebXR port {port} is available")
    finally:
        probe.close()

    if args.check_robot:
        try:
            from xarm.wrapper import XArmAPI

            arm = XArmAPI(robot.get("robot_ip", ""), do_not_open=True)
            arm.connect()
            if not arm.connected:
                fail(f"Could not connect to xArm: {robot.get('robot_ip')}")
            else:
                code, err_warn = arm.get_err_warn_code()
                if code == 0 and list(err_warn[:2]) == [0, 0]:
                    ok("xArm controller has no active error/warning")
                else:
                    fail(f"xArm error/warning readback: SDK={code}, values={err_warn}")
                code, joints = arm.get_servo_angle(is_radian=True)
                start_deg = robot.get("start_joints", [])
                if code != 0 or len(joints) < 7 or len(start_deg) != 7:
                    fail("Could not validate the seven xArm start joints")
                else:
                    errors = [
                        abs(math.degrees(actual) - float(target))
                        for actual, target in zip(joints[:7], start_deg)
                    ]
                    largest = max(errors)
                    if largest <= 2.0:
                        ok(f"xArm start pose is within 2 degrees (max {largest:.3f}°)")
                    else:
                        fail(
                            f"xArm start pose differs by {largest:.3f}°; "
                            "run ./run.sh init-position first"
                        )
            arm.disconnect()
        except Exception as exc:  # noqa: BLE001 - report any SDK/network validation failure
            fail(f"Read-only xArm validation failed: {type(exc).__name__}: {exc}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
