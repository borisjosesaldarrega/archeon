# ARCHEON Desktop Agent M3 report

Date: 2026-08-24

## State

| Area | State | Evidence |
|---|---|---|
| Vision component manager | WORKING | Atomic download, exact size/SHA-256 validation, AppPaths model directory, no repository model. |
| Vision runtime lifecycle | WORKING | UNLOADED/LOADING/READY/BUSY/UNLOADING, explicit cancel, idle unload, zero residual llama-server processes. |
| Screen understanding | WORKING | Real active custom-canvas Observe and controlled corpus; 9/10 semantic corpus categories met their minimum check. |
| Visual grounding | WORKING | Supports validated 0–1 and native 0–1000 normalized regions; stale handle/bounds rejected. |
| Observe | WORKING | Real UIA-to-Vision fallback identified the wake-detector error with visible evidence. |
| Guide | WORKING | Real native click-through overlay shown over the visually grounded OK control. |
| Control | WORKING | Real custom-canvas OK click changed the screen and was verified after the action. |
| Programming Agent | WORKING | Real controlled project: syntax error then logical bug, two checkpoints/replans, tests and startup verified. |
| Browser Agent | PARTIAL | DOM-first tabs/history/forms/upload/download tests pass; broad live dynamic-site coverage remains open. |
| Multi-App | WORKING | Files → PDF → TaskContext → Notepad → save → exact verification → close, 9/9 steps. |
| Context references | WORKING | Structured result references and safe `$template` composition across tools. |
| General replanning | PARTIAL | Runner supports bounded replacement replans; programming loop exercised real replans, broader multi-app fault matrix remains open. |
| Screenshot privacy | WORKING | Captures remain memory-only; semantic bodies and terminal/code bodies are redacted from TaskStore. |
| Build M3 | PACKAGED TESTED | Separate 108.02 MiB build, packaged smoke exit 0, zero residues, zero GGUF and zero FFmpeg bundled. |
| User verification | NOT STARTED | Boris must test the M3 build; no area is marked USER VERIFIED here. |

## Optional ARCHI Vision benchmark component

- Internal reference: Qwen3-VL-2B-Instruct GGUF Q4_K_M plus Q8 projector.
- Source revision: `52d6c8ffea26cc873ac5ad116f8631268d7eb503`.
- License recorded: Apache-2.0.
- Installed only in `%LOCALAPPDATA%\ARCHEON\models\archi-vision`.
- Download bytes: 1,552,463,168; installer bytes: 0.
- CPU-only backend; this llama.cpp build reports no Vulkan devices, so AMD acceleration was not forced.

## Vision performance

| Input | Cold load | First token | Inference | Wall |
|---|---:|---:|---:|---:|
| 640×400 | 2.838 s | 4.808 s | 16.639 s | 19.478 s |
| 960×600 | warm | 10.881 s | 21.388 s | 21.389 s |
| 1280×800 | warm | 21.098 s | 29.444 s | 29.450 s |

- Clean 640 CPU run: runtime peak 2,846.883 MiB; settled 2,840.613 MiB; sampled peak 714.8% across cores.
- Full corpus peak: 3,932.602 MiB; this is too high for a permanently resident component, so unload remains mandatory.
- Unload: 208–281 ms in real runs; post-unload host RSS about 36.6–36.8 MiB; residual PIDs: 0.
- 640/960 retained all three expected error-dialog cues. 1280 missed the OK cue and was slower, so 960 is the current operational ceiling and 640 is preferred when text remains readable.
- Known semantic failure: the synthetic latency chart was read as a salary chart.

## Packaged idle comparison

Measured with the same harness and clean temporary data directories:

| Build | RSS | CPU (1 s) | Threads | Children |
|---|---:|---:|---:|---:|
| M2 | 44.895 MiB | 0.0% | 9 | 0 |
| M3 | 44.855 MiB | 0.0% | 9 | 0 |

Vision adds no idle process and no measurable packaged idle regression in this comparison.

## Remaining work before USER VERIFIED

- User validation of Observe, Guide and Control on Boris's real applications.
- Broader live Browser Agent matrix for redirects, dynamic pages, forms, downloads and uploads.
- Broader replan fault matrix: closed/moved windows, renamed files, changed browser tabs and command failures.
- Programming Agent expansion beyond the intentionally conservative Python repairs proven in M3.
- Reevaluate a lighter/faster visual candidate or a stable Vulkan runtime because current CPU latency and 2.8–3.9 GiB runtime RAM are not acceptable for continuous use.
