# ARCHEON — M10 final closure report

Fecha: 2026-08-28.

```text
M10 CLOSED = NO
READY FOR CONSOLIDATION = NO
```

La implementación M10 no presenta fallos automatizados conocidos, pero el criterio estricto de cierre no se cumple todavía: la calidad multilingüe continúa parcial en 11 idiomas y la accesibilidad no tiene validación humana completa. No se convierten en `WORKING` por existir únicamente claves o interfaces.

## Completed / WORKING

- Core modular, portabilidad y rutas administradas.
- UI, Settings con efectos, personalización y layout persistente a nivel contractual.
- MediaSession, controles, pausa/reanudación, volumen y vinilo; regresión STT musical corregida.
- Launcher, Ghost y radial empaquetados.
- Planner/AgentTask, Browser y Computer Use con pruebas reales.
- Files/Documents, ArtifactEngine, Programming Intelligence.
- ARCHI Vision y ARCHI Image con lazy load/unload y cero procesos residuales en sus benchmarks.
- Operational Learning con source/scope/confidence/last_verified/forget/reset y sin cambiar pesos.
- KnowledgeRouter para conocimiento estable, actual y de alto riesgo.
- Motor de plugins local: manifiesto, hash, firma, versión, compatibilidad, instalación, update, enable/disable/remove y aislamiento.
- UpdateManager real y fail-closed; la UI declara honestamente que no hay backend.
- Paneles de Cloud, Extensiones y Actualizaciones respaldados por estados reales.
- Paquete M10 nuevo: 117.30 MiB, sin modelos, FFmpeg ni credenciales empaquetadas.

## Partial

- Auth/MFA/Sync: contratos y pruebas locales pasan; faltan pruebas reales con la cuenta/inbox final.
- Wake Word, voz y TTS: automatizados/empaquetados, todavía no USER VERIFIED en el equipo del usuario.
- Accesibilidad: controles existen; falta auditoría humana completa y tecnologías de asistencia.
- Idiomas: 12 locales y cambio mixto funcionan en pruebas; 11/12 carecen de STT instalado y cobertura end-to-end profunda. Los intents, documentos y formatos regionales siguen marcados PARTIAL.
- FFmpeg opcional: contrato lazy y benchmark de desarrollo; no hay runtime mínimo aprobado para distribución.
- ARCHEON Cloud: Auth y settings sync existen; el resto son contratos futuros/deferred.

## Blocked externally

- Mailer real: API key del proveedor, dominio verificado, SPF, DKIM, DMARC, sender, hook secret e inbox controlado.
- Remote relay: servidor/credenciales/infraestructura.
- ARCHI Image distribution: revisión final de procedencia/licencia del safetensors consolidado.
- Voces/STT de los otros idiomas: modelos y voces del sistema no están instalados.

## Deferred

- Marketplace de plugins.
- Device pairing, LAN direct, file transfer, remote commands y mobile integration.
- Backend firmado de releases/actualizaciones.

## Known regressions

- Ninguna regresión automatizada abierta.
- La regresión de seguimiento musical por STT quedó corregida y cubierta; se inmovilizaron ambos resolvers en la prueba para evitar un falso verde por acceso real a YouTube.
- Persisten validaciones manuales visuales/voz, que no se presentan como regresiones resueltas por el usuario.

## Tests

- Suite final: **354 passed**, **108 subtests passed**, 1 warning intencional por fixture ZIP duplicado de seguridad.
- Regresiones enfocadas: **150 passed**, **3 subtests passed**.
- Package smokes: headless, normal, Ghost y radial: exit code 0.
- Computer Use real: YouTube, Notepad, Explorer, cancelación y fallback visual: PASS.

## Performance

- Core: 16.858 ms startup; 40.477 MiB RSS; 0 % CPU idle.
- Ghost: 57.684 MiB; 1.71 % CPU promedio en la muestra.
- Ghost radial: 60.465 MiB; 0.5 % CPU promedio.
- Full UI steady de referencia: 457.344 MiB RSS / 0.31 % CPU; WebView2 explica la mayoría.
- ARCHI warm TTFT mediano: 1,588.836 ms; 7.565 tok/s.
- ARCHI Image: CPU 4,947 ms promedio; Vulkan 2,845 ms promedio; cero residuos.
- Vision CPU: 18,991 ms, 2,846.883 MiB peak, unload 216.552 ms, cero residuos.
- Evidencia completa: `benchmarks/M10_FINAL_PERFORMANCE_BASELINE.json`.

## Storage

- `%LOCALAPPDATA%\ARCHEON`: ~5.15 GiB; modelos ~4.77 GiB y runtimes ~323 MiB.
- Repeticiones build/dist/runtime/tmp: ~3.34 GiB y son candidatos a limpieza posterior.
- Backups: ~863 MiB; requieren política de retención.
- No se borró M1–M9 ni ningún dato.
- Inventario: `docs/PRE_CONSOLIDATION_STORAGE_INVENTORY.md`.

## Security

- Runtime source sin claves privadas ni rutas absolutas de desarrollo.
- Paquete final sin `.env`, Firebase JSON, GGUF o FFmpeg.
- Plugins y updates fallan cerrados sin firma confiable.
- Browser/terminal/files/Computer Use pasan por scopes y permisos.
- Advertencia: existen `.env` y credenciales Firebase legacy ignoradas dentro del workspace. No están empaquetadas, pero deben revocarse/retirarse durante Consolidation.
- `archeon_updater.py` legacy y helpers con rutas de usuario son REMOVE CANDIDATE.
- Evidencia: `benchmarks/M10_FINAL_SECURITY_AUDIT.json`.

## USER VERIFIED

- Portability: VERIFIED / PACKAGED TESTED según baseline aceptado.
- El resto de las capacidades no se elevó a USER VERIFIED sin una aceptación manual explícita.

## USER verification still needed

- registro → OTP de 8 dígitos → login, recovery, MFA y sync online/offline;
- voz, Wake Word, TTS, micrófono y altavoz reales;
- UI, personalización, Ghost/radial, Launcher y música;
- Computer Use con las tres frases de milestone;
- calidad visual de ARCHI Image;
- revisión lingüística por hablantes competentes o un servicio de QA externo.

## Gate

El siguiente gate puede cambiar a `M10 CLOSED = YES` cuando los 11 idiomas restantes dejen de estar parcialmente implementados (o se reduzca formalmente el alcance de idiomas) y se cierre la auditoría de accesibilidad. Las credenciales/infraestructura externas y las pruebas USER VERIFIED pueden seguir pendientes conforme al criterio del usuario.
