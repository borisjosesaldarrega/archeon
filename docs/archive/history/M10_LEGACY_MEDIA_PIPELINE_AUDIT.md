# M10 — auditoría del pipeline multimedia heredado

Fecha: 2026-08-26  
Fuentes inspeccionadas: `archeon_music.py`, `archeon_dialog_manager.py`, `archeon_reasoner.py`, `archeon_neuro.py` y `legacy_sanitized/Archeo32n.py`.

## Flujo real encontrado

```text
orden del usuario
→ DialogManager detecta intent `play_music`
→ MusicManager.play_audio_threaded(query)
→ hilo DJ y cola global
→ yt_dlp con `default_search=ytsearch`
→ primer resultado o búsqueda de cinco para radio
→ URL de formato con audio + título + thumbnail
→ proceso FFmpeg con reconexión
→ PCM s16le fijo 44.1 kHz / 2 canales
→ cola de 256 bloques
→ callback sounddevice
→ dispositivo de salida
```

`archeon_dialog_manager.py` llamaba directamente a `music_manager.play_audio_threaded(query)`. `archeon_music.py` resolvía búsqueda y reproducción dentro de la misma clase: `yt_dlp` devolvía la URL, título y miniatura; FFmpeg convertía el stream a PCM; `sounddevice.OutputStream` consumía la cola. `Archeo32n.py` leía `stream_out` y `current_thumbnail` para representar el estado visual. `archeon_neuro.py` infería música activa comprobando directamente `music_manager.stream_out`.

## Clasificación de piezas

| Pieza heredada | Clasificación | Decisión M10 |
|---|---|---|
| Pedir canción por título/artista | MIGRATE CONCEPT | Mantener mediante intent → request → matcher → providers. |
| Búsqueda y URL reproducible | REIMPLEMENT | Providers normales y fallback local ampliado explícitamente habilitado. |
| Título y thumbnail | MIGRATE CONCEPT | Metadata del provider, proxy/cache de artwork y fallback controlado. |
| `yt_dlp` como resolver/prober | SELECTIVE MIGRATION | Dos rutas lazy: fuentes HTTPS allowlisted y `LegacyLocalResolver` integrado con `ytsearch`. |
| `yt_dlp` como reproductor/estado global | DO NOT COPY | Solo resuelve candidatos/stream; FFmpeg decodifica y MediaSession conserva el estado. |
| FFmpeg como decoder a PCM | REIMPLEMENT | `FFmpegProvider` opcional, lazy, aislado y sin búsqueda. |
| Ruta `_MEIPASS/ffmpeg.exe` monolítica | PERFORMANCE DEBT | Runtime administrado separado; nada embebido en el núcleo por defecto. |
| PCM fijo 44.1 kHz estéreo | REIMPLEMENT | Conversión explícita y corpus 32/44.1/48 kHz; no asumir reloj de fuente. |
| Cola de 256 bloques / buffer 1024 KiB | PERFORMANCE DEBT | Backpressure y buffer mínimo estable medido. |
| `sounddevice` obligatorio | OBSOLETE | Mantener salida actual miniaudio/WASAPI y dispositivo configurado. |
| Polling de dispositivo cada 0.5 s | PERFORMANCE DEBT | No copiar; usar eventos/notificaciones de Windows. |
| Estado global (`stream_out`, flags, hilos) | DO NOT COPY | Una sola MediaSession/MediaEngine y eventos de estado. |
| Primer resultado de `ytsearch` | PERFORMANCE DEBT | Evaluar varios candidatos con matcher original-first. |
| Filtro de remix/live/cover | MIGRATE CONCEPT | Ya reforzado con scoring por versión, artista y título. |
| Historial corto y DJ | MIGRATE CONCEPT | Historial/rechazos de sesión, sin persistir búsquedas privadas. |
| `nocheckcertificate=True` | SECURITY RISK | No copiar; HTTPS validado y redirects acotados. |
| `except:` generalizado | SECURITY RISK | Errores tipados, timeouts y estado degradado explícito. |
| Kill sin espera garantizada | REIMPLEMENT | terminate → wait → kill con timeout y prueba de cero residuos. |

## Diferencia arquitectónica actual

```text
Intent Engine
→ MediaSearchQuery / contexto de rechazo
→ MediaDiscovery (providers lazy)
→ TrackMatcher (original-first)
→ MediaSearchResult / Track
→ única MediaEngine
→ CodecRouter
   ├── miniaudio
   ├── Media Foundation (adapter pendiente)
   └── FFmpegProvider opcional
→ WASAPI
```

FFmpeg ya no decide dónde está la canción. Solo decodifica la fuente que recibe.
YouTube puede terminar en el IFrame oficial o, si el usuario habilitó expresamente
la compatibilidad local ampliada, en `LegacyLocalResolver → CodecRouter → FFmpeg`.

## Capacidad útil recuperada de `yt-dlp`

El valor técnico del legado no era únicamente “usar YouTube”. También aportaba
un resolver capaz de inspeccionar una fuente, enumerar entradas/formatos,
obtener título, autor, duración y portada, y entregar una URL reproducible al
decoder sin descargar primero el archivo completo. Esa parte se conservó de
forma selectiva:

| Capacidad | M10 |
|---|---|
| Probar una URL HTTPS controlada/autorizada | `YtDlpAuthorizedResolver`, con allowlist explícita. |
| Leer metadata y formatos sin descargar | `skip_download=True`, `noplaylist=True`, timeout acotado. |
| Elegir una variante que contenga audio | Selección entre formatos HTTPS; resultado normalizado como `ResolvedMedia`. |
| Pasar el stream al decoder | `ResolvedMedia → CodecRouter → MediaEngine`. |
| Buscar varios candidatos con `ytsearch` | Migrado al `LegacyLocalResolver` opt-in, sin API key. |
| Resolver el candidato seleccionado como stream | Migrado; `TrackMatcher` puntúa antes de resolver. |
| Cargar `yt-dlp` siempre | No migrado. Se instala con ARCHEON, pero permanece sin importar y sin procesos durante idle. |

La tenacidad se trasladó a `MediaDiscovery`, no a un extractor concreto:
FAST prueba la consulta exacta; DEEP prueba variantes normalizadas y
`título + artista` / `artista + título`, reúne varios candidatos, los puntúa con
`TrackMatcher`, rechaza remix/live/cover cuando se pidió la original y deja una
traza de cada consulta, candidato y rechazo. El presupuesto es finito para no
convertir una orden musical en polling o búsquedas ilimitadas.

## Estado honesto

- Auditoría del legado: WORKING.
- Matcher original-first y rechazo contextual: WORKING / pruebas automatizadas.
- MediaSession, controles y salida local: WORKING / PACKAGED TESTED previo.
- FFmpegProvider y CodecRouter: WORKING, pendiente benchmark/corpus empaquetado.
- Media Foundation: PARTIAL; contrato/routing presente, adapter nativo pendiente.
- Catálogo comercial amplio: PENDING PROVIDER VALIDATION.
- YouTube Data API/IFrame: sigue disponible como ruta opcional; no es requisito.
- `Limón y Sal`: original de Julieta Venegas verificado mediante resolver local, score 326.0 y reloj avanzando.
- `Se Fue la Luz`: original de LATIN MAFIA/Jesse Baez verificado, score 261.2703.
- `Hello Cotto`: original de Duki verificado, score 326.0.
- Las tres pruebas usaron FFmpeg aislado, conservaron posición en pausa/reanudación y dejaron cero procesos residuales.
- USER VERIFIED: false.
