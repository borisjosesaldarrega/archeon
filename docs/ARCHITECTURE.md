# ARCHEON architecture

The only application runtime source is `src/archeon/`.

- Core and ARCHI: `app.py`, `core/`, `intelligence/`, `understanding/`, `agent/`.
- Voice: `audio/`, `voice/`.
- Media: `media/`.
- Computer Use and Browser: `desktop/`, `vision/`, `browser/`, `launcher/`.
- Files, documents, artifacts, image and programming: `context/`, `documents/`, `artifacts/`, `programming/`.
- Extensions, auth, sync and updates: `plugins/`, `auth/`, `sync/`, `cloud/`, `updates/`.
- UI and shared infrastructure: `ui/`, `system/`, `database/`, `learning/`, `search/`.

`ArcheonApplication` is the composition root. Components expose bounded contracts and lifecycle hooks. Root legacy modules are archived evidence, never imported. Local UI traffic requires a per-run token and application sessions; external services remain unconfigured unless explicit runtime configuration exists.
