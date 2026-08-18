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

Windows and Linux x64 releases are ready to extract and run. Each release
includes both `aksal` (command line) and `aksal-gui` (desktop GUI), sharing
one `_internal` directory -- keep it beside them. You can add that whole
directory to `PATH` if you want to run either from anywhere.

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
- Runs from the command line, or from a very simple `aksal-gui` desktop GUI
  that walks through the same two phases (see
  [installation and technical details](README_EXTENDED.md#installation-and-downloads)).

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

If you are completely new to karaoke making, AKSAL should not be your first
stop. Start by learning how karaoke timing works and becoming comfortable with
the essential Aegisub timing shortcuts. AKSAL makes the work much faster, but
you still need to understand the result well enough to review it.

These introductions cover the basics:

- [How to K-time using Aegisub](https://www.youtube.com/watch?v=3H5GuA--jhs)

or Some alternatives
- [Aegisub Lesson 10 — How to make a karaoke video with free software](https://www.youtube.com/watch?v=4YTIaMeKXts)
- [Aegisub karaoke timing tutorial](https://www.youtube.com/watch?v=BYhYgNnpNM0)
- [Vietnamese: Karaoke timing in Aegisub](https://www.youtube.com/watch?v=KG8IR8_LX_M)

Once you understand the concept, these tutorials show the three main AKSAL
workflows:

1. [Example 1: create karaoke from timed romaji lyrics](https://youtu.be/EnUfPCtAYCs)
[![Watch Example 1: timed romaji lyrics](https://img.youtube.com/vi/EnUfPCtAYCs/hqdefault.jpg)](https://youtu.be/EnUfPCtAYCs)
2. [Example 2: create karaoke from exact, untimed Japanese lyrics](https://youtu.be/1n42nikhjBo)
3. [Example 3: create karaoke from a full Japanese lyric sheet](https://youtu.be/BwdsPS7k6J4)

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

## FAQ

### How is AKSAL different from tools such as KarASS?

[KarASS](https://github.com/vladkorotnev/karass) gives you a simple interface
for manually timing lyric lines and syllables. AKSAL listens to the song and
does that timing automatically; you review the result and fix the places where
it gets things wrong.

### How good are AKSAL's results?

It depends on your use case and quality standards. I have seen human-made
karaoke that is far worse than what AKSAL produces. In my opinion, AKSAL is not
100% perfect, but its results are very acceptable for fun and singing along.
For a more formal release, you should review and correct them.

### Will AKSAL support languages other than Japanese?

It is not currently planned, but feel free to port AKSAL to your language. The
current acoustic model, segmentation, and romaji generation are all
Japanese-specific. A Korean or Chinese port would need a suitable acoustic
model plus language-specific segmentation and transliteration. Languages that
already use a Latin-based script and spaces may not need transliteration or the
same kind of segmentation, but they would still need a compatible acoustic
model and language-specific testing.

## More information

- **[Complete usage guide](USAGE.md)**: workflows and examples
- **[Extended README](README_EXTENDED.md)**: advanced usage, internals,
  Japanese analysis, limitations, changelog, and roadmap
- **[Third-party notices](THIRD-PARTY.md)**: dependencies, authors, and licences
