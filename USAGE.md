# AKSAL — how to use it

Choose the route that matches what you already have. They are ordered from the
easiest and most reliable to the most automatic:

| What you have | What to run |
|---|---|
| Lyric lines already timed in ASS or SRT | `phase2` only — best |
| Episode, TV-size lyrics, and an approximate start time | `phase1` without a reference |
| Episode, full lyrics, and the official full-length song | `phase1` with a reference |
| Only the anime title | `find` |

Run `aksal COMMAND --help` whenever you want the complete option list.

The downloaded application can check for a newer GitHub release with
`aksal update --check`, or download and install it with `aksal update`. Normal
commands check at most once a day and print a short notice only when an update
is available.

---

## 1. Your lyric lines are already timed — `phase2` only

**This is the easiest and most accurate route**, because you have already
answered the hardest question for AKSAL: where each line begins and ends.
Rough-time one lyric line per event in Aegisub, or reuse an existing ASS or SRT
subtitle:

```bash
aksal phase2 mylines.ass --video EP01.mkv
```

For a standalone subtitle, AKSAL creates `mylines.aksal/` beside it. The final
files are `mylines.kara.jp.ass` and `mylines.kara.romaji.ass` inside that
directory. Use `-o another-folder` if you want a different project directory.

Romaji input is auto-detected; it needs no extra flag:

```bash
aksal phase2 romaji-lines.ass --video EP01.mkv
```

With romaji input, your text is authoritative. AKSAL preserves its spelling,
spaces, capitalisation, and punctuation instead of translating it through a
Japanese analyser. For example, `tsudzukete` stays `tsudzukete`, and `PURAIDO`
keeps its capitals. Punctuation is displayed but receives no karaoke duration
of its own because it is not sung.

The Japanese-side output is named `.kara.kana.ass` for romaji input: AKSAL can
reconstruct the pronunciation in kana, but it cannot recover the original
kanji.

If you also have the official full-length song, AKSAL can time against that
cleaner reference and map the result back to the episode:

```bash
aksal phase2 mylines.ass --video EP01.mkv --reference "full song.flac"
```

---

## 2. Your lyrics are already trimmed to the TV-size cut

Use a text file containing only the lines actually sung in your video, in the
same order. Give AKSAL an approximate song start and duration; no official
full-length track is needed:

```bash
aksal phase1 --video EP01.mkv --lyrics tv-size.txt --song-start 0:36 --duration 90 -o OP01.aksal
```

For an ending, use its later start time:

```bash
aksal phase1 --video EP01.mkv --lyrics ed-tv.txt --song-start 21:30 --duration 90 -o ED01.aksal
```

Open `OP01.aksal/OP01.lines.ass` in Aegisub and correct the line boundaries,
then generate the final karaoke:

```bash
aksal phase2 OP01.aksal/OP01.lines.ass
```

Do not give this route a full lyric sheet. Forced alignment cannot know which
unsung lines the TV edit removed, so it may spread them over instrumental
passages. Either trim the lyrics first or use the reference workflow below.

---

## 3. You have full lyrics and the official song

The lyric sheet may contain the complete song. AKSAL aligns it to the official
recording, fingerprints that recording against your video, then keeps only the
sections used by the TV edit:

```bash
aksal phase1 --video EP01.mkv --lyrics lyrics.txt --reference "full song.flac" -o OP01.aksal
```

Correct `OP01.aksal/OP01.lines.ass` in Aegisub, then run:

```bash
aksal phase2 OP01.aksal/OP01.lines.ass
```

`--lyrics` accepts a local file, a Uta-Net song URL, an LRCLIB track URL, or an
LRCLIB search term. `--reference` accepts a local audio/video file or a URL
supported by yt-dlp:

```bash
aksal phase1 --video EP01.mkv --lyrics "https://www.uta-net.com/song/361192/" --reference "https://www.youtube.com/watch?v=..." -o OP01.aksal
```

Downloaded references are cached inside the project and fingerprint-verified
in the same way as local files.

For an ending, add an approximate start hint. AKSAL searches with generous
slack around it, so the timestamp need not be exact:

```bash
aksal phase1 --video EP01.mkv --lyrics ed.txt --reference "ed single.flac" --song-start 21:30 -o ED01.aksal
```

If a file contains two episodes, the hint tells AKSAL which occurrence to use:

```bash
aksal phase1 --video "EP03-04.mkv" --lyrics op.txt --reference op.flac --song-start 11:00 -o OP.aksal
```

Omitting `--song-start` searches the whole video; it is valid, but slower.

---

## 4. You only know the anime title — `find`

