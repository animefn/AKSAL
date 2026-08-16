# Reading arbitration: letting the audio choose between candidate readings

How AKSAL decides that 心 is **kokoro** and not **shin**, why the obvious way of
asking that question does not work, and what was measured before choosing the
way that does.

Written 2026-08-16. Read this before changing `align.disputed_readings`,
`readings.candidate_readings`, or the scoring in `align.reading_score`.

---

## 1. The problem

A kanji spelling does not determine its reading. Four cases from real lyrics,
all of which the tool must handle without asking the user anything:

| written | candidates | note |
|---|---|---|
| 心 | こころ / しん | both ordinary nouns |
| 未だ | まだ / いまだ | same word, two accepted readings |
| 方 | ほう / かた | different words, same spelling |
| 永遠 | えいえん / **とわ** | *gikun* — a reading the kanji do not carry, common in song |

For a karaoke tool this is not cosmetic. The reading becomes the mora sequence,
the mora sequence becomes the karaoke cells, and a wrong reading means the
aligner hunts for sounds nobody sang. こころ and しん differ in mora count, so
the **timing of the whole line** changes with the choice.

Nothing in the text settles these. The singer settles them, which is why the
audio has to be the arbiter.

---

## 2. Why this regressed when the analyser moved to ichiran

The arbitration mechanism was written for the UniDic era and **was never fed by
ichiran**. It nominates candidates from `pykakasi`, an independent dictionary,
and then scores them against audio. Moving the analyser did not touch the
arbitrator, but it changed everything the arbitrator sees.

Two gates in the old `rival_reading` rejected exactly the cases above:

**Gate 1 — equal mora count.** It refused to arbitrate candidates of different
length. That silently discards まだ/いまだ (2 vs 3), こころ/しん (3 vs 2) and
えいえん/とわ (4 vs 2). Three of the four cases die here. §4 explains why the
gate existed; it was not arbitrary.

**Gate 2 — the rival must see the word as one segment.** ichiran produces
*coarser* units than UniDic: `その方が良い` is now `その` + `方が良い`, one
dictionary match. `pykakasi` splits that into three pieces, the gate bails, and
**no nomination happens at all**. Under UniDic, 方 was its own short unit, one
segment, equal moras — so the ほう/かた dispute used to fire. Coarser units
switched the arbitrator off without any error.

**And the gikun never worked at all.** とわ *is* in the JMdict index as a
reading of 永遠, but it scores 65 against えいえん's 156, so `cull_segments`
(keep within ½ of best) drops it before anything can nominate it. `pykakasi`
does not know it either.

### The structural mistake

We ship a dictionary that holds every rival — いまだ, しん, かた, とわ, each
with a score — and then throw them away at `segment(chunk, limit=1)` →
`parses[0]`, and ask a weaker outside dictionary what the alternatives might be.

The beam genuinely carries them. Measured:

```
この心に   86  この | 心:こころ | に
この心に   86  この | 心:しん   | に      <- rank 2, identical score
未だ探し  240  未だ:まだ  | 探し
未だ探し  200  未だ:いまだ | 探し          <- rank 2
```

`心` scores **16 for こころ and 16 for しん** — an exact tie broken by index
order. A correct-looking output here is luck, not judgement, and any index
rebuild can flip it.

**Fix:** ichiran is the candidate source. `pykakasi` stays as an *extra*
nominator (independent lineage is its value) but is no longer the only one, and
culling for *nomination* uses a far looser threshold than culling for *parse
selection* — that is what suppressed とわ.

---

## 3. The mechanism

Unchanged in shape from the original design, and it is the right shape:

1. The analyser proposes candidate readings for a word.
2. Each candidate is scored **over that word's own audio span**.
3. The best-scoring candidate wins, if it wins by enough.
4. Anything below the margin is **flagged, never silently rewritten**.

Two properties are load-bearing and must not be lost:

- **Scoring is per word span, never over the whole track.** Measured earlier:
  scoring against the full song lets a candidate find a better-matching place
  somewhere else, and the true reading lost **34 times out of 34**.
- **It never blocks and never prompts.** Undecided cases become flags in the
  readings TSV and comment lines in the ASS. A choice is always made.

