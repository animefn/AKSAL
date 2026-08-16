"""Persist reading decisions and distinguish generated rows from user edits."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import jaconv

from . import readings
from .artifacts import atomic_write_json
from .reading_selector import LineSelection, WordDecision


SCHEMA_VERSION = 1
SCORER_ID = "complete-sentence-ctc-v1"
VALID_READING = re.compile(r"^[ぁ-ゖゝゞー\s]+$")


def _row_key(line: int, surface: str) -> str:
    return f"{line}\0{readings.normalise_surface(surface)}"


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return _empty()
    if data.get("schema_version") != SCHEMA_VERSION:
        return _empty()
    data.setdefault("decisions", {})
    data.setdefault("table_baseline", {})
    return data


def _empty() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "scorer": SCORER_ID,
        "decisions": {},
        "table_baseline": {},
    }


def save(path: Path, state: dict) -> None:
    state["schema_version"] = SCHEMA_VERSION
    state["scorer"] = SCORER_ID
    atomic_write_json(path, state)


def decision_key(*, surface: str, start: float, end: float,
                 model_identity: str, audio_identity: str,
                 choices: list[tuple[str, ...]], stage: str) -> str:
    payload = {
        "surface": readings.normalise_surface(surface),
        "start": float(start),
        "end": float(end),
        "model": model_identity,
        "audio": audio_identity,
        "choices": choices,
        "scorer": SCORER_ID,
        "analyser": readings.ENGINE,
        "stage": stage,
    }
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def get(state: dict, key: str) -> LineSelection | None:
    raw = state.get("decisions", {}).get(key)
    if not isinstance(raw, dict):
        return None
    try:
        decisions = tuple(WordDecision(
            index=int(item["index"]),
            surface=str(item["surface"]),
            current=str(item["current"]),
            chosen=str(item["chosen"]),
            ranked=tuple((str(reading), float(probability))
                         for reading, probability in item["ranked"]),
            confidence=str(item["confidence"]),
        ) for item in raw.get("decisions", []))
        return LineSelection(
            reading=str(raw["reading"]), decisions=decisions,
            combinations=int(raw["combinations"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def put(state: dict, key: str, selection: LineSelection, stage: str) -> None:
    state.setdefault("decisions", {})[key] = {
        "stage": stage,
        "reading": selection.reading,
        "combinations": selection.combinations,
        "decisions": [
            {
                "index": item.index,
                "surface": item.surface,
                "current": item.current,
                "chosen": item.chosen,
                "ranked": item.ranked,
                "confidence": item.confidence,
            }
            for item in selection.decisions
        ],
    }


def prune_stage(state: dict, stage: str, active_keys: set[str]) -> None:
    decisions = state.setdefault("decisions", {})
    state["decisions"] = {
        key: value for key, value in decisions.items()
        if value.get("stage") != stage or key in active_keys
    }


@dataclass
class ManualOverrides:
    by_line: dict[tuple[int, str], str]
    by_surface: dict[str, str]

    def __len__(self) -> int:
        return len(self.by_line)

    def get_for(self, line: int, surface: str) -> str | None:
        key = readings.normalise_surface(surface)
        return self.by_line.get((line, key), self.by_surface.get(key))

    def contains_row(self, line: int, surface: str) -> bool:
        return self.get_for(line, surface) is not None


def manual_overrides(table: Path, state: dict) -> ManualOverrides:
    """Return only TSV readings changed since ASKAL last generated the file."""
    if not table.exists():
        return ManualOverrides({}, {})
    baseline = state.get("table_baseline", {})
    by_line: dict[tuple[int, str], str] = {}
    surface_values: dict[str, set[str]] = {}
    surface_rows: dict[str, int] = {}
    for raw in table.read_text(encoding="utf-8-sig").splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        columns = raw.split("\t")
        if len(columns) < 4:
            continue
        try:
            line_number = int(columns[0])
        except ValueError:
            continue
        surface = readings.normalise_surface(columns[2])
        surface_rows[surface] = surface_rows.get(surface, 0) + 1
        reading = jaconv.kata2hira(
            unicodedata.normalize("NFKC", columns[3])).strip()
        if reading and baseline.get(_row_key(line_number, surface)) != reading:
            if not VALID_READING.fullmatch(reading):
                raise SystemExit(
                    f"invalid reading on row {line_number} of {table}: "
                    f"{reading!r}. Use hiragana and spaces only.")
            by_line[(line_number, surface)] = reading
            surface_values.setdefault(surface, set()).add(reading)
    # A unique reading remains usable if the user reordered the ASS. When two
    # identical surfaces were deliberately given different readings, only the
    # stable aksal-line identity may choose between them.
    by_surface = {
        surface: next(iter(values))
        for surface, values in surface_values.items()
        if len(values) == 1 and surface_rows.get(surface) == 1
    }
    return ManualOverrides(by_line, by_surface)


def update_table_baseline(state: dict,
                          rows: list[tuple[int, str, str, str]],
                          manual: ManualOverrides | None = None) -> None:
    """Record generated values while retaining the baseline under user edits."""
    previous = state.get("table_baseline", {})
    baseline: dict[str, str] = {}
    for line, _flag, surface, reading in rows:
        key = readings.normalise_surface(surface)
        row_key = _row_key(line, key)
        if manual and manual.contains_row(line, key) and row_key in previous:
            baseline[row_key] = previous[row_key]
        else:
            baseline[row_key] = reading
    state["table_baseline"] = baseline
