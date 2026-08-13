"""Decoding and signal conditioning.

Everything downstream works on 16 kHz mono float32 -- what the CTC acoustic
model expects, and plenty for fingerprinting.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

SR = 16000

# STFT settings for fingerprinting. These MUST match between reference and
# episode or the frame-offset arithmetic in fingerprint.py is meaningless.
N_FFT = 1024
HOP = 256                      # 16 ms per frame at 16 kHz
FRAME_SEC = HOP / SR


def decode(path: Path, start: float | None = None, dur: float | None = None,
           sr: int = SR) -> np.ndarray:
    """Decode a media file's first audio stream to mono float32 at `sr`."""
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(path)]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-map", "0:a:0", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed on {path.name}:\n{proc.stderr.decode(errors='replace')}")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def highpass(y: np.ndarray, cutoff: float = 80.0, sr: int = SR) -> np.ndarray:
    """Remove sub-bass. After source separation this is mostly bleed, and it
    contributes nothing the acoustic model can use."""
    from scipy.signal import butter, sosfiltfilt

    sos = butter(4, cutoff / (sr / 2), btype="highpass", output="sos")
    return sosfiltfilt(sos, y).astype(np.float32)


def normalize(y: np.ndarray, target_rms: float = 0.06) -> np.ndarray:
    """Scale the whole signal to a fixed RMS.

    Deliberately global rather than per-window: the feature extractor normalises
    each window it is handed, so a quiet window and a loud one get pushed to the
    same level and the model sees an inconsistent signal across window seams.
    Normalising once up front keeps the relative dynamics intact.
    """
    rms = float(np.sqrt(np.mean(np.square(y))))
    if rms < 1e-8:
        return y
    out = y * (target_rms / rms)
    peak = float(np.max(np.abs(out)))
    if peak > 1.0:
        out /= peak
    return out.astype(np.float32)


def prepare(path: Path, start: float | None = None, dur: float | None = None,
            condition: bool = True) -> np.ndarray:
    """Decode + condition, the standard path for anything fed to the aligner.

    `start`/`dur` matter more than they look: aligning a hand-made subtitle
    against a full episode would otherwise compute emissions over 24 minutes of
    audio, most of it dialogue the aligner has no text for.
    """
    y = decode(path, start=start, dur=dur)
    if not condition:
        return y
    return normalize(highpass(y))


def extract_wav(src: Path, dest: Path, start: float | None = None,
                dur: float | None = None, sr: int = SR) -> Path:
    """Write a mono wav slice, for tools that need a file rather than an array."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-map", "0:a:0", "-ac", "1", "-ar", str(sr), str(dest)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed slicing {src.name}:\n"
            f"{proc.stderr.decode(errors='replace')}")
    return dest


def envelope(y: np.ndarray, hop: int = 160, sr: int = SR) -> np.ndarray:
    """Short-time RMS envelope, used for onset snapping (10 ms hop)."""
    n = len(y) // hop
    trimmed = y[:n * hop].reshape(n, hop)
    return np.sqrt(np.mean(np.square(trimmed), axis=1))


def logspec(y: np.ndarray) -> np.ndarray:
    """Log-magnitude STFT, shape (freq_bins, frames)."""
    from scipy.signal import stft

    _, _, Z = stft(y, fs=SR, nperseg=N_FFT, noverlap=N_FFT - HOP,
                   window="hann", boundary=None, padded=False)
    return np.log1p(np.abs(Z).astype(np.float32) * 1000.0)


def duration(path: Path) -> float | None:
    """Length in seconds via ffprobe, or None if it cannot be determined.

    Used to verify that an LRCLIB hit is the same recording as the reference
    track. Never raises: a missing duration means "cannot verify", which the
    caller treats as "do not use", and that is the safe direction.
    """
    import subprocess

    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30).stdout.strip()
        return float(out) if out else None
    except Exception:                                   # noqa: BLE001
        return None
