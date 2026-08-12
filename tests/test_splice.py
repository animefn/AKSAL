"""Multi-chunk edits, and the boundaries they create.

A TV edit often keeps the opening and the final chorus while dropping the middle,
so the splice map has several chunks. Every one of these cases produced a
plausible-looking wrong answer before it was handled.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aksal import timing
from aksal.locate import Segment, SpliceError, validate
from aksal.project import Project

QUIET = lambda *a, **k: None      # noqa: E731


def proj(*segments, **kw):
    return Project(base=Path("x"), video=Path("v.mkv"), mode="reference",
                   align_audio=Path("a.wav"), segments=list(segments), **kw)


# "verse 1, then the final chorus": the middle of the song is not in the video.
TWO_CHUNK = (Segment(0, 30, 40, 70, 40, support=900),
             Segment(90, 120, 70, 100, -20, support=900))


# --- splice map validation ----------------------------------------------------

def test_zero_length_chunk_is_rejected():
    with pytest.raises(SpliceError, match="zero or negative"):
        validate([Segment(10, 10, 40, 70, 30)], log=QUIET)


def test_negative_length_chunk_is_rejected():
    with pytest.raises(SpliceError, match="zero or negative"):
        validate([Segment(30, 10, 40, 70, 30)], log=QUIET)


def test_chunks_overlapping_in_video_time_are_rejected():
    with pytest.raises(SpliceError, match="overlap"):
        validate([Segment(0, 30, 40, 70, 40),
                  Segment(40, 70, 60, 90, 20)], log=QUIET)


def test_a_reordering_edit_is_refused_not_mangled():
    """Video order and song order disagreeing is something nothing downstream
    can express, so it must fail loudly rather than emit subtitles that run
    backwards through the lyrics."""
    with pytest.raises(SpliceError, match="reorders"):
        validate([Segment(90, 120, 40, 70, -50),
                  Segment(0, 30, 70, 100, 70)], log=QUIET)


def test_valid_multi_chunk_map_passes_and_is_sorted():
    out = validate([TWO_CHUNK[1], TWO_CHUNK[0]], log=QUIET)
    assert [s.ep_start for s in out] == [40, 70]


def test_weak_support_warns_without_failing():
    msgs = []
    out = validate([Segment(0, 30, 40, 70, 40, support=5)], log=msgs.append)
    assert len(out) == 1
    assert any("separately mixed" in m for m in msgs)


def test_empty_map_is_not_an_error():
    assert validate([], log=QUIET) == []


# --- straddling a cut ---------------------------------------------------------

def test_a_line_spanning_a_cut_is_detected():
    """Its middle syllables are not in the video at all. Mapping the ends
    independently gives a short, plausible subtitle covering words never
    broadcast."""
    p = proj(*TWO_CHUNK)
    assert p.spans_cut(28.0, 92.0) is True


def test_a_line_inside_one_chunk_does_not_count_as_spanning():
    p = proj(*TWO_CHUNK)
    assert p.spans_cut(5.0, 25.0) is False
    assert p.spans_cut(95.0, 115.0) is False


def test_a_line_in_the_removed_middle_maps_nowhere():
    p = proj(*TWO_CHUNK)
    assert p.to_video(50.0) is None
    assert p.spans_cut(50.0, 60.0) is False      # neither end is in a chunk


def test_segment_lookup_by_each_clock():
    p = proj(*TWO_CHUNK)
    assert p.segment_at_ref(15.0) is TWO_CHUNK[0]
    assert p.segment_at_ref(105.0) is TWO_CHUNK[1]
    assert p.segment_at_ref(60.0) is None
    assert p.segment_at_video(55.0) is TWO_CHUNK[0]
    assert p.segment_at_video(85.0) is TWO_CHUNK[1]


def test_mapping_is_per_chunk_not_global():
    p = proj(*TWO_CHUNK)
    assert p.to_video(15.0) == pytest.approx(55.0)     # +40
    assert p.to_video(105.0) == pytest.approx(85.0)    # -20


# --- timing source seam -------------------------------------------------------

def test_video_source_offsets_by_its_slice_start():
    p = proj(*TWO_CHUNK)
    src = timing.from_video(p, first=40.0, last=100.0, pad=2.0)
    assert src.name == "video"
    assert src.start == pytest.approx(38.0)
    assert src.to_video(0.0) == pytest.approx(38.0)
    assert src.to_audio(38.0) == pytest.approx(0.0)


def test_video_source_decodes_only_the_span_the_lines_cover():
    """An acoustic model over a whole episode is minutes of work for audio with
    no lyrics to match."""
    p = proj(*TWO_CHUNK)
    src = timing.from_video(p, first=40.0, last=100.0, pad=2.0)
    assert src.dur == pytest.approx(64.0)


def test_video_source_never_starts_before_zero():
    p = proj(*TWO_CHUNK)
    src = timing.from_video(p, first=0.5, last=10.0, pad=2.0)
    assert src.start == 0.0


def test_reference_source_uses_the_first_chunk_offset():
    p = proj(*TWO_CHUNK)
    src = timing.from_reference(p)
    assert src.name == "reference"
    assert src.offset == pytest.approx(40.0)


def test_reference_source_on_an_empty_map_is_identity():
    src = timing.from_reference(proj())
    assert src.offset == 0.0
    assert src.to_video(12.0) == pytest.approx(12.0)


def test_the_two_sources_get_different_cache_names():
    """Emissions from the video and from the reference must never collide."""
    p = proj(*TWO_CHUNK)
    a = timing.from_video(p, 40.0, 100.0).cache_tag
    b = timing.from_reference(p).cache_tag
    assert a != b


def test_describe_reports_the_padded_span_actually_decoded():
    """The padded span is what gets decoded, so that is what should be shown."""
    p = proj(*TWO_CHUNK)
    text = timing.from_video(p, 40.0, 100.0, pad=2.0).describe()
    assert "38.0-102.0s" in text
    assert "video" in text
