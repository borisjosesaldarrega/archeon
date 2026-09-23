# Computer Use

The canonical owners are `src/archeon/desktop/`, `vision/`, `browser/` and `launcher/`. Observation produces bounded evidence before actions. Mouse/cursor actions, overlays, cancellation and cleanup are covered by automated tests. Sensitive or destructive actions remain permission-gated; the legacy empty-trash, arbitrary temp deletion and downloads reorganization functions were not migrated.

Manual release validation should exercise normal UI, Ghost, radial controls, cancel during an active action, DPI scaling, keyboard navigation and shutdown with a process check.