---

## 4. The length bias — the part that took measurement

### The inherited claim

> "Comparing candidates of DIFFERENT length does not work at all — CTC prefers
> the shorter sequence whatever was sung. Equal-length pairs scored 88%;
> unequal ones were a coin flip or worse."

This was true **for the metric it was measured with**, and that metric is the
problem, not the model.

### The old metric and why it fails

`_mean_conf` averages per-mora confidence over the word's crop. Audio the
candidate does not explain is **free**: a 2-mora candidate sitting in a 3-mora
span only needs to find two good frames, and the leftover sound costs it
nothing. This is structurally the same flaw as a segmenter with no gap penalty.

### The experiment

**Ground truth for free:** a word written *in kana* in the lyric sheet spells
its own reading. No corpus, no labelling, no human judgement — the truth is the
text. So: take those words, crop each one's own span, and ask each metric to
choose between the truth and a deliberately wrong decoy.

Four decoy kinds, because they test different things:

| decoy | what it tests |
|---|---|
| shorter by 1 / 2 (truncation) | pure length — decoy is a *prefix*, shares every sound |
| longer by 1 / 2 (mora repeated) | pure length, other direction |
| **different sounds, shorter/longer** | **the real case** — しん is not a prefix of こころ |

Both directions matter: a metric that beats short decoys may simply have
**inverted** the bias rather than removed it.

Harness: `scratchpad/length_bias.py`, 8 songs with cached emissions, 1,387
comparisons. **No model weights are loaded** — cached emissions *are* the
model's output, so the real `Aligner` methods are driven with the vocabulary
alone.

### Result: the raw score is a ruler, not an ear

Total CTC log-probability over the crop (`logprob`), picking the truth:

| decoy | picks truth |
|---|---|
| shorter by 1 | **12%** |
| shorter by 2 | **5%** |
| longer by 1 | 99% |
| longer by 2 | 100% |

It takes the shorter string ~90–95% of the time regardless of what was sung.
The near-perfect scores on longer decoys are not skill — the truth simply
happens to be the shorter option there. **Normalisation is genuinely required.**

### Result: on real-shaped disputes the model hears fine

Restricted to decoys that differ in *sound* as well as length — the shape of an
actual dispute:

| decoy | mean-conf (old) | raw logprob | /L |
|---|---|---|---|
| diff sounds, shorter | 71% | 25% | **86%** |
| diff sounds, longer | 80% | 100% | **79%** |
| shorter by 1 (prefix) | 43% | 12% | 78% |
| longer by 1 (repeat) | 89% | 99% | 54% |

The catastrophic 43% for the old metric is on *prefix* decoys, which are
pathological — a prefix is acoustically contained in the truth. On real-shaped
pairs the model discriminates, which is what makes this whole approach viable.

> The "longer by 1" column is unfairly harsh on every metric: repeating a mora
> in Japanese produces a long vowel, which sounds nearly identical to the
> original. It punishes metrics for not hearing a difference that barely exists.

---

## 5. Choosing the metric

Judged on the number the design actually uses: **accuracy over the most
confident quarter**, since the conservative gate only decides those.
577 real-shaped comparisons, `scratchpad/norm_sweep.py`:

| metric | overall | top-50% | **top-25%** |
|---|---|---|---|
| **emit-mean** | 78% | 89% | **93%** |
| +8L (length reward) | 79% | 89% | 90% |
| +4L | 72% | 88% | 88% |
| /L^0.5 | 71% | 84% | 86% |
| /L^0.7 | 78% | 85% | 85% |
| /L^1.0 | 80% | 88% | 84% |
| ctc/L (full marginal) | 78% | 87% | 84% |
| /L^1.5 | 69% | 84% | 83% |

> **⚠ SUPERSEDED BY §7a. `emit-mean` was chosen on this evidence and then
> FAILED on real rivals.** The sweep below is left in place because the
> reasoning is sound and the failure is instructive, but do not act on it
> without reading §7a first.

**`emit-mean` was chosen here.** Mean log-probability over only the frames that
actually *emit* a token, blanks excluded.

Why it is the right choice beyond the 9-point margin:

