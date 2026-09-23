# ARCHEON music-provider evaluation

Estado: **investigación previa a integración**  
Fecha: 2026-08-23  
Decisión de arquitectura: `MusicAudioProvider` y `VisualMediaProvider` son contratos distintos. Ningún resultado visual puede entrar al decoder nativo como si fuera una URL de audio.

## Resultado ejecutivo

No existe actualmente un proveedor público oficial que reúna simultáneamente:

- catálogo mainstream amplio;
- reproducción completa como stream de audio dentro del player nativo de ARCHEON;
- control por voz permitido;
- distribución comercial sin aprobación/contrato adicional;
- funcionamiento sin cuenta o suscripción del usuario.

Por tanto, **no hay un `GOOD PRIMARY PROVIDER` mainstream aprobado**. La estrategia segura sigue siendo:

```text
LocalMediaProvider
→ buscar en todos los MusicAudioProvider autorizados
→ MusicMatcher global (original antes que remix)
→ YouTubeVisualProvider visible como fallback
→ SystemMediaProvider / aplicación externa como último fallback
```

## Comparación

| Provider | Catalog breadth | Original/mainstream music | Full playback | Desktop support | Requires user subscription | Commercial use restrictions | Voice-control restrictions | Background playback | API credentials / limits / cost | Streaming method | Can use native ARCHEON player | FFmpeg required | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Local files | Archivos del usuario | Sí, según biblioteca | Sí | Sí, Windows | No | El usuario debe tener derecho a reproducir los archivos | Ninguna específica | Sí | Ninguna | Archivo/stream local → miniaudio/MF → WASAPI | Sí | No para MP3/WAV/FLAC/Vorbis; evaluar gaps | **GOOD PRIMARY PROVIDER** local |
| Audius | Amplio catálogo abierto, menor que servicios mainstream | Parcial; fuerte presencia independiente, remixes y uploads de creadores | Sí cuando `access`/gating lo permite | Sí | No para contenido público | Respetar API Terms, OML y licencia elegida por el creador; no asumir que cada upload concede usos adicionales | No se encontró prohibición general de control por voz; deben respetarse gating/licencia | No se encontró prohibición general para streams autorizados | Free: 10 req/s y 500,000 req/mes; Unlimited por contacto | Endpoint HTTPS oficial de stream | Sí, para streams no bloqueados | No para formatos soportados actualmente | **GOOD OPTIONAL PROVIDER** |
| Jamendo | ~500,000 tracks independientes | No es un catálogo mainstream | Sí para tracks disponibles | Sí | No | API gratis solo para uso no comercial; ARCHEON comercial requiere cotización/acuerdo. Respetar CC, atribución y backlink | No se encontró prohibición específica | Permitido dentro del uso/licencia acordados; sin ofrecer offline | `client_id`; contactar al superar 500,000 hits; comercial: precio por cotización | URL HTTPS de audio (`mp31`, `mp32`, `flac`) | Sí | No | **GOOD OPTIONAL PROVIDER**, condicionado a contrato comercial |
| Apple Music / MusicKit JS | Muy amplio, mainstream, millones de canciones | Sí | Sí para suscriptores con capacidad `canPlayCatalogContent` | Web funciona en navegadores desktop; WebView2 requiere prototipo de compatibilidad | Sí para catálogo completo; autorización del usuario | Apple Developer Program (USD 99/año). No cobrar ni monetizar directa o indirectamente el acceso a Apple Music; playback iniciado por usuario y controles estándar obligatorios | No se encontró veto explícito a voz; la orden debe ser una iniciación real del usuario, no autoplay autónomo | No hay veto general encontrado, sujeto a MusicKit/browser y estado de suscripción | Media ID, clave privada, developer token y Music User Token; cuota fija pública de playback no localizada | MusicKit JS/player oficial con DRM | **No**: no entrega un stream genérico al player nativo | No | **GOOD OPTIONAL PROVIDER**; mejor candidato mainstream, sujeto a prueba y revisión contractual |
| Deezer | Amplio/mainstream | Sí | La plataforma histórica tenía SDK/player, pero no hay una vía nueva fiable aprobable para ARCHEON | No aprobable actualmente | Normalmente cuenta/suscripción según playback | Creación de nuevas apps deshabilitada; staff indicó que monetizar incumple sus términos y desactiva IDs | No se validó una autorización vigente | No evaluable | No se aceptan nuevas aplicaciones de forma general; IDs existentes se revisan/desactivan | No hay integración oficial nueva verificable | No | No resolvería acceso/DRM | **NOT SUITABLE** |
| SoundCloud | Amplio UGC; mainstream irregular | Parcial | Sí para tracks con `access=playable`; otros son preview/bloqueados/geoblocked | Sí | No para tracks públicos reproducibles | Sus términos prohíben crear un servicio alternativo bajo demanda que agregue streams de múltiples usuarios o mezcle SoundCloud con otros servicios; conflicto directo con la arquitectura multi-provider | Sin veto técnico específico, pero el caso de uso agregado ya está prohibido | Técnicamente posible para streams autorizados | App registrada/OAuth; 15,000 solicitudes de stream por 24 h y `client_id` | Widget oficial o transcoding HTTPS con atribución obligatoria | Técnicamente sí, contractualmente no en este producto | No para transcodings compatibles | **NOT SUITABLE** para ARCHEON multi-provider |
| TIDAL | Amplio/mainstream | Sí | Fuera de TIDAL Embeds: hasta 30 s para no suscriptores; full playback de suscriptores en experiencia autorizada | SDK Web/embeds | Sí para full playback | Branding obligatorio; no mostrar junto a servicios similares; no crear experiencia standalone que no devuelva al usuario a TIDAL; playback solo mediante SDK | Las guías prohíben usar contenido TIDAL con servicios o herramientas de IA, incompatibilidad directa con ARCHI | Solo conforme al SDK/Embed | Client ID/OAuth; límites/precio público fijo no localizado | TIDAL SDK/Embed, manifests/DRM gestionados | No | No | **NOT SUITABLE** para un asistente IA agregador |
| Spotify Web Playback | Muy amplio/mainstream | Sí | Sí con Premium | Chrome/Firefox/Safari/Edge desktop | Sí, Premium | Streaming apps no pueden ser comerciales sin aprobación escrita; contenido no puede alterarse | Spotify enumera voice-control entre casos que no deben construirse | SDK/browser, sujeto a autoplay y sesión | OAuth/client ID; acceso y cuotas sujetos al modo de app | Web Playback SDK/Spotify Connect | No | No | **NOT SUITABLE** para el objetivo comercial y por voz |
| YouTube | Muy amplio | Sí, además de uploads no oficiales | Sí, audiovisual | Sí mediante IFrame visible | No necesariamente | Player visible oficial; no separar audio, no descargar, no ocultar branding/player ni usar background contrario a políticas | Comandos solo mediante controles/API oficiales y respetando iniciación/autoplay | No como hidden/background audio | Google project/API key; `search.list` tiene cuota propia (100 búsquedas/día por defecto en la documentación vigente) | YouTube IFrame Player visible | No | No | **VISUAL ONLY** (`YouTubeVisualProvider`) |
| Amazon Music | Muy amplio/mainstream | Sí | API de playback existe, pero está en beta cerrada | La certificación excluye plataformas donde el usuario pueda instalar software/acceder al filesystem: una PC Windows no cumple | Depende del tier del usuario | Dispositivo certificado, contrato y Widevine; no es una API desktop pública | No evaluable para ARCHEON | Solo dentro del cliente certificado | Beta cerrada, LWA, API key, certificación y acuerdo Widevine | DASH cifrado/Widevine | No | No; FFmpeg no sustituye DRM | **NOT SUITABLE** |
| iTunes Search / MusicBrainz | Catálogo/metadata amplio | Sí como metadata | Solo previews o ninguna reproducción completa | Sí para búsqueda | No | Solo uso de metadata/previews según términos de cada servicio | No aplica | No aplica | API pública con límites propios | JSON + artwork/previews | No para catálogo completo | No | **METADATA ONLY** |
| Windows `SystemMediaProvider` | Depende de Spotify/Apple Music/etc. instalado por el usuario | Sí | Sí en la aplicación propietaria | Sí | La del proveedor externo | ARCHEON controla la sesión del sistema; no recibe ni redistribuye audio | Debe respetar las reglas del proveedor controlado; Spotify sigue vetando experiencias de voz construidas con sus APIs | La gestiona la aplicación externa | Sin credenciales de catálogo en ARCHEON; usa GSMTC/SMTC | Playback externo + controles del sistema | No; audio pertenece a la app externa | No | **GOOD OPTIONAL PROVIDER** como fallback externo, no audio interno |

