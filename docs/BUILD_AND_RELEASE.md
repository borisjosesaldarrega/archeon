# Build and release

Development uses `.venv-archeon` and `pyproject.toml`. The canonical entry point is `python -m archeon`; `build_archeo.spec` packages only `src/archeon/` plus declared UI/media assets.

Release gate: full tests, JavaScript/JSON validation, headless startup/shutdown, normal UI and Ghost smoke, artifact package smoke, credential-name and content scan, legacy-import scan, absolute-path scan and residual-process check. Build output must be created fresh. Updates stay `NOT CONFIGURED` until a signed backend exists.
