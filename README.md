# AKSAL

**AnimeFN Karaoke Syllable Aligner for Lyrics**

*A lazier way to create karaoke for anime songs.*

This is a tool that helps you create karaoke for Japanese songs in a much lazier
way. Please note: *lazier*, not automated—it still needs a human to check the
results and make adjustments in
[Aegisub](https://github.com/TypesettingTools/Aegisub).

AKSAL succeeds our previous [K-Splitter](https://github.com/animefn/ksplitter),
also known unofficially as *AFKS* (AnimeFN K-Splitter). The older tool helped
you split karaoke correctly, although it could still make mistakes. This time,
AKSAL can take Japanese or romaji lyrics, split them **and** time them to your
audio. K-Splitter only gave hints about where to split; AKSAL can also time the
sung units and convert Japanese lyrics into romaji while making the karaoke.

## Download

### **[⬇️ Download the latest AKSAL release](https://github.com/animefn/AKSAL/releases/latest)**

Windows and Linux x64 releases are ready to extract and run. Keep the
`_internal` directory beside the AKSAL executable. You can add that whole
directory to `PATH` if you want to run `aksal` from anywhere.

AKSAL downloads its acoustic models into the visible `models` folder beside
the executable on first use, so the first run takes longer and needs an
internet connection. Keep that folder when moving or updating AKSAL.

Want to run it from source or see platform details? See
**[installation and technical details](README_EXTENDED.md#installation-and-downloads)**.

## What AKSAL does today

- Times lyric lines to a song in your video.
- Splits Japanese or romaji lyrics into timed sung units.
- Produces matching Japanese and romaji karaoke tracks.
- Can group highlights by syllable or by word.
- Can map a full three-to-four-minute song onto its shorter TV edit.
- Can help find lyrics and a reference track from the anime title.
- Runs from the command line; there is no GUI yet.

## Where AKSAL fits in the karaoke-making process

- **Step 0 (preparation): Find the karaoke or lyrics.** Check
  [kara.moe](https://kara.moe/) first. If somebody already made a good k-split
  karaoke, download it and skip to adding effects. Otherwise, find Japanese or
  romaji lyrics—or transcribe them from the credits.
- **Step 1: Time the lines.** Decide where each lyric line begins and ends.
  This is AKSAL **Phase 1**.
- **Step 2: Split and time the sung units.** Turn every line into timed karaoke
  cells. This is AKSAL **Phase 2**.
- **Step 3 (optional): Add effects.** Create your own or use tools and examples
  such as [KaraEffector](https://github.com/KaraEffect0r/Kara_Effector),
  [PyonFX](https://github.com/CoffeeStraw/PyonFX),
  [karaOK](https://github.com/slackingway/karaOK),
  [Seekladoom ASS Effect](https://github.com/Seekladoom/Seekladoom-ASS-Effect),
  or this [Aegisub/PyonFX effects collection](https://github.com/kakashi1987/aegisub-lua-pyonfx-karaoke-fx-collection).
  [NyuFX](https://github.com/Youka/NyuFX) is an older, unmaintained option.

AKSAL currently helps with Step 0 and performs Steps 1 and 2. Step 3 effects are
not generated yet—but a possible Phase 3 is in the community vote below.

## How to use AKSAL

### Video tutorials

*Coming soon.*

### Explanation

**The simple workflow:**

AKSAL generates karaoke in two phases, as explained in
[Where AKSAL fits in the karaoke-making process](#where-aksal-fits-in-the-karaoke-making-process)
above:

```text
Phase 1   video + lyrics + song  →  timed lyric lines
          ↓
          You manually check and correct the line timing in Aegisub
          ↓
Phase 2   corrected lyric lines  →  Japanese + romaji k-split karaoke
          ↓
          Review the romaji, adjust the splitting to your style,
          and optionally create karaoke effects
```

### Example 1 — Your lyric lines are already timed

If you already made the line timing in Aegisub, or found a subtitle with one
lyric line per event, skip Phase 1:

```bash
aksal phase2 mylines.ass --video EP01.mkv
```

This is usually the easiest and most accurate route because you have already
given AKSAL the line boundaries it otherwise has to estimate.

### Example 2 — Lyrics already trimmed to the TV-size version

You have only the lyrics actually sung in the short version, so you do not need
the official full-length song:

```bash
aksal phase1 --video EP01.mkv --lyrics tv-size.txt --song-start 0:36 --duration 90 -o OP01.aksal

# Correct OP01.aksal/OP01.lines.ass in Aegisub, then:
aksal phase2 OP01.aksal/OP01.lines.ass
```

For an ending, use its later start time—for example `--song-start 21:30`.

### Example 3 — Full lyrics and the official song

You have an episode containing the OP or ED, the full lyrics, and the official
full-length song:

```bash
aksal phase1 --video EP01.mkv --lyrics lyrics.txt --reference "full song.flac" -o OP01.aksal

# Open OP01.aksal/OP01.lines.ass in Aegisub and fix the line timings, then:
aksal phase2 OP01.aksal/OP01.lines.ass
```

`--lyrics` can also be a Uta-Net URL, an LRCLIB track URL, or an LRCLIB search
term. The reference can be a local audio/video file or a URL supported by
yt-dlp.

### Example 4 — You only know the anime title

Let AKSAL look for the opening, lyrics, and a matching reference track, then
offer to run Phase 1:

```bash
aksal find --anime "Cross Fight B-Daman eS" --video EP16.mkv --op
```

Use `--ed` instead of `--op` when looking for an ending.

Why two phases? Your corrected line boundaries become hard limits for Phase 2,
so AKSAL cannot quietly move a syllable into the wrong line. The tool is lazy;
do not be *too* lazy—check the Phase 1 file before continuing!

For trimmed lyrics, hand-made subtitles, anime-title discovery, and every
option, see **[USAGE.md](USAGE.md)**.

## A note about Japanese readings

Songs can give familiar Japanese spellings a non-standard or poetic reading,
often called *gikun* in this context—`永遠`, for example, may be sung as
`えいえん` (*eien*) or `とわ` (*towa*)—so remember that Phase 1 romaji is only a
preview, review the result after Phase 2 listens to your corrected line, and see
[how ambiguous readings work](README_EXTENDED.md#ambiguous-japanese-readings)
when a manual `readings.tsv` choice is needed.

## Updating AKSAL

Packaged builds notify you when a newer GitHub release is available. You can
also check or update manually:

```bash
aksal update --check
aksal update
```

## Vote on what comes next

The roadmap is being prioritized through a
**[community feature vote](https://github.com/animefn/AKSAL/discussions/1)**.
React with 👍 or 👎 on each option independently:

- [Web GUI with broader karaoke-lyrics search](https://github.com/animefn/AKSAL/discussions/1#discussioncomment-18055216)
- [Phase 3 with pre-made karaoke effects](https://github.com/animefn/AKSAL/discussions/1#discussioncomment-18055217)
- [Community web catalog with CLI and web submissions](https://github.com/animefn/AKSAL/discussions/1#discussioncomment-18055218)

## Expectations and limitations

AKSAL is Japanese-only and produces a strong starting point rather than
finished karaoke, so unusual readings, sustained notes, heavy song edits, and
imperfect lyrics can still need manual correction; see the
**[full limitations and accuracy notes](README_EXTENDED.md#limitations)**.

## Why “AKSAL”?

**A**nimeFN **K**araoke **S**yllable **A**ligner for **L**yrics, a pun on the
Arabic word أكسل (*aksal*), "lazier." A fitting name for a lazier way to make
karaoke for your favourite anime songs.


## More information

- **[Complete usage guide](USAGE.md)**: workflows and examples
- **[Extended README](README_EXTENDED.md)**: advanced usage, internals,
  Japanese analysis, limitations, changelog, and roadmap
- **[Third-party notices](THIRD-PARTY.md)**: dependencies, authors, and licences
