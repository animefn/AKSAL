# AKSAL

**AnimeFN Karaoke Syllable Aligner for Lyrics**

This is a tool that helps you create karaoke for Japanese songs in a much lazier way. Please note: lazier, not automated, which means it still requires human involvement for adjustments.

The tool supersedes our previous [ksplitter](https://github.com/animefn/ksplitter). This time the tool can take Japanese or romaji lyrics, time them to your audio and perform timed syllable k-splitting (the previous tool only gave you hints as to where to split, without timing). The tool can also convert from Japanese characters to romaji while making the karaoke.



```bash
aksal phase1 --video EP01.mkv --lyrics lyrics.txt --reference song.flac -o OP01.lines.ass
# fix the lines in Aegisub, then
aksal phase2 OP01.lines.ass
```

*أكسل — "lazier"*

*A lazier way to create karaoke for anime songs.*

**→ [USAGE.md](USAGE.md) — every workflow, with examples.**

---

## Motivation

Karaoke timing is one of the most tedious jobs in fansubbing, and it never gave me any satisfaction. Existing tools help you *do* it faster; none of them work out *when* the syllables land.

The input problem is also worse than it looks. You usually have the full-length
lyrics, but the video contains a **TV edit** — a ~90 second cut of a ~4 minute
song. So half the lyrics have no audio at all, and nothing tells you which half.

**AKSAL is built on several ideas to allow for flexibility:** you can align against the **full official track**, not
the episode, then map the result onto the episode timeline.

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



## How to create karaoke effects in general:
- Step 0 (preparation): Look up kara.moe — if they already have a k-split karaoke for your song then you're done! Download it, jump to step 3 and call it a day. If not, then you need to find the lyrics for your song and create the karaoke yourself from them. There are several ways to find the lyrics: you can read the credits on screen and type the romaji yourself, or look up the web for the lyrics already written out (in Japanese) and then use some assistant tooling to generate romaji out of them, or look up the web for the romaji lyrics directly if they exist (the common and simplest way for fairly well known anime).
- Step 1: Once you have the lyrics, you time each line for your video.
- Step 2:
  - 2.1: once you have the lyrics line-timed, split them per Japanese character (aka per Japanese vocal syllable)
  - 2.2: you time each syllable to when it's being sung
- Step 3 (optional): create karaoke effects

Currently this tool helps partially with step 0, and assists you in doing step 1 (aka phase 1) and step 2 (aka phase 2).

Step 3 is currently outside the scope of this tool.



### Why two phases

Our tool does the generation in 2 phases (step 1 and step 2 above)

```
phase1   the tool takes video + lyrics + song  -> generates timed kara LINES
      ... then you manually fix the lines in Aegisub in case of mistakes ...
phase2   the tool takes corrected lines (phase 1 after your correction)        ->  and output K-Split JP karaoke + Romaji karaoke
```

Phase 2 re-aligns **inside each line window you approved** via your manual correction. The tool is for the lazy, but don't be too lazy: check the output of phase 1 (and fix it if needed) before feeding it to phase 2!

Both karaoke tracks are built from **one** syllable segmentation, so their `\k`
splits match by construction rather than by coincidence. Phase 2 asserts this and warns if they ever diverge.

### Name origin

**A**nimeFN **K**araoke **S**yllable **A**ligner for **L**yrics.

أكسل (*aksal*) — "lazier": a perfect name for a tool that provides a much lazier way to create karaoke for your favourite Japanese songs.

---

## Download

For non-technical people, the easiest way is of course to download it from the releases page.

We provide a Windows build ready to use. It will need to download some "models" the first time you launch it; these are necessary for AKSAL to work and may require up to 3 GB in total.

For people who want to play with the code:
Requires **Python 3.10+**, plus `ffmpeg` and `ffprobe` on `PATH`.

```bash
git clone https://github.com/animefn/AKSAL.git
cd AKSAL
pip install -e .
```

Verified on Python 3.13, including `demucs`.

The packaged Windows build ships demucs inside it, so `--separate-audio` works
out of the box; its model weights (~80 MB) download once on first use, like the
acoustic model. On a pip install, separation is an extra:
`pip install aksal[separate]` (or just `pip install demucs`).

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
D:/Mykaraoke/
    OP01.lines.ass          <- you edit this
    OP01.lyrics.txt         <- fetched lyrics (in case of web import), editable
    OP01.readings.tsv       <- reading overrides, editable
    OP01.aksal.json         <- what phase 1 found
    OP01.emissions.*.pt     <- cache
    OP01.reference.m4a      <- only when --reference was a URL
    OP01.vocals.wav         <- only with --separate-audio
    OP01.kara.jp.ass        <- phase 2 output
    OP01.kara.romaji.ass
```

The caches live here too, deliberately. They are large, but they belong to one
song and are worthless once you are done with it, so you can delete them once you have finished your work on that specific song.

Phase 2 needs no arguments beyond the lines file. It finds `OP01.aksal.json`
next to it.

---

## The one rule: your lyrics and your reference file (audio or video) must describe the same thing

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
correct it by hand. `--reference` likewise takes a **local file or a URL** —
anything yt-dlp understands — downloaded once and cached beside the output:

```bash
aksal phase1 --video EP01.mkv \
    --reference "https://www.youtube.com/watch?v=..." \
    --lyrics "https://www.uta-net.com/song/361192/" -o OP01.lines.ass
```

A fetched reference gets no special trust: the fingerprint match that runs
right after treats it exactly like a local file, so a wrong download fails
with the same message a wrong file would.

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
| `--reference PATH\|URL` | — | The official track: a local file, or a URL for yt-dlp (cached beside the output). Lets you use the **full** lyric sheet: cut lines drop out automatically. |
| `--song-start TIME` | — | Roughly where the song starts, e.g. `0:36` or `21:30`. A hint with `--reference`; required and exact-ish without one. |
| `--duration TIME` | `92` (announced when assumed) | How long the song runs in the video, e.g. `90` or `1:30`. Without `--reference` it also bounds the lyrics. |
| `--insert-romaji` / `--no-insert-romaji` | **on** | Prefix each line with its romaji as `{*RO*…*RO*}`. Invisible when rendered, visible in Aegisub's edit box — you are about to correct these lines, so you need to tell them apart. |
| `--refresh-lyrics` | off | Re-fetch even if a cached copy exists. |
| `--lyrics-format` | `auto` | `auto`, `jp` or `romaji`. |
| `--analyser` | `ichiran` | `ichiran` or `unidic` — which engine decides word boundaries and readings. See below. |
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
| `--reference PATH\|URL` | — | With `--video`: align against the clean track instead. File or URL, as phase1. |
| `--time-against` | `video` | `video` or `reference`. The video measures what was actually broadcast. |
| `--group` | `syllable` | `syllable` or `word`. Timing is identical; only the cell boundaries differ. |
| `--tracks` | `jp,romaji` | Which karaoke tracks to write. |
| `--snap` / `--no-snap` | on | Snap syllable starts to energy onsets. |
| `--project PATH` | auto | Override the stem whose state file to use. |
| `--model`, `--device` | | As phase1. |

### find — anime name to a ready-to-run phase 1

| flag | default | meaning |
|---|---|---|
| `--anime NAME` | required | Series name, e.g. `"Cross Fight B-Daman eS"`. |
| `--video PATH` | — | The episode. **Optional**: without it this is a lookup only, since verifying a downloaded track means fingerprinting it against your episode. |
| `-o`, `--out PATH` | `<video>.lines.ass` | Where phase 1 should write. |
| `--op` / `--ed` | both | Consider only openings, or only endings. |
| `--song-start TIME` | — | Narrows the verification search; passed through to phase 1. |
| `--duration TIME` | `92` | As phase1. |
| `--pick N` | — | Choose candidate N without asking, for scripts. |
| `--yes` | off | Accept the first plausible answer at every prompt. |
| `--run` | off | Run phase 1 immediately without asking. |

---

## Accuracy notes

Ranked by impact:

1. **Per-line windowed alignment** in phase 2 — your corrections as hard bounds.
2. **Onset snapping.** CTC spikes land inside a syllable, not on its attack.
3. **Signal conditioning** — 80Hz high-pass, and one *global* RMS normalisation
   rather than per-window, so the model sees no level jumps at window seams.
4. **Vocal isolation** (`--separate-audio`, off by default). Measured over eight
   songs it is a wash for timing — marginally better on average, worse in the
   tail, ~4× the runtime. It earns its keep on a noisy mix: SFX or dialogue
   over the song.

### Two things that silently ruin output

Both are handled, but matter if you swap models:

- **The blank index is not 0.** The default model puts `[PAD]` at 85. Assuming 0
  makes the aligner treat a real kana as "no output".
- **CTC is peaky.** Every token comes back one frame wide regardless of how long
  it was sung. Spike *positions* are trustworthy; widths are not. Durations here
  are derived spike-to-spike and capped.

Any Japanese **CTC** model works, but it must be CTC — Whisper has no CTC head
and cannot be used for alignment.

### Which analyser reads the Japanese

Two engines, `--analyser`:

| | how it decides |
|---|---|
| **`ichiran`** (default) | Looks words up in **JMdict** and picks the best parse, using a port of [ichiran](https://github.com/tshatrov/ichiran)'s search — the engine behind ichi.moe. Because it is a dictionary, it knows set phrases as units. |
| `unidic` | The morphological analyser used by earlier versions. Splits text into short units and gives each its citation reading. |

The difference is not tuning, it is structural. A morphological analyser cannot
know that 夜 is read **よ** inside 夜が明ける — it segments into short units, and
夜 on its own is よる. A dictionary that contains 夜が明ける simply has the right
reading:

```
夜が明けても    ichiran  yo ga akete mo       unidic  yoru ga akete mo
一度            ichiran  ichido               unidic  ichi do
と共に          ichiran  totomoni             unidic  to tomoni
1人             ichiran  hitori               unidic  (digit unread)
```

Anything the dictionary does not cover falls back to `unidic`, which always has
an answer — every mora has to become a karaoke cell, so a missing reading is a
broken line rather than a slightly worse one.

**On word boundaries.** A dictionary unit is not always a karaoke cell, so a
joined unit is split again when splitting **costs nothing** — ように becomes
`you ni`, because よう + に joins back to exactly the same kana, so the entry
was contributing coarseness and no reading. Where the join carries the reading
it survives: 夜が明けて stays whole because 夜 is よ only inside the phrase.
Inflected forms (歌われる) and kanji expressions (と共に) are never split.

That leaves boundaries slightly coarser than a human timer's — 11 run-on words
against `unidic`'s 5 over the hand-timed set, down from 19 before the rule.
It affects `--group word` only; syllable grouping, the default, is unaffected.

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

---

## Limitations

Stated plainly, because each one produces plausible-looking output rather than
an error.

- **Word splitting has no single right answer in Japanese.** The language is
  written without spaces, and different timers, lyric sites and analysers all
  split defensibly and differently. AKSAL agrees with human karaoke authors on
  ~95% of sound boundaries; the rest is convention, not error. With romaji
  lyrics **the word spacing is actually tricky and not always unique** and none of this applies.
- **Romanisation styles differ.** Long vowels alone can be written `o`, `ou`,
  `oo` or `ō`, and particles は/へ/を romanise differently by house style.
  AKSAL writes one consistent style; if yours differs, supply romaji lyrics
  and your spelling is kept as-is.
- **Some words are legitimately read several ways, and lyricists invent more**
  ([gikun](https://www.japanesewithanime.com/2017/12/gikun.html)): no analyser
  can know what the singer chose. Disputed and unreadable cases are flagged in
  the readings TSV rather than guessed silently.
- **Full-version lyrics against a shorter video need `--reference`.** The
  aligner cannot discard lines on its own — only the fingerprint match against
  a reference can decide which lines are in the cut. That works when the video
  uses pieces of the song in order; an edit that reorders them (first verse,
  then the ending) can defeat the mapping, and then trimming the lyrics by
  hand is the fix. Without a reference, lyrics that cannot fit the window are
  timed wrongly as the aligner will force it.
- **A lyric sheet that omits something sung loses those lines.** If the
  anime version of song sings a hook the published lyrics do not print, no reference can find it. So always make sure to use romaji that really matches the video not just generic romaji of the full version of the song.
- **Sustained vowels and melisma (basically extended vowels at end of sentences when singers "scream")** These tend to terminate earlier in our automated sync.
- **Japanese only**, by construction: the model's vocabulary is kana.


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

**More ground truth.** Every segmentation rule here is validated against roughly 700 words of hand-timed karaoke. We hope to improve this in the future with bug-reports and more testing.

**Cross-platform builds.** Windows only today. Hoping to provide mac and linux builds in the future. 