## Disponibilidad geográfica

| Provider | Disponibilidad relevante para ARCHEON |
|---|---|
| Local | Sin restricción del provider; depende de los derechos del archivo del usuario. |
| Audius | Los deals documentados contemplan streaming mundial, pero cada track puede imponer gating/licencia y puede retirarse. |
| Jamendo | Servicio internacional; aplican licencia individual, sanciones y restricciones territoriales indicadas por Jamendo. |
| Apple Music | Depende del storefront, catálogo y disponibilidad de Apple Music en la región de la cuenta del usuario. No asumir que un ID es reproducible en todos los storefronts. |
| Deezer | La disponibilidad del servicio no corrige la falta actual de acceso fiable para nuevas aplicaciones. |
| SoundCloud | Track por track: puede ser `playable`, `preview` o `blocked`, incluyendo geoblocking. |
| TIDAL / Spotify | Depende de países soportados, plan y cuenta del usuario; además sus restricciones contractuales descartan el caso actual. |
| YouTube | Depende de que el video permita embed y esté disponible en el país del usuario; es fallback visual, no audio. |
| Amazon Music | Depende de tier/territorio y certificación; la beta cerrada no admite una app desktop Windows como ARCHEON. |
| SystemMediaProvider | Hereda territorio, cuenta y disponibilidad de la aplicación externa controlada. |

