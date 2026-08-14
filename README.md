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
## The one rule: your lyrics and your reference must describe the same thing

Everything about phase 1 follows from this, and most confusion comes from
breaking it.

Phase 1 has to know **which lines are sung, and where**. There are exactly two
ways it can find that out, and you pick whichever matches the lyrics you have:

| your lyrics are... | give it | how it works |
|---|---|---|
| the **full** song | `--reference` the **full** track | fingerprinting finds which chunks of the song are in the video; lines outside them drop out on their own |
| only what **your cut** sings | `--song-start` and `--duration` | you have already answered the question, so it only has to time them |

A third combination also works: lyrics trimmed to your cut *and* a reference
that is likewise only your cut — a creditless OP, say. The rule holds, because
the two still describe the same thing.

**The combination that cannot work is a full lyric sheet with no reference.**
Forced alignment has no way to say "this line is not sung": every token must be
consumed. Handed twice the text the cut contains, it does not fail — it spreads
the surplus over the instrumental passages and returns a confident, wrong
answer. Measured against hand-timed karaoke that produced median errors of
3–22 seconds with no sign anything was wrong, so phase 1 now checks whether the
lyrics can physically fit the window and stops if they cannot.

Given the choice, **trimming the lyrics beats supplying a reference**: measured
across the corpus it placed lines more accurately, because every line you hand
it is genuinely sung. The reference is the lower-effort route, not the better
one.

### Locating the song

`--song-start` is a rough hint, not a measurement.

- **With `--reference`** it only narrows the fingerprint search, and is searched
  with two minutes of slack either side — being a minute out costs nothing. Omit
  it and the whole video is searched, which is just slower.
- **Without `--reference`** it defines the window, together with `--duration`,
  and is required. Ten seconds in a player beats a scan that may be confidently
  wrong.

For an **ED**, it is the same flag with a later timestamp. For **two episodes in
one file**, the same again — the search follows the hint.

### No official track, and no time to trim the lyrics?

Skip phase 1. Rough-time the lines yourself in Aegisub — or reuse existing
subtitles — and run phase 2 on them directly. Given correct line boundaries,
phase 2 reproduces hand timing to roughly 70 ms, which is the most accurate
route there is:

    aksal phase2 mylines.ass --video EPISODE.mkv

---

## Example usage

### The normal case — full lyrics and the single

```bash
aksal phase1 \
    --video     EP01.mkv \
    --lyrics    lyrics.txt \
    --reference "full song.flac" \
    -o          D:/karaoke/OP01.lines.ass

# fix the lines in Aegisub, then
aksal phase2 D:/karaoke/OP01.lines.ass
```

`--lyrics` takes a **local file**, a **Uta-Net song URL**, or a **search term
for LRCLIB** — whatever it resolves to is cached beside your output so you can
correct it by hand:

```bash
aksal phase1 --video EP01.mkv --reference song.flac \
    --lyrics "https://www.uta-net.com/song/361192/" -o OP01.lines.ass
```

**An ED** is the same command with a later hint:

```bash
aksal phase1 --video EP01.mkv --lyrics ed.txt --reference "ed single.flac" \
    --song-start 21:30 -o ED01.lines.ass
```

### Lyrics trimmed to your cut — no reference needed

The file must hold **only the lines your version sings**, in order.

```bash
aksal phase1 --video EP01.mkv --lyrics tv-size.txt \
    --song-start 0:36 --duration 90 -o OP01.lines.ass
```

### You only know the anime — `find`

```bash
aksal find --anime "Cross Fight B-Daman eS" --video EP16.mkv --op
```

Asks three anime databases who performed the theme, finds lyrics, downloads the
official track and **fingerprints it against your episode to prove it is the
right recording**, then offers to run phase 1 immediately.

Check the series column it prints. A database asked for "eS" will answer with
the non-eS show's songs and flag nothing, so the matched series name and a
similarity score are always shown:

```
  1.00  Cross Fight B-Daman eS   OP  Dream   [animethemes]
? 0.43  Cross Game               OP  Summer Rain
```

Unattended, for an ending:

```bash
aksal find --anime "Duel Masters LOST" --video EP01.mkv --ed \
    --song-start 21:30 --pick 1 --yes --run
```

