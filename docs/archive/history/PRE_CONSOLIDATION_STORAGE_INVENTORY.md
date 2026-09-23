# ARCHEON — inventario de almacenamiento previo a Consolidation

Fecha de captura: 2026-08-28. No se eliminó ningún archivo durante este inventario.

## Repositorio y artefactos de desarrollo

| Categoría | Tamaño aproximado | Archivos | Clasificación previa |
|---|---:|---:|---|
| `src` | 3.80 MiB | 351 | KEEP |
| `tests` | 1.29 MiB | 141 | KEEP |
| `docs` | 3.10 MiB | 45 antes de este cierre | KEEP / MERGE |
| `benchmarks` | 0.85 MiB más evidencias PNG | 64 antes de este cierre | KEEP últimas evidencias |
| `tools` | 0.45 MiB | 78 | REVIEW / PARAMETERIZE |
| `assets` | 1.03 MiB | — | KEEP |
| `web` | 254.91 MiB | — | REVIEW; contiene legado visual pesado |
| `models` del repositorio | 57.49 MiB | 14 | MIGRATE/REMOVE tras verificar copia administrada |
| `.venv` | 663.79 MiB | 19,370 | REMOVE CANDIDATE |
| `.venv-archeon` | 165.40 MiB | 9,847 | KEEP una sola venv de desarrollo |
| `build` base | 281.87 MiB | — | REMOVE CANDIDATE |
| `dist` base | 39.63 MiB | — | REMOVE CANDIDATE |
| `backups` | 863.19 MiB | 20,391 | ARCHIVE; no borrar sin política de retención |
| `legacy_sanitized` | 0.09 MiB | — | ARCHIVE |
| `ffmpeg-8.0.1-essentials_build` | 295.98 MiB | — | REMOVE CANDIDATE; no se empaqueta |
| `tmp` | 8.58 MiB | — | REMOVE CANDIDATE |
| builds, dist, runtime y temporales generados | 3,422.15 MiB | 24,144 | REMOVE CANDIDATE tras checkpoint |
| `dist-m10-final/Archeo32n` | 117.30 MiB | 1,263 | KEEP como evidencia M10 |

La raíz conserva implementaciones Python antiguas (`Archeo32n.py`, `archeon_cloud.py`, `archeon_music.py`, `archeon_updater.py`, etc.). Son referencia histórica, no owners del runtime modular bajo `src/archeon`.

## Datos administrados fuera del repositorio

`%LOCALAPPDATA%\ARCHEON` ocupa aproximadamente 5.15 GiB / 204 archivos:

| Categoría | Tamaño aproximado | Observación |
|---|---:|---|
| `models` | 4,882.79 MiB | Qwen3, ARCHI Image, ARCHI Vision y Vosk |
| `runtimes` | 323.18 MiB | stable-diffusion.cpp CPU/Vulkan y Real-ESRGAN |
| `runtime` | 61.05 MiB | llama.cpp y componentes administrados |
| `artifacts` | 8.02 MiB | salidas del usuario/benchmarks |
| `cache` | 0.36 MiB | caché regenerable |
| `memory` | 0.14 MiB | memoria persistente pequeña |

Modelos principales:

- Qwen3-4B Q4_K_M: 2,497,280,256 bytes.
- ARCHI Image Lite SDXS: 882,587,118 bytes.
- ARCHI Image upscale RealESRGAN: 67,061,725 bytes.
- ARCHI Vision language model: 1,107,409,952 bytes.
- ARCHI Vision projector: 445,053,216 bytes.
- Vosk ES y una copia marcada `corrupt-20260822-232950`; esta última es REMOVE CANDIDATE, no se borró.

## Decisión

El mayor ahorro no está en el Core: está en builds/dist repetidos, dos venv, backups, FFmpeg legado y runtimes temporales. La eliminación solo debe comenzar después de un checkpoint y una clasificación por ruta KEEP/MIGRATE/MERGE/DEPRECATE/DELETE.
