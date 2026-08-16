"""Acoustic-model names and command-line precedence.

The public name of the built-in model is its real Hugging Face repository ID.
Its unusual bare-checkpoint loading remains an implementation detail.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

DEFAULT_MODEL = "sakasegawa/japanese-wav2vec2-large-hiragana-ctc"


def resolve(model: str | None, timing: str | None,
            selection: str | None) -> tuple[str, str]:
    """Resolve the general model first, then role-specific overrides."""
    base = (model or DEFAULT_MODEL).strip()
    return ((timing or base).strip(), (selection or base).strip())


def decision_identity(spec: str) -> str:
    """Identity usable before loading model weights for saved decisions.

    Hub IDs are cache-first everywhere else in ASKAL, so once downloaded they
    are stable until the cache is explicitly replaced. Local models additionally
    include a recursive file manifest so editing weights at the same path
    invalidates prior decisions without loading the model.
    """
    value = spec.strip()
    local = value[len("hiragana-asr:"):].strip() \
        if value.startswith("hiragana-asr:") else value
    path = Path(local) if local else None
    if path is None or not path.exists():
        return f"spec:{value}"
    digest = hashlib.sha256()
    items = [path] if path.is_file() else sorted(
        item for item in path.rglob("*") if item.is_file())
    for item in items:
        stat = item.stat()
        name = item.name if path.is_file() else str(item.relative_to(path))
        digest.update(name.encode("utf-8"))
        digest.update(f":{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
    return f"local:{path.resolve()}@{digest.hexdigest()}"