Needs `yt-dlp` on PATH. It is optional and never auto-updated — a dependency
that changes itself mid-run changes your results silently.

### Lyrics in romaji

Auto-detected; no flag. **Your spacing is authoritative** and no morphological
analyser runs at all, which removes the largest error source in the Japanese
path. The kana track is named `.kara.kana.ass` rather than `.jp.ass`, because
reconstructed kana is not the original orthography.

### Phase 2 from a hand-made subtitle

```bash
aksal phase2 mylines.ass --video EP01.mkv
```

Any subtitle with one lyric line per event. Add `--reference` to time against
the clean studio track instead of the broadcast mix.

---

## CLI reference

Three commands: `find` (optional, discovery), then `phase1` → you edit →
`phase2`.

### phase1 — lyrics to timed lines

| flag | default | meaning |
|---|---|---|
| `--video PATH` | required | Video containing the song. |
| `--lyrics SOURCE` | required | A local file, a Uta-Net song URL, or a search term for LRCLIB. Cached beside your output for hand-correction. |
| `-o`, `--out PATH` | `<video>.lines.ass` here | Where to write the lines file. **Everything else is written beside it, sharing that stem.** |
| `--reference PATH` | — | The official track. Lets you use the **full** lyric sheet: cut lines drop out automatically. |
| `--song-start TIME` | — | Roughly where the song starts, e.g. `0:36` or `21:30`. A hint with `--reference`; required and exact-ish without one. |
| `--duration SEC` | `92` | How long the song runs in the video. Without `--reference` it also bounds the lyrics. |
| `--insert-romaji` | off | Prefix each line with its romaji as `{*RO*…*RO*}`. Invisible when rendered, visible in Aegisub's edit box. |
| `--refresh-lyrics` | off | Re-fetch even if a cached copy exists. |
| `--lyrics-format` | `auto` | `auto`, `jp` or `romaji`. |
| `--lead-in SEC` | `0` | Shift every cue earlier. |
| `--no-lrc-hints` | off | Ignore LRCLIB synced line timings even when verified. |
| `--lrc-query TEXT` | — | Override the search string used to find those timings. |
| `--skip-cost N` | off | Let audio between lines match nothing. Measured a win on two songs and a regression on three, so off; try `-1.5` if output looks smeared across an instrumental. |
| `--model SPEC` | built-in | A Hugging Face id or a checkpoint path. Must emit kana; refused if not. |
| `--separate-audio` | off | Isolate vocals with demucs first. A wash for ~4× the runtime; worth trying on a noisy mix. |
| `--device` | auto | demucs device. |

### phase2 — corrected lines to karaoke

| flag | default | meaning |
|---|---|---|
| `LINES` | required | Your corrected lines file, or any hand-made subtitle. |
| `--video PATH` | — | Required only for a hand-made subtitle with no phase-1 project behind it. |
| `--reference PATH` | — | With `--video`: align against the clean track instead. |
| `--time-against` | `video` | `video` or `reference`. The video measures what was actually broadcast. |
| `--group` | `syllable` | `syllable` or `word`. Timing is identical; only the cell boundaries differ. |
| `--tracks` | `jp,romaji` | Which karaoke tracks to write. |
| `--snap` / `--no-snap` | on | Snap syllable starts to energy onsets. |
| `--project PATH` | auto | Override the stem whose state file to use. |
| `--model`, `--separate-audio`, `--device` | | As phase1. |

### find — anime name to a ready-to-run phase 1

| flag | default | meaning |
|---|---|---|
| `--anime NAME` | required | Series name, e.g. `"Cross Fight B-Daman eS"`. |
| `--video PATH` | required | The episode, used to verify the downloaded track really is this show's. |
| `-o`, `--out PATH` | `<video>.lines.ass` | Where phase 1 should write. |
| `--op` / `--ed` | both | Consider only openings, or only endings. |
| `--song-start TIME` | — | Narrows the verification search; passed through to phase 1. |
| `--duration SEC` | `92` | As phase1. |
| `--pick N` | — | Choose candidate N without asking, for scripts. |
| `--yes` | off | Accept the first plausible answer at every prompt. |
| `--run` | off | Run phase 1 immediately without asking. |

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

