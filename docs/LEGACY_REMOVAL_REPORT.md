# Legacy removal report

| Result | Items | Reason / verification |
|---|---|---|
| Migrated/merged | media playback and resolver concepts; auth/session/settings; context/learning; intent routing; desktop/vision; system status | Canonical capability owners and regression suite cover retained behavior. |
| Archived | 13 root Python modules plus sanitized monolith | Preserved for audit under `docs/archive/legacy-source/`; no runtime imports. |
| Intentionally not migrated | unsigned updater; TLS bypass; broad exception swallowing; global media state; arbitrary temp/trash/download cleanup; Firebase-coupled social/chat store | Unsafe, duplicated or outside current product scope. |
| Removed | old build/dist trees, duplicate broken venv, legacy FFmpeg/PortAudio/PyArmor, stale runtime/temp directories, old web installer bundle | Fresh source and packaged smokes passed afterward. |
| Preserved | models, backups, output, user/local databases/config, tests, fixtures, migrations and benchmarks | Explicit preservation rule. |

Post-change full suite: 389 passed, 128 subtests passed, one expected duplicate-ZIP warning. Packaged headless/UI/Ghost/artifact smokes all exited 0; residual processes: 0.
