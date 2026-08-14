"""AKSAL -- AFN Karaoke Syllable Aligner for Lyrics.

Two-phase karaoke timing for any song in a video.

    phase1   video + lyrics (+ optional reference track)  ->  timed LINES
             ... you fix the lines in Aegisub ...
    phase2   corrected lines                              ->  JP + Romaji karaoke

Phase 2 re-aligns inside each line window you approved, so your corrections are
hard constraints rather than suggestions.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import align as A
from . import ass, locate, lyrics as lyrics_mod, moras, readings, romaji, separate
from . import timing
from . import audio as audio_mod
from .audio import envelope, prepare
from . import project as project_mod
from .project import Project

MAX_HOLD = 2.0          # longest a single unit may be held before it is a rest

# Slack around a --song-start hint when searching for the song. A hint only
# bounds the search -- the fingerprint match decides the actual timing -- so
# being a minute out should cost nothing.
SEARCH_MARGIN = 120.0

# The fastest anyone actually sings. Measured across the test set, sung moras
# bottom out around 0.10 s; nothing real goes below it for a whole song.
MIN_SEC_PER_MORA = 0.10


def check_fits_window(n_units: int, window: float, log=print) -> None:
    """Refuse a lyric sheet that cannot physically fit the window.

    This is the one combination that never works: a FULL lyric sheet with no
    reference track. Forced alignment cannot express "this line is not sung" --
    every token must be consumed -- so handed twice the text the cut contains it
    does not fail, it distributes the surplus across instrumental passages and
    returns a confident, wrong answer. Measured against hand-timed karaoke that
    produced medians of 3-22 seconds, with no signal that anything was wrong.

    With a reference track the question never arises: fingerprinting decides
    which chunks of the song are present before any alignment runs.

    So the check is a physical one. If the sheet needs more time than the window
    has, at the fastest anyone sings, the sheet is not the text of this cut.
    """
    if window <= 0 or n_units <= 0:
        return
    need = n_units * MIN_SEC_PER_MORA
    if need <= window:
        return
    raise SystemExit(
        f"these lyrics cannot fit this window.\n\n"
        f"  {n_units} moras need at least {need:.0f}s at the fastest anyone\n"
        f"  sings ({MIN_SEC_PER_MORA:.2f}s each), but the window is {window:.0f}s.\n\n"
        "  This is almost always a FULL lyric sheet being aligned against a TV\n"
        "  size. Without a reference track nothing can work out which lines were\n"
        "  cut, and the result would look plausible and be wrong throughout.\n\n"
        "  Either:\n"
        "    * pass --reference SONG.flac  (the official track; the song is then\n"
        "      located by fingerprint and cut lines drop out automatically), or\n"
        "    * put ONLY the lines your cut actually sings in the lyrics file.\n"
        "      That is the most accurate route there is -- more accurate than a\n"
        "      reference -- because every line you give it is genuinely sung.")


def log(*a, **kw):
    print(*a, **kw, flush=True)


def parse_time(v: str) -> float:
    """Accept 96.4, 1:36.4 or 0:01:36.4."""
    parts = v.strip().split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(f"bad timestamp: {v!r}")


# =============================================================================
# phase 1
# =============================================================================

def cmd_phase1(args) -> None:
    video: Path = args.video
    # Everything is a sibling of the output you asked for. No project directory,
    # nothing written to the tool's own folder.
    out_lines = args.out or Path.cwd() / f"{video.stem[:60]}.lines.ass"
    base = project_mod.stem_of(out_lines)
    base.parent.mkdir(parents=True, exist_ok=True)

    mode = "reference" if args.reference else "video"
    window: tuple[float, float] | None = None   # slice of source to decode
    log(f"output  : {base}.*")
    log(f"mode    : {mode}")

    # --- 1. decide what audio we align against, and how it maps to the video --
    if mode == "reference":
        source = args.reference
        # The fingerprint search window is DERIVED from the same two numbers
        # that describe the song, rather than being described again separately.
        # A hint only bounds the search; the match itself decides the timing, so
        # the margin is generous and being a minute out costs nothing.
        if args.song_start is not None:
            s_start = max(args.song_start - SEARCH_MARGIN, 0.0)
            s_dur = args.duration + 2 * SEARCH_MARGIN
        else:
            s_start, s_dur = 0.0, None          # None: the whole video
            log("  no --song-start: searching the whole video (slower)")

        log("\nlocating song in video (fingerprint)")
        segments = locate.locate_by_fingerprint(source, video, s_start, s_dur,
                                                log=log)
        if not segments:
            raise SystemExit(
                "no match between reference and video.\n"
                "  - is the reference this show's song?\n"
                "  - is --song-start roughly right? it is searched with two\n"
                "    minutes of slack either side\n"
                "  - drop --song-start entirely to search the whole video")
        segments = locate.validate(segments, log=log)
        total = sum(s.ep_end - s.ep_start for s in segments)
        log(f"\n  {len(segments)} chunk(s), {total:.1f}s of song in the video:")
        for s in segments:
            log(f"    video {s.ep_start:8.2f}-{s.ep_end:8.2f}  <- "
                f"song {s.ref_start:7.2f}-{s.ref_end:7.2f}  (support {s.support})")
    else:
        source = video
        start = args.song_start
        if start is None:
            start = locate.chapter_guess(video)
            if start is not None:
                log(f"\nusing chapter marker at {start:.2f}s")
        if start is None:
            raise SystemExit(
                "cannot locate the song.\n\n"
                "  No --song-start was given, no reference track was supplied,\n"
                "  and the container has no usable chapter markers.\n\n"
                "  Pass --song-start (e.g. --song-start 0:36); ten seconds in\n"
                "  mpv beats a scan that may be confidently wrong. For an ED,\n"
                "  the same flag works -- it is just a later timestamp.")
        end = start + args.duration
        # Decode ONLY this window. Forced alignment has no skip state, so it
        # forces every lyric into whatever audio it is handed -- give it the
        # whole episode and the lyrics get smeared across all 24 minutes.
        # The aligner's t=0 is therefore the window start, which is exactly the
        # offset back to video time.
        segments = [locate.Segment(ref_start=0.0, ref_end=round(end - start, 3),
                                   ep_start=round(start, 3), ep_end=round(end, 3),
                                   offset=round(start, 3))]
        window = (start, end - start)
        log(f"\nsong window: {start:.2f}s .. {end:.2f}s (video timeline)")

    # --- 2. audio preprocessing ----------------------------------------------
    if not args.separate_vocals:
        align_source = source
    else:
        log("\nisolating vocals")
        if window is not None:
            # demucs needs a file, so cut the window out first rather than
            # separating a whole episode to use 80 seconds of it.
            source = audio_mod.extract_wav(
                source, base.parent / (base.name + ".window.wav"), *window)
            window = None
        align_source = separate.separate(
            source, base.parent / (base.name + ".vocals.wav"),
            device=args.device, log=log)

    log("\nlyrics")
    lyrics_file = base.parent / (base.name + ".lyrics.txt")
    resolved = lyrics_mod.resolve(args.lyrics, cache=lyrics_file,
                                  refresh=args.refresh_lyrics, log=log)
    log(resolved.describe())

    proj = Project(base=base, video=video,
                   mode=mode, align_audio=align_source,
                   reference=args.reference, segments=segments,
                   model=args.model, conditioned=bool(args.separate_vocals))
    proj.audio_start, proj.audio_dur = (window if window else (None, None))
    proj.save()

    # --- 3. readings ---------------------------------------------------------
    log("\nreadings")
    source = args.lyrics_format
    if source == "auto":
        source = readings.detect_source(lyrics_file)
        log(f"  detected lyric script: {source}")
    proj.lyrics_source = source
    proj.save()

    if source == "romaji":
        log("  romaji source: parsing straight to kana, no analyser involved")
    overrides = readings.load_overrides(proj.readings_tsv)
    if overrides:
        log(f"  {len(overrides)} manual override(s) carried over")
    rows = readings.from_lyrics(lyrics_file, overrides, source)
    log(f"  {len(rows)} lyric lines")

    # Without a reference, the lyrics file is the ONLY statement of what this
    # cut sings, so it has to be the text of the cut. Check that it can be.
    if mode == "video":
        n_units = sum(len(moras.split(r.replace(" ", ""))) for _n, _s, r in rows)
        check_fits_window(n_units, args.duration, log=log)

    # --- 4. align ------------------------------------------------------------
    log("\nalignment")
    aligner = A.Aligner(args.model, log=log)
    y = prepare(align_source, proj.audio_start, proj.audio_dur,
                condition=proj.conditioned)
    lp = aligner.emissions(y, cache=proj.emissions_cache)
    log(f"  emissions: {tuple(lp.shape)}")

    # One unit per character here: phase 1 only needs line boundaries.
    line_units = [[ch for ch in reading if not ch.isspace()]
                  for _n, _s, reading in rows]
    line_nos = [n for n, _s, _r in rows]

    if args.skip_cost is None:
        timed_flat = aligner.align_units(lp, [u for g in line_units for u in g])
        groups, cursor = [], 0
        for g in line_units:
            groups.append(timed_flat[cursor:cursor + len(g)])
            cursor += len(g)
    else:
        # Let the path spend instrumental passages on a skip state instead of
        # on syllables. See Aligner.align_groups.
        groups = aligner.align_groups(lp, line_units, skip_cost=args.skip_cost)

    timed = [item for g in groups for item in g]
    for g, line_no in zip(groups, line_nos):
        for item in g:
            item["line"] = line_no
    groups = [g for g in groups if g]

    # LRCLIB line timings, where they can be trusted, are ground truth for line
    # STARTS. They are timed against the studio track starting at zero, which is
    # exactly the clock the reference alignment runs on -- so in reference mode
    # the two coincide and no conversion is needed. Without a reference they are
    # in a different timeline entirely and must not be used.
    anchors: dict[int, float] = {}
    if mode == "reference" and not args.no_lrc_hints:
        timings = resolved.timings
        if not timings and (resolved.title or args.lrc_query):
            # The lyrics came from Uta-Net or a file, so they carry no timings.
            # Look LRCLIB up separately and keep only the timings: the TEXT
            # stays whatever the user chose. The two sheets disagree about where
            # lines break, so `match_timings` pairs them by text and a line that
            # differs simply goes unanchored.
            query = args.lrc_query or " ".join(
                x for x in (resolved.title, resolved.artist) if x)
            # args.reference, NOT `source`: by this point `source` has been
            # reassigned to the lyrics SCRIPT ("jp"/"romaji"), and probing that
            # for a duration silently yields None, which reads as "unverifiable"
            # and throws away every hint.
            ref_dur = audio_mod.duration(args.reference)
            hit = lyrics_mod.fetch_lrclib_verified(
                query, ref_dur, resolved.artist, log=log)
            timings = hit.timings if hit else []
        if timings:
            by_index = lyrics_mod.match_timings([s for _n, s, _r in rows], timings)
            anchors = {rows[i][0]: t for i, t in by_index.items() if i < len(rows)}
            log(f"  {len(anchors)} of {len(rows)} lines anchored by LRCLIB "
                f"({len(timings)} synced lines available)")

    smeared = A.fix_tail_smear(groups, MAX_HOLD)
    A.derive_durations(timed, MAX_HOLD)
    trimmed = A.trim_line_tails(groups, MAX_HOLD)
    if smeared:
        log(f"  corrected {smeared} tail-smeared character(s)")
    if trimmed:
        log(f"  ended {trimmed} line(s) at their last syllable rather than at "
            "the next line")

    # --- 5. map to the video timeline and write ------------------------------
    surface_of = {n: s for n, s, _ in rows}

    # Romaji hints for the timer. This tool is for karaoke timers, who often
    # cannot read Japanese -- and phase 1 asks them to correct lines in Aegisub,
    # which is impossible if you cannot tell one line from another. Aegisub's
    # edit box shows raw text, so the hint is readable while editing, and
    # nothing renders on screen because players ignore unknown tag content.
    romaji_of: dict[int, str] = {}
    if args.insert_romaji:
        for line_no, surface, _reading in rows:
            units, owner, cells = readings.units_and_romaji(
                surface, overrides, source)
            romaji_of[line_no] = "".join(cells)
        log(f"  romaji hints on {len(romaji_of)} line(s)")

    events, cut, straddled = [], [], []
    anchored = 0
    for grp in groups:
        placed = [c for c in grp if c["start"] is not None
                  and proj.to_video(c["start"]) is not None]
        if not placed:
            cut.append(grp[0]["line"])
            continue
        # A line whose ends sit in different retained chunks has middle
        # syllables that are not in the video at all. Mapping each end
        # independently yields a short, plausible-looking subtitle covering
        # words never broadcast, which is worse than dropping it.
        if proj.spans_cut(placed[0]["start"], placed[-1]["start"]):
            straddled.append(grp[0]["line"])
            continue
        # An anchor replaces the aligner's guess at where the line BEGINS, but
        # only when it lands inside a retained chunk and only for the start.
        # Ends still come from the audio: LRCLIB times lines of the full song,
        # and this cut may end a line early at a splice.
        ref_start = placed[0]["start"]
        anchor = anchors.get(grp[0]["line"])
        if anchor is not None and proj.to_video(anchor) is not None:
            if abs(anchor - ref_start) > 0.15:
                anchored += 1
            ref_start = anchor

        start = proj.to_video(ref_start)
        seg = next(s for s in proj.segments if s.contains_ref(ref_start))
        end = min(placed[-1]["end"], seg.ref_end) + seg.offset
        line_no = grp[0]["line"]
        events.append(ass.Event(
            start=start - args.lead_in,
            end=max(end, start + 0.4) - args.lead_in,
            text=romaji.annotate(surface_of[line_no], romaji_of.get(line_no, "")),
            style="KARA-JP"))

    if not events:
        raise SystemExit("nothing landed inside the song window -- check "
                         "--song-start / --duration.")

    ass.write(out_lines, events, [ass.STYLE_JP], project=base.resolve())

    # Flag readings worth a human look, including any the audio disagrees with.
    table = []
    for line_no, surface, reading in rows:
        grp = next((g for g in groups if g[0]["line"] == line_no), None)
        flag = readings.flags_for(surface, reading, source)
        if grp:
            weak = sum(1 for c in grp if c["conf"] < 0.02)
            if len(grp) and weak / len(grp) > 0.7:
                flag = ",".join(filter(None, [flag, "low-confidence"]))
        table.append((line_no, flag, surface, reading))
    readings.write_table(proj.readings_tsv, table)

    log(f"\nwrote {out_lines}   ({len(events)} lines)")
    log(f"wrote {proj.readings_tsv}")
    if cut:
        log(f"\nlyric lines not present in this cut: "
            f"{', '.join(str(c) for c in cut)}")
    flagged = [t for t in table if t[1]]
    if flagged:
        log(f"\n{len(flagged)} reading(s) worth checking: "
            f"{', '.join(str(t[0]) for t in flagged)}")
    log(f"\nNext: fix the lines in Aegisub, then run\n"
        f"  aksal phase2 {out_lines}")


# =============================================================================
# phase 2
# =============================================================================

def resolve_base(lines_file: Path, explicit: Path | None) -> Path:
    """Find the stem whose state file belongs to this lines file.

    Phase 2 needs the audio path, the time mapping and the readings, but you
    should not have to type any of that -- phase 1 wrote it next door. Tried in
    order, so an editor that mangles the header stamp is still recoverable.
    """
    if explicit:
        return project_mod.stem_of(explicit) if explicit.suffix else explicit

    stamped = ass.read_project_stamp(lines_file)
    if stamped is not None:
        cand = Path(stamped)
        if (cand.parent / (cand.name + project_mod.STATE_SUFFIX)).exists():
            return cand

    guess = project_mod.stem_of(lines_file)
    if (guess.parent / (guess.name + project_mod.STATE_SUFFIX)).exists():
        return guess

    raise SystemExit(
        f"no state file for {lines_file.name}.\n"
        f"  looked for: a header stamp, then "
        f"{guess.name + project_mod.STATE_SUFFIX} beside it\n\n"
        "  If this subtitle was made by hand rather than by phase1, pass\n"
        "  --video (and --reference if you have the clean track):\n"
        f"    aksal phase2 {lines_file} --video EPISODE.mkv")


def standalone_project(lines_file: Path, events: list[ass.Event], args) -> Project:
    """Build a project for a hand-made subtitle, with no phase 1 behind it.

    Everything phase 1 would have recorded has to be established here instead:
    what audio to align against, and how its timeline maps to the video's.

    Only the span the subtitle actually covers is decoded. Aligning a 90-second
    song against a whole episode would otherwise compute emissions over 24 minutes
    of audio, nearly all of it dialogue with no text to match.
    """
    base = project_mod.stem_of(lines_file)
    base.parent.mkdir(parents=True, exist_ok=True)

    pad = 2.0
    start = max(min(e.start for e in events) - pad, 0.0)
    end = max(e.end for e in events) + pad
    dur = end - start

    if args.reference:
        # The subtitle is timed to the video, so we still need the offset
        # between the video and the clean track.
        log("\nlocating song in video (fingerprint)")
        segments = locate.locate_by_fingerprint(
            args.reference, args.video, max(start - 30.0, 0.0), dur + 60.0,
            log=log)
        if not segments:
            raise SystemExit("reference track does not match this video.")
        source, a_start, a_dur = args.reference, None, None
        for s in segments:
            log(f"    video {s.ep_start:8.2f}-{s.ep_end:8.2f}  <- "
                f"song {s.ref_start:7.2f}-{s.ref_end:7.2f}")
    else:
        # Video's own audio: the aligner's t=0 is the start of the slice, so
        # the offset back to video time is exactly that slice start.
        log(f"\naligning against the video's own audio, {start:.2f}s-{end:.2f}s")
        segments = [locate.Segment(ref_start=0.0, ref_end=round(dur, 3),
                                   ep_start=round(start, 3), ep_end=round(end, 3),
                                   offset=round(start, 3))]
        source, a_start, a_dur = args.video, start, dur

    align_source = source
    if args.separate_vocals:
        log("\nisolating vocals")
        if a_start is not None:
            source = audio_mod.extract_wav(
                source, base.parent / (base.name + ".window.wav"),
                a_start, a_dur)
            a_start = a_dur = None
        align_source = separate.separate(
            source, base.parent / (base.name + ".vocals.wav"),
            device=args.device, log=log)

    proj = Project(base=base, video=args.video,
                   mode="reference" if args.reference else "video",
                   align_audio=align_source, reference=args.reference,
                   segments=segments, model=args.model,
                   conditioned=bool(args.separate_vocals))
    proj.audio_start, proj.audio_dur = a_start, a_dur
    proj.save()
    return proj


def cmd_phase2(args) -> None:
    lines_file: Path = args.lines
    if not lines_file.exists():
        raise SystemExit(f"lines file not found: {lines_file}")

    events = ass.read(lines_file)
    if not events:
        raise SystemExit(f"no dialogue events in {lines_file.name}")

    if args.video:
        proj = standalone_project(lines_file, events, args)
    else:
        try:
            proj = Project.load(resolve_base(lines_file, args.project))
        except SystemExit as exc:
            raise SystemExit(
                f"{exc}\n\n"
                "  If this subtitle was made by hand rather than by phase1,\n"
                "  pass --video (and --reference if you have the clean track):\n"
                f"    aksal phase2 {lines_file} --video EPISODE.mkv")
        proj.audio_start = proj.audio_dur = None

    log(f"\nproject : {proj.name}  ({proj.mode} mode)")
    log(f"lines   : {lines_file}   {len(events)} line(s)")

    overrides = readings.load_overrides(proj.readings_tsv)
    if overrides:
        log(f"  {len(overrides)} reading override(s)")

    # A hand-made subtitle may be romaji; the ASS text is the only clue.
    if args.video:
        sample = "\n".join(e.plain for e in events)
        proj.lyrics_source = "romaji" if romaji.looks_like_romaji(sample) else "jp"
        proj.save()
        log(f"  lyric script: {proj.lyrics_source}")

    log("\nalignment")
    # Structure came from the reference; timing comes from wherever the caller
    # says. Defaulting to the video means syllable durations are measured on
    # what was actually broadcast, so a separately mixed TV size or a cross-fade
    # at a splice join cannot carry a wrong duration across.
    if args.time_against == "video":
        first = min(e.start for e in events)
        last = max(e.end for e in events)
        src = timing.from_video(proj, first, last)
    else:
        src = timing.from_reference(proj)
    log(f"  timing against {src.describe()}")

    aligner = A.Aligner(proj.model or None, log=log)
    y = prepare(src.audio, src.start, src.dur, condition=src.conditioned)
    lp = aligner.emissions(y, cache=proj.sibling(f".emissions.{src.cache_tag}.pt"))
    env = envelope(y)

    jp_events: list[ass.Event] = []
    ro_events: list[ass.Event] = []
    snapped = 0

    for ev in events:
        surface = ev.plain
        if not surface:
            continue
        units, owner, ro_cells = readings.units_and_romaji(
            surface, overrides, proj.lyrics_source)
        if not units:
            continue

        # Re-align inside the window you approved. Because the window is ground
        # truth, an error here cannot leak into any other line.
        if src.name == "video":
            a, b = src.to_audio(ev.start), src.to_audio(ev.end)
        else:
            # Clamp both ends into the SAME chunk: a window spanning a cut
            # would slice across audio the video does not contain.
            seg = proj.segment_at_video(ev.start) or proj.segment_at_video(ev.end)
            a, b = proj.clamp_to_audio(ev.start), proj.clamp_to_audio(ev.end)
            if seg is not None:
                a = min(max(a, seg.ref_start), seg.ref_end)
                b = min(max(b, seg.ref_start), seg.ref_end)
        if b <= a:
            b = a + 0.5
        f0, f1 = int(a / A.SEC_PER_FRAME), int(b / A.SEC_PER_FRAME) + 1
        f1 = min(f1, lp.shape[0])

        if f1 - f0 < len(units):
            log(f"  line at {ass.ts(ev.start)}: window too short for "
                f"{len(units)} moras; spacing evenly")
            step = (ev.end - ev.start) / len(units)
            timed = [{"text": u, "start": round(a + step * i, 3),
                      "end": round(a + step * (i + 1), 3)}
                     for i, u in enumerate(units)]
        else:
            timed = aligner.align_units(lp[f0:f1], units, frame_offset=f0)
            if args.snap:
                snapped += A.snap_to_onsets(timed, env)
            A.derive_durations(timed, MAX_HOLD, limit=b)

        starts = [t["start"] if t["start"] is not None else a for t in timed]

        # Audio time -> video time, through whichever source we timed against.
        if src.name == "reference":
            seg = proj.segment_at_ref(a)
            if seg is not None:
                src.offset = seg.offset
        v_starts = [src.to_video(s) for s in starts]

        jp_cells = units
        cell_starts = v_starts

        if args.group == "word":
            # One cell per word: keep each word's FIRST start, so the highlight
            # still lands on the syllable that begins it.
            spans = moras.group_by_word(owner)
            jp_cells = ["".join(units[a:b + 1]) for a, b in spans]
            # Join the per-mora cells rather than re-romanising the units: with
            # a romaji sheet those cells carry the user's own spelling, and
            # going back to `romaji.line` would discard it here only.
            ro_cells = ["".join(ro_cells[a:b + 1]) for a, b in spans]
            cell_starts = [v_starts[a] for a, _ in spans]

        # Both tracks tile from ONE list of boundaries, so their splits match by
        # construction rather than by coincidence.
        jp_events.append(ass.Event(
            start=ev.start, end=ev.end, style="KARA-JP",
            text=ass.karaoke_text(jp_cells, cell_starts, ev.start, ev.end)))
        ro_events.append(ass.Event(
            start=ev.start, end=ev.end, style="KARA-RO",
            text=ass.karaoke_text(ro_cells, cell_starts, ev.start, ev.end)))

    # From a romaji sheet the "JP" track is reconstructed kana, not the original
    # orthography -- there is no kanji to recover -- so name it honestly.
    kana_only = proj.lyrics_source == "romaji"
    base = proj.base

    if snapped:
        log(f"  snapped {snapped} mora start(s) to onsets")
    log("")
    wanted = {t.strip() for t in args.tracks.split(",") if t.strip()}
    if wanted - {"jp", "romaji"}:
        raise SystemExit("--tracks accepts jp and/or romaji")
    if "jp" in wanted:
        out_jp = base.parent / (
            base.name + (".kara.kana.ass" if kana_only else ".kara.jp.ass"))
        ass.write(out_jp, jp_events, [ass.STYLE_JP], project=base.resolve())
        log(f"wrote {out_jp}")
    if "romaji" in wanted:
        out_ro = base.parent / (base.name + ".kara.romaji.ass")
        ass.write(out_ro, ro_events, [ass.STYLE_RO], project=base.resolve())
        log(f"wrote {out_ro}")

    mismatched = [i for i, (j, r) in enumerate(zip(jp_events, ro_events))
                  if len(ass.karaoke_durations(j.text))
                  != len(ass.karaoke_durations(r.text))]
    if mismatched:
        log(f"\nWARNING: {len(mismatched)} line(s) have differing JP/Romaji "
            f"split counts -- this should be impossible, please report it.")
    else:
        log(f"\nJP and Romaji splits match on all {len(jp_events)} lines.")


# =============================================================================

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aksal", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("phase1", help="produce timed lines for you to correct")
    p1.add_argument("--video", required=True, type=Path)
    p1.add_argument("-o", "--out", type=Path, default=None,
                    help="where to write the lines file, e.g. "
                         "D:/karaoke/OP01.lines.ass. Everything else -- lyrics, "
                         "readings, state and caches -- is written beside it "
                         "sharing that stem. Default: the video's name in the "
                         "current directory.")
    p1.add_argument("--lyrics", required=True,
                    help="a local file, a Uta-Net song URL, or a search term "
                         "for LRCLIB. Whatever the source, the text is cached "
                         "into the project so you can correct it by hand.")
    p1.add_argument("--insert-romaji", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="prefix each line with its romaji as {*RO*...*RO*}. "
                         "ON by default: phase 1 exists to be corrected in "
                         "Aegisub, which is impossible if you cannot tell the "
                         "lines apart, and the hint is invisible when rendered "
                         "because players ignore unknown tag content. Strip "
                         r"with \{\*RO\*.*?\*RO\*\} or pass --no-insert-romaji.")
    p1.add_argument("--refresh-lyrics", action="store_true",
                    help="re-fetch even if the project already has a cached copy")
    p1.add_argument("--reference", type=Path,
                    help="full-length official track. With it, the song is "
                         "located automatically and alignment runs on clean "
                         "studio audio -- strongly preferred.")
    p1.add_argument("--song-start", type=parse_time,
                    help="roughly where the song starts in the video, e.g. "
                         "0:36 or 21:30 for an ED. With --reference it just "
                         "narrows the search and may be a minute out; without "
                         "one it defines the window and is required.")
    p1.add_argument("--duration", type=float, default=92.0,
                    help="song length in video-only mode (default: 92s)")
    p1.add_argument("--lyrics-format", choices=("auto", "jp", "romaji"),
                    default="auto",
                    help="script of the lyrics file (default: auto-detect). "
                         "Romaji is parsed straight to kana, skipping the "
                         "morphological analyser entirely.")
    def skip_cost(v):
        return None if str(v).lower() in ("none", "off") else float(v)

    p1.add_argument("--skip-cost", type=skip_cost, default=None,
                    help="log-probability of the skip state, which lets audio "
                         "between lines match nothing. Less negative skips "
                         "more freely; --skip-cost=none disables it and falls "
                         "back to plain forced alignment, which must place "
                         "every syllable somewhere. Off by default: measured across the "
                         "corpus it is a real win on two songs and a real "
                         "regression on three. Try -1.5 when phase 1 output "
                         "looks smeared across an instrumental.")
    p1.add_argument("--lrc-query",
                    help="override the search string used to look up LRCLIB "
                         "synced timings (default: the song title and artist)")
    p1.add_argument("--no-lrc-hints", action="store_true",
                    help="ignore LRCLIB synced line timings even when they are "
                         "available and verified. They anchor line STARTS on "
                         "the reference clock; without a reference they are in "
                         "a different timeline and are never used anyway.")
    p1.add_argument("--lead-in", type=float, default=0.0,
                    help="shift every cue earlier by N seconds")
    p1.set_defaults(func=cmd_phase1)

    p2 = sub.add_parser(
        "phase2", help="turn corrected lines into karaoke",
        description="With a phase1 project, the lines file is the only argument "
                    "needed. For a hand-made subtitle, add --video.")
    p2.add_argument("lines", type=Path,
                    help="corrected lines file, or any hand-made subtitle")
    p2.add_argument("--time-against", choices=("video", "reference"),
                    default="video",
                    help=r"which audio decides the \k values (default: video). "
                         "The reference chooses WHICH lines are in the cut; "
                         "timing against the video measures what was actually "
                         "broadcast, so a separately mixed TV size or a "
                         "cross-fade at a splice join cannot skew durations.")
    p2.add_argument("--group", choices=("syllable", "word"), default="syllable",
                    help="one karaoke cell per syllable (default) or per word. "
                         "Word grouping gives a simpler highlight; timing is "
                         "identical either way.")
    p2.add_argument("--tracks", default="jp,romaji",
                    help="which karaoke tracks to write (default: jp,romaji)")
    p2.add_argument("--video", type=Path,
                    help="required only for a hand-made subtitle with no "
                         "phase1 project behind it")
    p2.add_argument("--reference", type=Path,
                    help="with --video: align against this clean track instead "
                         "of the video's own audio (better, needs the song)")
    p2.add_argument("--project", type=Path,
                    help="override the stem whose state file to use; normally "
                         "found from the lines file automatically")
    p2.add_argument("--snap", action="store_true", default=True,
                    help="snap mora starts to energy onsets (default: on)")
    p2.add_argument("--no-snap", dest="snap", action="store_false")
    p2.set_defaults(func=cmd_phase2)

    pf = sub.add_parser("find",
                        help="anime name -> song, lyrics and reference track")
    pf.add_argument("--anime", required=True,
                    help="series name, e.g. \"Cross Fight B-Daman eS\"")
    pf.add_argument("--video", type=Path, default=None,
                    help="the episode. Optional: without it this is a lookup "
                         "only -- it will tell you what the song is and where "
                         "the lyrics are, but cannot fetch a reference track, "
                         "because the check that a download is really this "
                         "show's recording is fingerprinting it against your "
                         "episode.")
    pf.add_argument("-o", "--out", type=Path, default=None,
                    help="where phase 1 should write; everything is a sibling")
    pf.add_argument("--op", dest="kind", action="store_const", const="OP",
                    help="consider only openings")
    pf.add_argument("--ed", dest="kind", action="store_const", const="ED",
                    help="consider only endings")
    pf.add_argument("--song-start", type=parse_time,
                    help="roughly where the song starts; narrows the "
                         "fingerprint search and is passed through to phase 1")
    pf.add_argument("--duration", type=float, default=92.0)
    pf.add_argument("--pick", type=int,
                    help="choose candidate N without asking (for scripts)")
    pf.add_argument("--yes", action="store_true",
                    help="accept the first plausible answer at every prompt")
    pf.add_argument("--run", action="store_true",
                    help="run phase 1 immediately without asking")
    pf.set_defaults(func=cmd_find)

    for sp in (p1, p2):
        sp.add_argument("--model", default=None,
                        help="override the acoustic model, e.g. "
                             "hiragana-asr:D:/models/custom.pt")
        sp.add_argument("--device", default="cpu", help="demucs device")
        sp.add_argument("--separate-audio", dest="separate_vocals",
                        action="store_true",
                        help="isolate vocals with demucs before aligning. "
                             "Off by default: measured over eight songs against "
                             "hand-timed karaoke it is a wash -- very slightly "
                             "better on average, worse in the tail -- for about "
                             "four times the runtime. Worth trying on a noisy "
                             "mix.")
    return p


def cmd_find(args) -> None:
    """Anime name in, ready-to-run phase 1 out -- as one continuous process.

    It ends by offering to run phase 1 rather than printing a command, because
    a CLI that only replaces the searching half of the job is not worth using
    over a browser.
    """
    from . import discover

    video: Path | None = args.video
    stem = video.stem[:60] if video else args.anime[:60].replace(" ", "-")
    out = args.out or Path.cwd() / f"{stem}.lines.ass"
    out.parent.mkdir(parents=True, exist_ok=True)

    if video is None:
        log("  lookup only: no --video, so no reference track can be verified")

    found = discover.run(args.anime, video, out, kind=args.kind,
                         song_start=args.song_start, duration=args.duration,
                         auto=args.yes, pick=args.pick, log=log)

    if found.theme is None:
        raise SystemExit("nothing selected.")

    log("\n" + "-" * 62)
    log(f"song      : {found.theme.title}"
        + (f" by {found.theme.artist}" if found.theme.artist else ""))
    log(f"lyrics    : {found.lyrics_url or 'NOT FOUND -- supply a file'}")
    if video is None:
        log("reference : not looked for (lookup only)")
    else:
        log(f"reference : {found.reference or 'NOT FOUND -- exact-cut lyrics needed'}")
    if found.synced:
        log(f"lrclib    : {found.synced} synced line timings available as hints")
    log("-" * 62)

    if not found.lyrics_url:
        raise SystemExit(
            "no lyrics. Save them to a file and pass --lyrics FILE to phase1.")
    if video is None:
        # Lookup only. Nothing failed, so this is not an error -- the user asked
        # what the song was and got an answer.
        log("\nTo go further, add --video: the official track can then be\n"
            "fetched and checked against your episode, which is the only way\n"
            "to know a download is really this show's recording.")
        return
    if found.reference is None and args.song_start is None:
        raise SystemExit(
            "no reference track was verified, so phase 1 needs BOTH\n"
            "  --song-start and lyrics containing only the lines your cut sings.")

    cmd = discover.phase1_command(found, video, out, args.song_start)
    log("\nphase 1 command:\n  " + " ".join(cmd))

    go = args.run or args.yes or discover.ask(
        "\nrun phase 1 now? [Y/n]: ", "y").lower().startswith("y")
    if not go:
        return

    p1 = build_parser().parse_args(cmd[1:])
    p1.func(p1)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args(argv)

    # Checked once, up front. Every audio step shells out to ffmpeg, so finding
    # out it is missing forty seconds into a fingerprint search is worse than
    # being asked about it immediately.
    from . import tools

    tools.ensure(log=log)

    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
