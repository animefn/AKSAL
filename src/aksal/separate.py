"""Vocal isolation via demucs.

Opt-in (`--separate-audio`), because it was measured: over eight songs against
hand-timed karaoke it is a wash for syllable timing -- marginally better on
average, worse in the tail -- for about four times the runtime. Where it earns
its keep is a NOISY mix: SFX and dialogue over the song, or a master where the
instruments bury the voice.

Runs IN-PROCESS through demucs' Python API, and the history of that choice is
worth keeping. The first version shelled out to `sys.executable -m demucs`,
which works from a normal install and breaks in the packaged build in the
worst possible way: inside a PyInstaller executable `sys.executable` is
aksal.exe itself, so the tool silently re-launched ITSELF with demucs'
arguments, failed, and blamed demucs -- with an error message that pointed at
a flag that no longer existed. An import either works or raises something
honest, and it is the same code path packaged and unpackaged.
"""
from __future__ import annotations

from pathlib import Path
import tempfile

MODEL = "htdemucs"


def separate(source: Path, target: Path, device: str = "cpu",
             force: bool = False, log=print) -> Path:
    """Isolate vocals to `target`, running demucs if it is not already there.

    The separated stem is cached at the flat sibling path the rest of the tool
    uses; a re-run costs nothing. demucs' own model weights (~80 MB) download
    on first use into the torch cache, once, shared across every song.
    """
    from . import artifacts

    metadata = target.with_suffix(target.suffix + ".json")
    identity = artifacts.derived_audio_identity(
        source, operation=artifacts.SEPARATION_PIPELINE,
        options={"model": MODEL},
    )
    if (target.exists() and not force
            and artifacts.metadata_matches(metadata, identity)):
        log(f"  using cached stem: {target.name}")
        return target

    try:
        from demucs.api import Separator, save_audio
    except ImportError as exc:
        raise RuntimeError(
            "vocal separation needs demucs, which this copy of AKSAL does not "
            "have.\n"
            "    pip install demucs\n"
            "  Separation is optional -- simply dropping --separate-audio "
            "runs the normal path,\n"
            "  which is what the published accuracy figures were measured "
            "on.") from exc

    log(f"  separating vocals ({MODEL}, {device}) -- this is the slow step")
    separator = Separator(model=MODEL, device=device, progress=True)
    _original, stems = separator.separate_audio_file(Path(source))
    if "vocals" not in stems:
        raise RuntimeError(
            f"demucs returned stems {sorted(stems)} but no 'vocals' for "
            f"{Path(source).name}")

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=target.parent, prefix=f".{target.stem}-", suffix=target.suffix,
        delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        save_audio(stems["vocals"], str(temporary),
                   samplerate=separator.samplerate)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    artifacts.atomic_write_json(metadata, identity)
    log(f"  vocal stem: {target.name}")
    return target
