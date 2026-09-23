# ARCHEON — Artifact Intelligence M7

Fecha de cierre técnico: 2026-08-25

## Estado honesto

- M1–M6 se conservaron; M7 amplía la misma arquitectura.
- Artefactos XLSX, PPTX, PDF, TXT, Markdown, CSV, JSON y HTML: `WORKING / PACKAGED TESTED`.
- ZIP, TAR y TAR.GZ: creación, reapertura, inspección, lectura selectiva, extracción segura y hashes verificados.
- 7Z: proveedor opcional no disponible en el equipo; no se fingió compatibilidad.
- RAR: requiere proveedor instalado/licenciado; no se incluyó ni se fingió compatibilidad.
- TaskBoard: validación estática, sintaxis JavaScript, recursos, responsive y persistencia local aprobados.
- Browser Agent TaskBoard E2E: `BLOCKED_BY_BROWSER_URL_POLICY`. La herramienta autorizada rechazó `file://` y prohibió explícitamente usar HTTP local u otro navegador como workaround.
- Todo M7 permanece `NO USER VERIFIED` hasta prueba de Boris Saldarrega.

## Implementación

- `ArchiveEngineProvider` desacoplado con proveedores nativos ZIP/TAR y proveedores opcionales 7Z/RAR.
- Detección de traversal, rutas absolutas, duplicados, cifrado, ratio de compresión, límites de miembros/tamaño y tipos potencialmente riesgosos.
- Lectura y extracción selectiva; nunca ejecuta contenido extraído.
- `FileRouter`, `AttachmentManager`, `DocumentResolver`, `TaskContext` y la aplicación enrutan archivos comprimidos y conservan referencias a miembros.
- `RequirementChecker` reabre artefactos finales y realiza controles semánticos y visuales sin confiar en contadores de generación.
- Lenguaje natural reparado para variantes de JSON/CSV/ZIP y acciones de inspección/extracción.

## Pruebas

- Suite completa: `209 passed`, `3 subtests passed`, una advertencia deliberada del fixture de ZIP duplicado.
- Build: `dist-artifacts-m7/Archeo32n/Archeo32n.exe`.
- Smoke empaquetado: correcto; 0 herramientas cargadas antes y 2 después de solicitarlas.
- Reposo empaquetado: 47.824 MiB RSS, 0.0 % CPU en la muestra, 1 proceso, 9 hilos.
- Artefactos cargados: 69.117 MiB RSS, 0.0 % CPU en la muestra, 1 proceso, 9 hilos.
- Procesos residuales: ninguno.
- Modelos GGUF incluidos: 0. FFmpeg/avcodec incluidos: 0.
- Verificación de archivo: ZIP 2.767 ms, TAR 3.575 ms, TAR.GZ 1.946 ms.

## Entregables

Los entregables finales están en `C:\Users\salda\Downloads\ARCHI-Artifactos-M7`.

- Hoja de cálculo con dos hojas, fórmulas, dos tablas y gráfico nativo.
- Presentación editable de seguridad web, exactamente siete diapositivas, más PDF.
- Infografía vertical editable de embriología, más PDF.
- TaskBoard web funcional y portable de cuatro archivos.
- Datos equivalentes en CSV y JSON.
- TXT, Markdown y HTML.
- TaskBoard en ZIP, TAR y TAR.GZ.
- `M7_ARTIFACT_VALIDATION.json` y `M7_ARCHIVE_VALIDATION.json` con evidencia reabierta.

## Pendiente de validación humana

Abrir `ARCHI_TaskBoard/index.html` en un navegador permitido y comprobar: crear, completar, descompletar, eliminar, filtrar, recargar y persistir. Esta acción es necesaria para convertir la parte Browser Agent de `PARTIAL` a `USER VERIFIED`.