AKSAL can search for an opening or ending, locate lyrics and a candidate
reference, verify that reference against your episode, and offer to start
Phase 1:

```bash
aksal find --anime "Cross Fight B-Daman eS" --video EP16.mkv --op
```

Use `--ed` for an ending. Check the series names and confidence scores in the
result list: similarly named anime can have misleading database matches.

To identify a theme without processing an episode, omit `--video`:

```bash
aksal find --anime "Cross Fight B-Daman eS" --op
```

Without a video, AKSAL can identify the song and lyrics but cannot verify that
a downloaded track is the same recording used in your episode.

For a non-interactive run, choose a result and approve the remaining prompts:

```bash
aksal find --anime "Duel Masters LOST" --video EP01.mkv --ed --song-start 21:30 --pick 1 --yes --run
```

Reference downloading needs `yt-dlp`. If it is not on `PATH`, AKSAL can offer
to download its standalone executable or let you point to an existing copy.

---

## Options worth knowing

| Flag | What it does |
|---|---|
| `-o DIR`, `--output-dir DIR` | Chooses the self-contained project directory. It is a directory, not an ASS filename. |
| `--no-insert-romaji` | Hides the provisional romaji helper lines in the Phase 1 subtitle. |
| `--group word` | Makes one karaoke cell per word instead of per mora. The timing itself is unchanged. |
| `--tracks jp`, `--tracks romaji` | Writes only the requested final karaoke track. |
| `--time-against video` | In Phase 2, times directly against the video instead of a saved reference. |
| `--analyser unidic` | Uses UniDic instead of the default Ichiran analyser. `--analyzer` is accepted too. |
| `--model ID` | Changes both timing and reading-selection models. The model must emit kana. |
| `--timing-model ID` | Changes only the alignment model; it overrides `--model` for timing. |
| `--selection-model ID` | Changes only the ambiguous-reading model; it overrides `--model` for selection. |
| `--device DEVICE` | Chooses the device used by Demucs. The default is `cpu`; use a supported accelerator such as `cuda` explicitly. |
| `--separate-audio` | Runs Demucs on the full working audio before timing and reading selection. It is much slower and is best treated as an option for difficult mixes. |
| `--separate-selection-audio` | Runs Demucs only on short ambiguous-reading clips. Rough timing still uses the original mix. |
| `--skip-cost N` | Enables the experimental skip state and controls how freely audio between lines may be treated as unsung. It is off by default; `none` or `off` disables it. |
| `--no-lrc-hints` | Ignores verified LRCLIB synced timings. |
| `--lead-in SEC` | Shifts every generated cue earlier by the chosen amount. |

`--separate-audio` and `--separate-selection-audio` cannot be used together.
The selected separation mode is saved in a Phase 1 project so Phase 2 can use
the same reading-selection source after you correct the lines.

Model precedence is predictable: `--model` sets both roles, then a specific
`--timing-model` or `--selection-model` overrides only its own role.

## Project files

A Phase 1 project looks like this:

```text
OP01.aksal/
    project.json
    OP01.lines.ass             ← correct this in Aegisub
    OP01.kara.jp.ass           ← generated by Phase 2
    OP01.kara.romaji.ass
    lyrics.txt                 ← fetched lyrics, editable
    readings.tsv               ← reading overrides, editable
    selections.json            ← cached acoustic reading choices
    audio/
    cache/emissions/
```

The directory name without a final `.aksal` becomes the base name of every ASS
file. Phase 2 creates the same project layout beside a standalone subtitle
unless you choose another directory with `-o`.

## Readings and corrections

Phase 1 romaji is a timing aid, not the final answer. Phase 2 analyses the text
again against your corrected line window. For example, if Phase 1 missed the
initial `い` of `未だ` and previewed *mada*, moving the line start earlier can
let Phase 2 select *imada*.

Open `readings.tsv` before the final pass. Correct any flagged choice and any
poetic reading that the singer uses, such as `永遠` read as `とわ` (*towa*)
instead of `えいえん` (*eien*). Spaces in the reading column define word
breaks and therefore the spaces in romaji karaoke. A manual edit always wins
over an automatic selection.

See [README_EXTENDED.md](README_EXTENDED.md#ambiguous-japanese-readings) for
details about Ichiran, UniDic, phrase boundaries, and acoustic tie-breaking.

## What to expect

Line timing is usually a strong starting point. Syllable boundaries still need
a human pass: sustained vowels, melisma, noisy mixes, and unusual poetic
readings are the hardest cases. Review the Phase 1 lines first, then polish the
final `\k` timing in Aegisub while looking at the waveform.