- **It removes the cause instead of rescaling the symptom.** Blank padding is
  where the length bias comes from, so it stops counting the biased part and
  asks the model only about the sounds the candidate claims were sung.
- **It has no tuned constant.** `+8L` is close behind but 8 is arbitrary — it
  fits these songs and may not fit others. An exponent or a reward is a knob
  that will silently rot; this is not.

Two findings worth recording so they are not re-derived:

- **The full CTC marginal was no better** (84%). Summing over every alignment
  rather than the best path is more principled and bought nothing here, so the
  extra cost is not worth paying.
- **The literature constant α≈0.7 underperformed** plain `/L` on real-shaped
  cases (85% vs 84% on the gate, but 68% vs 86% on the sound-differing shorter
  decoys in the earlier run). Do not adopt it because a paper recommends it;
  it is tuned for open-vocabulary decoding, not two fixed candidates over one
  fixed crop.

### Why confidence gating is what makes 78% usable

Accuracy rises monotonically with the margin between candidates, which means
the metric knows when it is unsure:

| slice by margin | accuracy |
|---|---|
| top 10% | 98% |
| top 25% | 98% |
| top 50% | 93% |
| everything | 82% |

(`/L`, earlier harness — see the caveat in §7.) The headline number is an
average over cases including near-ties, and near-ties are exactly the ones that
must not be decided. Decide the clear ones; flag the rest.

---

## 6. Why this is not the textbook length-normalisation problem

Worth stating because the literature will mislead you here.

The standard problem is **decoding**: beam search compares hypotheses of
different lengths where each extra token adds another negative log-probability,
so longer hypotheses lose. The standard fixes are dividing by `length^α`
(α≈0.6–0.7) or adding a per-token reward β.

We are not decoding. We have **two fixed candidates and one fixed audio crop**,
and in CTC *both paths span the same frames*. The shorter candidate must fill
the remainder with **blank**. So the real question is not "does it penalise
long strings" but **"how cheap is blank in a voiced region?"** — and the answer,
measured, is *very cheap*, which is why the raw score is a ruler.

That difference is why `emit-mean` (ignore the blanks) beats the textbook
rescalings (compensate for the blanks) on this problem.

---

## 7a. What actually happened: emit-mean failed on real rivals

**Read this before doing anything with §5.** `emit-mean` scored 93% on the
confident quarter against synthetic decoys, was implemented, and was then run
against real candidates on real songs. Result, at the conservative gate
(`MARGIN_DECIDE = 3.0`): **one override in 286 contested words, and it was
wrong** (割って わって → さって).

Lowering the gate to 1.0 proposed 32 overrides. Essentially all of them were
wrong, and wrong in the same direction — a correct *kun'yomi* replaced by a
rarer *on'yomi*:

```
君  きみ    -> くん        胸  むね   -> むな  (x4)
今  いま    -> こん        涙  なみだ -> なだ
声  こえ    -> しょう      時  とき   -> じ
罪  つみ    -> ざい        日  ひ     -> にち
埃  ほこり  -> あい        囀って さえずって -> てんって
```

The last two are not even words in context. This is not a threshold problem.

### Why the synthetic measurement did not transfer

`emit-mean` averages over **only the frames the alignment chose to emit on**.
So a candidate is scored on *its own best-matching frames* and pays nothing for
the audio it does not account for — which is the **same free-lunch flaw as the
old `mean-conf`**, wearing a different hat.

It scored well against the decoys because those were consonant-shifted
nonsense: no plausible frames existed anywhere, so nothing could cherry-pick.
Real rivals are real kana sequences that *can* find plausible frames in a
short span. Hence 93% on synthetic and systematic failure on real.

**The lesson, stated plainly so it is not repeated:** a decoy that cannot
possibly match is not a test of discrimination. Any future metric must be
validated against *real competing readings* before it is believed, and §7's
caveat that "the ranking should hold" was itself wrong — the ranking did not
hold either.

### What ships instead

- **Nomination and flagging: ON.** This half genuinely works and is the larger
  half of the original bug. 永遠/とわ, 未だ/いまだ, 心/しん and 方/かた now
  reach the user as visible alternatives, where before the gikun was culled
  and the ほう/かた dispute was never raised at all.
