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
import shlex
import subprocess
import sys
from pathlib import Path

from . import ass, lyrics as lyrics_mod, model_spec, moras, readings, romaji
from . import project as project_mod
from .project import Project

MAX_HOLD = 2.0          # longest a single unit may be held before it is a rest
READING_CONTEXT = 0.75  # audio on each side of a line, for reading selection

# Slack around a --song-start hint when searching for the song. A hint only
# bounds the search -- the fingerprint match decides the actual timing -- so
# being a minute out should cost nothing.
SEARCH_MARGIN = 120.0

# The fastest anyone actually sings. Measured across the test set, sung moras
# bottom out around 0.10 s; nothing real goes below it for a whole song.
MIN_SEC_PER_MORA = 0.10

# Applied when --duration is not given. A TV size runs ~89-92s; stated as a
# constant so the CLI can tell the user it is guessing rather than measuring.
DEFAULT_DURATION = 92.0

# Above this share of the window (at the fastest pace) the sheet holds more
# text than any real cut. Measured over 109 hand-timed karaoke files: genuine
# cuts need at most 0.49 of their own window (median 0.24, p90 0.30), while a
# full 4-minute sheet against a TV size needs 2-3x the window. So between 0.55
# and 1.0 the run continues with a loud warning, and above 1.0 it stops.
WARN_FIT = 0.55


def display_command(arguments: list[str], *, windows: bool | None = None) -> str:
    """Render a copyable command without ever executing it."""
    if windows is None:
        windows = sys.platform == "win32"
    return (subprocess.list2cmdline(arguments) if windows
            else shlex.join(arguments))


def display_reading(reading: str) -> str:
    """Kana plus the same modified-Hepburn romaji AKSAL emits."""
    cells: list[str] = []
    for word_index, word in enumerate(reading.split()):
        if word_index:
            cells.append(" ")
        cells.extend(romaji.line(moras.split(word)))
    return f"{reading} [{''.join(cells)}]"


def reading_score_interval(start: float, end: float,
                           audio_duration: float,
                           context: float = READING_CONTEXT
                           ) -> tuple[float, float]:
    """Pad a reading-selection interval without changing subtitle timing.

    Phase 1's provisional reading can place the rough start after a mora that
    exists only in a rival reading (まだ versus いまだ).  The CTC scorer needs
    to hear that mora to choose correctly.  Symmetric context is safe because
    CTC can spend silence on blanks; clamping keeps the crop inside the audio.
    """
    limit = max(audio_duration, 0.0)
    padded_start = min(max(start - context, 0.0), limit)
    padded_end = min(max(end + context, padded_start), limit)
    return padded_start, padded_end


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
    if need <= WARN_FIT * window:
        return
    if need <= window:
        # More text than any real cut carries, but not physically impossible.
        # A warning rather than a stop: dense rap sections exist, and the user
        # may know something the statistics do not.
        log(f"\n  WARNING: these lyrics are unusually long for this window --\n"
            f"  {n_units} moras need {need:.0f}s of the {window:.0f}s window at "
            f"the fastest anyone sings.\n"
            f"  No genuine cut in 109 measured songs is this dense. If this is "
            f"a FULL lyric\n"
            f"  sheet, the output will be confidently wrong: trim the sheet to "
            f"what the cut\n"
            f"  sings, or pass --reference and let the cut lines drop out "
            f"automatically.")
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


def resolve_media(spec: str | None, dest: Path, log=print) -> Path | None:
    """Turn a --reference value into a local file: a path, or a URL for yt-dlp.

    The same shape --lyrics already has, because the same person supplies both
    and reference tracks live in the same places lyrics do. Anything yt-dlp
    understands works; the download is cached beside the project, so a re-run
    -- and phase 2 -- reads the file rather than the network.

    The fetched audio is verified the same way a local file is: by the
    fingerprint match that runs right after. A download that is not this
    show's recording fails there with the same message a wrong local file
    would, so no separate trust decision is introduced here.
    """
    if spec is None:
        return None
    if spec.lower().startswith(("http://", "https://")):
        if dest.exists():
            log(f"  using cached reference: {dest.name}")
            return dest
        from . import fetch

        log(f"  fetching reference audio: {spec}")
        try:
            return fetch.download_audio(spec, dest)
        except fetch.FetchError as exc:
            raise SystemExit(str(exc))
    path = Path(spec)
    if not path.exists():
        raise SystemExit(f"reference not found: {spec}")
    return path


# =============================================================================
# phase 1
# =============================================================================

