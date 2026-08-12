# AKSAL

**AFN Karaoke Syllable Aligner for Lyrics**

Turns a song and its lyrics into syllable-timed karaoke. Works on openings,
endings and insert songs alike — nothing in it assumes an OP.

```bash
aksal phase1 --name OP01 --video EP01.mkv --lyrics lyrics.txt --reference song.flac
# fix the lines in Aegisub, then
aksal phase2 out/OP01.lines.ass
```

*أكسل — "lazier". It does the tedious part.*

---

## Motivation

Karaoke timing is the most tedious job in fansubbing. Existing tools help you
*do* it faster; none of them work out *when* the syllables land.

The input problem is also worse than it looks. You usually have the full-length
lyrics, but the video contains a **TV edit** — a ~90 second cut of a ~4 minute
song. So half the lyrics have no audio at all, and nothing tells you which half.

**The idea AKSAL is built on:** align against the **full official track**, not
the episode. Then map the result onto the episode timeline.

That inversion is what makes it tractable:

- The reference has the **whole song in order**, so a repeated chorus is
  unambiguous — a monotonic alignment path can only pair the two instances one
  way. Aligning the TV edit directly leaves the aligner guessing which of two
  identical chorus blocks it is hearing.
- The reference is **studio-clean**: no dialogue, no SFX, no ducking.
- Lines the TV edit dropped **fall outside the mapped window and disappear on
  their own.** No manual trimming of lyrics to match the cut.

And the key structural fact: a TV edit is **splices, not time-stretching**, so
every retained chunk sits at a constant offset from the reference. Matching
fingerprint hashes form diagonals in (reference time, video time) space, and
clustering them by offset recovers the entire edit structure in one cheap pass.

### Why two phases

```
phase1   video + lyrics + song  ->  timed LINES
         ... you fix the lines in Aegisub ...
phase2   corrected lines        ->  JP karaoke + Romaji karaoke
```

Phase 2 re-aligns **inside each line window you approved**. Your corrections
become hard constraints, so an error in one line cannot leak into its
neighbours — the failure mode of any single-pass aligner. Fixing lines is also
far cheaper than fixing syllables, so the manual effort lands where it buys most.

Both karaoke tracks are built from **one** syllable segmentation, so their `\k`
splits match by construction rather than by coincidence. Phase 2 asserts this and
warns if they ever diverge.

### Name origin

**A**FN **K**araoke **S**yllable **A**ligner for **L**yrics.

أكسل (*aksal*) — "lazier".

---

## Download

Requires **Python 3.10+**, plus `ffmpeg` and `ffprobe` on `PATH`.

`demucs` is a hard dependency and lags behind new Python releases, so it dictates
your interpreter version. Use a dedicated environment:

```bash
conda create -n aksal python=3.11 -y
conda activate aksal
git clone https://github.com/animefn/AKSAL.git
cd AKSAL
pip install -e .
```

The acoustic model downloads from Hugging Face on first run and is cached.

---

## Two input modes

| | Mode A — reference | Mode B — video only |
|---|---|---|
| inputs | video + lyrics + full song | video + lyrics |
| lyrics may be | the **full** version | must match the **cut** |
| locating the song | automatic (fingerprint) | needs `--song-start` |
| aligns against | clean studio audio | broadcast mix |
| repeated chorus | unambiguous | ambiguous |

**Mode A is strongly preferred.** With the full song you get clean audio, the
lyrics in order, and automatic location — all three at once.

### Locating the song

Tried in order:

1. **`--song-start 0:36`** — always wins, costs nothing, cannot be wrong.
2. **Chapter markers**, if the container has them.
3. **Fingerprinting** against the reference (Mode A only). Cheap: pure numpy,
   well under a minute over a 7-minute search window.

There is deliberately **no automatic fallback beyond that.** CTC cannot be used
as a locator: forced alignment has no skip state, so given 7 minutes of audio and
90 seconds of lyrics it will not fail — it will spread the lyrics across all 7
minutes and return a confident, monotonic, completely wrong path. A locator that
fails silently is worse than one that refuses. Mode B without a timestamp or
chapters exits and names the flag to pass.

For an **ED or insert song**, `--song-start` is the whole answer — it is just a
different timestamp.

---

## Example usage

### Mode A — the normal case

