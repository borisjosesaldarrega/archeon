# Consolidation report

The active runtime is exclusively `src/archeon/`. Milestone-named artifact modules, active test modules, fixture names and packaged diagnostic flags were renamed to capability names. Thirteen root legacy Python implementations and the sanitized recovery copy were moved to `docs/archive/legacy-source/` after import and behavior comparison. Historical reports, screenshots and audits were moved to `docs/archive/history/`.

One canonical owner now exists for Core/ARCHI, Voice, Media, Computer Use, Browser, Files/Documents, Artifacts/Image, Programming, Extensions, Auth, Sync, Updates, UI and shared infrastructure. No runtime or package import points to the archived modules.

Cleanup removed 186 old build/dist/runtime/temp candidates, the broken duplicate `.venv`, legacy FFmpeg bundle, old web/installer output, PyArmor runtime and root PortAudio binary. One read-only temporary Git object required clearing its read-only bit before removal. Preserved: `.venv-archeon`, `models`, `backups`, `output`, tests, fixtures, migrations, benchmarks, user/local databases and prediction/config data.

Credentials were not deleted because external revocation/rotation could not be proven. `.env`, `.env.local`, `firebase_key.json` and its copy remain ignored and outside the package. Google/OpenRouter keys and Firebase service-account credentials must be rotated/revoked first; the Supabase publishable value is configuration rather than a private secret.

Checkpoint: tag `pre-consolidation-20260915`; verified minimum backup `.recovery/pre-consolidation-20260915/workspace-minimum.zip`; SHA-256 `48641E45A607570528F3348B12A09F2C14DF33C8444379C14A0C480B6505547E`.