- **Overriding: OFF**, behind `--audio-readings`. The dictionary's reading
  stands, every alternative is listed in the readings table and as an ASS
  comment, and the user settles it.

The mechanism is sound and the plumbing is in place; **the metric is the
unsolved part.** A better one drops into `Aligner.reading_score` alone.

### Ideas not yet tried

- Score the FULL crop for both candidates (all frames, blanks included) but
  normalise by the crop length rather than the token count — punishes
  cherry-picking without a pure length bias.
- Use the free decode as an independent witness: it is length-agnostic, and
  edit distance to what the model actually emitted cannot be gamed by picking
  favourable frames.
- Require agreement between two dissimilar metrics before overriding.
- Restrict overrides to cases where the candidates differ in mora COUNT, where
  the timing consequence is large enough to be worth the risk.

---

## 7. Caveats — read before trusting any number here

- **The decoys are synthetic.** Consonant-shifted nonsense of the right length,
  not real rival words. こころ/しん may behave differently from こころ/のとの.
  The *ranking* of metrics should hold; the *absolute* accuracies may not.
- **Two harnesses disagreed on absolute values.** `length_bias.py` reported
  `/L` at 98% for the top quarter; `norm_sweep.py` gives the same metric 84% on
  the same songs. Subsets differ (508 vs 577 comparisons) but not enough to
  explain it. The metric *ranking* is apples-to-apples inside `norm_sweep.py`,
  but **no absolute threshold from either run should be treated as final** —
  the margin cutoff must be calibrated on real candidates. Unresolved.
- **8 songs, one domain.** Anime OP/ED, a narrow range of vocal styles and
  mixes. Separated vocals (demucs) and raw mixes both appear, but not, say, a
  dense rock mix or spoken-word.
- **Ground truth is kana-written words**, which may not be representative of
  the kanji words the arbiter actually runs on.

---

## 8. Reproducing the measurements

```
python scratchpad/length_bias.py          # bias by decoy kind + margin curve
python scratchpad/norm_sweep.py           # metric comparison on the gate
```

Both take the project root as `sys.argv[2]` (default hardcoded). Both need
`tests/*.emissions*.pt` and the matching lyrics; neither loads model weights,
so both run in about 80 seconds.

> A trap worth remembering: the first version of `length_bias.py` located the
> project root by walking up until a directory was named `s3`. The scratchpad
> lives under a folder *ending* in `-s3` that never *equals* `s3`, so the walk
> ran past the filesystem root — where `.parent` is the root itself — and spun
> forever, burning 50 CPU-minutes at a 14 MB footprint, printing nothing.
> The tiny footprint was the clue: torch had never even been imported.

---

## 9. If this needs to change

- **A switch back to `/L`** is one line in `align.reading_score`. It was the
  runner-up and is the obvious fallback if `emit-mean` disappoints on real
  rivals; keeping both selectable is deliberate.
- **The threshold is the tuning surface, not the metric.** If too much is
  flagged, lower it; if wrong readings slip through, raise it. Both are visible
  to the user by design, so the failure mode is noisy rather than silent.
- **If a better acoustic model arrives**, re-run §8 before assuming any of this
  transfers. Every number here is a property of *this* checkpoint's blank
  behaviour.

---

## Sources

Technique background (length normalisation in sequence scoring):

- Beam search decoding and length normalisation —
  <https://www.arunbaby.com/ml-system-design/0023-beam-search-decoding/>
- Streaming ASR with the Transformer model (length-normalised scoring in
  practice) — <https://arxiv.org/pdf/2001.02674>
- CTC forced alignment API, torchaudio (the `forced_align` primitive used for
  both alignment and scoring) —
  <https://docs.pytorch.org/audio/stable/tutorials/ctc_forced_alignment_api_tutorial.html>
- CTC-Segmentation of large corpora (confidence scoring from CTC alignment) —
  <https://arxiv.org/pdf/2007.09127>

Acoustic model: `sakasegawa/japanese-wav2vec2-large-hiragana-ctc`, see
[THIRD-PARTY.md](../THIRD-PARTY.md).

Candidate source: JMdict via the ichiran port, see
[src/aksal/ichiran/](../src/aksal/ichiran/).
