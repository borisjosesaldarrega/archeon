# ARCHEON — Artifact Quality M8

Fecha: 2026-08-25

## Estado

`PACKAGED TESTED / NO USER VERIFIED`

M8 conserva M1–M7 e incorpora una capa posgeneración que distingue validez técnica de calidad. Los scores se calculan desde evidencia reabierta y conservan limitaciones reales; no existe una ruta que asigne “10/10” por nombre o formato.

## Arquitectura añadida

- `ArtifactQualityEngine`: dimensiones independientes, problemas, severidad y reparación dirigida.
- `DesignIntentEngine`: convierte críticas coloquiales en objetivos de jerarquía, densidad, relevancia visual y estilo.
- `VisualAssetRouter`: separa evidencia, fotografía legítima, ilustración educativa, diagrama, gráfico e iconografía.
- `DiagramEngine`, `InfographicEngine`, `PrintLayoutEngine` y `WebDesignEngine`.
- `AssignmentIntelligence` y `RequirementPlan` para objetivos multi-formato y datos personales faltantes.
- `CreativeAssetEngine` con interfaces desacopladas de generación/edición futura.
- `ArtifactPreviewSurface`: contrato conceptual restringido, sin acceso general al filesystem, navegación externa ni ejecución de JavaScript desconocido.
- `archives.analyze_project`: reconocimiento estático y acotado de proyectos comprimidos, sin ejecución.
- `artifacts.quality_review`: herramienta lazy para revisar evidencia después de renderizar.

## Artefactos reales

- Infografía de embriología editable con una ilustración educativa de nueve etapas, etiqueta explícita de esquema no clínico, fuentes visibles y notas.
- Presentación de seguridad de siete diapositivas; cada una tiene una función visual distinta y diagramas nativos editables.
- TaskBoard M8 vanilla con edición, contador, limpieza, validación, teclado, estados completos, tres estrategias responsive y `localStorage`.
- XLSX con dos hojas, fórmulas, tabla, gráfico y configuración A4 horizontal a una página de ancho/alto.
- PDF del XLSX revisado en dos páginas: tabla completa y resumen/gráfico juntos.
- ZIP del TaskBoard reabierto, inspeccionado, reconocido como web, extraído y verificado por hash sin ejecutar contenido.

## QA y limitaciones honestas

- Infografía: el visual científico compuesto es raster y no es editable internamente; el texto, orden, etiquetas y layout sí lo son.
- Seguridad: prioriza diagramas educativos; no incluye capturas de incidentes reales porque no eran necesarias para esta guía.
- XLSX: la paginación fue verificada con Excel de escritorio; otro motor puede producir variaciones tipográficas pequeñas.
- Web: la validación estructural y de sintaxis pasó. Browser Agent E2E sigue bloqueado por la política de URL local de la herramienta autorizada. No se intentó workaround.
- Los binarios finales M7 ya no estaban en `Downloads` al cerrar M8. La comparación cualitativa usa los problemas M7 aceptados por el usuario y marca explícitamente esa procedencia; no inventa una reapertura inexistente.

## Pruebas y rendimiento

- Suite: 216 pruebas aprobadas y 3 subpruebas.
- Se corrigió una carrera de caché bytecode en el Programming Agent; la prueba afectada pasó cinco veces consecutivas antes de la suite final.
- Build: `dist-artifacts-m8/Archeo32n/Archeo32n.exe`.
- Reposo: 48.082 MiB RSS, 0.0 % CPU en la muestra, 1 proceso, 9 hilos.
- M7: 47.824 MiB RSS; aumento M8: 0.258 MiB.
- Artefactos cargados: 69.914 MiB RSS, 1 proceso, sin procesos residuales.
- Quality review: mediana 0.0048 ms; p95 0.0089 ms sobre 5,000 iteraciones.
- Herramientas cargadas: 0 antes, 2 después del smoke.
- GGUF incluidos: 0. FFmpeg/avcodec incluidos: 0.

## Evidencia

- `C:\Users\salda\Downloads\ARCHI-Artifactos-M8\M8_ARTIFACT_QUALITY.json`
- `C:\Users\salda\Downloads\ARCHI-Artifactos-M8\M8_VISUAL_ASSETS.json`
- `C:\Users\salda\Downloads\ARCHI-Artifactos-M8\M8_ARCHIVE_VALIDATION.json`
- `C:\Users\salda\Desktop\asistente\benchmarks\artifacts-m8-packaged.json`
