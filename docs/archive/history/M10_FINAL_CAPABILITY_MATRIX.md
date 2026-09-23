# ARCHEON M10 — matriz final de capacidades

Fecha: 2026-08-28. `USER VERIFIED = NO` significa que existe evidencia automatizada/empaquetada, pero Boris todavía no la ha aceptado mediante una prueba manual.

| Capability | Status | Real implementation | Tests / runtime validation | External dependency | Known limitation | USER VERIFIED | Next action |
|---|---|---|---|---|---|---|---|
| Core modular / lifecycle | WORKING | `ArcheonApplication`, lifecycle y EventBus | suite 354 tests; packaged headless exit 0 | No | Ninguna regresión conocida | NO | Validación manual final |
| AppPaths / portability | WORKING | rutas administradas y ResourceManager | path tests; packaged outside source | Windows profile | Ninguna ruta de usuario en runtime source | YES | Preserve |
| Main UI / WebView | WORKING | servidor local tokenizado + WebView2 | UI contracts; packaged normal exit 0 | WebView2 | Memoria dominada por multiproceso WebView | NO | Revisión visual manual |
| Settings effects | WORKING | borrador, preview, confirmación, side effects | application/core/startup tests | Windows registry for startup | Algunos textos UI aún no están traducidos 12/12 | NO | Revisión visual manual |
| Personalization / layout | WORKING | posiciones viewport, escala, color, fondos y recorte | UI persistence tests | Codecs WebView | Aceptación visual pendiente | NO | Probar cerrar/reabrir |
| Accessibility | PARTIAL | escala, contraste, reduced motion, targets, left-handed, voice cues/listening phrases | config/UI tests | OS voices/devices | No auditoría humana WCAG completa | NO | Prueba de usuario |
| Auth email/password | PARTIAL | Supabase Auth, DPAPI, OTP 8 dígitos, recuperación, unicidad normalizada | auth/UI contracts | Supabase + correo | Entrega real pendiente | NO | Prueba con inbox controlado |
| MFA / account security | PARTIAL | enroll/challenge/verify/unenroll TOTP + account operations | auth contracts | Supabase hosted settings | AAL/RLS real no validado con cuenta final | NO | Prueba real AAL2 |
| Mailer | BLOCKED | Edge Function/hook/template contracts | M10 mailer matrices | API key, domain, SPF/DKIM/DMARC, hook secret | No entrega controlada | NO | Configurar credenciales y probar inbox |
| Settings sync | PARTIAL | PostgREST on-demand + atomic offline queue | sync tests; unauthenticated RLS denial | Supabase and user JWT | Authenticated roundtrip pending | NO | Prueba cuenta controlada online/offline |
| Wake Word | PARTIAL | Vosk local lightweight activation | 2 h soak, 0 errors | Microphone + ES Vosk | False negatives/positives spoken not user-labelled | NO | Prueba hablada del usuario |
| Voice end-to-end | PARTIAL | audio capture → VAD → STT → intent → TTS | voice suite and benchmarks | Mic/speaker/OS voice | Equipo real not USER VERIFIED | NO | Prueba física |
| STT contextual music follow-up | WORKING | contextual resolver tolerates accents/mojibake and preserves media intent | regression + full suite pass | Vosk/microphone | Spoken acceptance pending | NO | Manual voice regression |
| TTS | PARTIAL | Windows SAPI, styles and preview contract | voice benchmark | Installed Windows voices | Naturalness/12 languages vary by OS | NO | Audition voices |
| MediaSession | WORKING | provider/decoder/session state separation | media state/session/UI tests | Source/provider | Commercial catalog depends on provider | NO | User playback test |
| Music controls / vinyl | WORKING | pause/resume position, volume persistence, artwork/vinyl sync | `M10_MEDIA_UI_CONTROLS_VALIDATION.json` PASS | Player/source | USER VERIFIED pending | NO | Manual UI playback |
| YouTube visual media | WORKING | search metadata → official visible player | provider/UI tests | YouTube | No hidden audio/background extraction | NO | Manual regional playback |
| Direct authorized media | WORKING | provider → CodecRouter → player/WASAPI | media streaming tests | Authorized HTTPS stream | Availability/provider terms vary | NO | Provider credential tests |
| Optional FFmpeg decoder | PARTIAL | lazy isolated process for authorized/local unsupported formats | codec benchmark, zero residual | Separate runtime | Distribution candidate/license not approved | NO | Select minimal signed runtime |
| Launcher | WORKING | Start Menu + Steam/Epic manifests, stale-path validation | launcher tests; 44.8 ms / 147 items | Installed apps | Store-specific metadata can change | NO | User test installed/uninstalled games |
| Ghost | WORKING | native lightweight window and persisted mode | ghost tests; packaged exit 0 | Windows GUI | Visual acceptance pending | NO | User test |
| Ghost radial | WORKING | contextual actions/menus, theme/artwork sync | ghost tests; packaged radial exit 0 | Windows GUI | Visual/interaction acceptance pending | NO | User test |
| Planner / AgentTask | WORKING | goal, plan, steps, observe/verify/retry/cancel | agent runner tests | Tools per task | General autonomy bounded by available tools | NO | Real projects |
| Computer Use OBSERVE/GUIDE/CONTROL | WORKING | app API → UIA/accessibility → DOM → vision fallback | real YouTube/Notepad/Explorer/cancel/vision PASS | Windows apps | Not every third-party UI mapped | NO | User milestone phrases |
| Browser Engine | WORKING | visible browser accessibility/DOM operations | browser + real YouTube search | Browser/site | Site anti-automation and consent dialogs | NO | Broader site corpus |
| ARCHI Vision | WORKING | on-demand local VLM, region capture, unload | CPU real benchmark; zero residual | 1.55 GB models + llama.cpp | CPU latency ~19 s | NO | GPU/runtime optimization |
| Files / attachments | WORKING | drag, paste, multi-file, typed routing, bounded storage | M5/M6 tests and packaged evidence | File parsers | Some uncommon formats unsupported | NO | User file corpus |
| Document resolver/context | WORKING | approximate/recent/open/selected resolution + references | document tests | Windows/filesystem | Ambiguous files require confirmation | NO | User voice test |
| ArtifactEngine | WORKING | DOCX/PDF/XLSX/PPTX/TXT/MD/CSV/HTML + validation | M7/M8/M9 tests/evidence | Office renderers for visual QA | Complex layout still needs review | NO | User artifacts |
| ARCHI Image Lite | WORKING | conversation → provider → CPU/Vulkan → chat artifact → unload | real 512 generation; zero residual | SDXS/stable-diffusion.cpp | License provenance conditional; not medical/diagram precision | NO | Distribution review + visual acceptance |
| Image upscale 1024 | WORKING | optional Real-ESRGAN 2× pass | real 1.86 s, zero residual | Vulkan runtime | Upscale does not repair semantic errors | NO | User quality review |
| Programming Intelligence | WORKING | language/router/type/planner/toolchain/build/test/context | programming stacks tests | Installed toolchains | Real compilers vary by machine | NO | Real multi-stack projects |
| Operational Learning | WORKING | explicit/verified scoped correction memory; forget/reset | operational learning tests | Local storage | No automatic model weight changes | NO | User correction trial |
| Knowledge routing | WORKING | stable/current/high-risk routing with fresh-source requirement | knowledge and relevance tests | Search for current/high-risk | Retrieval quality depends on source/provider | NO | Broader eval set |
| 12-language architecture | PARTIAL | locales, language context, documents and quality gate | M9 multilingual matrix | STT/TTS models/OS voices | Only ES/EN have deep end-to-end coverage | NO | Native-speaker/external QA |
| Plugins local engine | WORKING | `.arx` manifest, permissions metadata, install/update/remove, enable/disable, compatibility, hash/signature, process isolation | lifecycle/tamper tests | Trusted publisher verifier | Production trusted key not configured | NO | Configure publisher trust root |
| Plugin marketplace | DEFERRED | No marketplace implementation | Honest UI state | Marketplace backend | Explicitly outside M10 | NO | Future phase |
| ARCHEON Cloud account/settings | PARTIAL | Auth + settings sync exist | auth/sync tests | Supabase | Controlled account roundtrip pending | NO | Real account validation |
| Device pairing | DEFERRED | Schema/architecture only | Cloud contract tests | Pairing service | No backend | NO | Future infrastructure |
| LAN direct | DEFERRED | Not implemented | N/A | LAN discovery/transport | No protocol/backend | NO | Future infrastructure |
| Remote relay | BLOCKED | Contract only | Fails closed | Relay infrastructure | No server/credentials | NO | Provision external relay |
| File transfer | DEFERRED | Not implemented | N/A | Transfer service | No backend | NO | Future phase |
| Remote commands | DEFERRED | Permission model reusable, transport absent | N/A | Secure remote transport | No backend | NO | Future phase |
| Mobile integration | DEFERRED | Cloud capability schema only | Contract tests | Mobile app/backend | No client/server | NO | Future phase |
| Updates | NOT CONFIGURED | provider abstraction, version/release/download/verify/install/restart state contracts | update tests; UI reports NOT CONFIGURED | Signed release backend | Cannot check available version | NO | Configure signed release provider |
| Search/current information | WORKING | dated retrieval route, Brave optional/RSS fallback | context/relevance tests | Internet/providers | No claim of freshness offline | NO | Source quality eval |
| Security boundaries | WORKING | permissions, scopes, target verification, redacted logs, signed plugins/updates | security audit + tests | OS/Supabase | Ignored legacy secrets remain in workspace, not package | NO | Revoke during Consolidation |
| Packaging | WORKING | lean onedir package; models/runtimes external | 117.3 MiB; 4 packaged smokes exit 0 | WebView2 + managed models | Installer signing/release backend pending | NO | Sign release and user install test |

## Ownership / duplicate responsibility audit

| Responsibility | Current owner | Related but distinct | Consolidation candidate |
|---|---|---|---|
| Application composition | `src/archeon/app.py` | root legacy entrypoints | Deprecate root runtime files |
| Tool authorization/execution | `core/permissions.py`, `core/tools.py` | `agent/tools.py` resolves plans into Core tools | Preserve separation |
| Media source/decoding/state | `media/discovery.py`, `media/codecs.py`, `media/engine.py` | root `archeon_music.py` is reference | Archive legacy after parity checkpoint |
| Browser | `browser/engine.py`, `browser/session.py`, `browser/visible.py` | DOM and visible UIA paths | Preserve layered ownership |
| Archives/artifact quality | `artifacts/archive.py`, `quality_m9.py` | `archive_m7.py`, `quality_m8.py` retain milestone layers | Merge after regression mapping |
| Updater | `updates/manager.py` | root `archeon_updater.py` unsafe legacy | REMOVE CANDIDATE |
| Cloud | `sync/engine.py` for real settings sync; `cloud/contracts.py` for future schemas | root `archeon_cloud.py` legacy | Migrate only verified behavior |

No duplicated module was deleted in M10.
