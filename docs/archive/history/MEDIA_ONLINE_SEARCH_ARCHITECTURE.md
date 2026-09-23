# Media Online + Search — foundation

Estado: implementación base en progreso. No se marca el bloque B como completo todavía.

## Decisiones de providers (2026-08-22)

- **Jamendo** es el primer `OnlineMediaProvider` reproducible. Su API oficial devuelve URL de stream, título, artista, álbum, duración, licencia y artwork. Los perfiles actuales mapean `LOW → mp31`, `MEDIUM/AUTO → mp32` y `HIGH → flac`. Requiere `ARCHEON_JAMENDO_CLIENT_ID` y no hace ninguna petición al iniciar. [Documentación oficial de tracks](https://developer.jamendo.com/v3.0/tracks)
- **YouTube Data API no es obligatoria.** La ruta oficial visible permanece disponible, y el usuario puede habilitar por separado el resolver local ampliado para recuperar compatibilidad de búsqueda sin API key.
- **Spotify Web Playback** exige cuenta Premium y su SDK no puede usarse comercialmente sin aprobación previa de Spotify. Se conserva como provider futuro autenticado, no como dependencia del Core. [SDK oficial](https://developer.spotify.com/documentation/web-playback-sdk)
- **Brave Search** es el primer `SearchProvider` opcional porque ofrece búsqueda web actual con resultados citables y filtros de frescura. Requiere `ARCHEON_BRAVE_SEARCH_API_KEY`; la clave sólo viaja en el header y nunca se devuelve a UI. [API oficial](https://api-dashboard.search.brave.com/api-reference/web/search/get)
- Bing Search API fue retirado el 11 de agosto de 2025 y Google Custom Search está cerrado a clientes nuevos, por lo que no se construyen providers nuevos sobre servicios en retirada. [Microsoft](https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement), [Google](https://developers.google.com/custom-search/v1/overview)

## Arquitectura implementada

```text
MediaDiscovery
├── LocalMediaProvider (índice JSON atómico, escaneo explícito y acotado)
└── JamendoMediaProvider (red sólo al solicitar fallback)

MediaEngine
├── BufferedHttpSource (HTTPS → buffer 256 KB → miniaudio)
└── CodecRouter (native/light decoder → optional FFmpeg for authorized codec gaps)

SearchEngine
└── BraveSearchProvider (fuentes + caché RAM de 5 minutos)
```

No se añadió FFmpeg al paquete base, ni `requests`, ni una base de datos. El decoder y la red permanecen descargados en idle. Un runtime FFmpeg separado se utiliza bajo demanda después de que un provider o el resolver local opt-in entregue la fuente reproducible. El stream usa un buffer acotado, sin polling constante, y libera decoder/proceso al detenerse.

## Verificación actual

- 60 pruebas automatizadas pasan.
- El stream MP3 público mostrado en la documentación de Jamendo entregó y decodificó 2048 muestras; el hilo de descarga se liberó al cerrar.
- Core idle después de añadir providers: 30.711 MB RSS, 0% CPU, 0% GPU y un proceso.
- El client id público de prueba que aparece en la documentación de Jamendo respondió `Suspended Application`; por eso la búsqueda real con credencial propia queda pendiente y no se simula como aprobada.

## Pendiente para cerrar B

- credencial de aplicación Jamendo válida y prueba búsqueda → stream → artwork;
- proxy/caché local acotado para artwork online (CSP continúa bloqueando imágenes remotas directas);
- UI de calidad y providers;
- intent de búsqueda web con presentación visible de fuentes;
- benchmark de buffer, reproducción online y recuperación offline.
