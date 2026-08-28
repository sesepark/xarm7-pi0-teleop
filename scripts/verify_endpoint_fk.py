#!/usr/bin/env python3
"""로컬 xArm7 FK를 컨트롤러 자체 FK와 대조하는 읽기 전용 검증 도구.

로봇을 절대 움직이지 않는다. get_forward_kinematics(컨트롤러 계산)와
get_position/get_servo_angle(현재 상태 getter)만 사용한다.

검사 항목
1. 현재 관절값에 대한 로컬 FK(TCP offset 포함) vs 컨트롤러 보고 현재 TCP
2. 관절 한계 내 무작위 자세 N개에 대한 로컬 FK vs 컨트롤러 get_forward_kinematics
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lerobot_robot_ufactory" / "src"))

from lerobot_robot_ufactory.devices.umi.vive_tracker.transformations import Transformations
from lerobot_robot_ufactory.teleoperators.gello_teleop.xarm7_kinematics import (
    fk_tcp_matrix_mm,
    fk_flange_matrix_m,
    tcp_offset_matrix_mm,
)

# xArm7 관절 한계(rad) — xarm_description 기준. 무작위 표본은 여유를 두고 축소한다.
JOINT_LIMITS = [
    (-2.0 * math.pi, 2.0 * math.pi),
    (-2.059, 2.0944),
    (-2.0 * math.pi, 2.0 * math.pi),
    (-0.19198, 3.927),
    (-2.0 * math.pi, 2.0 * math.pi),
    (-1.69297, math.pi),
    (-2.0 * math.pi, 2.0 * math.pi),
]


def rotation_gap_deg(R_a: np.ndarray, R_b: np.ndarray) -> float:
    cos_angle = np.clip((np.trace(R_a @ R_b.T) - 1.0) / 2.0, -1.0, 1.0)
    return math.degrees(float(np.arccos(cos_angle)))


def main() -> int:
    parser = argparse.ArgumentParser(description="로컬 FK vs 컨트롤러 FK 읽기 전용 대조")
    parser.add_argument("--config", type=Path,
                        default=Path(__file__).resolve().parents[1] / "config/xarm7_gello_teleop_endpoint.yaml")
    parser.add_argument("--samples", type=int, default=30, help="무작위 자세 표본 수")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    data = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    robot = data.get("robot", {})
    teleop = data.get("teleop", {})
    robot_ip = robot.get("robot_ip", "192.168.0.240")
    tcp_offset_cfg = list(teleop.get("tcp_offset", [0, 0, 172, 0, 0, 0]))
    offset_matrix = tcp_offset_matrix_mm(
        tcp_offset_cfg[:3] + [math.radians(v) for v in tcp_offset_cfg[3:6]]
    )

    from xarm.wrapper import XArmAPI

    arm = XArmAPI(robot_ip, do_not_open=True)
    arm.connect()
    failed = False
    try:
        # 1) 현재 자세 대조
        code, current_rad = arm.get_servo_angle(is_radian=True)
        assert code == 0, f"관절 읽기 실패 code={code}"
        code, current_pose = arm.get_position(is_radian=True)  # [mm, rad RPY]
        assert code == 0, f"TCP 읽기 실패 code={code}"
        local = fk_tcp_matrix_mm(current_rad[:7], offset_matrix)
        ctrl = Transformations.xyzrpy_to_rotation_matrix(
            current_pose[0], current_pose[1], current_pose[2],
            current_pose[3], current_pose[4], current_pose[5],
        )
        pos_gap = float(np.linalg.norm(local[:3, 3] - ctrl[:3, 3]))
        rot_gap = rotation_gap_deg(local[:3, :3], ctrl[:3, :3])
        print(f"[현재 자세] 로컬 FK vs 컨트롤러 TCP: 위치 {pos_gap:.3f}mm / 회전 {rot_gap:.4f}°")
        print("  (참고: endpoint 텔레옵 런타임은 컨트롤러 FK를 직접 사용하므로 이 오차의 영향을 받지 않습니다.")
        print("   이 값은 로컬 FK가 통신 장애 시 폴백으로 쓸 만한지의 기준입니다. 컨트롤러 FK에는")
        print("   공칭 DH에 없는 공장 캘리브레이션 보정이 포함되어 수 mm 차이가 정상입니다.)")
        if pos_gap > 15.0 or rot_gap > 1.0:
            print("❌ [FAIL] 현재 자세의 로컬 FK 오차가 폴백 허용값(15mm/1°)을 넘습니다.")
            failed = True

        # 2) 무작위 자세 대조 (컨트롤러가 FK만 계산, 모션 없음)
        rng = np.random.default_rng(args.seed)
        worst_pos, worst_rot = 0.0, 0.0
        flange_mode = None
        for _ in range(args.samples):
            q = [
                float(rng.uniform(low * 0.5, high * 0.5)) if abs(high) > 3.2 else
                float(rng.uniform(low + 0.05, high - 0.05))
                for (low, high) in JOINT_LIMITS
            ]
            code, ctrl_pose = arm.get_forward_kinematics(q, input_is_radian=True, return_is_radian=True)
            if code != 0:
                print(f"⚠️ 컨트롤러 FK code={code}, 표본 건너뜀")
                continue
            ctrl_T = Transformations.xyzrpy_to_rotation_matrix(*ctrl_pose)

            # 컨트롤러 FK가 TCP offset을 포함하는지/플랜지 기준인지 자동 판별
            local_tcp = fk_tcp_matrix_mm(q, offset_matrix)
            local_flange = fk_flange_matrix_m(q).copy()
            local_flange[:3, 3] *= 1000.0
            gap_tcp = float(np.linalg.norm(local_tcp[:3, 3] - ctrl_T[:3, 3]))
            gap_flange = float(np.linalg.norm(local_flange[:3, 3] - ctrl_T[:3, 3]))
            if flange_mode is None:
                flange_mode = gap_flange < gap_tcp
                print(f"[판별] 컨트롤러 get_forward_kinematics는 "
                      f"{'플랜지' if flange_mode else 'TCP(offset 포함)'} 기준입니다.")
            local_T = local_flange if flange_mode else local_tcp
            pos_gap = float(np.linalg.norm(local_T[:3, 3] - ctrl_T[:3, 3]))
            rot_gap = rotation_gap_deg(local_T[:3, :3], ctrl_T[:3, :3])
            worst_pos = max(worst_pos, pos_gap)
            worst_rot = max(worst_rot, rot_gap)

        print(f"[무작위 {args.samples}개 자세] 로컬 FK 최악 오차: 위치 {worst_pos:.3f}mm / 회전 {worst_rot:.4f}°")
        if worst_pos > 15.0 or worst_rot > 1.0:
            print("❌ [FAIL] 로컬 FK 오차가 폴백 허용값(15mm/1°)을 넘습니다.")
            failed = True
        if not failed:
            print("✅ 컨트롤러 FK 사용 가능 + 로컬 FK는 폴백 허용 범위 안입니다.")
    finally:
        arm.disconnect()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
