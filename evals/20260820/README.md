# 2026-08-20 evaluation boundary

The checked-in files under this date contain reusable scripted corpora and
evaluation tooling. Human-session evidence is intentionally **not** part of the
repository payload.

The following local directories are gitignored pending explicit consent review
and redaction:

- `owner_session_1/`
- `shadow_assertions_run_1/`
- `voice_corpus_v1/live_run_1/`
- `voice_corpus_v1/replay_run_1/`

Those folders include household transcripts, provider/session identifiers,
timestamps, machine-specific paths, and runtime snapshots. Raw WAV/FLAC/MP3/
Opus files recorded beside `voice_corpus_v1/queries.tsv` are ignored as well.
The dated scrum status records retain the engineering conclusions and explicit
limitations without treating private raw evidence as a release artifact.

This boundary does not claim the omitted evidence has been anonymized,
reproduced by CI, or approved for redistribution.
