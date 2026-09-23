# Final architecture

```text
ARCHEON
├── Core / ARCHI             src/archeon/app.py, core, intelligence, understanding, agent
├── Voice                    audio, voice
├── Media                    media
├── Computer Use / Vision    desktop, vision
├── Browser / Files          browser, launcher, context
├── Documents / Artifacts    documents, artifacts
├── Image / Programming      artifacts/image_generation.py, programming
├── Extensions               plugins
├── Auth / Sync / Cloud      auth, sync, cloud
├── Updates                  updates
├── UI                       ui
└── Shared Infrastructure    system, database, learning, search
```

Composition root: `ArcheonApplication`. Executable entry point: `src/archeon/__main__.py`. Package input: canonical source plus declared assets only. Archived code and historical milestone evidence are excluded from packaging.
