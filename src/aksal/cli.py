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
from . import audio as audio_mod
from .audio import envelope, prepare
from .project import Project

MAX_HOLD = 2.0          # longest a single unit may be held before it is a rest


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


def parse_range(v: str) -> tuple[float, float]:
    if "-" not in v:
        raise argparse.ArgumentTypeError("expected START-END, e.g. 18:00-24:00")
    a, b = v.split("-", 1)
    return parse_time(a), parse_time(b)


# =============================================================================
# phase 1
# =============================================================================

def cmd_phase1(args) -> None:
    video: Path = args.video
    name = args.name or video.stem[:60]
    root: Path = args.work / name
    root.mkdir(parents=True, exist_ok=True)
    args.out = args.out or Path("out")
    args.out.mkdir(parents=True, exist_ok=True)

    mode = "reference" if args.reference else "video"
    window: tuple[float, float] | None = None   # slice of source to decode
    log(f"project : {name}")
    log(f"mode    : {mode}")

    # --- 1. decide what audio we align against, and how it maps to the video --
    if mode == "reference":
        source = args.reference
        # Fingerprinting is cheap; a start hint only narrows the window.
        if args.song_start is not None:
            s_start = max(args.song_start - 30.0, 0.0)
            s_dur = args.search_window
        elif args.search:
            s_start, s_dur = args.search[0], args.search[1] - args.search[0]
        else:
            s_start, s_dur = 0.0, args.search_window

        log("\nlocating song in video (fingerprint)")
        segments = locate.locate_by_fingerprint(source, video, s_start, s_dur,
                                                log=log)
        if not segments:
            raise SystemExit(
                "no match between reference and video.\n"
                "  - is the reference this show's song?\n"
                "  - widen with --search 0:00-10:00, or pass --song-start.")
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
    if args.no_preprocess:
        log("\n--no-preprocess: raw audio, no separation or conditioning "
            "(measurably less accurate)")
        align_source = source
    else:
        log("\nisolating vocals")
        if window is not None:
            # demucs needs a file, so cut the window out first rather than
            # separating a whole episode to use 80 seconds of it.
            source = audio_mod.extract_wav(source, root / "window.wav", *window)
            window = None
        align_source = separate.separate(source, root / "stems",
                                         device=args.device, log=log)

    log("\nlyrics")
    lyrics_file = root / "lyrics.txt"
    resolved = lyrics_mod.resolve(args.lyrics, cache=lyrics_file,
                                  refresh=args.refresh_lyrics, log=log)
    log(resolved.describe())

    proj = Project(name=name, root=root, video=video, lyrics=lyrics_file,
                   mode=mode, align_audio=align_source,
                   reference=args.reference, segments=segments,
                   model=args.model, conditioned=not args.no_preprocess)
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

    # --- 4. align ------------------------------------------------------------
    log("\nalignment")
    aligner = A.Aligner(args.model, log=log)
    y = prepare(align_source, proj.audio_start, proj.audio_dur,
                condition=proj.conditioned)
    lp = aligner.emissions(y, cache=proj.emissions_cache)
    log(f"  emissions: {tuple(lp.shape)}")

    # One unit per character here: phase 1 only needs line boundaries.
    units, owner = [], []
    for line_no, _surface, reading in rows:
        for ch in reading:
            if not ch.isspace():
                units.append(ch)
                owner.append(line_no)

    timed = aligner.align_units(lp, units)
    for item, line_no in zip(timed, owner):
        item["line"] = line_no

    groups: list[list[dict]] = []
    for item in timed:
        if groups and groups[-1][0]["line"] == item["line"]:
            groups[-1].append(item)
        else:
            groups.append([item])

    smeared = A.fix_tail_smear(groups, MAX_HOLD)
    A.derive_durations(timed, MAX_HOLD)
    if smeared:
        log(f"  corrected {smeared} tail-smeared character(s)")

    # --- 5. map to the video timeline and write ------------------------------
    surface_of = {n: s for n, s, _ in rows}
    events, cut = [], []
    for grp in groups:
        placed = [c for c in grp if c["start"] is not None
                  and proj.to_video(c["start"]) is not None]
        if not placed:
            cut.append(grp[0]["line"])
            continue
        start = proj.to_video(placed[0]["start"])
        seg = next(s for s in proj.segments if s.contains_ref(placed[0]["start"]))
        end = min(placed[-1]["end"], seg.ref_end) + seg.offset
        events.append(ass.Event(start=start - args.lead_in,
                                end=max(end, start + 0.4) - args.lead_in,
                                text=surface_of[grp[0]["line"]],
                                style="KARA-JP"))

    if not events:
        raise SystemExit("nothing landed inside the song window -- check "
                         "--song-start / --duration.")

    out_lines = args.out / f"{name}.lines.ass"
    ass.write(out_lines, events, [ass.STYLE_JP], project=root.resolve())

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
    log(f"\nNext: fix the lines in Aegisub, then\n"
        f"  aksal phase2 {out_lines}")


