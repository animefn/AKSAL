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

With romaji input, **your spacing is authoritative**: no morphological analyser
runs at all, which removes the single largest error source. The kana track is
named `.kara.kana.ass` rather than `.jp.ass`, because reconstructed kana is not
the original orthography.

If you also have the official single, time against it instead of the broadcast:

```bash
aksal phase2 mylines.ass --video EP01.mkv --reference "full song.flac"
```

---

## 2. You only know the anime — `find`

```bash
aksal find --anime "Cross Fight B-Daman eS" --video EP16.mkv --op
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

Needs `yt-dlp` on PATH (`pip install -U yt-dlp`). It is optional, and never
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
    -o          D:/karaoke/OP01.lines.ass

# fix the lines in Aegisub, then
aksal phase2 D:/karaoke/OP01.lines.ass
```

`--lyrics` also takes a Uta-Net song URL or an LRCLIB search term directly:

```bash
aksal phase1 --video EP01.mkv --reference song.flac \
    --lyrics "https://www.uta-net.com/song/361192/" -o OP01.lines.ass
```

**Endings**: restrict the fingerprint search, or it scans the wrong part of the
episode.

```bash
aksal phase1 --video EP01.mkv --lyrics ed.txt --reference "ed single.flac" \
    --search 18:00-24:00 -o ED01.lines.ass
```

**Two episodes in one file**: same thing, a wider window.

```bash
aksal phase1 --video "EP03-04.mkv" --lyrics op.txt --reference op.flac \
    --search 0:00-12:00 -o OP.lines.ass
```

---

## 4. Lyrics of your cut + a start time — `phase1` mode B

No official track needed. The lyrics file must hold **only the lines your
version sings**, in order.

```bash
aksal phase1 --video EP01.mkv --lyrics tv-size.txt \
    --song-start 0:36 --duration 90 -o OP01.lines.ass
```

Typing the text is the whole cost, and it buys the most accurate line placement
phase 1 can produce — because every line you gave it is genuinely sung. For an
ending it is the same flag, later:

```bash
aksal phase1 --video EP01.mkv --lyrics ed-tv.txt \
    --song-start 21:30 --duration 90 -o ED01.lines.ass
```

**Refused:** a full lyric sheet with no reference. Forced alignment cannot say
"this line is not sung", so it would spread the surplus across the instrumental
passages and return a confident, wrong answer. Give it `--reference`, or cut the
lyrics down.

---

## Options worth knowing

| flag | why |
|---|---|
| `--insert-romaji` | prefixes each phase-1 line with its romaji, invisible when rendered. For timers who cannot read Japanese. |
| `--group word` | one karaoke cell per word instead of per syllable. Timing is identical. |
| `--no-preprocess` | skip vocal separation. **~4x faster and about as accurate** — measured over eight songs it is a wash: separation is marginally better on average and worse in the tail. |
| `--skip-cost N` | how freely the aligner may treat audio between lines as unsung. `none` disables it. |
| `--no-lrc-hints` | ignore LRCLIB synced timings even when verified. |
| `--lead-in SEC` | shift every cue earlier. |
| `--tracks jp` | write only one karaoke track. |

## Files

Everything is a visible sibling of `-o`, sharing its stem — no project
directory, nothing hidden:

```
OP01.lines.ass        <- you edit this
OP01.lyrics.txt       <- fetched lyrics, editable
OP01.readings.tsv     <- reading overrides, editable
OP01.kara.jp.ass      <- phase 2 output
OP01.kara.romaji.ass
```

**`OP01.readings.tsv` is worth opening.** Fix any row that is flagged, and any
reading the singer does not use — analysers do not know that 永遠 is often sung
とわ. **Spaces in the reading column mark word breaks**, and they set where the
romaji karaoke puts its spaces.

If you previously ran an older version, delete `OP01.readings.tsv` and re-run
phase 1: an unspaced table loads as an override and keeps the old behaviour.

## What to expect

Line timings come out good. **Syllable boundaries are a solid first pass, not a
finished one** — sustained vowels and melisma are where alignment smears. Budget
time in Aegisub's karaoke mode over the waveform, starting with whatever phase 1
flagged.
