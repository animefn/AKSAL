# Third-party components

AKSAL is glue. Almost all of the hard work belongs to other people, and this
file records whose.

## The acoustic model

**hiragana-asr** — the dual-CTC wav2vec2 model AKSAL aligns with, and the kana
vocabulary that goes with it.

- Author: Sakasegawa
- Source: <https://github.com/nyosegawa/hiragana-asr>
- Weights: <https://huggingface.co/sakasegawa/japanese-wav2vec2-large-hiragana-ctc>
- Licence: Apache-2.0 (weights unrestricted; training data ReazonSpeech,
  CDLA-Sharing-1.0)

The vocabulary in `src/aksal/dualctc.py` is reproduced verbatim from that
project's `src/asr/kana_vocab.py`, because token order is part of the checkpoint
contract. The model is fine-tuned from
[reazon-research/japanese-wav2vec2-large](https://huggingface.co/reazon-research/japanese-wav2vec2-large),
whose config and feature extractor AKSAL also loads.

Downloaded on first run. Not bundled.

## Japanese language analysis

| | what it does here | licence |
|---|---|---|
| [fugashi](https://github.com/polm/fugashi) | MeCab bindings — the tokeniser everything else builds on | MIT |
| [unidic-lite](https://github.com/polm/unidic-lite) | the dictionary that supplies readings and parts of speech | BSD / UniDic terms |
| [ipadic](https://github.com/polm/ipadic-py) | a second opinion on compound nouns, where unidic splits set phrases and gets their reading wrong | see package |
| [jaconv](https://github.com/ikegami-yukino/jaconv) | kana conversion | MIT |

**cutlet**, by the same author as fugashi, is not a dependency but shaped the
work: reading its spacing rules found a missing prefix rule in ours. Where the
two disagree it is deliberate — cutlet targets readable prose romaji, AKSAL
targets where a karaoke timer breaks the highlight.

## Alignment and audio

| | | licence |
|---|---|---|
| [PyTorch](https://pytorch.org/) / torchaudio | the model runs here, and `torchaudio.functional.forced_align` **is** the alignment | BSD-3-Clause |
| [transformers](https://github.com/huggingface/transformers) | wav2vec2 implementation and model loading | Apache-2.0 |
| [huggingface_hub](https://github.com/huggingface/huggingface_hub) | fetches the model on first run | Apache-2.0 |
| [NumPy](https://numpy.org/) / [SciPy](https://scipy.org/) | fingerprinting and signal handling | BSD-3-Clause |
| [soundfile](https://github.com/bastibe/python-soundfile) | audio I/O | BSD-3-Clause |

## External programs

Not bundled. AKSAL finds them on PATH, or offers to download the first two.

| | | licence |
|---|---|---|
| [ffmpeg](https://ffmpeg.org/) | all audio decoding. Static builds fetched from [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) | LGPL-2.1+ / GPL-2+ depending on build |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | fetches a reference track for `aksal find` | Unlicense |
| [demucs](https://github.com/adefossez/demucs) | optional vocal separation (`--separate-audio`) | MIT |

## Data services

Queried at runtime; none is bundled or redistributed.

| | used for |
|---|---|
| [AnimeThemes](https://animethemes.moe/) | anime title → theme song |
| [Anime News Network](https://www.animenewsnetwork.com/encyclopedia/) | the same, as a second source |
| [MyAnimeList](https://myanimelist.net/) via [Jikan](https://jikan.moe/) | the same, as a third |
| [Uta-Net](https://www.uta-net.com/) | lyrics, from a URL you supply |
| [LRCLIB](https://lrclib.net/) | synced line timings, when they can be verified |

Lyrics and audio fetched through these belong to their rights holders. AKSAL
caches them beside your output for your own use; it does not redistribute them,
and neither the repository nor the released build contains any.

## Packaging

[PyInstaller](https://pyinstaller.org/) (GPL-2.0 with a bootloader exception
permitting distribution of frozen applications under any licence).
