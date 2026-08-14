# AKSAL

**AFN Karaoke Syllable Aligner for Lyrics**

Turns a song and its lyrics into syllable-timed karaoke. Works on openings,
endings and insert songs alike.

```bash
aksal phase1 --video EP01.mkv --lyrics lyrics.txt --reference song.flac -o OP01.lines.ass
# fix the lines in Aegisub, then
aksal phase2 OP01.lines.ass
```

*أكسل — "lazier". It does the tedious part.*

**→ [USAGE.md](USAGE.md) — every workflow, with examples.**

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

```bash
git clone https://github.com/animefn/AKSAL.git
cd AKSAL
pip install -e .
```

Verified on Python 3.13, including `demucs` 4.1.0. An earlier note here claimed
demucs forced a 3.11 environment; that turned out not to be true when actually
tried, and is left recorded because the claim had been repeated.

The acoustic model downloads on first run (~630 MB), is cached, and is shared
across every song. Everything else a run produces is per-song and lives beside
your output.

`--model` accepts any other CTC model that emits kana, as a Hugging Face id or a
checkpoint path. The three things the pipeline actually requires -- a kana
vocabulary, a CTC blank, 20 ms frames -- are all verified on load, because each
one fails silently rather than loudly.

---

## Where files go

Everything a run produces is a **visible sibling of the output**, sharing its
stem. There is no project directory, no hidden state, and nothing is written to
the tool's own folder:

```
D:/karaoke/
    OP01.lines.ass          <- you edit this
    OP01.lyrics.txt         <- fetched lyrics, editable
    OP01.readings.tsv       <- reading overrides, editable
    OP01.aksal.json         <- what phase 1 found
    OP01.emissions.*.pt     <- cache
    OP01.vocals.wav         <- isolated vocal stem
    OP01.kara.jp.ass        <- phase 2 output
    OP01.kara.romaji.ass
```

The caches live here too, deliberately. They are large, but they belong to one
song and are worthless once you are done with it -- so `OP01.*` removes every
trace of a run and there is nowhere else to go looking. (The acoustic model is
different: it is shared across every song, so it stays in the normal Hugging
Face cache.)

Phase 2 needs no arguments beyond the lines file. It finds `OP01.aksal.json`
next to it.

## Two input modes

The choice is really about **what your lyrics file contains**, not about the
reference track. Everything follows from that.

| | Mode A — reference | Mode B — exact text |
|---|---|---|
| inputs | video + **full** lyrics + full song | video + lyrics of **your cut** |
| lyrics must be | anything; cut lines drop out | exactly what the cut sings |
| locating the song | automatic (fingerprint) | needs `--song-start` |
| aligns against | clean studio audio | broadcast mix |
| repeated chorus | can be ambiguous | unambiguous |
| effort | point at the single | type the lines |

**Both are good, and they fail differently.** Mode A costs you nothing but the
single, and answers "which lines were broadcast" acoustically. Mode B is the
more accurate of the two when you can supply the text — measured against
hand-timed karaoke it puts most line onsets inside 0.2s — because every line you
give it is genuinely sung, which is the one thing forced alignment cannot work
out for itself.

### The combination that does not work

**A full lyric sheet with no reference track.** This is refused, not attempted.

Forced alignment has no way to express *"this line is not sung"*: every token in
the transcript must be consumed by some frame. Hand it the full sheet against a
TV size and it does not fail — it distributes the surplus across the
instrumental passages and returns a confident, monotonic, wrong path. Measured
against hand-timed karaoke that produced median errors of 3–22 seconds, with no
signal that anything had gone wrong.

So phase 1 checks whether the lyrics can physically fit the window, at the
fastest anyone sings, and stops with an explanation if they cannot. Pass
`--reference`, or cut the lyrics down to what your version actually sings.

### Locating the song

1. **`--song-start 0:36`** — always wins, costs nothing, cannot be wrong.
2. **Chapter markers**, if the container has them.
3. **Fingerprinting** against the reference (Mode A only). Cheap: pure numpy,
   well under a minute over a 7-minute search window.

There is deliberately **no automatic fallback beyond that**, for the same reason
as above: CTC cannot be used as a locator. A locator that fails silently is
worse than one that refuses.

For an **ED or insert song**, `--song-start` is the whole answer — it is just a
different timestamp. With a reference, use `--search 18:00-24:00` instead.

### No official track and no time to type the lyrics?

Skip phase 1. Rough-time the lines yourself in Aegisub — or reuse existing
subtitles — and run phase 2 on them directly. Given correct line boundaries,
phase 2 reproduces hand timing to roughly 70 ms:

    aksal phase2 mylines.ass --video EPISODE.mkv

---

## Example usage

### Mode A — the normal case

