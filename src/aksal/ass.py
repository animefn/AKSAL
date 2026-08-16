"""Minimal ASS reading and writing.

Only what this tool needs: dialogue events with times and text, plus karaoke
`\\k` construction. Not a general ASS parser.
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

KTAG = re.compile(r"\{\\k[f]?(\d+)\}")
ANY_TAG = re.compile(r"\{[^}]*\}")

PROJECT_KEY = "; aksal-project:"

HEADER = """[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1080
YCbCr Matrix: TV.709
{info}
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

STYLE_JP = ("Style: KARA-JP,Yu Gothic UI,72,&H00FFFFFF,&H000098FF,&H00202020,"
            "&H80000000,-1,0,0,0,100,100,0,0,1,4,1,8,60,60,54,1")
STYLE_RO = ("Style: KARA-RO,Arial,64,&H00FFFFFF,&H000098FF,&H00202020,"
            "&H80000000,-1,0,0,0,100,100,0,0,1,4,1,8,60,60,54,1")


@dataclass
class Event:
    start: float
    end: float
    text: str
    style: str = "KARA-JP"
    # A Comment line renders nothing but travels with the file, so a note about
    # a line stays attached to it in Aegisub instead of living in a log the
    # user closed. Used for readings the audio settled or could not settle.
    comment: bool = False
    layer: str = "0"
    name: str = ""
    margin_l: str = "0"
    margin_r: str = "0"
    margin_v: str = "0"
    effect: str = ""

    @property
    def plain(self) -> str:
        """Text with all override tags stripped."""
        return ANY_TAG.sub("", self.text).strip()


def ts(t: float) -> str:
    centiseconds = max(int(round(t * 100)), 0)
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, cs = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{cs:02}"


def parse_ts(v: str) -> float:
    parts = v.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"bad ASS timestamp: {v!r}")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def read(path: Path) -> list[Event]:
    events: list[Event] = []
    fields = ["Layer", "Start", "End", "Style", "Name", "MarginL",
              "MarginR", "MarginV", "Effect", "Text"]
    in_events = False
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line.startswith("["):
            in_events = line.casefold() == "[events]"
            continue
        if in_events and line.casefold().startswith("format:"):
            fields = [field.strip() for field in line.split(":", 1)[1].split(",")]
            continue
        if not in_events or not line.casefold().startswith("dialogue:"):
            continue
        values = line.split(":", 1)[1].lstrip().split(",", len(fields) - 1)
        if len(values) != len(fields):
            continue
        row = {field.casefold(): value for field, value in zip(fields, values)}
        try:
            events.append(Event(
                start=parse_ts(row["start"]), end=parse_ts(row["end"]),
                style=row.get("style", "KARA-JP").strip(),
                text=row.get("text", ""), layer=row.get("layer", "0"),
                name=row.get("name", ""), margin_l=row.get("marginl", "0"),
                margin_r=row.get("marginr", "0"),
                margin_v=row.get("marginv", "0"), effect=row.get("effect", ""),
            ))
        except (KeyError, ValueError):
            continue
    return sorted(events, key=lambda e: e.start)


def read_project_stamp(path: Path) -> Path | None:
    """Recover the work directory phase 1 stamped into a lines file.

    Belt-and-braces only: phase 2 can also derive the project from the file
    name, so losing this to an editor that drops unknown header lines is not
    fatal.
    """
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line.startswith(PROJECT_KEY):
            value = line[len(PROJECT_KEY):].strip()
            if value:
                return Path(value)
        if line.startswith("[Events]"):
            break
    return None


def write(path: Path, events: list[Event], styles: list[str],
          project: Path | None = None) -> None:
    info = f"{PROJECT_KEY} {project}\n" if project else ""
    body = [HEADER.format(styles="\n".join(styles), info=info)]
    for e in events:
        kind = "Comment" if getattr(e, "comment", False) else "Dialogue"
        body.append(
            f"{kind}: {e.layer},{ts(e.start)},{ts(e.end)},{e.style},"
            f"{e.name},{e.margin_l},{e.margin_r},{e.margin_v},{e.effect},{e.text}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}-",
        suffix=".tmp", delete=False, newline="\n"
    ) as handle:
        handle.write("\n".join(body) + "\n")
        temporary = Path(handle.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def karaoke_text(units: list[str], starts: list[float],
                 line_start: float, line_end: float,
                 min_k: float = 0.05) -> str:
    """Build a `{\\kNN}` run that TILES the line exactly.

    ASS karaoke is relative: the highlight begins at the line's Start time and
    each `\\k` advances it. So the values must tile the whole line -- any gap
    before the first mora has to be spent as an empty leading cell, and the last
    cell has to reach the line end. Emitting each mora's own measured duration
    instead leaves the highlight drifting further out of sync with every rest.

    Boundaries are rounded once, in centiseconds relative to the line start, so
    accumulated rounding cannot pull the tiling off the line end.
    """
    n = len(units)
    if n == 0:
        return ""
    if len(starts) != n:
        # A positional pairing that has gone wrong. Left to run it either
        # produces a line whose cells are shifted by one, or an IndexError deep
        # in the tiling loop -- both a long way from the cause.
        raise ValueError(
            f"karaoke_text got {n} cell(s) but {len(starts)} start time(s); "
            "the aligner and the cell list have diverged")

    s = [min(max(x, line_start), line_end) for x in starts]
    for i in range(1, n):                       # monotonic, and singable
        s[i] = max(s[i], s[i - 1] + min_k)

    # If the minimum spacing overran the line, squeeze back into it.
    if s[-1] + min_k > line_end:
        span = (s[-1] + min_k) - s[0]
        avail = line_end - s[0]
        if span > 0 and avail > 0:
            s = [s[0] + (x - s[0]) * (avail / span) for x in s]

    total_cs = max(int(round((line_end - line_start) * 100)), 0)
    cs = [min(max(int(round((x - line_start) * 100)), 0), total_cs)
          for x in s]
    if total_cs >= n:
        # Reserve one centisecond for every remaining cell before accepting a
        # desired boundary. This keeps the sum exact without pushing the last
        # boundary beyond the event on very dense lines.
        previous = 0
        for i in range(n):
            lower = previous + (1 if i else 0)
            upper = total_cs - (n - i)
            cs[i] = min(max(cs[i], lower), upper)
            previous = cs[i]
    else:
        # ASS centiseconds cannot give N positive cells to a line shorter than
        # N centiseconds. Zero-length cells are preferable to extending the
        # karaoke beyond the subtitle event.
        cs = [round(i * total_cs / n) for i in range(n)]
    cs.append(total_cs)

    parts = []
    if cs[0] > 0:
        parts.append(f"{{\\k{cs[0]}}}")         # lead-in before the first mora
    for i, u in enumerate(units):
        parts.append(f"{{\\k{cs[i + 1] - cs[i]}}}{u}")
    return "".join(parts)


def karaoke_durations(text: str) -> list[int]:
    """Extract the `\\k` values from an existing karaoke line."""
    return [int(v) for v in KTAG.findall(text)]