```bash
aksal phase1 --name OP01 \
    --video     EP01.mkv \
    --lyrics    lyrics.txt \
    --reference "full song.flac"
```

Writes `out/OP01.lines.ass` and `work/OP01/readings.tsv`, and reports what it
found:

```
  1 chunk(s), 87.1s of song in the video:
    video    36.56-  123.66  <- song    0.54-  87.65  (support 7539)
  ...
  lyric lines not present in this cut: 22, 23, 24, 25, 27, 28, 30, 31, 33...
```

Fix the lines in Aegisub, fix any flagged readings, then:

```bash
aksal phase2 out/OP01.lines.ass
```
→ `out/OP01.kara.jp.ass` and `out/OP01.kara.romaji.ass`

The lines file is phase 2's only required argument — the project is found from a
header stamp phase 1 leaves in it, falling back to the filename.

### Mode B — no reference track

```bash
aksal phase1 --name ED01 --video EP01.mkv --lyrics lyrics.txt \
    --song-start 21:30 --duration 90
```

### Lyrics in romaji

Auto-detected; no flag needed. Output is named `.kara.kana.ass` rather than
`.jp.ass`, because reconstructed kana is not the original orthography.

```bash
aksal phase1 --name OP01 --video EP01.mkv --lyrics romaji.txt --reference song.flac
```

Measured on the same song, romaji vs Japanese lyrics: **line boundaries
identical** (34/34 within 0.000s), 15/17 lines with identical syllable splits.
Romaji input also skips the morphological analyser entirely, removing the largest
error source in the Japanese path.

Two things do degrade, both syllable-count only, never line timing: small vowels
(`あぁ` is one mora but romanises to `aa`, which returns as two) and `n`+vowel
(`kani` could be か-に or か-ん-い — write `kan'i`; rows at risk are flagged).

### Phase 2 from a hand-made subtitle

Phase 1 is not a prerequisite:

```bash
aksal phase2 mylines.ass --video EP01.mkv                       # video's own audio
aksal phase2 mylines.ass --video EP01.mkv --reference song.flac # clean audio
```

Only the span your subtitle covers is decoded, so this costs seconds rather than
the half hour an acoustic model over a whole episode would take.

Aligning against episode audio instead of the clean track costs accuracy:
measured, syllable onsets moved by a median of 0.02s but a 90th percentile of
0.22s, with only 79% landing within 100ms. Pass `--reference` when you can.

---

## CLI reference

```
aksal phase1 [options]
aksal phase2 LINES [options]
```

### Global

| flag | default | meaning |
|---|---|---|
| `--work DIR` | `./work` | State directory. |
| `--out DIR` | `./out` | Output directory. Phase 2 defaults to the lines file's folder. |

### phase1

| flag | default | meaning |
|---|---|---|
| `--video PATH` | required | Video containing the song. |
| `--lyrics PATH` | required | Plain-text lyrics, one line per subtitle line. Japanese or romaji, auto-detected. |
| `--reference PATH` | — | Full-length official track. Strongly preferred. |
| `--song-start TIME` | — | Where the song starts, e.g. `0:36`. Required in video-only mode without chapters. |
| `--duration SEC` | `92` | Song length, video-only mode. |
| `--search START-END` | — | Restrict fingerprint search, e.g. `18:00-24:00` for an ED. |
| `--search-window SEC` | `420` | Seconds of video to fingerprint. |
| `--lyrics-format` | `auto` | `auto`, `jp` or `romaji`. |
| `--name NAME` | video stem | Project name. |
| `--lead-in SEC` | `0` | Shift every cue earlier. |

### phase2

| flag | default | meaning |
|---|---|---|
| `LINES` | required | Your corrected lines file. |
| `--tracks` | `jp,romaji` | Which karaoke tracks to write. |
| `--video PATH` | — | Only for a hand-made subtitle with no phase1 project. |
| `--reference PATH` | — | With `--video`: align against the clean track instead. |
| `--project DIR` | auto | Override the work directory; normally found automatically. |
| `--snap` / `--no-snap` | on | Snap syllable starts to energy onsets. |

### Both

| flag | default | meaning |
|---|---|---|
| `--model NAME` | kana wav2vec2 | Japanese **CTC** acoustic model. |
| `--device` | `cpu` | demucs device. |
| `--no-preprocess` | off | Skip separation and conditioning; align raw audio. Avoids demucs; measurably worse. |