## Regla de matching global

`MusicMatcher` debe recibir todos los candidatos elegibles antes de decidir. El orden de registro de providers no concede prioridad automática.

Para `Julieta de Latin Mafia`:

1. normalizar título, artista y versión solicitada;
2. consultar en paralelo o dentro de un presupuesto acotado todos los providers autorizados;
3. rechazar resultados bloqueados/no reproducibles antes de rankear;
4. puntuar coincidencia de artista/título, versión, duración y señales verificables de oficialidad;
5. penalizar fuertemente `remix`, `cover`, `live`, `slowed`, `sped up`, `nightcore`, `bootleg`, etc. si se pidió original;
6. reproducir automáticamente solo una coincidencia original suficientemente fiable;
7. si solo hay alternativa, preguntar o bloquear según preferencia; nunca reproducir el remix solo porque Audius respondió primero.

Para YouTube, “official” solo puede derivarse de señales comprobables del API/canal y de coincidencia de metadata. Las palabras “official audio” en el título, por sí solas, no prueban oficialidad.

## Decisión recomendada

1. Mantener **Local + Audius + Jamendo autorizado** como audio nativo, aplicando MusicMatcher global.
2. Prototipar **Apple Music/MusicKit JS** como provider opcional separado. Antes de integrar: verificar MusicKit JS en WebView2, user initiation por voz, salida de audio seleccionada, login, geografía y revisión contractual de la edición comercial de ARCHEON.
3. Diseñar **YouTubeVisualProvider** fuera de `MediaEngine`: búsqueda/metadata con Data API y reproducción con IFrame visible oficial.
4. Implementar **SystemMediaProvider** para controlar aplicaciones instaladas como fallback externo, sin afirmar que ARCHEON reproduce internamente.
5. No integrar Deezer, SoundCloud, TIDAL, Spotify ni Amazon Music mientras sus condiciones actuales sean incompatibles o no exista aprobación escrita específica.

## Fuentes oficiales consultadas

- [Audius developer docs and API plans](https://docs.audius.co/sdk/)
- [Audius Terms / Open Music License context](https://blog.audius.co/posts/audius-terms-of-service-update)
- [Jamendo API terms](https://devportal.jamendo.com/api_terms_of_use)
- [Jamendo API documentation](https://developer.jamendo.com/v3.0/docs)
- [Apple MusicKit](https://developer.apple.com/musickit/)
- [Apple Developer Program License Agreement, MusicKit section](https://developer.apple.com/support/terms/apple-developer-program-license-agreement/)
- [Apple Developer Program cost](https://developer.apple.com/programs/whats-included/)
- [Deezer staff discussion on disabled/reviewed API IDs](https://en.deezercommunity.com/your-account-favorites-and-playlists-70/oauth-exception-81676)
- [SoundCloud playback API](https://developers.soundcloud.com/docs/api/)
- [SoundCloud API Terms](https://developers.soundcloud.com/docs/api/terms-of-use)
- [SoundCloud rate limits](https://developers.soundcloud.com/docs/api/rate-limits.html)
- [TIDAL design and content rules](https://developer.tidal.com/documentation/guidelines/guidelines-design-guidelines)
- [TIDAL Web SDK](https://github.com/tidal-music/tidal-sdk-web)
- [Spotify Web Playback SDK](https://developer.spotify.com/documentation/web-playback-sdk)
- [Spotify compliance tips, including voice control](https://developer.spotify.com/compliance-tips)
- [YouTube IFrame Player API](https://developers.google.com/youtube/iframe_api_reference)
- [YouTube required minimum functionality](https://developers.google.com/youtube/terms/required-minimum-functionality)
- [Amazon Music DRM/playback requirements](https://www.developer.amazon.com/docs/music/playback_overview.html)

Esta evaluación técnica no reemplaza revisión jurídica antes de firmar acuerdos o distribuir una integración comercial.
