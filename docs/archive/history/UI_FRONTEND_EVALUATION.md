# Full UI frontend evaluation

Recorded 2026-08-21 on the current Windows host. These are measured engineering
inputs, not a framework migration decision.

## Current WebView2 host

The corrected process sampler follows the real interpreter PID instead of the
short-lived virtual-environment launcher. With a 2 s warm-up and 3 s sample:

| Scenario | Working set avg | Private avg | CPU avg | Processes | UI ready |
|---|---:|---:|---:|---:|---:|
| Full UI idle (short) | 466.3 MB | 257.2 MB | 9.88% | 1 Python + 6 WebView2 | 869 ms |
| Full UI + local music (short) | 459.0 MB | 248.0 MB | 4.43% | 1 Python + 6 WebView2 | 865 ms |
| Full UI steady (5 s warm-up, 10 s sample) | 457.3 MB | 245.8 MB | 0.31% | 1 Python + 6 WebView2 | 868 ms |

The packaged HTML, CSS, JavaScript, images and demo audio total only 220,497
bytes. The dominant cost is the WebView2 process family (browser, renderer, GPU
and utilities), not Flask (not used), the standard-library loopback server, or
large frontend assets. The short CPU window includes renderer warm-up; the
longer sample shows the event-driven UI near idle, although it is not a
five-minute claim. Per-process GPU utilization remains `null`: psutil on
this host exposes no GPU engine counters, so no value was invented.

Static UI assets now use `Cache-Control: no-cache, must-revalidate` to prevent
mixed HTML/JavaScript versions after upgrades. Dynamic runtime configuration is
`no-store`; album art keeps a private one-day cache. UI state uses SSE and the
clock has one minute-aligned timeout; there is no periodic API polling.

## Native Tk/Win32 feasibility probe

A disposable 1100×720 probe renders the same coarse structure—brand, access
panel, controls and concentric orb—without animation or application services.
It measured 27.0 MB average working set, 12.2 MB private memory, 1.51% CPU over
the short sample, one process, 201 handles and seven threads. It exited with
code 0. This is a rendering feasibility number only: it excludes real auth,
media, accessibility work and the CSS-level visual fidelity of the product UI.

The native Ghost is the stronger production proof: 39.8 MB idle and 44.6 MB
with real music, one process, and no WebView2.

## WinUI / Windows App SDK

Windows App Runtime packages 1.5, 1.7, 1.8 and 2.x are installed, but this host
has no .NET SDK or WinUI project templates. Building a real comparable prototype
would therefore require installing a new SDK/toolchain. It was not installed
silently and no memory number is claimed. A runtime-only package listing is not
a benchmark.

## Decision

Keep WebView2 for the full interface in this iteration because it already
delivers the recovered visual identity, localization and accessibility semantics.
Keep it destroyed in long-lived Ghost mode. Do not migrate the main UI on the
strength of a non-functional Tk mockup. The native result is large enough to
justify a later, isolated WinUI/WPF prototype once its SDK is explicitly
approved; that prototype must implement the same auth screen, orb states, SSE
bridge and media controls before its numbers are comparable.
