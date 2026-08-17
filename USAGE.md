# AKSAL — how to use it

Every workflow, shortest first. Pick by **what you already have**.

```
what you have                                    what to run
─────────────────────────────────────────────────────────────────────────
lines already timed (yours, or existing subs)    phase2 alone      ← best
only the anime name                              find
episode + full lyrics + the official single      phase1 (mode A)
episode + lyrics of your cut + a start time      phase1 (mode B)
```

The downloaded application can check or install a newer GitHub release with
`aksal update --check` or `aksal update`. Normal commands check at most once a
day and print a notice only when a newer version exists.

---

## 1. You already have timed lines — `phase2` alone

**The most accurate path there is** (~70 ms against hand timing), because you
have answered the only question the tool cannot: where each line begins and
ends. Rough-time the lines in Aegisub, or reuse any existing subtitle.

```bash
aksal phase2 mylines.ass --video EP01.mkv
```

Input is any ASS/SRT-shaped subtitle whose events hold one lyric line each.
Output: `mylines.kara.jp.ass` + `mylines.kara.romaji.ass`.

Romaji lines work too and are **auto-detected** — no flag:

```bash
aksal phase2 romaji-lines.ass --video EP01.mkv
```

With romaji input, **your text is authoritative and comes back character for
character** -- spacing, spelling, capitalisation and punctuation alike. No
morphological analyser runs at all, which removes the single largest error
source, and the romaji track is built from the characters you typed rather than
re-romanised from the kana. So `tsudzukete` stays `tsudzukete`, not
`tsuzukete`; `PURAIDO` keeps its capitals; `stop !` keeps its mark.

This is structural, not best-effort: the syllables to align, the word
boundaries and your text all come out of one pass over the line, so there is no
second derivation that could disagree with the first and quietly win. The only
line that does not survive is one with nothing pronounceable in it, which
produces no karaoke because there is nothing to time.

Punctuation never takes a karaoke cell of its own -- it is written, not sung,
so a cell would hand it a share of the line's duration.

The kana track is named `.kara.kana.ass` rather than `.jp.ass`, because
reconstructed kana is not the original orthography -- there is no kanji to
recover.

If you also have the official single, time against it instead of the broadcast:

```bash
aksal phase2 mylines.ass --video EP01.mkv --reference "full song.flac"
```

---

## 2. You only know the anime — `find`

```bash
aksal find --anime "Cross Fight B-Daman eS" --video EP16.mkv --op
```

Just want to know what the song is? Drop `--video` — it will name the theme and
find the lyrics, but cannot fetch a reference track, because the only way to
know a download really is this show's recording is to fingerprint it against
your episode:

```bash
aksal find --anime "Cross Fight B-Daman eS" --op
```

Asks three anime databases who did the theme, downloads the official track,
**fingerprints it against your episode to prove it is the right recording**,
looks for lyrics, then offers to run phase 1 immediately.

Check the series column it prints. A database asked for "eS" will happily answer
with the non-eS show's songs and flag nothing, so the matched series name and a
similarity score are always shown:

```
  1.00  Cross Fight B-Daman eS   OP  Dream   [animethemes]
? 0.43  Cross Game               OP  Summer Rain
```

For an ending, and unattended:

```bash
aksal find --anime "Duel Masters LOST" --video EP01.mkv --ed \
    --song-start 21:30 --pick 1 --yes --run
```

Needs `yt-dlp`. If it is not on PATH, AKSAL offers to download the native
standalone executable or lets you point at one. It is optional and never
auto-updated — a dependency that changes itself mid-run changes your results
silently.

---

## 3. Full lyrics + the official single — `phase1` mode A

The lyric sheet may be the **full** version. Lines the TV edit dropped fall
outside the mapped window and disappear by themselves.

```bash
aksal phase1 \
    --video     EP01.mkv \
    --lyrics    lyrics.txt \
    --reference "full song.flac" \
    -o          D:/karaoke/OP01.aksal

# fix the lines in Aegisub, then
aksal phase2 D:/karaoke/OP01.aksal/OP01.lines.ass
```

`--lyrics` also takes a Uta-Net song URL, an LRCLIB track URL, or an LRCLIB
search term directly, and `--reference` takes a URL for yt-dlp (YouTube etc) as
well as a file -- downloaded once, cached beside the output, and then
fingerprint-verified exactly like a local file:

```bash
aksal phase1 --video EP01.mkv \
    --reference "https://www.youtube.com/watch?v=..." \
    --lyrics "https://www.uta-net.com/song/361192/" -o OP01.aksal
```

**Endings**: the same command with a later hint. It is searched with two minutes
of slack either side, so being a minute out costs nothing.

```bash
aksal phase1 --video EP01.mkv --lyrics ed.txt --reference "ed single.flac" \
    --song-start 21:30 -o ED01.aksal
```

**Two episodes in one file**: same again — the search follows the hint. Omit
`--song-start` entirely and the whole file is searched, which is only slower.

```bash
aksal phase1 --video "EP03-04.mkv" --lyrics op.txt --reference op.flac \
    --song-start 11:00 -o OP.aksal
```

---

