from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class HardwareProfile:
    cpu_count: int
    cuda_available: bool
    cuda_device_count: int
    whisper_device: str
    whisper_compute_type: str
    whisper_model_size: str

    @property
    def label(self) -> str:
        accel = "cuda" if self.cuda_available else "cpu"
        return f"{accel}/{self.cpu_count}c"


def _detect_cuda() -> tuple[bool, int]:
    try:
        import ctranslate2

        count = int(ctranslate2.get_cuda_device_count())
        return count > 0, max(0, count)
    except Exception:  # CUDA probing is best-effort; CPU is always a valid fallback
        return False, 0


def detect_hardware_profile() -> HardwareProfile:
    """Pick Whisper defaults from the detected runtime capability."""
    cpu_count = max(1, os.cpu_count() or 1)
    cuda_available, cuda_count = _detect_cuda()

    if cuda_available:
        device, compute_type, model_size = "cuda", "float16", "large-v3-turbo"
    else:
        device, compute_type = "cpu", "int8"
        model_size = "small" if cpu_count <= 4 else "medium"

    return HardwareProfile(
        cpu_count=cpu_count,
        cuda_available=cuda_available,
        cuda_device_count=cuda_count,
        whisper_device=device,
        whisper_compute_type=compute_type,
        whisper_model_size=model_size,
    )