## Releases

Windows builds are produced by GitHub Actions from a tag:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

That is the whole ritual — the tag names the release, the archive and the
version. Tests run first, and the build refuses to publish anything whose
executable does not start.

`.github/workflows/tests.yml` runs the suite on every push; the release
workflow is separate because Windows runners are slower and billed at double.

---

## Attribution

AKSAL is glue around other people's work — the acoustic model, the Japanese
analysers, ffmpeg, PyTorch. **[THIRD-PARTY.md](THIRD-PARTY.md)** records who
made what and under which licence.

The acoustic model in particular is
[hiragana-asr](https://github.com/nyosegawa/hiragana-asr) by Sakasegawa
(Apache-2.0), and the kana vocabulary in `dualctc.py` is reproduced from that
project because token order is part of the checkpoint contract.

---

## Changelog

### 0.1.0 — first packaged build

**Alignment**
- Fingerprint-based song location, recovering the whole TV-edit splice structure
  in one pass, including edits that keep several non-adjacent chunks
- CTC forced alignment, with results mapped onto the video timeline
- Two-phase workflow: line timings you correct, then syllable timings
  constrained to those windows
- Emission caching, so iterating on readings costs seconds rather than minutes
- LRCLIB synced line timings used as anchors when they can be verified against
  the reference by duration and artist

**Acoustic model**
- Dual-CTC wav2vec2 fine-tuned from a Japanese-only encoder, downloaded on
  first run
- `--model` accepts any other kana CTC model, with its vocabulary, blank index
  and frame stride all checked rather than trusted

**Japanese**
- Mora splitting with っ as its own beat, matching how a timer counts it
- Word boundaries from unidic, with ipadic as a second opinion on compounds
- Foreign words detected and left whole rather than transliterated
- Furigana resolved to the reading that is actually sung
- Every reading and word boundary overridable in an editable TSV

**Output**
- Japanese and romaji karaoke tracks built from one segmentation, so their `\k`
  splits match by construction
- `--group word` for a calmer highlight, at identical timing

**Discovery**
- `find`: anime name → song → lyrics → reference track, each step confirmable
- The downloaded track is fingerprinted against your episode before it is
  accepted, because the top search result for a song is routinely a MAD or a
  cover

**Measured**, against hand-timed karaoke over eight songs on three shows:
0.059 s median syllable error given correct lines, 73–86% of syllables inside
100 ms. See `tests/` for the harness that produces those numbers.

---

## Limitations

Stated plainly, because each one produces plausible-looking output rather than
an error.

- **A repeated chorus can be mapped to the wrong occurrence.** Both instances
  fingerprint identically. Detected and resolved in favour of the earlier one,
  which keeps the map consistent but can cost the lines in the disputed span.
- **A lyric sheet that omits something sung loses those lines.** If the
  broadcast sings a hook the published lyrics do not print, no reference can
  find it.
- **About five words in seven hundred segment differently** from a human timer's
  convention. The remaining cases are lexical rather than grammatical — the
  readings TSV is the fix, not another rule.
- **Sustained vowels and melisma** are where syllable timing still smears.
- **Japanese only**, by construction: the model's vocabulary is kana.
- **The published numbers are without separation.** `--separate-audio` measured
  as a wash and is off by default.

---

## Roadmap

**The skip state.** Forced alignment must consume every token, so a line that is
not sung has nowhere to go and the surplus lands in the nearest instrumental
passage. `torchaudio.functional.forced_align` supports a `<star>` token for
exactly this, and it is implemented behind `--skip-cost` — but measured across
the corpus it is a win on two songs and a regression on three, so it is off. The
complementary half, not yet built, is deciding *which* lines are sung: decode
the window freely, then align the lyric sheet against that hypothesis as a
text-to-text problem, where skipping is free.

**More ground truth.** Every segmentation rule here is validated against roughly
700 words of hand-timed karaoke. That is thin. `tests/segaudit.py` scales to
more of it unchanged, and more of it would settle more than any further rule
would.

**Cross-platform builds.** Windows only today.