## 4. Lyrics of your cut + a start time — `phase1` mode B

No official track needed. The lyrics file must hold **only the lines your
version sings**, in order.

```bash
aksal phase1 --video EP01.mkv --lyrics tv-size.txt \
    --song-start 0:36 --duration 90 -o OP01.aksal
```

Typing the text is the whole cost, and it buys the most accurate line placement
phase 1 can produce — because every line you gave it is genuinely sung. For an
ending it is the same flag, later:

```bash
aksal phase1 --video EP01.mkv --lyrics ed-tv.txt \
    --song-start 21:30 --duration 90 -o ED01.aksal
```

**Refused:** a full lyric sheet with no reference. Forced alignment cannot say
"this line is not sung", so it would spread the surplus across the instrumental
passages and return a confident, wrong answer. Give it `--reference`, or cut the
lyrics down.

---

## Options worth knowing

| flag | why |
|---|---|
| `--no-insert-romaji` | phase 1 prefixes each line with its romaji by default, invisible when rendered. This turns that off. |
| `--group word` | one karaoke cell per word instead of per syllable. Timing is identical. |
| `--separate-audio` | isolate vocals with demucs first. **Off by default** — measured over eight songs it is a wash: marginally better on average, worse in the tail, for ~4x the runtime. Worth trying on a noisy mix. |
| `--separate-selection-audio` | run demucs only on short ambiguous-reading windows. Rough timing remains on the original mix, and one Demucs model load is shared across all such windows. |
| `--model` | use a different acoustic model: a Hugging Face id, or a path to a checkpoint. It must emit **kana** and the tool refuses it if not. |
| `--skip-cost N` | how freely the aligner may treat audio between lines as unsung. `none` disables it. |
| `--no-lrc-hints` | ignore LRCLIB synced timings even when verified. |
| `--lead-in SEC` | shift every cue earlier. |
| `--tracks jp` | write only one karaoke track. |

`--separate-audio` and `--separate-selection-audio` are mutually exclusive.
The latter is persisted in a phase-1 project, so phase 2 uses the same
tie-breaking source if corrected timings require a fresh decision.

## Files

`-o/--output-dir` is a self-contained project directory:

```
OP01.aksal/
    project.json
    OP01.lines.ass             <- you edit this
    OP01.kara.jp.ass           <- phase 2 output
    OP01.kara.romaji.ass
    lyrics.txt                 <- fetched lyrics, editable
    readings.tsv               <- reading overrides, editable
    selections.json
    audio/
    cache/emissions/
```

`-o/--output-dir` names the directory, not an ASS filename. The directory name
without a trailing `.aksal` is used for every ASS artifact.

Lyric sheets are normalised before analysis: half-width katakana, full-width
latin, combining marks and old kanji forms are all folded first. Those failed
**silently** -- 孃 has no reading at all in the analyser's dictionary, so the
aligner was handed a character it could not pronounce and nothing in the output
looked wrong. Your romaji is untouched by this: the romaji track is built from
the raw line, not the normalised one.

Set phrases are kept whole. The analyser emits *short unit words* -- it
segments grammar, so `共に` comes back as two words and `どうにか` as three -- but
every dictionary lists those as single entries, so a short list rejoins them:
`tomoni`, `dounika`, `sonnani`, `dareka`, `itsumo`, `dakara`, `dakedo`. Word
boundaries move; the syllables and the `\k` values do not.

That list is a convention rather than a fact, so it is editable. Put
`aksal.phrases.tsv` in AKSAL's per-user data directory, two tab-separated
columns -- the phrase, and a reading only when concatenating the parts would be
wrong. `DELETE` in the second column removes a built-in entry:

```
本当に
誰か	DELETE
```

Ambiguous Japanese readings are scored as complete sentence hypotheses against
the line audio. Likely choices feed final mora timing; uncertain alternatives
remain flagged. Phase 2 repeats this against the corrected line window and
caches the decision in `selections.json`. Manual table edits always win.

**`readings.tsv` is worth opening.** Fix any row that is flagged, and any
reading the singer does not use — analysers do not know that 永遠 is often sung
とわ. **Spaces in the reading column mark word breaks**, and they set where the
romaji karaoke puts its spaces.

## The acoustic model

Downloaded once on first use (~630 MB) and cached, the way faster-whisper does
it. Nothing is bundled with the tool, so the download happens on the first run
and never again.

It is fine-tuned from a Japanese-only encoder pretrained on 35,000 hours.
Against hand-timed karaoke it places most syllables within 0.06s, and 73-86% of
them inside 100 ms.

You can point `--model` at anything else that emits kana. The pipeline needs
only three things -- a kana vocabulary, a CTC blank, and 20 ms frames -- and all
three are checked, because each fails **silently** otherwise. A general Japanese
ASR model that writes kanji will align to the wrong sounds while producing
output that looks completely ordinary, so those are refused outright.

## What to expect

Line timings come out good. **Syllable boundaries are a solid first pass, not a
finished one** — sustained vowels and melisma are where alignment smears. Budget
time in Aegisub's karaoke mode over the waveform, starting with whatever phase 1
flagged.