def cmd_phase1(args) -> None:
    from . import align as A
    from . import audio as audio_mod
    from . import locate, reading_selector, separate
    from .audio import prepare

    video: Path = args.video
    timing_model, selection_model = model_spec.resolve(
        args.model, args.timing_model, args.selection_model)
    root = (args.output_dir or project_mod.default_output_dir(video)).resolve()
    root.mkdir(parents=True, exist_ok=True)
    audio_dir = root / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    out_lines = root / f"{project_mod.project_name(root)}.lines.ass"

    reference = resolve_media(
        args.reference, audio_dir / "reference.m4a", log=log)
    duration = args.duration if args.duration is not None else DEFAULT_DURATION

    mode = "reference" if reference else "video"
    window: tuple[float, float] | None = None   # slice of source to decode
    log(f"output directory: {root}")
    log(f"mode    : {mode}")
    log(f"timing model   : {timing_model}")
    log(f"selection model: {selection_model}")

    # --- 1. decide what audio we align against, and how it maps to the video --
    if mode == "reference":
        source = reference
        # The fingerprint search window is DERIVED from the same two numbers
        # that describe the song, rather than being described again separately.
        # A hint only bounds the search; the match itself decides the timing, so
        # the margin is generous and being a minute out costs nothing.
        if args.song_start is not None:
            s_start = max(args.song_start - SEARCH_MARGIN, 0.0)
            s_dur = duration + 2 * SEARCH_MARGIN
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
        # Without a reference the two numbers on this command line are the ONLY
        # statement of where the song is and what it sings. Say what is being
        # assumed rather than letting a default pass silently.
        if args.duration is None:
            log(f"  no --duration: assuming the song runs {duration:.0f}s -- "
                "set it if this cut is longer or shorter")
        log("  video-only mode: the lyrics must contain ONLY the lines this "
            "cut sings.\n  A full-version sheet cannot work here -- every line "
            "is forced into the\n  window and the result is confidently wrong. "
            "For full lyrics, pass --reference.")
        end = start + duration
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
                source, audio_dir / "window.wav", *window)
            window = None
        align_source = separate.separate(
            source, audio_dir / "vocals.wav",
            device=args.device, log=log)

    log("\nlyrics")
    lyrics_file = root / "lyrics.txt"
    resolved = lyrics_mod.resolve(args.lyrics, cache=lyrics_file,
                                  refresh=args.refresh_lyrics, log=log)
    log(resolved.describe())

    proj = Project(root=root, video=video,
                   mode=mode, align_audio=align_source,
                   reference=reference, segments=segments,
                   timing_model=timing_model,
                   selection_model=selection_model,
                   analyser=args.analyser,
                   conditioned=bool(args.separate_vocals),
                   separated=bool(args.separate_vocals),
                   selection_separated=bool(args.separate_selection_audio))
    proj.audio_start, proj.audio_dur = (window if window else (None, None))
    proj.save()

    # --- 3. readings ---------------------------------------------------------
    log("\nreadings")
    # `script` and never `source`: this function already has a `source` meaning
    # "the audio we align against", and reusing the name for the lyric SCRIPT
    # caused a real bug once -- a later branch probed the string "romaji" for
    # an audio duration, got None, and silently threw away every LRCLIB hint.
    script = args.lyrics_format
    if script == "auto":
        script = readings.detect_source(lyrics_file)
        log(f"  detected lyric script: {script}")
    proj.lyrics_source = script
    proj.save()

    if script == "romaji":
        log("  romaji source: parsing straight to kana, no analyser involved")
    from . import selection_state

    selection_data = selection_state.load(proj.selections)
    overrides = selection_state.manual_overrides(proj.readings, selection_data)
    if overrides:
        log(f"  {len(overrides)} manual override(s) carried over")
    rows = readings.from_lyrics(lyrics_file, overrides, script)
    log(f"  {len(rows)} lyric lines")

    # Without a reference, the lyrics file is the ONLY statement of what this
    # cut sings, so it has to be the text of the cut. Check that it can be.
    if mode == "video":
        n_units = sum(len(moras.split(r.replace(" ", ""))) for _n, _s, r in rows)
        check_fits_window(n_units, duration, log=log)

    # --- 4. align ------------------------------------------------------------
    log("\nalignment")
    aligner = A.Aligner(timing_model, log=log)
    y = prepare(align_source, proj.audio_start, proj.audio_dur,
                condition=proj.conditioned)
    from .artifacts import array_identity, emissions_key

    audio_identity = array_identity(y)
    cache_key = emissions_key(
        aligner.model_identity, aligner.frame_stride, y, audio_identity)
    lp = aligner.emissions(y, cache=proj.emissions_cache_for(cache_key))
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
            # The RESOLVED reference file. Probing anything that is not the
            # audio silently yields None, which reads as "unverifiable" and
            # throws away every hint -- that bug happened, which is why the
            # lyric script now lives in `script` and audio in `reference`.
            ref_dur = audio_mod.duration(reference)
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

    # --- 5. settle ambiguous readings over complete line audio --------------
    selections: dict[int, reading_selector.LineSelection] = {}
    selection_errors: dict[int, str] = {}
    active_selection_keys: set[str] = set()
    group_of = {g[0]["line"]: g for g in groups if g}
    plans = []
    if script != "romaji":
        for line_no, surface, _reading in rows:
            key = readings.normalise_surface(surface)
            if overrides.get_for(line_no, key) is not None:
                # A human correction outranks audio.
                continue
            words = readings.analyse_words(key)
            choices = reading_selector.candidate_choices(
                words, readings.candidate_readings)
            if not any(len(choice) > 1 for choice in choices):
                continue
            grp = group_of.get(line_no)
            placed = [c for c in (grp or []) if c.get("start") is not None]
            if not placed:
                selection_errors[line_no] = "no rough line timing"
                continue
            start = anchors.get(line_no, placed[0]["start"])
            end = placed[-1].get("end") or (placed[-1]["start"] + 0.25)
            if end <= start:
                selection_errors[line_no] = "rough line interval is empty"
                continue
            start, end = reading_score_interval(
                start, end, len(y) / audio_mod.SR)
            plans.append((line_no, words, choices, start, end))

    if plans:
        log(f"\nreading selection ({len(plans)} ambiguous line(s), "
            f"{READING_CONTEXT:.2f}s context on each side)")
        fresh_plans = []
        decision_model = model_spec.decision_identity(selection_model)
        selection_audio = (f"demucs:{separate.MODEL}"
                           if args.separate_selection_audio else "source")
        for line_no, words, choices, start, end in plans:
            decision_key = selection_state.decision_key(
                surface="".join(surface for surface, _reading in words),
                start=start, end=end, model_identity=decision_model,
                audio_identity=audio_identity, choices=choices,
                stage="phase1", selection_audio=selection_audio,
            )
            active_selection_keys.add(decision_key)
            saved = selection_state.get(selection_data, decision_key)
            if saved is not None:
                selections[line_no] = saved
            else:
                fresh_plans.append(
                    (decision_key, line_no, words, choices, start, end))

        direct_plans = []
        direct_clips = []
        for plan in fresh_plans:
            try:
                direct_clips.append(reading_selector.audio_clip(
                    y, plan[-2], plan[-1], audio_mod.SR))
                direct_plans.append(plan)
            except reading_selector.SelectionError as exc:
                selection_errors[plan[1]] = str(exc)

        if direct_plans and args.separate_selection_audio:
            direct_clips = separate.separate_waveforms(
                direct_clips, sample_rate=audio_mod.SR,
                device=args.device, log=log)
            direct_clips = [
                audio_mod.normalize(audio_mod.highpass(clip))
                for clip in direct_clips
            ]

        if direct_plans:
            if selection_model == timing_model:
                selector = aligner
            else:
                # Rough timing is complete. Release its model before loading a
                # different selector checkpoint.
                del lp
                import gc

                del aligner
                gc.collect()
                selector = A.Aligner(selection_model, log=log)

        for plan, clip in zip(direct_plans, direct_clips):
            decision_key, line_no, words, choices, _start, _end = plan
            try:
                # Always run the model on the bounded line clip. Reusing a
                # slice of full-track emissions changes normalisation and
                # contextual attention; EDLONG's 未だ measured 94% いまだ here
                # but only 45% in the long-track slice.
                line_lp = selector.emissions(clip)
                selections[line_no] = reading_selector.select(
                    words, selector, line_lp, readings.candidate_readings,
                    choices=choices)
                selection_state.put(
                    selection_data, decision_key, selections[line_no],
                    "phase1")
            except reading_selector.SelectionError as exc:
                selection_errors[line_no] = str(exc)
                continue

        rows = [
            (line_no, surface,
             selections[line_no].reading if line_no in selections else reading)
            for line_no, surface, reading in rows
        ]
    else:
        del lp
    selection_state.prune_stage(
        selection_data, "phase1", active_selection_keys)

    # Selected readings must feed the romaji hints and phase-2 table exactly as
    # manual readings do. This local map does not mutate the user's old table.
    # --- 6. map to the video timeline and write ------------------------------
    surface_of = {n: s for n, s, _ in rows}

    # Romaji hints for the timer. This tool is for karaoke timers, who often
    # cannot read Japanese -- and phase 1 asks them to correct lines in Aegisub,
    # which is impossible if you cannot tell one line from another. Aegisub's
    # edit box shows raw text, so the hint is readable while editing, and
    # nothing renders on screen because players ignore unknown tag content.
    romaji_of: dict[int, str] = {}
    if args.insert_romaji:
        for line_no, surface, row_reading in rows:
            key = readings.normalise_surface(surface)
            manual = overrides.get_for(line_no, key)
            selected = selections.get(line_no)
            value = manual or (selected.reading if selected else row_reading)
            effective_overrides = {key: value}
            units, owner, cells = readings.units_and_romaji(
                surface, effective_overrides, script)
            romaji_of[line_no] = "".join(cells)
        log(f"  romaji hints on {len(romaji_of)} line(s)")

    events, cut, straddled = [], [], []
    event_at: dict[int, ass.Event] = {}
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
        event = ass.Event(
            start=start - args.lead_in,
            end=max(end, start + 0.4) - args.lead_in,
            text=romaji.annotate(surface_of[line_no], romaji_of.get(line_no, "")),
            style="KARA-JP")
        events.append(event)
        event_at[line_no] = event

    # The TSV line id is the line's position in the emitted ASS.  Numbering
    # only lines that survived the cut makes the same identity available to
    # phase 2 without smuggling private metadata into Aegisub's Effect field.
    events.sort(key=lambda event: event.start)
    position_of = {id(event): position
                   for position, event in enumerate(events, 1)}
    output_line_id = {
        source_line: position_of[id(event)]
        for source_line, event in event_at.items()
    }

    if not events:
        raise SystemExit("nothing landed inside the song window -- check "
                         "--song-start / --duration.")

    # Flag readings worth a human look, including any the audio disagrees with.
    table = []
    decided_by_audio: list[tuple] = []
    unclear: list[tuple] = []
    notes: list[ass.Event] = []
    for line_no, surface, reading in rows:
        if line_no not in output_line_id:
            continue
        grp = group_of.get(line_no)
        flag = readings.flags_for(surface, reading, script)
        if grp:
            weak = sum(1 for c in grp if c["conf"] < 0.02)
            if len(grp) and weak / len(grp) > 0.7:
                flag = ",".join(filter(None, [flag, "low-confidence"]))
        if line_no in selection_errors:
            flag = ",".join(filter(None, [flag, "selection-error"]))
        selected = selections.get(line_no)
        for decision in selected.decisions if selected else ():
            _top_reading, top_probability = decision.ranked[0]
            alternatives = tuple(r for r, _p in decision.ranked)
            if decision.changed:
                decided_by_audio.append(
                    (line_no, decision.surface, decision.current,
                     decision.chosen, top_probability, decision.confidence))
                flag = ",".join(filter(None, [
                    flag,
                    f"audio?{decision.surface}:"
                    f"{decision.current}>{decision.chosen}"]))
            elif decision.confidence == "uncertain":
                unclear.append(
                    (line_no, decision.surface, decision.current,
                     alternatives, top_probability))
                flag = ",".join(filter(None, [
                    flag,
                    f"unclear?{decision.surface}:{'/'.join(alternatives)}"]))
        table.append((output_line_id[line_no], flag, surface, reading))

    # One comment per note, on the line it belongs to. These render nothing --
    # Aegisub shows them in the grid and libass ignores them -- so the karaoke
    # is unchanged while the reasoning travels with the file.
    for line_no, surf, was, now, probability, certainty in decided_by_audio:
        ev = event_at.get(line_no)
        if ev:
            notes.append(ass.Event(
                start=ev.start, end=ev.end, style=ev.style, comment=True,
                text=f"AKSAL: audio chose {surf} = {display_reading(now)} "
                     f"(not {display_reading(was)}), "
                     f"{probability:.1%}, {certainty}"))
    for line_no, surf, ours_r, alternatives, probability in unclear:
        ev = event_at.get(line_no)
        if ev:
            notes.append(ass.Event(
                start=ev.start, end=ev.end, style=ev.style, comment=True,
                text=f"AKSAL: {surf} candidates "
                     f"{' / '.join(display_reading(r) for r in alternatives)}; "
                     f"kept {display_reading(ours_r)} "
                     f"(top {probability:.1%}, uncertain)"))

    ass.write(out_lines, events + notes, [ass.STYLE_JP], project=root)
    readings.write_table(proj.readings, table)
    selection_state.update_table_baseline(selection_data, table, overrides)
    selection_state.save(proj.selections, selection_data)

    log(f"\nwrote {out_lines}   ({len(events)} lines)")
    log(f"wrote {proj.readings}")

    # AMBIGUOUS READINGS ARE REPORTED, NEVER BURIED. A word like 心 is こころ
    # or しん and the kanji does not say which; the audio does, when it can.
    # Both outcomes are printed because both are things a human might overrule,
    # and a changed reading changes the MORA COUNT and so the timing.
    if decided_by_audio:
        log(f"\nthe audio settled {len(decided_by_audio)} reading(s) "
            f"against the dictionary:")
        for line_no, surf, was, now, probability, certainty in decided_by_audio[:12]:
            log(f"  line {line_no}: {surf}  {display_reading(was)} -> "
                f"{display_reading(now)}  "
                f"({probability:.1%}, {certainty})")
        if len(decided_by_audio) > 12:
            log(f"  ... and {len(decided_by_audio) - 12} more")
    if unclear:
        log(f"\n{len(unclear)} reading(s) have a plausible alternative the "
            f"audio could not settle -- the dictionary's choice was kept:")
        for line_no, surf, ours_r, alternatives, probability in unclear[:12]:
            shown = " / ".join(display_reading(r) for r in alternatives)
            log(f"  line {line_no}: {surf}  kept {display_reading(ours_r)}; "
                f"candidates {shown}  (top {probability:.1%})")
        if len(unclear) > 12:
            log(f"  ... and {len(unclear) - 12} more")
    if decided_by_audio or unclear:
        log(f"\n  all of these are marked in {proj.readings.name} and as "
            f"comments in the ASS; correct any there and re-run.")
    if selection_errors:
        log(f"\n{len(selection_errors)} ambiguous line(s) could not be "
            "scored and kept their existing readings:")
        for line_no, reason in list(selection_errors.items())[:12]:
            log(f"  line {line_no}: {reason}")
    if cut:
        log(f"\nlyric lines not present in this cut: "
            f"{', '.join(str(c) for c in cut)}")
    flagged = [t for t in table if t[1]]
    if flagged:
        log(f"\n{len(flagged)} reading(s) worth checking: "
            f"{', '.join(str(t[0]) for t in flagged)}")
    command = display_command(["aksal", "phase2", str(out_lines)])
    log(f"\nNext: fix the lines in Aegisub, then run\n  {command}")


