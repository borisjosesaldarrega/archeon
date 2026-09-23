# ARCHEON Files/Documents M6

Fecha de cierre técnico: 2026-08-25

## Resultado

M6 amplía M5 sin sustituir `ArtifactEngine`, `FileTypeRouter`, `TaskContext`, Desktop, Browser ni ARCHI. La entrada original del usuario se conserva y la interpretación corregida se registra por separado, con confianza y bloqueo explícito cuando una acción destructiva es ambigua.

## Implementado y probado

| Bloque | Estado técnico | Evidencia |
|---|---|---|
| NaturalLanguageRepair | WORKING / PACKAGED TESTED | 2.000 interpretaciones; mediana 0,0247 ms, p95 0,0300 ms |
| WritingStyleEngine | WORKING / PACKAGED TESTED | perfiles separados de formato visual; “no tan IA” se interpreta como tono natural, sin evasión ni errores artificiales |
| Memoria de estilo | WORKING | una preferencia se aprende solo después de retroalimentación repetida; persistencia probada |
| DocumentStyleProfile DOCX | WORKING / PACKAGED TESTED | propiedades reales de página, márgenes, fuente, interlineado, títulos y numeración |
| EvidenceCapture + manifest | WORKING / PACKAGED TESTED | tres capturas reales con URL, viewport, paso, fecha y SHA-256 |
| RequirementChecker | WORKING / PACKAGED TESTED | reabre el artefacto final y ejecuta QA semántico y visual |
| UI de artefactos | WORKING / PACKAGED TESTED | tarjetas compactas con Abrir, Mostrar en carpeta, Otra versión, Editar y Convertir |
| Auditoría real de python.org | WORKING / PACKAGED TESTED para este caso | navegación real, scroll real y viewport 390×844; sin métricas inventadas |
| DOCX/PDF final | WORKING / PACKAGED TESTED | DOCX reabierto; PDF rasterizado y revisado en sus 6 páginas |
| Tolerancia a errores escritos | WORKING / PACKAGED TESTED | errores frecuentes, formatos fonéticos y referencias contextuales cubiertos |
| Tolerancia a error de voz | PARTIAL | se probó la ruta con confianza STT simulada; falta voz real en el equipo del usuario |
| Estilos equivalentes XLSX/PPTX | PARTIAL | M5 sigue funcionando; la semántica avanzada de estilo natural se implementó primero para DOCX |
| Auditoría web autónoma general | PARTIAL | el flujo real de python.org está probado; no se declara generalización universal |
| Privacidad avanzada de evidencia | PARTIAL | metadatos, hash y filtros básicos existen; OCR/redacción automática integral sigue abierta |

Ningún bloque se marca como USER VERIFIED.

## Auditoría web real

Sitio: `https://www.python.org/`

- Vista inicial medida: 1280×720.
- Vista desplazada: `scrollY=650`.
- Vista responsive medida: 390×844.
- No se detectó desbordamiento horizontal en la vista estrecha observada.
- Se registraron estructura, búsqueda etiquetada, navegación, jerarquía de encabezados, imagen/alt y contenido visible.
- Rendimiento Lighthouse, Core Web Vitals, tiempos de red y contraste automatizado se etiquetaron como **no medidos**.

## Validación del entregable

- Capturas reales: 3.
- Hallazgos: 7.
- Recomendaciones: 5.
- DOCX válido: sí.
- PDF válido: sí, 6 páginas A4.
- QA visual: aprobado, 6/6 páginas inspeccionadas.
- QA semántico: aprobado.
- Requisitos incumplidos: 0.

El renderizador canónico basado en LibreOffice no estaba disponible en el equipo. La exportación se hizo mediante Microsoft Word instalado y el PDF se rasterizó con Poppler para inspección visual. Esta sustitución queda registrada, no oculta.

## Rendimiento empaquetado

Fuente: `benchmarks/files-documents-m6-packaged.json`.

| Medida | M5 | M6 | Cambio |
|---|---:|---:|---:|
| RAM idle | 47,383 MiB | 47,578 MiB | +0,195 MiB |
| CPU idle (muestra) | 0,0 % | 0,0 % | 0,0 pp |
| Procesos idle | 1 | 1 | 0 |
| Hilos idle | 9 | 9 | 0 |
| RAM artefactos cargados | 68,691 MiB | 69,094 MiB | +0,403 MiB |
| Herramientas cargadas bajo demanda | 2 | 2 | 0 |

El paquete pesa 114.972.181 bytes en 1.233 archivos, no incluye GGUF ni FFmpeg y dejó cero procesos hijos residuales en ambos casos. Las cifras son muestras de esta ejecución, no garantías para todos los equipos.

## Pruebas

- Suite completa: 199 pruebas aprobadas en 26,435 s.
- Pruebas M6 y regresión relevante: 57 aprobadas.
- Sintaxis JavaScript: aprobada.
- Smoke empaquetado de DOCX, XLSX, PPTX y archivo: aprobado.
- Inicio headless empaquetado: aprobado.

## Rutas de salida

- Entregables: `C:\Users\salda\Downloads\ARCHI-Actividad-Web-M6`
- Build: `C:\Users\salda\Desktop\asistente\dist-files-m6\Archeo32n\Archeo32n.exe`
- Benchmark: `C:\Users\salda\Desktop\asistente\benchmarks\files-documents-m6-packaged.json`
- Validación: `C:\Users\salda\Downloads\ARCHI-Actividad-Web-M6\ARCHI-M6-ACTIVITY-VALIDATION.json`
- Evidencia: `C:\Users\salda\Downloads\ARCHI-Actividad-Web-M6\EVIDENCE-MANIFEST.json`