# =============================================================================
# phase 2
# =============================================================================

def resolve_project(lines_file: Path, explicit: Path | None,
                    work: Path) -> Path:
    """Find the work directory belonging to a corrected lines file.

    Phase 2 needs the audio path, the time mapping and the readings, but you
    should not have to type any of that -- phase 1 already recorded it. Tried in
    order, so an editor that mangles the header stamp is still recoverable.
    """
    if explicit:
        return explicit

    stamped = ass.read_project_stamp(lines_file)
    if stamped and (stamped / "project.json").exists():
        return stamped

    # out/OP01.lines.ass -> work/OP01, and likewise OP01.lines.fixed.ass.
    # Strip repeatedly: people stack these suffixes.
    editing_suffixes = {"lines", "fixed", "corrected", "edited", "edit", "final"}
    parts = lines_file.stem.split(".")
    while len(parts) > 1 and parts[-1].lower() in editing_suffixes:
        parts.pop()
    guess = work / ".".join(parts)
    if (guess / "project.json").exists():
        return guess

    candidates = [p.parent for p in work.glob("*/project.json")]
    if len(candidates) == 1:
        return candidates[0]

    raise SystemExit(
        f"cannot tell which project {lines_file.name} belongs to.\n"
        f"  looked for: a header stamp, then {guess}\n"
        + (f"  {len(candidates)} projects exist in {work}; "
           "pass --project to pick one." if candidates
           else f"  no projects found in {work} -- run phase1 first."))


