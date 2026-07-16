from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tts_more"))


def test_worker_status_uses_torch_uuid_without_spawning_nvidia_smi(monkeypatch) -> None:
    from app.workers import runtime

    class FakeCuda:
        is_available = staticmethod(lambda: True)
        current_device = staticmethod(lambda: 0)
        memory_allocated = staticmethod(lambda _index: 0)
        memory_reserved = staticmethod(lambda _index: 0)
        mem_get_info = staticmethod(lambda _index: (1024, 2048))
        get_device_properties = staticmethod(
            lambda index: types.SimpleNamespace(uuid=f"GPU-logical-{index}")
        )

    monkeypatch.setitem(
        sys.modules,
        "torch",
        types.SimpleNamespace(cuda=FakeCuda(), version=types.SimpleNamespace(cuda="12.8")),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ordinary worker status must not spawn nvidia-smi")
        ),
    )
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    runtime._DEVICE_UUID_CACHE.clear()

    status = runtime.worker_runtime_status(loaded=False, model=None)

    assert status["device_uuid"] == "GPU-logical-0"


def test_worker_status_uses_visible_uuid_when_torch_uuid_is_unavailable(monkeypatch) -> None:
    from app.workers import runtime

    class FakeCuda:
        is_available = staticmethod(lambda: True)
        current_device = staticmethod(lambda: 0)
        memory_allocated = staticmethod(lambda _index: 0)
        memory_reserved = staticmethod(lambda _index: 0)
        mem_get_info = staticmethod(lambda _index: (1024, 2048))
        get_device_properties = staticmethod(
            lambda _index: (_ for _ in ()).throw(RuntimeError("uuid unavailable"))
        )

    monkeypatch.setitem(
        sys.modules,
        "torch",
        types.SimpleNamespace(cuda=FakeCuda(), version=types.SimpleNamespace(cuda="12.8")),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ordinary worker status must not spawn nvidia-smi")
        ),
    )
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-abcdef")
    runtime._DEVICE_UUID_CACHE.clear()

    status = runtime.worker_runtime_status(loaded=False, model=None)

    assert status["device_uuid"] == "GPU-abcdef"
