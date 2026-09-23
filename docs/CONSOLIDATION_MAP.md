# ARCHEON consolidation map

Checkpoint: `pre-consolidation-20260915` (`c82f41ef`). Recovery archive and dependency/storage snapshots are under `.recovery/pre-consolidation-20260915/`.

| Legacy owner | Classification | Canonical owner | Parity decision |
|---|---|---|---|
| `Archeo32n.py` | ARCHIVE | `src/archeon/__main__.py`, `app.py`, `ui/` | Startup, UI, auth, voice and lifecycle are split into tested owners. The monolith is not imported. |
| `archeon_music.py` | ARCHIVE | `src/archeon/media/` | Play/pause/resume/stop, queue, metadata, provider resolution, device selection and cleanup migrated. Unsafe TLS bypass, global state and polling were not copied. |
| `archeon_cloud.py` | ARCHIVE | `auth/`, `sync/`, `cloud/`, `context/`, `learning/` | Identity, sessions, settings and offline sync migrated. Firebase and the old social/chat store are deprecated, not runtime dependencies. |
| `archeon_updater.py` | ARCHIVE | `src/archeon/updates/` | Replaced by a fail-closed manager requiring verified hash and signature. The unsigned downloader was intentionally rejected. |
| `archeon_system.py` | ARCHIVE | `desktop/`, `launcher/`, `system/`, `core/tools.py` | Safe window, launcher, clipboard, observation and system status behavior migrated. Destructive cleanup/organize actions remain intentionally absent. |
| `archeon_vision.py` | ARCHIVE | `src/archeon/vision/`, `desktop/` | On-demand capture/observation migrated with evidence and cancellation. |
| `archeon_context_memory.py` | ARCHIVE | `context/`, `agent/context_store.py` | Bounded task context and persistence migrated. |
| `archeon_dialog_manager.py` | ARCHIVE | `core/orchestrator.py`, `agent/runner.py` | Routing, task lifecycle and cancellation migrated. |
| `archeon_knowledge.py` | ARCHIVE | `core/knowledge.py`, `intelligence/` | Knowledge routing migrated; mutable root-relative database was not retained. |
| `archeon_reasoner.py`, `archeon_neuro.py`, `archeon_openrouter.py` | ARCHIVE | `intelligence/`, `understanding/`, `search/` | Provider-neutral routing and false-positive guards replace direct legacy coupling. Root `.env` API-key loading is removed. |
| `sistema_predicciones.py` | ARCHIVE | `learning/`, `context/` | Bounded local learning replaces background root-file mutation. |

Canonical source contains one owner per responsibility. Historical milestone reports and benchmarks are evidence only and do not participate in imports or packaging.