def standalone_project(lines_file: Path, events: list[ass.Event], args) -> Project:
    """Build a project for a hand-made subtitle, with no phase 1 behind it.

    Everything phase 1 would have recorded has to be established here instead:
    what audio to align against, and how its timeline maps to the video's.

    Only the span the subtitle actually covers is decoded. Aligning a 90-second
    song against a whole episode would otherwise compute emissions over 24 minutes
    of audio, nearly all of it dialogue with no text to match.
    """
    name = args.name or lines_file.stem.split(".")[0]
    root = args.work / name
    root.mkdir(parents=True, exist_ok=True)

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
    if not args.no_preprocess:
        log("\nisolating vocals")
        if a_start is not None:
            source = audio_mod.extract_wav(source, root / "window.wav",
                                           a_start, a_dur)
            a_start = a_dur = None
        align_source = separate.separate(source, root / "stems",
                                         device=args.device, log=log)

    proj = Project(name=name, root=root, video=args.video, lyrics=lines_file,
                   mode="reference" if args.reference else "video",
                   align_audio=align_source, reference=args.reference,
                   segments=segments, model=args.model,
                   conditioned=not args.no_preprocess)
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
            proj = Project.load(resolve_project(lines_file, args.project,
                                                args.work))
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
    aligner = A.Aligner(proj.model or A.DEFAULT_MODEL, log=log)
    y = prepare(proj.align_audio, proj.audio_start, proj.audio_dur,
                condition=proj.conditioned)
    lp = aligner.emissions(y, cache=proj.emissions_cache)
    env = envelope(y)

    jp_events: list[ass.Event] = []
    ro_events: list[ass.Event] = []
    snapped = 0

    for ev in events:
        surface = ev.plain
        if not surface:
            continue
        reading = readings.resolve(surface, overrides, proj.lyrics_source)
        units = moras.split(reading)
        if not units:
            continue

        # Re-align inside the window you approved. Because the window is ground
        # truth, an error here cannot leak into any other line.
        a = proj.clamp_to_audio(ev.start)
        b = proj.clamp_to_audio(ev.end)
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

        # Audio time -> video time. Segment offsets are constant, so a mora that
        # falls just outside a segment edge is placed by the same offset rather
        # than dropped.
        offset = next((s.offset for s in proj.segments if s.contains_ref(a)),
                      proj.segments[0].offset if proj.segments else 0.0)
        v_starts = [s + offset for s in starts]

        # Both tracks tile from ONE list of boundaries, so their splits match by
        # construction rather than by coincidence.
        jp_events.append(ass.Event(
            start=ev.start, end=ev.end, style="KARA-JP",
            text=ass.karaoke_text(units, v_starts, ev.start, ev.end)))
        ro_events.append(ass.Event(
            start=ev.start, end=ev.end, style="KARA-RO",
            text=ass.karaoke_text(romaji.line(units), v_starts, ev.start, ev.end)))

    # From a romaji sheet the "JP" track is reconstructed kana, not the original
    # orthography -- there is no kanji to recover -- so name it honestly.
    kana_only = proj.lyrics_source == "romaji"
    outdir = args.out or lines_file.parent
    outdir.mkdir(parents=True, exist_ok=True)

    if snapped:
        log(f"  snapped {snapped} mora start(s) to onsets")
    log("")
    wanted = {t.strip() for t in args.tracks.split(",") if t.strip()}
    if wanted - {"jp", "romaji"}:
        raise SystemExit("--tracks accepts jp and/or romaji")
    if "jp" in wanted:
        out_jp = outdir / f"{proj.name}.kara.{'kana' if kana_only else 'jp'}.ass"
        ass.write(out_jp, jp_events, [ass.STYLE_JP], project=proj.root.resolve())
        log(f"wrote {out_jp}")
    if "romaji" in wanted:
        out_ro = outdir / f"{proj.name}.kara.romaji.ass"
        ass.write(out_ro, ro_events, [ass.STYLE_RO], project=proj.root.resolve())
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
    p.add_argument("--work", type=Path, default=Path("work"),
                   help="state directory (default: ./work)")
    p.add_argument("--out", type=Path, default=None,
                   help="output directory (default: ./out for phase1, and "
                        "alongside the lines file for phase2)")
    sub = p.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("phase1", help="produce timed lines for you to correct")
    p1.add_argument("--video", required=True, type=Path)
    p1.add_argument("--lyrics", required=True,
                    help="a local file, a Uta-Net song URL, or a search term "
                         "for LRCLIB. Whatever the source, the text is cached "
                         "into the project so you can correct it by hand.")
    p1.add_argument("--refresh-lyrics", action="store_true",
                    help="re-fetch even if the project already has a cached copy")
    p1.add_argument("--reference", type=Path,
                    help="full-length official track. With it, the song is "
                         "located automatically and alignment runs on clean "
                         "studio audio -- strongly preferred.")
    p1.add_argument("--song-start", type=parse_time,
                    help="where the song starts in the video (e.g. 0:36). "
                         "Required in video-only mode unless the container has "
                         "chapter markers. Works for EDs too.")
    p1.add_argument("--duration", type=float, default=92.0,
                    help="song length in video-only mode (default: 92s)")
    p1.add_argument("--search", type=parse_range,
                    help="restrict fingerprint search, e.g. 18:00-24:00 for an ED")
    p1.add_argument("--search-window", type=float, default=420.0,
                    help="seconds of video to fingerprint (default: 420)")
    p1.add_argument("--lyrics-format", choices=("auto", "jp", "romaji"),
                    default="auto",
                    help="script of the lyrics file (default: auto-detect). "
                         "Romaji is parsed straight to kana, skipping the "
                         "morphological analyser entirely.")
    p1.add_argument("--name", help="project name (default: video stem)")
    p1.add_argument("--lead-in", type=float, default=0.0,
                    help="shift every cue earlier by N seconds")
    p1.set_defaults(func=cmd_phase1)

    p2 = sub.add_parser(
        "phase2", help="turn corrected lines into karaoke",
        description="With a phase1 project, the lines file is the only argument "
                    "needed. For a hand-made subtitle, add --video.")
    p2.add_argument("lines", type=Path,
                    help="corrected lines file, or any hand-made subtitle")
    p2.add_argument("--tracks", default="jp,romaji",
                    help="which karaoke tracks to write (default: jp,romaji)")
    p2.add_argument("--video", type=Path,
                    help="required only for a hand-made subtitle with no "
                         "phase1 project behind it")
    p2.add_argument("--reference", type=Path,
                    help="with --video: align against this clean track instead "
                         "of the video's own audio (better, needs the song)")
    p2.add_argument("--name", help="project name for a standalone run")
    p2.add_argument("--project", type=Path,
                    help="override the work/<name> directory; normally found "
                         "from the lines file automatically")
    p2.add_argument("--snap", action="store_true", default=True,
                    help="snap mora starts to energy onsets (default: on)")
    p2.add_argument("--no-snap", dest="snap", action="store_false")
    p2.set_defaults(func=cmd_phase2)

    for sp in (p1, p2):
        sp.add_argument("--model", default=A.DEFAULT_MODEL)
        sp.add_argument("--device", default="cpu", help="demucs device")
        sp.add_argument("--no-preprocess", action="store_true",
                        help="skip vocal separation and signal conditioning, "
                             "aligning against raw audio. Avoids the demucs "
                             "dependency; measurably less accurate.")
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
