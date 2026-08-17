# AKSAL — extended documentation

This is the technical companion to the friendly [main README](README.md). It
collects installation details, advanced workflows, implementation notes,
Japanese analysis, limitations, release information, and the changelog.

For command examples organized by what material you already have, start with
[USAGE.md](USAGE.md).

## Contents

- [Installation and downloads](#installation-and-downloads)
- [Project files](#project-files)
- [Choosing the correct input workflow](#choosing-the-correct-input-workflow)
- [Advanced usage](#advanced-usage)
- [How alignment works](#how-alignment-works)
- [Accuracy and acoustic models](#accuracy-and-acoustic-models)
- [Japanese analysis: Ichiran and UniDic](#japanese-analysis-ichiran-and-unidic)
- [Ambiguous Japanese readings](#ambiguous-japanese-readings)
- [Limitations](#limitations)
- [Updates and release builds](#updates-and-release-builds)
- [Changelog](#changelog)
- [Technical roadmap](#technical-roadmap)

## Installation and downloads

The easiest route is the
[latest packaged release](https://github.com/animefn/AKSAL/releases/latest).
Unzip the Windows archive and keep `aksal.exe` beside its `_internal` folder.

A tested Linux x64 archive is produced by the manual `build-linux` GitHub
Actions workflow. Runtime storage and helper-tool selection support macOS, but
a distributable macOS application still needs a native build, code signing,
and notarization.

Packaged builds offer to download a compatible FFmpeg build when it is missing.
On macOS, install FFmpeg with `brew install ffmpeg`. The acoustic and Demucs
models are not bundled; they download into AKSAL's writable per-user cache on
first use. The default acoustic model is roughly 630 MB and the Demucs model is
roughly 80 MB; the packaged application, framework caches, and any additional
models can bring total disk use to several gigabytes.

### Running from source

Source installs require Python 3.10 or newer, plus `ffmpeg` and `ffprobe` on
`PATH`:

```bash
git clone https://github.com/animefn/AKSAL.git
cd AKSAL
pip install -e .
```

The source installation has been verified on Python 3.13, including Demucs.

For optional vocal separation:

```bash
pip install -e ".[separate]"
```

The repository pins application dependencies because model behavior and
alignment accuracy can change across library versions. Release builders use
`requirements.lock` and a CPU-only PyTorch index.

### Runtime storage

- `AKSAL_CACHE_HOME` overrides the model and reproducible-download cache.
- `AKSAL_HOME` overrides configuration, update metadata, and downloaded helper
  programs.
- Project-specific audio and emissions stay inside the selected project
  directory.

## Project files

`-o/--output-dir` names one self-contained project directory. If omitted, the
default is `<video>.aksal` beside the video. It is a directory, not an ASS
filename, and project-specific files are never written into AKSAL's own program
folder.

```text
OP01.aksal/
    project.json
    OP01.lines.ass          ← correct this after Phase 1
    OP01.kara.jp.ass        ← Phase 2 output
    OP01.kara.romaji.ass
    lyrics.txt              ← fetched lyrics; editable
    readings.tsv            ← reading and word-boundary overrides
    selections.json         ← reusable acoustic reading choices
    audio/                  ← reference, window, and vocal derivatives
    cache/emissions/        ← model emissions
```

Phase 2 normally needs only `OP01.lines.ass`; it finds `project.json` beside
the subtitle. Project caches can be large, but they are safe to delete after
you have finished that song because they have no value outside its project.

All generated ASS files live together in the project root. AKSAL does not use
the ASS `Effect` field for hidden line identifiers, so ordinary Aegisub scripts
remain free to use it.

## Choosing the correct input workflow

Phase 1 must know both **which lines are sung** and **where the song is**. The
lyrics and reference audio/video must describe the same material.

| Your lyrics contain | Give AKSAL | Result |
|---|---|---|
| The full song | `--reference` with the full official track | Fingerprinting maps retained chunks into the video and drops lines outside them. |
| Only the lines sung by your cut | `--song-start` and `--duration` | AKSAL times exactly the text you supplied. |
| A short cut | A reference containing that same short cut | This also works because the two inputs still describe the same material. |

The broken combination is a full lyric sheet with no reference. Forced
alignment cannot decide that a line was omitted: it must place every token, so
surplus lyrics get spread across instrumental passages. AKSAL checks whether
the text can physically fit and rejects clearly impossible cases.

When convenient, manually trimming the lyrics to exactly what the cut sings is
often more accurate than reference mapping. Supplying the full single is the
lower-effort route.

### Locating the song

`--song-start` is a rough hint:

- With `--reference`, it narrows the fingerprint search with generous slack.
  It may be omitted, at the cost of searching more of the video.
- Without `--reference`, it defines the actual alignment window together with
  `--duration`, so it is required and should be reasonably accurate.

For an ending, use the later timestamp where the ED begins. The same mechanism
works when two episodes share one media file.

### Skip Phase 1 when you already have line timing

If you can rough-time the lyrics yourself in Aegisub—or reuse an existing
subtitle—run Phase 2 directly:

```bash
aksal phase2 mylines.ass --video EPISODE.mkv
```

Correct line boundaries are the strongest input AKSAL can receive because
Phase 2 treats them as hard constraints.

## Advanced usage

The full workflow guide is [USAGE.md](USAGE.md), and the installed program is
always authoritative:

```bash
aksal phase1 --help
aksal phase2 --help
aksal find --help
```

### Full lyrics and the official single

```bash
aksal phase1 --video EP01.mkv --lyrics lyrics.txt --reference "full song.flac" -o OP01.aksal

aksal phase2 OP01.aksal/OP01.lines.ass
```

`--lyrics` accepts a local file, a Uta-Net song URL, an LRCLIB track URL, or an
LRCLIB search term. Lyrics are cached into the project so you can correct them.
`--reference` accepts a local audio/video file or a URL understood by yt-dlp.
Downloaded references receive no special trust: AKSAL fingerprints them
against the episode and rejects a wrong recording.

### Lyrics trimmed to the TV cut

```bash
aksal phase1 --video EP01.mkv --lyrics tv-size.txt --song-start 0:36 --duration 90 -o OP01.aksal
```

The file must contain only the lines that this version sings, in order.

### Discovering a song from the anime title

```bash
aksal find --anime "Cross Fight B-Daman eS" --video EP16.mkv --op
```

`find` asks anime databases for the theme, searches for lyrics and a reference,
checks the candidate recording against the episode, and offers to start Phase
1. Without `--video`, it performs lookup only because it has no audio against
which to verify a downloaded track.

### Romaji input

Romaji lyrics are detected automatically. Their spelling, capitalization,
punctuation, and spacing are authoritative; no Japanese morphological analyser
runs. Because Japanese orthography cannot be reconstructed from romaji, the
kana output is named `.kara.kana.ass` instead of `.kara.jp.ass`.

### Options worth understanding

| Option | Purpose |
|---|---|
| `--group word` | Highlight one word at a time instead of one sung unit. Timing is unchanged. |
| `--tracks jp` | Write only the requested karaoke track. |
| `--time-against reference` | In Phase 2, time against the clean reference instead of the broadcast mix. |
| `--lead-in SEC` | Shift all Phase 1 cues earlier by a fixed amount. |
| `--no-lrc-hints` | Ignore verified LRCLIB synchronized line starts. |
| `--skip-cost -1.5` | Allow audio between lines to consume no lyric. Experimental: it improves some songs and regresses others. |
| `--analyser ichiran` or `--analyser unidic` | Select Japanese word boundaries and dictionary readings. |
| `--model SPEC` | Set both timing and reading-selection acoustic models. |
| `--timing-model SPEC` | Override only the timing model. It takes precedence over `--model`. |
| `--selection-model SPEC` | Override only the ambiguous-reading model. It takes precedence over `--model`. |
| `--separate-audio` | Run Demucs on the full working audio before timing and selection. |
| `--separate-selection-audio` | Run Demucs only on short ambiguous-reading clips. It is mutually exclusive with full separation. |

The default model remains in effect for whichever role you do not override. A
replacement timing model must be a compatible Japanese kana CTC model; AKSAL
checks its vocabulary, blank token, and frame stride and rejects incompatible
models. Whisper-style sequence-to-sequence models are not CTC aligners.

## How alignment works

Karaoke timing is awkward because published lyrics usually describe a full
three-to-four-minute song while an anime uses a roughly ninety-second edit.
AKSAL can align the full lyrics against the full official recording, then map
the retained audio chunks onto the episode.

Audio fingerprints form diagonal runs in reference-time/video-time space.
Grouping those runs by their offset recovers multiple retained chunks, even
when the TV edit jumps from an early verse to the ending. Repeated choruses are
handled as ordered chunks rather than flattened into one global offset.

The reference is also cleaner than the episode: it has no dialogue, sound
effects, ducking, or broadcast cross-fade. The video still remains the default
source for final Phase 2 timing because it measures what was actually aired.

Once the relevant material is known, a kana CTC model supplies acoustic token
positions. Phase 1 turns those into editable line windows. Phase 2 aligns again
inside each corrected line and derives karaoke durations from the positions of
successive CTC spikes, with optional energy-onset snapping.

## Accuracy and acoustic models

The main accuracy decisions, in descending practical importance, are:

1. Phase 2 aligns each line inside the boundaries you approved.
2. Energy-onset snapping adjusts CTC spikes toward audible attacks.
3. Signal conditioning uses a high-pass filter and consistent normalization.
4. Optional Demucs separation can help when dialogue or effects mask the song,
   though it is slower and is not consistently better on clean material.

Reading selection deliberately uses a direct, padded clip for each ambiguous
line. It does not slice probabilities computed across the whole song: neural
context and normalization make those two operations observably different.
`--separate-selection-audio` isolates vocals only for these small clips and
loads Demucs once for the batch.

### CTC details that matter

- The blank token is model-specific; it is not safe to assume index zero.
- CTC output is peaky. Spike positions are useful, but spike widths do not
  represent how long a syllable was held. AKSAL derives durations from the
  distance between positions and caps implausible holds.
- A model that cannot emit the required kana cannot align Japanese lyrics,
  even if it is otherwise advertised as Japanese speech recognition.

The built-in model downloads once and is shared across projects. Emissions are
cached per project so correcting readings does not require re-running the
entire acoustic model unnecessarily.

## Japanese analysis: Ichiran and UniDic

Japanese has no written spaces, and a kanji may change reading inside a phrase.
AKSAL therefore needs both a reading and a defensible place to draw word
boundaries.

| Engine | How it decides |
|---|---|
| **Ichiran** (default) | Searches the bundled JMdict-derived index for the best phrase parse. It can recognize set phrases and number-plus-counter readings as units. This is a Python port of [Ichiran](https://github.com/tshatrov/ichiran), the engine behind ichi.moe. |
| **UniDic** | Uses the morphological analyser from earlier AKSAL versions. It reliably supplies a fallback analysis but tends to split phrases into shorter dictionary forms. |

The difference is structural rather than a tuning preference. A morphological
analysis may read `夜` alone as `よる`, while a dictionary phrase entry knows
that `夜が明ける` begins with `よ`. Representative differences include:

```text
                Ichiran                 UniDic
夜が明けても    yo ga aketemo           yoru ga akete mo
狂っていた      kurutteita              kurutte i ta
一度            ichido                  ichi do
と共に          totomoni                to tomoni
10冊            jussatsu                10 satsu
1人             hitori                  1nin
```

Anything the dictionary path cannot cover falls back to UniDic. A dictionary
unit is not automatically kept as one karaoke word: AKSAL splits a joined unit
again when doing so loses no reading information. This makes `--group word`
less coarse without changing the default syllable-level timing.

Word splitting still has no single culturally neutral answer. Whether a
particle attaches to the preceding word is often a karaoke-author convention,
not a pronunciation error. This affects word grouping; it does not remove or
retime sounds in syllable grouping.

### Custom phrase boundaries

AKSAL rejoins a small built-in list of familiar expressions such as `共に` and
`どうにか` when the analyser splits them into shorter grammatical units. This
changes word grouping and romaji spaces, but not the mora or their timing.

The list is editable. Put `aksal.phrases.tsv` in AKSAL's per-user data
directory, with the phrase in the first tab-separated column. Add a reading in
the second column only when joining the analysed parts would produce the wrong
one. Use `DELETE` in that column to remove a built-in entry:

```text
本当に
誰か	DELETE
```

## Ambiguous Japanese readings

A spelling can have several real readings, and songs frequently choose a
poetic one. Examples include:

- `心`: `こころ` (*kokoro*) or `しん` (*shin*)
- `未だ`: `まだ` (*mada*) or `いまだ` (*imada*)
- `方`: `ほう` (*hou*) or `かた` (*kata*)
- `永遠`: `えいえん` (*eien*) or the common lyrical reading `とわ` (*towa*)

These are not cosmetic differences: they change the mora count and therefore
the alignment. AKSAL records known alternatives in `readings.tsv` and as an
ASS comment beside the affected line, including romaji:

```text
AKSAL: 永遠 candidates えいえん [eien] / とわ [towa]; kept えいえん [eien]
```

For Japanese input, the selection model scores complete-sentence reading
hypotheses against the line's own audio clip, with context added before and
after it. It changes the baseline only when the acoustic result is sufficiently
clear; uncertain alternatives stay visible for human review.

Phase 1 romaji is deliberately provisional. Suppose
`未だ探し歩いている` is sung as `いまだ…`, but the rough line starts after the
initial `い`. Phase 1 may preview *mada*. If you move the start earlier in
Aegisub, Phase 2 scores the corrected clip and can choose *imada*.

Phase 2 saves acoustic choices in `selections.json` and reuses them until a
relevant input changes: text, timing, audio, model, candidates, analyser, or
scorer. A manual edit in `readings.tsv` always wins. See
[reading arbitration internals](docs/reading-arbitration.md).

## Limitations

These matter because several can produce plausible-looking output rather than
a clean error:

- **AKSAL is Japanese-only.** Its acoustic vocabulary is kana.
- **The result is a first pass.** Line timing is usually the strongest part;
  sustained vowels, melisma, breaths, and expressive attacks still benefit
  from Aegisub waveform correction.
- **Japanese word boundaries are conventional.** Different analysers and
  karaoke authors can split valid text differently. Syllable grouping is less
  sensitive to that choice than word grouping.
- **Romanization styles differ.** Long vowels may be written `o`, `ou`, `oo`,
  or `ō`, and particles vary by house style. With romaji input, your spelling
  and spacing are preserved.
- **Some readings cannot be inferred from spelling.** Alternative and poetic
  readings—including gikun—need acoustic evidence or a manual override.
- **Full lyrics need a matching reference.** Without one, AKSAL cannot know
  which lines a short edit omitted.
- **Reference mapping assumes retained chunks remain in chronological order.**
  Ordinary TV edits and repeated choruses work; a cut that deliberately
  reorders the song can defeat the mapping. Trim the lyrics manually in that
  case.
- **Missing source lyrics stay missing.** If the anime sings a hook omitted by
  the lyric site, fingerprinting cannot invent the line. Use lyrics that match
  what is actually sung.
- **Poor audio can mislead both timing and reading selection.** Try corrected
  line windows, a clean reference, `--separate-selection-audio`, or a manual
  reading before assuming the dictionary candidate is absent.
- **The application is currently CLI-only.** A web GUI is one of the proposed
  features in the [community vote](https://github.com/animefn/AKSAL/discussions/1).

## Updates and release builds

Packaged builds check GitHub at most once per day after a successful command.
The check is best-effort and never turns a successful alignment into a failure.
Set `AKSAL_NO_UPDATE_CHECK=1` to disable notices.

```bash
aksal update --check
aksal update
```

Self-update is available only to a packaged `onedir` build for which the latest
release has a matching OS/CPU archive. AKSAL downloads the archive, verifies
its GitHub or sidecar SHA-256, validates paths while extracting, and starts a
small system helper. The helper waits for AKSAL to exit, replaces only the
top-level entries shipped by the new archive, smoke-tests the new executable,
and restores the previous bundle if installation fails. Unrelated files beside
AKSAL are preserved. Details are written to the user-data `update.log`.

Source and pip installations should be updated through Git or their package
manager instead of the self-updater.

### Building a release

PyInstaller builds are native; they cannot be cross-compiled. A tag drives the
Windows release version and archive name:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The workflow runs tests, freezes the application as an `onedir` bundle,
verifies `--help`, `--version`, model imports, and separation imports, writes a
SHA-256 sidecar, then publishes the archive. The manual Linux workflow follows
the same native build and smoke-test path without publishing a release.

`onedir` is intentional: a one-file PyTorch executable would unpack hundreds
of megabytes on every launch.

## Changelog

### Unreleased

- Added a checksum-verified, rollback-capable self-updater and daily release
  notification.
- Added native Linux build support and platform-correct FFmpeg/yt-dlp helpers.
- Improved full-song-to-TV-edit fingerprint mapping across multiple retained
  chunks and repeated choruses.
- Scores ambiguous readings from direct padded clips and can run Demucs only
  for those tie-breaking windows.
- Uses Ichiran/JMdict as the default Japanese analyser, with UniDic fallback
  and editable alternatives carrying both kana and romaji.
- Keeps project output together as `.lines.ass`, `.kara.jp.ass`, and
  `.kara.romaji.ass`, with reusable reading selections.

### 0.1.0 — initial packaged build

**Alignment**

- Fingerprint-based song location with mapping back onto the video timeline.
- CTC forced alignment and a two-phase correction workflow.
- Project emission caching and optional verified LRCLIB line anchors.

**Japanese and output**

- Mora-aware splitting, Japanese-to-romaji conversion, and editable reading
  overrides.
- Japanese and romaji tracks built from one segmentation so their `\k` splits
  match by construction.
- Optional word grouping at the same timing.

**Discovery**

- `find` connects anime-theme lookup, lyrics discovery, reference acquisition,
  fingerprint verification, and Phase 1 handoff.

## Technical roadmap

User-facing roadmap choices are tracked in the
[feature vote](https://github.com/animefn/AKSAL/discussions/1).

Technical work that remains useful regardless of that vote includes:

- **Skip-state research.** Forced alignment normally consumes every lyric
  token. An experimental skip state exists behind `--skip-cost`, but current
  measurements show mixed results. A stronger future approach would decode the
  window freely and align the lyric text against that hypothesis, where entire
  unsung lines can be skipped explicitly.
- **More ground truth.** Broader hand-timed evaluation data would make changes
  to alignment, word splitting, and reading selection safer.
- **macOS distribution.** Runtime paths already support macOS, but producing a
  friendly downloadable application requires a native runner, signing, and
  notarization.

## Attribution

AKSAL integrates work by many projects: the acoustic model, Japanese
analysers, FFmpeg, PyTorch, Demucs, and others. See
[THIRD-PARTY.md](THIRD-PARTY.md) for authors, source links, and licences.

The default acoustic model is based on
[hiragana-asr](https://github.com/nyosegawa/hiragana-asr) by Sakasegawa under
Apache-2.0. The Ichiran search design is based on
[tshatrov/ichiran](https://github.com/tshatrov/ichiran).
