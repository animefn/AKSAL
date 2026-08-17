# Audio selection of ambiguous readings

ASKAL selects readings at the complete-line level. The earlier word-crop
arbiter was removed after it failed on real competing readings: each candidate
could cherry-pick favourable emitting frames inside a short crop, and its
confidence thresholds did not transfer from synthetic decoys to real words.

## Pipeline position

1. The configured analyser supplies a provisional reading.
2. `readings.candidate_readings` aggregates alternatives from the Ichiran
   index and the independent pykakasi nominator.
3. The timing model obtains rough line intervals.
4. Every complete-sentence combination is scored against its line audio by the
   selection model using total CTC loss.
5. Complete-sentence probabilities are marginalised back to each ambiguous
   word. A likely result changes the reading; an uncertain result keeps the
   provisional reading and is flagged.
6. The selected reading is persisted in the readings TSV and becomes the input
   to final mora alignment.

Manual readings already present in the TSV are never sent to audio selection.
They are user decisions and have highest priority.

Reading selection hears 0.75 seconds of additional audio before and after the
line, clamped to the available source. This prevents a provisional reading
from cutting off a mora that exists only in an alternative, such as the initial
い in いまだ. The context changes only the acoustic scoring crop: it never
moves phase-1 lines or timing corrected by the user in Aegisub.

## Models

The public model values are real Hugging Face IDs:

```text
--model MODEL
--timing-model MODEL
--selection-model MODEL
```

`--model` establishes the value for both roles. A role-specific option wins
over it. With no arguments both roles use
`sakasegawa/japanese-wav2vec2-large-hiragana-ctc`, the existing default.

When the two roles resolve to the same ID, ASKAL reuses the loaded checkpoint
and crops the existing timing emissions to each rough line interval. When they
differ, timing emissions are completed and cached before the timing checkpoint
is released and the selection checkpoint is loaded.

## Scoring contract

`reading_selector.py` intentionally matches the standalone
`reading_candidates.py` experiment:

- candidate combinations are exact, with a safety limit of 256;
- every target is the complete kana sentence, not an isolated word;
- the score is negative summed CTC loss over the fixed line interval;
- softmax is computed across complete readings;
- word probabilities are marginals of complete-reading probabilities;
- `highly likely` requires probability >= 0.90 and an 0.80 lead;
- `likely` requires probability >= 0.70 and an 0.40 lead;
- an `uncertain` result is reported but cannot silently change timing.

Do not add length normalisation, per-word cropping, emitting-frame selection,
or new thresholds without validating them on real ambiguous readings. Those
changes would no longer be the implementation whose song examples motivated
this replacement.

## Caching

Emission cache names include the timing model ID, audio source tag, selected
window and conditioning state. A cache created by one model must never be
accepted by another model: the tensor shape may look valid while every score
and timestamp is wrong.
