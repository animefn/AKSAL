"""Acoustic-model names and command-line precedence.

The public name of the built-in model is its real Hugging Face repository ID.
Its unusual bare-checkpoint loading remains an implementation detail.
"""
from __future__ import annotations

import hashlib


DEFAULT_MODEL = "sakasegawa/japanese-wav2vec2-large-hiragana-ctc"


def resolve(model: str | None, timing: str | None,
            selection: str | None) -> tuple[str, str]:
    """Resolve the general model first, then role-specific overrides."""
    base = (model or DEFAULT_MODEL).strip()
    return ((timing or base).strip(), (selection or base).strip())


def cache_tag(model: str) -> str:
    """Short stable tag which prevents emissions crossing model boundaries."""
    return hashlib.sha256(model.encode("utf-8")).hexdigest()[:12]
