# Publish review — 2026-08-21 checkpoint

This checkpoint intentionally lands the completed R20–R27, EV-1/F1-SI, and
PG-1–PG-3 wave plus its synthetic fixtures, generated evaluation evidence, and
audits. The five W-1/C-1/C-2/C-3/E-2 files are planning-only roadmap records and
are committed separately from the implemented wave.

## Privacy and provenance decision

The reviewed publish set contains no API credential, private key, JWT, raw owner
audio, household transcript, owner voice profile, speaker embedding, or live
conversation database. Those remain excluded by `.gitignore` and by the
enrollment tool's repo-path refusal. `owner_voice_profile.json` is now ignored
explicitly as defense in depth.

Machine-generated nav/nightly evidence and historical status records retain the
host-local repository path, scratch identifier, and hostname captured at run
time. This is an intentional evidence-provenance choice for this source-control
checkpoint, not a claim that those paths are portable or public API. They carry
no credential or conversation content; rewriting immutable run evidence after
measurement would be less honest than recording the boundary here.

## Known red, intentionally retained

The commit tier is green. The first recorded hard nightly remains RED on the
flagship lamppost semantic-arrival test (and recorded environment limitations).
That failure is not waived or relabeled: backlog N45 owns arrival reliability,
and N46 owns the subsequent current-stack baseline/follow-bench re-freeze.
