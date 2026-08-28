#!/usr/bin/env python3
"""OpenPI π0 full fine-tuning 전용 GPU 메모리 차단 검사."""

from __future__ import annotations

import shutil
import subprocess
import sys


MIN_VRAM_MIB = 70 * 1024  # OpenPI 공식 full fine-tuning 요구량: 70GB 초과


def main() -> int:
    if shutil.which("nvidia-smi") is None:
        print("❌ [중단] nvidia-smi를 찾지 못했습니다. GPU 노드 안에서 실행하세요.")
        return 1
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        print("❌ [중단] NVIDIA GPU 정보를 읽지 못했습니다. GPU 할당 상태를 확인하세요.")
        return 1

    devices = []
    for line in result.stdout.strip().splitlines():
        name, memory = [item.strip() for item in line.rsplit(",", maxsplit=1)]
        devices.append((name, int(memory)))
    print("=" * 72)
    print("OpenPI π0 full fine-tuning GPU 검사")
    print(f"필요 조건: GPU 한 장의 VRAM이 {MIN_VRAM_MIB} MiB(약 70GB) 초과")
    for index, (name, memory) in enumerate(devices):
        print(f"GPU {index}: {name} / {memory} MiB ({memory / 1024:.1f} GiB)")
    if max(memory for _, memory in devices) <= MIN_VRAM_MIB:
        print("❌ [중단] 할당 GPU가 full fine-tuning 요구량에 못 미칩니다.")
        print("   이 경우 LoRA로 바꾸거나 80GB급 A100/H100 GPU를 요청해야 합니다.")
        return 1
    print("✅ [통과] full fine-tuning을 시도할 수 있는 VRAM 조건입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
