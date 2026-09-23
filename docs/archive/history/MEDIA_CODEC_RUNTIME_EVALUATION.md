# ARCHEON Media Codec Runtime evaluation

Estado: **CodecRouter y worker opcional integrados; runtime no empaquetado**  
Fecha: 2026-08-26  
Regla: `ARCHEON Base` no incluye ni mantiene FFmpeg residente.

## Conclusión

Decisión: **FFmpeg es un backend multimedia opcional legítimo, no un proveedor de contenido**.

No se descarga ni se incluye automáticamente. El `CodecRouter` ya admite un runtime administrado separado y, en desarrollo, detecta una instalación del sistema. Primero usa el backend ligero adecuado; FFmpeg se inicia solo si el formato lo requiere, y se cierra al detener, cambiar de pista o apagar ARCHEON. Media Foundation conserva prioridad para AAC/M4A/WMA y su adaptador nativo continúa pendiente de corpus y benchmark.

FFmpeg no participa en búsqueda ni estado: únicamente decodifica. YouTube puede usar el `OfficialWebMediaProvider` o, cuando el usuario habilita la compatibilidad multimedia ampliada, una fuente resuelta por `LegacyLocalResolver`. El resolver y el decoder permanecen separados y lazy.

## Arquitectura conservada

```text
MediaProviderRouter → playable source autorizado
↓
MediaSession / MediaEngine
↓
CodecRouter
├── MediaFoundationDecoder
├── MiniAudioDecoder
├── FFmpegProvider (opcional y efímero)
└── OfficialWebMediaProvider handoff (no decoder de audio)
↓
AudioManager → WASAPI → selected output device

FFmpegProvider
└── runtime separado → proceso efímero → PCM acotado → cierre verificado
```

Proveedor y decodificador son contratos separados: el primero localiza contenido reproducible; el segundo interpreta su formato. `MediaEngine` no contiene búsqueda ni comandos FFmpeg. `CodecRouter` selecciona por fuente, formato y autorización, no por mera disponibilidad.

## Cobertura y routing propuesto

| Formato/contenedor | Ruta preferida | Estado actual | ¿Candidato FFmpeg? |
|---|---|---|---|
| WAV/PCM | miniaudio | Soportado | No |
| MP3 | miniaudio | Soportado local y HTTPS | No |
| FLAC | miniaudio | Soportado | No |
| Ogg/Vorbis | miniaudio Python 1.71 | Soportado | No |
| AAC/ADTS | Media Foundation | Windows lo soporta nativamente; adapter aún no implementado | No antes de probar MF |
| M4A/AAC | Media Foundation | Windows soporta contenedor MPEG-4 y decoder AAC; adapter pendiente | No antes de probar MF |
| WMA/ASF | Media Foundation | Soporte nativo Windows; adapter pendiente | No antes de probar MF |
| Ogg/Opus | OptionalCodecRuntime | miniaudio stock no declara Opus; comprobar extensiones/decoders del sistema | Sí, solo si falla MF/sistema |
| WebM/Opus audio | OptionalCodecRuntime | Gap probable; requiere corpus real | Sí |
| Video codecs | Fuera de alcance | No habilitar | No |

## Comparación medida

| Backend | Formatos relevantes | Tamaño instalado | RAM/startup | CPU/latencia | Streaming | Calidad | Licencia |
|---|---|---:|---|---|---|---|---|
| miniaudio 1.71 actual | WAV, MP3, FLAC, Ogg/Vorbis | 691,701 B (`_miniaudio.pyd` + wrapper Python) | 0 B/0 ms mientras no se importa. Medición aislada de primer import: +8,699,904 B RSS y 57.144 ms | MP3 de 6.6 s decodificado en 5.210 ms (1266.7× realtime), medición única del host | Sí, callback + buffer 256 KiB | PCM 16-bit/44.1 kHz en pipeline actual | MIT |
| Windows Media Foundation | MP3, AAC/ADTS, M4A/MP4, WMA/ASF; FLAC según stack/contenedor moderno | 0 B añadidos al instalador | DLLs del sistema, carga bajo demanda; falta medir adapter | Falta benchmark real | Sí, mediante `IMFByteStream`/source reader | Decoder del sistema | Componente de Windows; respetar licencias de codecs/plataforma |
| Minimal FFmpeg | Solo gaps demostrados; candidato inicial Opus + Ogg/Matroska/WebM → PCM | **No medido: build todavía no creada** | 0 en idle si no está instalado/cargado; RAM activa pendiente | Pendiente | Sí, stdin/stdout acotados | PCM sin pérdida adicional después de decode | LGPL 2.1+ si se evita GPL/nonfree; obligaciones de redistribución |
| FFmpeg 8.0.1 essentials recuperado | Bundle general con muchos codecs, video, ffplay y ffprobe | 310,354,584 B total; 299,079,168 B en tres ejecutables; `ffmpeg.exe` 99,264,000 B | Proceso externo solo al ejecutar, pero paquete desproporcionado | No se justifica medir como solución base | Sí | Amplia | La configuración concreta debe auditarse; distribución recuperada no se acepta |

