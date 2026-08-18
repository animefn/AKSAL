# Development notes

These are current design constraints, not a chronological changelog.

## Ichiran startup

Do not add an Ichiran daemon, eager preload, database replacement, or alternate
dictionary solely to remove its cold-start delay. The packaged JMdict index is
loaded once per AKSAL process, so a complete karaoke run pays that cost once,
not once per sentence. Revisit this only if end-to-end profiling shows it is a
material part of real project runtime.

## Reading scorer

The reading selector intentionally uses the complete-sentence, direct-clip CTC
likelihood mechanism documented in
[`reading-arbitration.md`](reading-arbitration.md). It hears 0.75 seconds of
context on each side without changing subtitle timing. Do not replace its
scoring, normalize by candidate length, or recalibrate thresholds without a
real ambiguous-reading evaluation set. Integration work belongs around it:
candidate nomination, bounded audio windows, persistence/invalidation and
explicit timing/selection model roles.

## Projects and model storage

`-o/--output-dir` is a project directory. ASS outputs stay together at its
root; derived audio and emissions live under `audio/` and `cache/`. Manual
`readings.tsv` edits override saved acoustic choices.

Packaged builds download Hugging Face and Demucs/PyTorch weights into the
visible `models/` directory beside the executable. The updater preserves it.
Only read-only installations fall back to a per-user cache. Source installs
retain their libraries' normal cache defaults.

## Novice GUI direction

The CLI remains the complete local/offline interface. The novice interface is
planned as a multilingual centralized web application so users do not need to
install models, FFmpeg or use a terminal. Full videos should not be uploaded.
The browser should select the OP/ED range, extract a small mono audio clip
locally and send the original time offset with it; returned ASS times are mapped
back onto the video timeline.

The first feasibility test is `ffmpeg.wasm` against real multi-gigabyte anime
MKV files, especially clips near the end. Measure seeking, runtime, peak memory,
audio-track selection and failure behavior. LosslessCut is UX inspiration but
uses native FFmpeg inside Electron, so its performance must not be attributed
to WebAssembly. If WASM is unreliable, offer a small optional native AKSAL
Helper containing FFmpeg but no acoustic models. Direct audio upload is the
third path.

The web workflow should ask what the user has rather than expose phase names:
timed lyrics, untimed TV-size lyrics, full-song lyrics plus a reference, or no
lyrics. Models and specialist flags stay in an Advanced drawer. Initial
localization targets are English, Arabic (full RTL), Vietnamese, Simplified and
Traditional Chinese, and Japanese.

A useful GUI must include basic line review—waveform/playback, draggable line
boundaries, low-confidence markers, kana-plus-romaji reading alternatives,
autosave and one final create/download action. It should not attempt to replace
Aegisub's detailed karaoke polishing or effects workflow.

Hosted workers should keep default models warm, expose structured progress and
cancellation, and reserve full Demucs for requested/difficult jobs. Uploaded
audio is untrusted and must be sandboxed, limited, short-lived and deleted on a
clearly stated schedule. Accounts should not be required for an initial trial.

CLI, any future desktop GUI and hosted workers must call one shared Python
workflow/application layer. Do not shell out to the CLI or duplicate phase,
candidate-selection or project-path logic in each interface.

## Current technical roadmap

- Prototype browser audio extraction before selecting a frontend shell or
  hosting architecture.
- Add broader hand-timed ground truth for timing and reading regressions.
- Keep the experimental CTC skip state opt-in; full lyrics without a reference
  still require explicit line selection research.
- Produce a signed/notarized macOS build when a native runner is available.
