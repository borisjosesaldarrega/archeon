# ARCHI Image — evaluación M9

Fecha de evaluación: 2026-08-25  
Equipo objetivo: AMD Ryzen 5 5600GT, gráficos AMD integrados, memoria compartida.  
Decisión actual: **NOT IMPLEMENTED / COMPONENT NOT INSTALLED**.

No se descargó ningún modelo. No se creó `ARCHI_Image_Test.png`. La existencia de interfaces o pruebas con fixtures no se presenta como generación real.

## Arquitectura implementada

```text
ImageGenerationProvider
├── LocalImageProvider      (sidecar opcional bajo AppPaths.model_dir)
├── RemoteImageProvider     (opt-in; transporte/credenciales inyectados)
└── DisabledImageProvider   (predeterminado honesto)

ModelResourceManager
├── admisión por RAM disponible
├── carga únicamente al generar
├── proceso aislado por solicitud
└── unload completo al finalizar
```

El contrato local usa JSON por entrada estándar, exige un PNG/JPEG real, valida dimensiones y SHA-256, limita tiempo de ejecución y borra salidas inválidas. El runtime y los pesos solo pueden residir en `%LOCALAPPDATA%\ARCHEON\models\archi-image` o en el `AppPaths.model_dir` configurado internamente. No se empaquetan en el EXE.

## Comparación técnica

| Candidato | Tamaño/huella observada | Licencia | CPU Ryzen 5 5600GT | AMD integrada | Calidad general | Diagramas/infografías | Multilingüe | Unload | Veredicto |
|---|---:|---|---|---|---|---|---|---|---|
| SDXL Base 1.0 | familia SDXL de gran huella; base utilizable sola | OpenRAIL++ | posible pero previsiblemente lento | memoria compartida limitada | alta | texto/diagramas no fiables sin composición adicional | prompts no ingleses variables | sí con sidecar | NO DESCARGAR para este equipo |
| SDXL Turbo | pipeline SDXL; artefactos de varios GB | Stability AI Community License | más pasos reducidos, pero huella SDXL | riesgo alto de presión RAM/VRAM | buena para imágenes rápidas | no sustituye un motor de diagramas | variable | sí | NO SELECCIONADO; restricciones/licencia y huella |
| SDXL-Lightning | LoRA de 394 MB, pero necesita base SDXL; UNet ~5.14 GB | OpenRAIL++ | rápido en GPU compatible; CPU no es objetivo principal | ruta Windows requiere validación real | buena | limitada para texto exacto | variable | sí | CANDIDATO DE LABORATORIO, no de producción |
| SD 1.5 + LCM / fine-tune | normalmente menor que SDXL; conversiones dependen del proveedor | licencia por checkpoint | candidato más realista | ONNX/Windows ML u OpenVINO por validar | inferior a SDXL, usable | aún requiere CompositionEngine | requiere traducción/normalización de prompt | sí | MEJOR CANDIDATO FUTURO, sin fuente/hash aprobados aún |
| Servicio remoto oficial | sin pesos locales | depende del proveedor | ligero localmente | N/A | potencialmente alta | depende del API | generalmente buena | inmediato | OPCIONAL; requiere consentimiento, credencial, coste y privacidad |

## Hallazgos que bloquean una descarga responsable

1. SDXL Base y sus aceleradores conservan una huella demasiado alta para compartir con ARCHI textual en un equipo modesto sin medición de presión real.
2. SDXL Turbo usa actualmente la Stability AI Community License: el uso comercial gratuito tiene condiciones y umbral de ingresos; no debe adoptarse silenciosamente como dependencia irreversible.
3. SDXL-Lightning reduce pasos, pero sus LoRA requieren la base SDXL; el repositorio oficial muestra checkpoints UNet de aproximadamente 5.14 GB y LoRA de 394 MB.
4. DirectML continúa soportado, pero Microsoft movió el desarrollo nuevo hacia Windows ML. La ruta AMD futura debe evaluarse con ONNX/Windows ML y un modelo concreto, no suponerse.
5. Las conversiones SD 1.5/LCM comunitarias más pequeñas no aportan por sí solas una cadena oficial completa con hash, licencia del fine-tune y runtime reproducible aprobados.

## Fuentes primarias

- Stability AI, SDXL Base 1.0: https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0
- Licencia OpenRAIL++ de SDXL Base: https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/d5d78e469acad6b8f0534f137610fbee74099480/LICENSE.md
- Stability AI, SDXL Turbo y licencia: https://huggingface.co/stabilityai/sdxl-turbo y https://huggingface.co/stabilityai/sdxl-turbo/blob/ef0d007d296a24f621ab6d376e7055eb6116877b/LICENSE.md
- ByteDance, SDXL-Lightning: https://huggingface.co/ByteDance/SDXL-Lightning
- Microsoft DirectML: https://learn.microsoft.com/windows/ai/directml/dml
- Microsoft Windows AI / Windows ML: https://learn.microsoft.com/windows/ai/

## Próximo paso permitido

Crear un benchmark separado —sin tocar el EXE— de un único candidato SD 1.5/LCM con revisión manual de licencia, fuente oficial o mantenedor verificable, revisión del grafo ONNX, tamaño y SHA-256 fijados. Solo si supera calidad, latencia, RAM pico y memoria post-unload se propondrá la descarga. Hasta entonces `DisabledImageProvider` es el comportamiento correcto.