# =============================================================================
# phase 2
# =============================================================================

def resolve_project_root(lines_file: Path, explicit: Path | None) -> Path:
    """Find the output directory whose state belongs to this lines file.

    Phase 2 needs the audio path, the time mapping and the readings, but you
    should not have to type any of that -- phase 1 wrote it next door. Tried in
    order, so an editor that mangles the header stamp is still recoverable.
    """
    if explicit:
        root = explicit.resolve()
        if (root / project_mod.STATE_NAME).exists():
            return root
        raise SystemExit(f"no ASKAL project at {root / project_mod.STATE_NAME}")

    stamped = ass.read_project_stamp(lines_file)
    if stamped is not None:
        root = Path(stamped)
        if (root / project_mod.STATE_NAME).exists():
            return root

    root = lines_file.resolve().parent
    if (root / project_mod.STATE_NAME).exists():
        return root

    raise SystemExit(
        f"no state file for {lines_file.name}.\n"
        f"  looked for an ASS header stamp, then {project_mod.STATE_NAME} "
        f"beside it\n\n"
        "  If this subtitle was made by hand rather than by phase1, pass\n"
        "  --video (and --reference if you have the clean track):\n"
        f"    {display_command(['aksal', 'phase2', str(lines_file),
                               '--video', 'EPISODE.mkv'])}")