```bash
aksal phase1 \
    --video     EP01.mkv \
    --lyrics    lyrics.txt \
    --reference "full song.flac" \
    -o          D:/karaoke/OP01.lines.ass
```

Writes `OP01.lines.ass` and `OP01.readings.tsv` into `D:/karaoke/`, and reports
what it found:

```
  1 chunk(s), 87.1s of song in the video:
    video    36.56-  123.66  <- song    0.54-  87.65  (support 7539)
  ...
  lyric lines not present in this cut: 22, 23, 24, 25, 27, 28, 30, 31, 33...
```

Fix the lines in Aegisub, fix any flagged readings, then:

```bash
aksal phase2 D:/karaoke/OP01.lines.ass
```
→ `OP01.kara.jp.ass` and `OP01.kara.romaji.ass`, beside the rest

The lines file is phase 2's only required argument — the project is found from a
header stamp phase 1 leaves in it, falling back to the filename.

### Mode B — no reference track, exact text

The lyrics file must hold **only the lines your cut sings**, in order. Nothing
else works without a reference, and phase 1 will tell you so rather than guess.

```bash
aksal phase1 --video EP01.mkv --lyrics tv-size.txt -o ED01.lines.ass \
    --song-start 21:30 --duration 90
```

Typing the text is the whole cost, and it buys the most accurate line placement
the tool can produce — because you have answered the one question the aligner
cannot.

### Lyrics in romaji

Auto-detected; no flag needed. Output is named `.kara.kana.ass` rather than
`.jp.ass`, because reconstructed kana is not the original orthography.

```bash
aksal phase1 --video EP01.mkv --lyrics romaji.txt --reference song.flac -o OP01.lines.ass
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
| `-o`, `--out PATH` | `<video>.lines.ass` in the current directory | Where to write the lines file. **Everything else is written beside it, sharing that stem.** phase1 only. |

### phase1

| flag | default | meaning |
|---|---|---|
| `--video PATH` | required | Video containing the song. |
| `--lyrics PATH` | required | Plain-text lyrics, one line per subtitle line. Japanese or romaji, auto-detected. |
| `--reference PATH` | — | Full-length official track. Lets you use the **full** lyric sheet: cut lines drop out automatically. |
| `--song-start TIME` | — | Where the song starts, e.g. `0:36`. Required without a reference, unless the container has chapters. |
| `--duration SEC` | `92` | Song length. Without a reference this also bounds the lyrics: a sheet that cannot fit this window is refused. |
| `--search START-END` | — | Restrict fingerprint search, e.g. `18:00-24:00` for an ED. |
| `--search-window SEC` | `420` | Seconds of video to fingerprint. |
| `--lyrics-format` | `auto` | `auto`, `jp` or `romaji`. |
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

`<name>.readings.tsv`, beside the lines file, is an editable override table, keyed by **surface
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

- **demucs measurements are thin** — the benchmark below is raw-mix, so the
  numbers are a floor rather than what the defaults produce.
- **Japanese only**, by construction: the acoustic model's vocabulary is kana.
- **Merged-episode targets are lightly tested.**
- **A repeated chorus can be matched to the wrong occurrence.** Two identical
  chorus blocks fingerprint equally well against either, and when the wrong one
  is picked the two chunks claim the same span of the song. That is now detected
  and resolved in favour of the earlier chunk — which keeps the map monotonic,
  but can cost the lines in the disputed span. Watch for it in phase 1's output.
- **TV-original content is unreachable in Mode A.** If the broadcast sings
  something the released single does not contain, no reference can locate it.

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

### 1. The skip state

The single largest remaining win, and the root cause behind most of what phase 1
still gets wrong.

Forced alignment must consume every token, so a line that is not sung has
nowhere to go and the surplus lands in the nearest instrumental passage. That is
why a line after a long rest starts too early, why a 13-second interlude gets
swallowed, and why a full lyric sheet cannot be used without a reference.

`torchaudio.functional.forced_align` — the function already in use — supports a
`<star>` token for exactly this: extend the emission matrix by one column and
interleave stars between lines. A small penalty lets the path absorb rests; a
larger one lets it decide a line is absent. No new dependency and no hand-written
trellis.

The complementary approach, for deciding *which* lines are sung: greedily decode
the window (argmax over an emission matrix already computed, so nearly free),
then locally align the lyric sheet against that rough hypothesis as a
**text-to-text** problem. Skipping is free in local alignment, which is the whole
point of it. Lines that match a region are sung; lines that match nothing were
cut. Then force-align only the matched lines inside their matched spans. This is
the standard anchor-based method for long audio with an imperfect transcript.

### 2. Verify what is currently assumed

- **Run demucs end to end across the test set.** It is the default path and
  every published number here is `--no-preprocess`.
- The skip state (see below) — the single largest remaining win.

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
