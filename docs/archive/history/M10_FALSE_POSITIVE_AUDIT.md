# M10 — False-positive routing audit

Date: 2026-08-25

Status: `PACKAGED TESTS PASS / USER VERIFICATION PENDING`

## Scope

This pass audits deterministic routing that can bypass normal ARCHI reasoning or
start a tool path: media controls and search, current-information search,
document resolution, artifact follow-ups, desktop observation/guide/control,
capability metadata, product help, and natural-language action repair.

## Safety rules enforced

- A conversational noun (`trabajo`, `actividad`, `PDF`, `canción`) is not an action.
- Ambiguous verbs require their domain context (`ponme un ejemplo` is not music).
- Short media controls remain exact; longer controls require a direct command and media context.
- References such as `esa persona` do not inherit a selected document.
- `actualmente` alone does not request live information.
- ARCHEON help requires an explicit product anchor.
- Negated and indirectly negated actions are not routed as executable actions.
- Contrast resets negation scope (`no X, pero haz Y`).
- Desktop observation, guide, and control require an explicit, unnegated request.
- Artifact follow-ups require an action-shaped request, not merely `ahora` or a format name in a discussion.

## Regression corpus

The dedicated corpus is in `tests/test_false_positive_routing_m10.py`. It covers
the reported job/study advice failure plus negative routing examples for media,
documents, artifacts, current information, product help, and desktop actions.

Final automated result:

```text
271 passed, 108 subtests passed
```

The single warning is the expected Python `zipfile` warning produced by the
archive-security test that intentionally creates a duplicate ZIP entry.

## Remaining verification boundary

These tests prove the known deterministic routing invariants and regression
suite. They do not claim that arbitrary future natural-language input can never
be ambiguous. New reported phrases must be added to the negative corpus, and
commands produced by noisy real STT still require USER VERIFICATION on the
target device.