def standalone_project(lines_file: Path, events: list[ass.Event], args) -> Project:
    """Build a project for a hand-made subtitle, with no phase 1 behind it.

    Everything phase 1 would have recorded has to be established here instead:
    what audio to align against, and how its timeline maps to the video's.

    Only the span the subtitle actually covers is decoded. Aligning a 90-second
    song against a whole episode would otherwise compute emissions over 24 minutes
    of audio, nearly all of it dialogue with no text to match.
    """
    from . import audio as audio_mod
    from . import locate, separate

    root = (args.output_dir or project_mod.default_output_dir(lines_file)).resolve()
    root.mkdir(parents=True, exist_ok=True)
    audio_dir = root / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Same contract as phase 1: a local file or a URL for yt-dlp, cached
    # beside the project under the same name so the two phases share it.
    reference = resolve_media(
        args.reference, audio_dir / "reference.m4a", log=log)

    pad = 2.0
    start = max(min(e.start for e in events) - pad, 0.0)
    end = max(e.end for e in events) + pad
    dur = end - start

    if reference:
        # The subtitle is timed to the video, so we still need the offset
        # between the video and the clean track.
        log("\nlocating song in video (fingerprint)")
        segments = locate.locate_by_fingerprint(
            reference, args.video, max(start - 30.0, 0.0), dur + 60.0,
            log=log)
        if not segments:
            raise SystemExit("reference track does not match this video.")
        source, a_start, a_dur = reference, None, None
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
                source, audio_dir / "window.wav",
                a_start, a_dur)
            a_start = a_dur = None
        align_source = separate.separate(
            source, audio_dir / "vocals.wav",
            device=args.device, log=log)

    timing_model, selection_model = model_spec.resolve(
        args.model, args.timing_model, args.selection_model)
    proj = Project(root=root, video=args.video,
                   mode="reference" if reference else "video",
                   align_audio=align_source, reference=reference,
                   segments=segments,
                   timing_model=timing_model,
                   selection_model=selection_model,
                   analyser=args.analyser or "ichiran",
                   conditioned=bool(args.separate_vocals),
                   separated=bool(args.separate_vocals),
                   selection_separated=bool(args.separate_selection_audio))
    proj.audio_start, proj.audio_dur = a_start, a_dur
    proj.save()
    return proj