La medición miniaudio es un smoke reproducible del equipo actual, no un benchmark estadístico final. Deben repetirse 10+ iteraciones con archivos largos y memoria privada/working set.

## Micro-build candidata — todavía no ejecutar

El punto de partida debe ser el source oficial fijado por versión y hash. Una configuración conceptual para cubrir solo Opus en Ogg/WebM sería:

```text
--disable-everything
--disable-autodetect
--disable-doc
--disable-debug
--disable-network
--disable-avdevice
--disable-swscale
--disable-postproc
--disable-ffplay
--disable-ffprobe
--enable-ffmpeg
--enable-protocol=pipe
--enable-demuxer=ogg,matroska
--enable-decoder=opus
--enable-parser=opus
--enable-encoder=pcm_s16le
--enable-muxer=s16le
--enable-swresample
```

Esto es una hipótesis que debe validarse contra la versión elegida de FFmpeg; no se afirma todavía que configure, compile o cubra todo el corpus. ARCHEON descargaría HTTPS con su `BufferedHttpSource` y alimentaría stdin, por lo que el runtime no necesita TLS, HTTP, caché ni lógica de red propia.

No se habilitarán `libopus`, `libvorbis`, `libmp3lame`, x264, x265 ni otras librerías externas salvo que una medición demuestre una necesidad que el decoder nativo de FFmpeg no cubra. No se usarán `--enable-gpl` ni `--enable-nonfree`.

## Contrato propuesto

```text
CodecRouter.probe(source)
→ NativeDecoder.can_decode?
→ MediaFoundationDecoder.can_decode?
→ OptionalCodecRuntime.required_capability
→ pedir autorización para “Compatibilidad multimedia adicional”
→ HTTPS + manifest firmado + SHA-256
→ staging temporal
→ verificar versión/hash/firma
→ instalación atómica versionada
→ spawn sin ventana
→ stdin stream bounded → stdout PCM bounded
→ cerrar pipes → esperar salida → matar solo si excede timeout
→ verificar cero procesos residuales
```

No se guardará la canción completa ni se crearán temporales gigantes. El pack no se anunciará como FFmpeg fuera de Developer Mode, pero los avisos legales y el nombre FFmpeg no pueden ocultarse en About/EULA/documentación de distribución.

## Licencia y distribución

La guía oficial de FFmpeg indica:

- FFmpeg es LGPL 2.1+ por defecto; habilitar componentes GPL cambia la licencia del conjunto;
- no usar `--enable-gpl` ni `--enable-nonfree`;
- conservar notices y licencia;
- proporcionar el source exacto correspondiente a los binarios y la configuración de build;
- indicar el uso de FFmpeg en About/EULA/página de descarga;
- auditar también cada librería externa;
- preferir linking dinámico cuando ARCHEON enlace bibliotecas FFmpeg.

El diseño candidato usa un ejecutable separado por pipes, no linking directo, pero esto no elimina las obligaciones de redistribución del binario LGPL ni posibles consideraciones de patentes. Revisión jurídica sigue siendo necesaria antes de distribuir comercialmente.

## Criterios de aceptación antes de incluir el pack

1. Media Foundation implementado y probado primero.
2. Corpus mínimo: MP3, WAV, FLAC, Vorbis, AAC/ADTS, M4A/AAC, WMA, Ogg/Opus y WebM/Opus; archivos locales y streams HTTPS con range/no-range.
3. La micro-build debe resolver fallos reales que no resuelvan miniaudio/MF.
4. Medir ZIP, tamaño instalado, número de archivos/DLL, tiempo de spawn, TTFA de audio, CPU, working set pico, memoria después de cerrar y procesos residuales.
5. Manifest versionado, source exacto, build config, SHA-256, firma y rollback verificados.
6. Si la mejora no compensa tamaño/complejidad/licencia: `DO NOT INCLUDE`.

## Fuentes

- [FFmpeg legal and LGPL compliance checklist](https://ffmpeg.org/legal.html)
- [FFmpeg documentation: selective decoders/demuxers](https://www.ffmpeg.org/ffmpeg-all.html)
- [miniaudio decoding documentation](https://miniaud.io/docs/manual/index.html)
- [Microsoft Media Foundation supported formats](https://learn.microsoft.com/en-us/windows/win32/medfound/supported-media-formats-in-media-foundation)
- [Windows supported codecs](https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/supported-codecs)

## Próximo paso autorizado

Completar el `MediaFoundationDecoder` lazy y ejecutar el corpus comparativo. Medir el FFmpeg del sistema solo como referencia de desarrollo y, después, decidir una micro-build o paquete independiente. No añadir ni descargar el runtime en equipos de usuarios antes de presentar tamaño, hash, configuración de compilación, licencias y resultados.
