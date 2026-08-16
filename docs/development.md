# Development notes

## Ichiran startup

Do not add an Ichiran daemon, eager preload, database replacement, or alternate
dictionary solely to remove its cold-start delay. The packaged JMdict index is
loaded once per ASKAL process, so a complete karaoke run pays that cost once,
not once per sentence. Revisit this only if end-to-end profiling shows it is a
material part of real project runtime; otherwise the packaging and lifecycle
complexity would buy little practical improvement.

## Reading scorer

The reading selector intentionally uses the complete-sentence CTC likelihood
mechanism proven in `reading_candidates.py`. Do not recalibrate or replace it
without corpus evidence. Integration work belongs around it: candidate
nomination, exact audio windows, persistence/invalidation, and explicit model
roles.