def cmd_phase2(args) -> None:
    from . import align as A
    from . import audio as audio_mod
    from . import reading_selector, separate, timing
    from .audio import SR, envelope, prepare

    lines_file: Path = args.lines
    if not lines_file.exists():
        raise SystemExit(f"lines file not found: {lines_file}")

    # Validated BEFORE any work. This used to be checked after alignment, so a
    # typo in --tracks cost the whole model-loading and alignment run before
    # the run died having written nothing.
    wanted = {t.strip() for t in args.tracks.split(",") if t.strip()}
    if not wanted or wanted - {"jp", "romaji"}:
        raise SystemExit("--tracks accepts jp and/or romaji, e.g. --tracks jp "
                         "or --tracks jp,romaji")

    events = ass.read(lines_file)
    if not events:
        raise SystemExit(f"no dialogue events in {lines_file.name}")

    if args.video:
        proj = standalone_project(lines_file, events, args)
    else:
        try:
            proj = Project.load(resolve_project_root(lines_file, args.output_dir))
        except SystemExit as exc:
            raise SystemExit(
                f"{exc}\n\n"
                "  If this subtitle was made by hand rather than by phase1,\n"
                "  pass --video (and --reference if you have the clean track):\n"
                f"    {display_command(['aksal', 'phase2', str(lines_file),
                                         '--video', 'EPISODE.mkv'])}")

    # Command-line role flags override saved project choices. The general
    # --model applies to both roles; a role-specific flag wins over it.
    if args.model:
        proj.timing_model = args.model
        proj.selection_model = args.model
    if args.timing_model:
        proj.timing_model = args.timing_model
    if args.selection_model:
        proj.selection_model = args.selection_model
    if args.analyser:
        proj.analyser = args.analyser
    readings.set_engine(proj.analyser)
    if args.separate_vocals:
        proj.separated = True
        proj.conditioned = True
    if args.separate_selection_audio:
        proj.selection_separated = True
    proj.save()

    log(f"\nproject : {proj.name}  ({proj.mode} mode)")
    log(f"lines   : {lines_file}   {len(events)} line(s)")

    from . import selection_state

    selection_data = selection_state.load(proj.selections)
    overrides = selection_state.manual_overrides(proj.readings, selection_data)
    if overrides:
        log(f"  {len(overrides)} manual reading override(s)")

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
        src = timing.from_video(
            proj, first, last, device=args.device, log=log)
    else:
        if proj.mode != "reference" or proj.reference is None:
            raise SystemExit(
                "--time-against reference requires a project created with "
                "--reference")
        src = timing.from_reference(proj, device=args.device, log=log)
    log(f"  timing against {src.describe()}")

    y = prepare(src.audio, src.start, src.dur, condition=src.conditioned)
    from .artifacts import array_identity, emissions_key

    audio_identity = array_identity(y)

    def line_audio_interval(event: ass.Event) -> tuple[float, float]:
        if src.name == "video":
            start, end = src.to_audio(event.start), src.to_audio(event.end)
        else:
            segment = (proj.segment_at_video(event.start)
                       or proj.segment_at_video(event.end))
            start = proj.clamp_to_audio(event.start)
            end = proj.clamp_to_audio(event.end)
            if segment is not None:
                start = min(max(start, segment.ref_start), segment.ref_end)
                end = min(max(end, segment.ref_start), segment.ref_end)
        if end <= start:
            end = start + 0.5
        return start, end

    # Reading selection is a line-level operation and therefore runs before
    # mora timing. It adds bounded context around the corrected ASS windows,
    # persists decisions, and reuses them only while text, audio, model and
    # candidates all match. The timing pass below still uses the exact window.
    selected_by_event: dict[int, reading_selector.LineSelection] = {}
    selection_errors: dict[int, str] = {}
    selection_plans = []
    active_selection_keys: set[str] = set()
    if proj.lyrics_source != "romaji":
        for event_index, event in enumerate(events):
            surface = readings.normalise_surface(event.plain)
            line_id = event_index + 1
            if not surface or overrides.get_for(line_id, surface) is not None:
                continue
            words = readings.analyse_words(surface)
            choices = reading_selector.candidate_choices(
                words, readings.candidate_readings)
            if any(len(choice) > 1 for choice in choices):
                start, end = line_audio_interval(event)
                start, end = reading_score_interval(
                    start, end, len(y) / SR)
                selection_plans.append(
                    (event_index, surface, words, choices, start, end))

    aligner = None
    lp = None
    if selection_plans:
        log(f"\nreading selection ({len(selection_plans)} ambiguous line(s), "
            f"{READING_CONTEXT:.2f}s context on each side)")
        fresh_plans = []
        decision_model = model_spec.decision_identity(proj.selection_model)
        isolate_selection = proj.selection_separated and not proj.separated
        selection_audio = (f"demucs:{separate.MODEL}"
                           if isolate_selection else "source")
        for event_index, surface, words, choices, start, end in selection_plans:
            key = selection_state.decision_key(
                surface=surface, start=start, end=end,
                model_identity=decision_model,
                audio_identity=audio_identity, choices=choices,
                stage="phase2", selection_audio=selection_audio,
            )
            active_selection_keys.add(key)
            saved = selection_state.get(selection_data, key)
            if saved is not None:
                selected_by_event[event_index] = saved
            else:
                fresh_plans.append(
                    (key, event_index, words, choices, start, end))

        direct_plans = []
        direct_clips = []
        for plan in fresh_plans:
            try:
                direct_clips.append(reading_selector.audio_clip(
                    y, plan[-2], plan[-1], SR))
                direct_plans.append(plan)
            except reading_selector.SelectionError as exc:
                selection_errors[plan[1]] = str(exc)

        if direct_plans and isolate_selection:
            direct_clips = separate.separate_waveforms(
                direct_clips, sample_rate=SR, device=args.device, log=log)
            direct_clips = [
                audio_mod.normalize(audio_mod.highpass(clip))
                for clip in direct_clips
            ]

        if direct_plans:
            selector = A.Aligner(proj.selection_model, log=log)

        for plan, clip in zip(direct_plans, direct_clips):
            key, event_index, words, choices, _start, _end = plan
            try:
                selection = reading_selector.select(
                    words, selector, selector.emissions(clip),
                    readings.candidate_readings, choices=choices)
            except reading_selector.SelectionError as exc:
                selection_errors[event_index] = str(exc)
                continue
            selected_by_event[event_index] = selection
            selection_state.put(
                selection_data, key, selection, "phase2")

        if direct_plans and proj.selection_model == proj.timing_model:
            aligner = selector
        elif direct_plans:
            del selector
            import gc

            gc.collect()

    selection_state.prune_stage(
        selection_data, "phase2", active_selection_keys)

    if aligner is None:
        aligner = A.Aligner(proj.timing_model, log=log)
    if lp is None:
        cache_key = emissions_key(
            aligner.model_identity, aligner.frame_stride, y, audio_identity)
        lp = aligner.emissions(y, cache=proj.emissions_cache_for(cache_key))
    env = envelope(y)

    jp_events: list[ass.Event] = []
    ro_events: list[ass.Event] = []
    snapped = 0

    phase2_table: list[tuple[int, str, str, str]] = []
    for event_index, ev in enumerate(events):
        surface = ev.plain
        if not surface:
            continue
        line_id = event_index + 1
        manual = overrides.get_for(line_id, surface)
        line_overrides = ({readings.normalise_surface(surface): manual}
                          if manual else {})
        selected = selected_by_event.get(event_index)
        if selected is not None:
            line_overrides[readings.normalise_surface(surface)] = selected.reading
        if proj.lyrics_source == "romaji":
            units, owner, ro_cells = readings.units_and_romaji(
                surface, line_overrides, "romaji")
            chosen_reading = ""
        else:
            words = readings.resolve_words(surface, line_overrides, "jp")
            units, owner = moras.split_words(words)
            ro_cells = romaji.line_spaced(units, owner)
            chosen_reading = " ".join(words)
        if not units:
            continue

        if proj.lyrics_source != "romaji":
            flag = readings.flags_for(surface, chosen_reading, "jp")
            if event_index in selection_errors:
                flag = ",".join(filter(None, [flag, "selection-error"]))
            phase2_table.append(
                (line_id, flag, surface, chosen_reading))

        # Re-align inside the window you approved. Because the window is ground
        # truth, an error here cannot leak into any other line.
        a, b = line_audio_interval(ev)
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

    if phase2_table:
        readings.write_table(proj.readings, phase2_table)
        selection_state.update_table_baseline(
            selection_data, phase2_table, overrides)
    selection_state.save(proj.selections, selection_data)

    # From a romaji sheet the "JP" track is reconstructed kana, not the original
    # orthography -- there is no kanji to recover -- so name it honestly.
    kana_only = proj.lyrics_source == "romaji"
    if snapped:
        log(f"  snapped {snapped} mora start(s) to onsets")
    log("")
    if "jp" in wanted:
        out_jp = proj.kara_kana_file if kana_only else proj.kara_jp_file
        ass.write(out_jp, jp_events, [ass.STYLE_JP], project=proj.root)
        log(f"wrote {out_jp}")
    if "romaji" in wanted:
        out_ro = proj.kara_romaji_file
        ass.write(out_ro, ro_events, [ass.STYLE_RO], project=proj.root)
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
    p1.add_argument("-o", "--output-dir", type=Path, default=None,
                    help="project directory (not an ASS filename) for lines, "
                         "editable readings, audio, caches and karaoke. Default: "
                         "<video>.aksal beside the video.")
    p1.add_argument("--lyrics", required=True,
                    help="a local file, a Uta-Net or LRCLIB track URL, or a "
                         "search term for LRCLIB. Whatever the source, the "
                         "text is cached into the project so you can correct "
                         "it by hand.")
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
    p1.add_argument("--reference",
                    help="full-length official track: a local file, or a URL "
                         "for yt-dlp (YouTube etc), downloaded once and cached "
                         "beside the output. With it, the song is located "
                         "automatically and alignment runs on clean studio "
                         "audio -- strongly preferred.")
    p1.add_argument("--song-start", type=parse_time,
                    help="roughly where the song starts in the video, e.g. "
                         "0:36 or 21:30 for an ED. With --reference it just "
                         "narrows the search and may be a minute out; without "
                         "one it defines the window and is required.")
    p1.add_argument("--duration", type=parse_time, default=None,
                    help="how long the song runs in the video, e.g. 90 or "
                         f"1:30 (default: {DEFAULT_DURATION:.0f}s, announced "
                         "when assumed). Without --reference it also bounds "
                         "the lyrics.")
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
    p2.add_argument("--reference",
                    help="with --video: align against this clean track instead "
                         "of the video's own audio (better, needs the song). "
                         "A local file or a URL for yt-dlp, as in phase1.")
    p2.add_argument("-o", "--output-dir", type=Path,
                    help="project directory, not an ASS filename. Normally "
                         "inferred from the lines file; required to choose a "
                         "location for a hand-made subtitle when the default "
                         "is unsuitable.")
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
    pf.add_argument("-o", "--output-dir", type=Path, default=None,
                    help="project directory passed to phase 1")
    pf.add_argument("--op", dest="kind", action="store_const", const="OP",
                    help="consider only openings")
    pf.add_argument("--ed", dest="kind", action="store_const", const="ED",
                    help="consider only endings")
    pf.add_argument("--song-start", type=parse_time,
                    help="roughly where the song starts; narrows the "
                         "fingerprint search and is passed through to phase 1")
    pf.add_argument("--duration", type=parse_time, default=None,
                    help=f"as phase1 (default: {DEFAULT_DURATION:.0f}s)")
    pf.add_argument("--pick", type=int,
                    help="choose candidate N without asking (for scripts)")
    pf.add_argument("--yes", action="store_true",
                    help="accept the first plausible answer at every prompt")
    pf.add_argument("--run", action="store_true",
                    help="run phase 1 immediately without asking")
    pf.set_defaults(func=cmd_find)

    for sp in (p1, p2, pf):
        sp.add_argument("--analyser", "--analyzer", dest="analyser",
                        choices=readings.ENGINES,
                        default=None if sp is p2 else "ichiran",
                        help="which engine decides word boundaries and "
                             "readings (phase 2 keeps the project's choice; "
                             "otherwise default: ichiran). ichiran looks words "
                             "up in JMdict and picks the best parse, so it "
                             "reads set phrases as units -- 夜が明ける is "
                             "yo ga akeru, not yoru ga akeru. unidic is the "
                             "morphological analyser used by earlier versions. "
                             "Either way, anything the dictionary does not "
                             "cover falls back to unidic.")
        sp.add_argument("--model", default=None,
                        help="set both timing and reading-selection acoustic "
                             "models to this Hugging Face ID or local model")
        sp.add_argument("--timing-model", default=None,
                        help="override --model for timing only")
        sp.add_argument("--selection-model", default=None,
                        help="override --model for reading selection only")
        sp.add_argument("--device", default="cpu", help="demucs device")
        separation = sp.add_mutually_exclusive_group()
        separation.add_argument(
            "--separate-audio", dest="separate_vocals", action="store_true",
            help="isolate vocals with demucs before timing and reading "
                 "selection. Off by default: measured over eight songs it is "
                 "a wash for timing and costs about four times the runtime.")
        separation.add_argument(
            "--separate-selection-audio", action="store_true",
            help="run demucs only on short ambiguous-reading windows. Rough "
                 "timing stays on the original audio; faster than separating "
                 "the whole song and useful when music masks a reading.")
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
    root = args.output_dir or (
        project_mod.default_output_dir(video) if video
        else Path.cwd() / f"{stem}.aksal")
    root.mkdir(parents=True, exist_ok=True)

    if video is None:
        log("  lookup only: no --video, so no reference track can be verified")

    duration = args.duration if args.duration is not None else DEFAULT_DURATION
    found = discover.run(
        args.anime, video,
        root / f"{project_mod.project_name(root)}.lines.ass", kind=args.kind,
                         song_start=args.song_start, duration=duration,
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

    cmd = discover.phase1_command(found, video, root, args.song_start)
    cmd += ["--analyser", args.analyser]
    for flag, value in (("--model", args.model),
                        ("--timing-model", args.timing_model),
                        ("--selection-model", args.selection_model)):
        if value:
            cmd += [flag, value]
    if args.separate_vocals:
        cmd.append("--separate-audio")
        cmd += ["--device", args.device]
    elif args.separate_selection_audio:
        cmd.append("--separate-selection-audio")
        cmd += ["--device", args.device]
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

    # Selected before any work, so every reading in the run comes from the same
    # engine. `find` has no --analyser of its own: it hands off to phase1,
    # which does.
    if getattr(args, "analyser", None):
        readings.set_engine(args.analyser)

    # Lookup-only `find` does not touch media. All other paths do, and check
    # once up front so a missing ffmpeg is reported before model loading.
    if args.cmd != "find" or args.video is not None:
        from . import tools

        tools.ensure(log=log)

    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
