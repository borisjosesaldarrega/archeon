# ARCHEON — informe de estado del proyecto

Fecha: 2026-09-15.

```text
CORE / APP = WORKING
READY FOR PRIVATE USER TEST = YES
READY FOR PUBLIC RELEASE = NO
USER VERIFIED = false
```

## Resumen ejecutivo

ARCHEON ya es una aplicación de escritorio funcional y no una demostración web. El flujo principal, la interfaz WebView/Ghost, el agente, voz, archivos, creación de artefactos, imágenes, presentaciones con elementos visuales, navegación y control de aplicaciones tienen implementación real y cobertura automatizada. Esta revisión cerró fallos concretos del host de plugins y endureció el servidor local y la sesión de autenticación.

No corresponde declarar el proyecto totalmente terminado ni listo para publicación. Quedan credenciales legacy que deben rotarse y retirarse, infraestructura externa no configurada, firma de distribución y comprobaciones humanas en el equipo del usuario.

## Qué tiene y funciona

- Aplicación Windows: UI principal, modo Ghost, radial, configuración persistente, personalización, inicio automático y Launcher.
- Asistente local: enrutamiento de intención, contexto acotado, memoria operativa, planificación, reintentos, cancelación y verificación de resultados.
- Voz: captura, VAD, STT, TTS, palabra de activación, selección de dispositivos y perfiles de voz autorizados. La aceptación acústica sigue pendiente.
- Archivos y documentos: lectura, búsqueda, adjuntos, resolución contextual, Word, PDF, Excel, PowerPoint, texto, Markdown, CSV, HTML y ZIP con validaciones.
- Creación visual: imágenes PNG independientes y presentaciones con imágenes distintas generadas para cada diapositiva; se evita el falso positivo que creaba un PNG extra cuando solo se pedían imágenes dentro del PowerPoint.
- Programación: detección de proyecto/lenguaje, búsqueda y edición controlada, terminal, compilación/pruebas y verificación.
- Browser y Computer Use: observar, guiar y controlar mediante accesibilidad/DOM, con fallback visual y permisos.
- Multimedia: biblioteca local, búsqueda autorizada, controles de reproducción, volumen, carátulas, YouTube visible y decodificación opcional.
- Idiomas: arquitectura y UI para 12 idiomas; español e inglés tienen la cobertura más profunda.
- Actualizaciones: contrato y verificación fail-closed; informa correctamente `NOT CONFIGURED` mientras no exista backend firmado.

## Plugins: qué quedó cerrado

- Inspección `.arx`, límites de tamaño, bloqueo de traversal, symlinks y rutas ZIP duplicadas o ambiguas.
- Manifiesto y entrypoint estrictos, hash del payload, versión mínima, actualización ascendente y firma obligatoria.
- Instalación, enable/disable, update, remove y reactivación de plugins habilitados al iniciar.
- Ejecución en proceso separado tanto desde código como desde el ejecutable empaquetado.
- Handshake de inicio con token aleatorio; si el plugin no confirma su arranque, se detiene y se reporta `plugin_startup_not_verified`.
- El host no genera `.pyc` dentro del payload firmado, por lo que no invalida el plugin después de ejecutarlo.
- Sin verificador de confianza configurado, la instalación y activación fallan cerradas.

Límites reales: la clave pública/lista de editores confiables de producción aún no está configurada, el panel visual solo informa estado y no administra paquetes, y el proceso separado no constituye por sí solo un sandbox del sistema operativo. Los permisos del manifiesto son metadatos; para admitir plugins de terceros no confiables todavía hace falta un broker de capacidades y aislamiento tipo AppContainer. El marketplace continúa diferido.

## Seguridad cerrada en esta revisión

- `/runtime-config.js` ya no entrega tokens sin autorización.
- La UI arranca mediante un loader tokenizado y el recurso se restringe a mismo origen.
- CSP reducida: scripts y conexiones solo desde el servidor local; YouTube queda limitado a frames.
- `Cross-Origin-Resource-Policy: same-origin` en respuestas del servidor local.
- Sesiones persistentes cifradas con DPAPI del usuario de Windows y modo sin interfaz interactiva.
- Mínimo coherente de 10 caracteres para contraseña, incluido el proveedor local de desarrollo.
- Plugins y actualizaciones mantienen política fail-closed cuando falta confianza verificable.
- El paquete generado no contiene archivos `.env`, claves Firebase ni modelos pesados.

## Validación realizada

- Suite completa: **383 passed**, **128 subtests passed**.
- Advertencias: una, esperada, causada por el fixture que construye un ZIP duplicado para comprobar su rechazo.
- Bloque focal de plugins, autenticación y UI: **73 passed**.
- Ejecutable headless empaquetado: exit code 0.
- Host de plugins empaquetado: inicia, confirma el token, queda activo, se detiene y no crea bytecode en el payload.
- Build nuevo: `dist-final-closure-v2/Archeo32n/Archeo32n.exe`.
- Tamaño total del paquete: 117.78 MiB; 1,264 archivos.
- SHA-256 del EXE: `CF6EF23C1A1D140038E5A65ED7FDD1EEBA53239D02CF5824A76FCC96126F062D`.

## Pendientes antes de publicar — prioridad alta

1. Rotar/revocar y después retirar del workspace `.env`, `.env.local`, `firebase_key.json` y `firebase_key copy.json`. Están ignorados por Git y no entraron al paquete, pero su presencia local sigue siendo un riesgo. No se borraron automáticamente para no destruir configuración o credenciales del usuario.
2. Configurar el verificador real de editores de plugins. Hasta entonces el sistema permanece seguro pero no permite instalar plugins de producción.
3. Si se admitirán plugins no confiables, implementar broker de capacidades y sandbox del sistema operativo. Si solo se admitirán plugins firmados por DZKnight, documentar formalmente ese alcance.
4. Firmar el ejecutable/instalador y configurar un backend de releases con manifiestos y artefactos firmados.
5. Completar pruebas reales de Supabase, OTP, recovery, MFA, RLS y sincronización con cuenta e inbox controlados.
6. Configurar mailer: proveedor, dominio, SPF/DKIM/DMARC, remitente y secreto del hook.

## Pendientes de validación del usuario

- Reconocimiento del dueño de la voz, alta/eliminación de voces autorizadas y falsos positivos/negativos en un ambiente real.
- Micrófono, altavoz, Wake Word, STT y TTS de extremo a extremo.
- Revisión visual de UI, Ghost, radial, documentos, imágenes y PowerPoint.
- Computer Use con las aplicaciones concretas del usuario y cierre controlado de procesos.
- Accesibilidad con teclado, lector de pantalla, alto contraste, escalado y movimiento reducido.
- Calidad lingüística profunda de los 11 idiomas distintos del español; depende también de voces y modelos STT instalados.

## Diferido, no presentado como terminado

- Marketplace de plugins.
- Emparejamiento de dispositivos, LAN directa, relay remoto, transferencia de archivos, comandos remotos y aplicación móvil.
- Runtime FFmpeg mínimo firmado para distribución.
- Limpieza y consolidación de módulos legacy (`archeon_updater.py`, `archeon_cloud.py` y pipelines antiguos) después de una revisión de paridad; no se eliminaron para evitar perder comportamiento todavía no migrado.

## Criterio de cierre

El código queda apto para una prueba privada controlada. El gate de publicación requiere cerrar todos los puntos de prioridad alta. `USER VERIFIED` se mantiene en `false` hasta que el usuario ejecute y acepte las pruebas manuales.
