# ARCHEON Desktop Agent M4

Fecha de prueba: 2026-08-25  
Estado global: **PACKAGED TESTED / NO USER VERIFIED**

## Resultado

M4 conserva M1/M2/M3 y añade una ruta unificada de objetivo a capacidades, herramientas validadas, permisos, acciones, observación y verificación. No se marca todo M4 como terminado: la ejecución JavaScript compleja del navegador, los renders visuales de Office y la prueba personal del usuario siguen abiertos.

## Bloques implementados y probados

- Mouse físico como último recurso: mover, clic izquierdo/doble/derecho/central, scroll vertical/horizontal, press/release, drag/drop y liberación segura al cerrar.
- Cursor ARCHI nativo temporal: anillo cian click-through, DPI/multimonitor, estados internos, sin proceso idle.
- Browser DOM ligero: navigate/back/forward/reload/tabs/find/click/type/select/checkbox/radio/form/upload/download, detección de dialog y scroll acotado con reload/paginación; wrapper asyncio probado.
- ArtifactEngine: DOCX, XLSX, PPTX, PDF, TXT, MD, CSV, JSON y HTML; create/read/inspect/edit-copy/verify con reapertura, SHA-256 y checkpoint.
- ArchiveEngine: ZIP/TAR/TAR.GZ nativos con integridad y extracción segura; 7Z opcional detectado; RAR solo mediante proveedor licenciado detectado. No se integraron binarios.
- CapabilityRouter: Conversation/Search/Browser/Files/Documents/Artifacts/Programming/Terminal/Desktop/Vision/Media/Music/Device/Archives/Knowledge/Memory/Future Cloud/Future Extensions.
- TaskStore: checkpoint durante ejecución, historial y recuperación de tareas incompletas sin persistir cuerpos privados.
- Extensiones: manifest completo, contrato `.arx`, firma confiable obligatoria e aislamiento en proceso separado. No hay marketplace.
- Cloud: schemas/interfaces autenticados y consentimiento explícito; backend deliberadamente no implementado.
- ImprovementCandidate: solo evidencia/propuesta/plan de validación; no puede autoaplicarse ni automodificar ARCHEON.

## Pruebas reales

### Mouse visual

- Objetivo controlado rojo pulsado y cambiado a verde.
- Cursor overlay visible y click-through.
- Revalidación de ventana y posición: aprobada.
- Botones retenidos al terminar: 0.
- Latencia: 129.947 ms.

Evidencia: `benchmarks/desktop-agent-m4-mouse-cursor.json` y `benchmarks/desktop-agent-m4-mouse-cursor.png`.

### Objetivo compuesto Docker

Flujo real:

1. búsqueda con fuentes;
2. Docker Docs oficial, HTTP 200;
3. verificación DOM de `containers`;
4. DOCX de 41,092 bytes reabierto;
5. XLSX de dos hojas, fórmula y un gráfico reabierto;
6. PPTX de seis diapositivas reabierto;
7. ZIP de tres miembros creado y verificado con SHA-256.

Salida: `C:\Users\salda\Downloads\ARCHEON-Docker-20260825-002641-712885`.

La búsqueda keyless actual es un fallback de noticias y no es un buscador web general óptimo; el contenido del informe se fundamentó separadamente en Docker Docs oficial. No se confunden esos resultados con la fuente oficial.

### Objetivo compuesto lasaña

- DOCX con receta y tabla: creado/reabierto.
- XLSX con ingredientes, fórmula de total y gráfico: creado/reabierto.
- 5/5 pasos verificados.

Salida: `C:\Users\salda\Downloads\ARCHEON-Lasagna-20260825-003329-927901`.

### Regresión

- 179 pruebas aprobadas.
- 0 fallos.

## Build separada

- Ejecutable: `dist-desktop-agent-m4\Archeo32n\Archeo32n.exe`
- Tamaño total: 114,920,067 bytes (109.60 MiB).
- Diferencia frente a M3: +1,654,144 bytes (1.58 MiB).
- GGUF incluidos: 0.
- FFmpeg incluido: 0.
- Archivos de build M1/M2/M3: no modificados.

## Benchmark empaquetado

| Estado | RAM | CPU | Procesos | Hilos |
|---|---:|---:|---:|---:|
| Idle estable | 47.258 MiB | 0.0% | 1 | 9 |
| Artifacts cargados | 68.426 MiB | 0.0% | 1 | 9 |

- Startup Core empaquetado: 8.494 ms.
- Herramientas instanciadas antes del uso: 0.
- Herramientas instanciadas después del smoke: 2.
- Salida del proceso: 0.
- Procesos residuales: 0.
- Smoke empaquetado: DOCX, XLSX con gráfico, PPTX de 6 slides y ZIP aprobados.

Evidencia: `benchmarks/desktop-agent-m4-packaged.json`.

## Estado honesto pendiente

- Browser con DOM server-side: WORKING/PACKAGED TESTED.
- Aplicaciones web con JavaScript complejo, infinite scroll real y modales dinámicos: PARTIAL, requiere proveedor de navegador interactivo y pruebas live adicionales.
- ArtifactEngine estructural: WORKING/PACKAGED TESTED.
- Preview/render visual exacto de Word/Excel/PowerPoint: PARTIAL; no se afirma porque todavía no se automatizó Office/LibreOffice para render visual.
- 7Z: contrato opcional, proveedor no disponible en este equipo.
- RAR: contrato de proveedor licenciado, no disponible en este equipo.
- Cursor/Mouse: WORKING en prueba controlada; NO USER VERIFIED.
- M4 UX completa: NO USER VERIFIED.