---

## Accuracy notes

Ranked by impact:

1. **Vocal isolation** (on by default). The acoustic model was trained on speech;
   in a full mix the drums and bass occupy the same spectral space as the voice.
2. **Per-line windowed alignment** in phase 2 — your corrections as hard bounds.
3. **Onset snapping.** CTC spikes land inside a syllable, not on its attack; an
   isolated vocal stem has a much sharper envelope than the posterior does.
4. **Signal conditioning** — 80Hz high-pass, and one *global* RMS normalisation
   rather than per-window, so the model sees no level jumps at window seams.

### Two things that silently ruin output

Both are handled, but matter if you swap models:

- **The blank index is not 0.** The default model puts `[PAD]` at 85. Assuming 0
  makes the aligner treat a real kana as "no output".
- **CTC is peaky.** Every token comes back one frame wide regardless of how long
  it was sung. Spike *positions* are trustworthy; widths are not. Durations here
  are derived spike-to-spike and capped.

Any Japanese **CTC** model works, but it must be CTC — Whisper has no CTC head
and cannot be used for alignment.

### Readings

`work/<name>/readings.tsv` is an editable override table, keyed by **surface
text, not line number**, so corrections survive splitting or reordering lines
between phases.

Fix anything flagged, and anything where the singer uses a non-standard reading —
analysers do not know that 永遠 is often sung とわ. On one test song the analyser
got **9 of 32 readings wrong**.

---

## Expectations

Line timings come out good. **Syllable boundaries are a solid first pass, not a
finished one** — sustained vowels and melisma are where CTC alignment smears.
Nobody ships auto-karaoke unpolished; budget time in Aegisub's karaoke mode over
the waveform, starting with whatever phase 1 flagged.

---

## Limitations

- **No test suite yet.** Everything is verified by hand on a small number of
  songs. This is the top roadmap item.
- **demucs has never been run end to end** — all measurements are raw-mix, so
  they are a floor rather than what the defaults produce.
- **Japanese only**, by construction: the acoustic model's vocabulary is kana.
- Mode B and merged-episode targets are lightly tested.

---

## Changelog

### 0.1.0

Initial release.

**Alignment**
- Fingerprint-based song location, recovering the full TV-edit splice structure
  in one pass
- CTC forced alignment against a clean reference track, with results mapped onto
  the video timeline
- Two-phase workflow: line timings you correct, then syllable timings constrained
  to those windows
- Emission caching, so iterating on readings costs seconds rather than minutes

**Output**
- JP and Romaji karaoke from one syllable segmentation, guaranteeing identical
  `\k` splits
- `\k` values tile each line exactly, including an empty lead-in cell, so the
  highlight cannot drift from the audio
- Modified Hepburn with doubled long vowels

**Input**
- Japanese or romaji lyrics, auto-detected
- Editable reading overrides keyed by surface text
- Phase 2 runnable standalone from a hand-made subtitle

---

## Roadmap

### 1. A test suite

The most urgent gap. There is currently none. ASRI's experience is the argument:
its 211 synthetic tests still missed every important bug, but they made
refactoring safe. Priority order:

- Pure-function units first: syllable splitting, romaji, `\k` tiling, ASS I/O
- Contract tests for the JP/Romaji split invariant
- Synthetic end-to-end: build audio with known syllable positions and assert
  recovery

### 2. Verify what is currently assumed

- **Run demucs end to end.** It is the default path and has never executed.
- Mode B (no reference track) at more than spot-check depth
- More songs, more artists — one OP is not a corpus

### 3. Improve syllable accuracy

- Posterior-mass durations instead of the spike-to-spike heuristic, removing the
  `max_hold` fudge factor
- Reading verification by disagreement: greedy-decode the emissions we already
  compute and flag lines where the audio disagrees with the analyser, which
  catches the 永遠/とわ class automatically and for free
- Furigana output so the JP track can show kanji with readings above

### 4. Packaging and GUI

Shared with ASRI — a standalone binary, then a GUI. Note that AKSAL drags in
torch and demucs, so a frozen AKSAL is far larger than a frozen ASRI; they should
stay separate packages even if they share a front end.
