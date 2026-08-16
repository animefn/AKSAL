"""Stable identities for derived audio and acoustic-model artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

import numpy as np


CACHE_SCHEMA = 1
AUDIO_PIPELINE = "mono-f32-16k-v2"
SEPARATION_PIPELINE = "demucs-v1"


def file_identity(path: Path) -> dict[str, object]:
    """Cheap but mutation-sensitive identity for a potentially huge media file."""
    resolved = path.resolve()
    stat = resolved.stat()
    return {
        "path": os.path.normcase(str(resolved)),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def array_identity(samples: np.ndarray) -> str:
    """Hash the exact conditioned waveform used to produce emissions."""
    contiguous = np.ascontiguousarray(samples, dtype=np.float32)
    digest = hashlib.sha256()
    digest.update(str(contiguous.shape).encode("ascii"))
    digest.update(memoryview(contiguous).cast("B"))
    return digest.hexdigest()


def stable_key(kind: str, **values: object) -> str:
    payload = {"schema": CACHE_SCHEMA, "kind": kind, **values}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def emissions_key(model_identity: str, frame_stride: int,
                  samples: np.ndarray,
                  waveform_identity: str | None = None) -> str:
    return stable_key(
        "emissions",
        model=model_identity,
        frame_stride=frame_stride,
        waveform=waveform_identity or array_identity(samples),
        audio_pipeline=AUDIO_PIPELINE,
    )


def derived_audio_identity(source: Path, *, operation: str,
                           options: dict[str, object]) -> dict[str, object]:
    return {
        "schema": CACHE_SCHEMA,
        "operation": operation,
        "source": file_identity(source),
        "options": options,
    }


def metadata_matches(path: Path, expected: dict[str, object]) -> bool:
    try:
        return json.loads(path.read_text(encoding="utf-8")) == expected
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}-",
        suffix=".tmp", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
