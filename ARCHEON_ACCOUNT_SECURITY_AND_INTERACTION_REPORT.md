# ARCHEON — Informe de seguridad, interacción y rendimiento

Fecha de la iteración: 2026-08-22  
Proyecto: `C:\Users\salda\Desktop\asistente`

## Estado ejecutivo

La capa actual está implementada sobre el Core modular nuevo, sin recuperar dependencias ni procesos monolíticos del ejecutable legado. Wake Word, personalización, Launcher, Ghost radial y sincronización Supabase funcionan mediante carga bajo demanda y no agregan polling permanente.

La validación integral de cuenta con correo real y la ida/vuelta autenticada de sincronización permanecen pendientes por decisión explícita: se harán al final con una dirección controlada por el propietario.

## Arquitectura y rendimiento

- Core: un proceso, servidor UI loopback, EventBus acotado y módulos administrados por ciclo de vida.
- Voz: captura WASAPI compartida; VAD siempre ligero; Vosk se carga solo después de una frase candidata y se descarga al terminar.
- Ghost: ventana Tk nativa independiente, sin WebView2 ni frontend en segundo plano.
- Launcher: detección limitada a menús Inicio, claves de desinstalación, manifiestos Steam y Epic; caché de 15 minutos; sin escaneo completo de discos.
- Personalización: archivos locales transmitidos por streaming acotado; soporte HTTP Range para video; video pausado cuando la ventana deja de estar visible.
- Sync: llamadas PostgREST explícitas al iniciar una cuenta, guardar preferencias o pulsar sincronización; cola offline atómica; sin worker ni polling.
- Secretos: contraseña nunca persistida; refresh token protegido con DPAPI; access token solo en memoria y nunca retornado por la API UI.

## Wake Word

- Activación local por `Archeon`, con aliases fonéticos iniciales y comparación tolerante a acentos.
- Nombre configurable hasta 24 caracteres.
- El nombre se refleja en configuración, estado principal y Ghost nativo.
- `Archeon + comando` entrega el resto directamente al pipeline.
- La separación `wake name + comando` conserva correctamente texto en español, inglés y francés.
- Los 12 idiomas configurables resuelven un modelo Vosk lateral por idioma cuando existe; no hay escaneo fuera de `models`. El instalador incluye únicamente español y declara los demás como no disponibles hasta instalar su modelo, evitando cientos de MB obligatorios.
- STT completo no permanece cargado en reposo ni después de una escucha.
- El primer soak descubrió retención nativa de Vosk al cargarlo repetidamente en el Core (1,1 GB privados en ~20 minutos). La transcripción se aisló en un worker efímero y ese resultado defectuoso fue descartado.
- Verificación de recuperación: tres ciclos completos de Vosk dejaron 0,0 MB de crecimiento privado, 0,012 MB RSS, modelo descargado y cero procesos hijos residuales.
- Soak prolongado real: 2,0005 horas, 0,765% CPU promedio (7,0% pico puntual), 38,76 MB RSS promedio y 44,52 MB pico.
- Memoria privada durante el soak: 24,44 MB promedio, 25,46 MB pico y +2,22 MB netos incluyendo la inicialización; no reapareció la fuga nativa.
- Ambiente real: 843 candidatos rechazados, 0 activaciones falsas y 0 errores del monitor.
- Cálculo formal de falsos negativos: pendiente de una serie hablada y etiquetada por una persona; el soak ambiental mide detecciones y candidatos rechazados.

## Personalización

- Tema claro, oscuro y sistema.
- Fondo predeterminado, imagen y video.
- Ajuste, desenfoque y opacidad de fondo.
- Logo personalizado.
- Reloj visible, fecha, segundos y formato 24 horas.
- Escala UI, escala de texto, alto contraste y movimiento reducido.
- Persistencia local atómica.
- Opciones portables sincronizables por cuenta; rutas locales conservadas en el ámbito del dispositivo.

## Launcher

- Aplicaciones y juegos reales.
- Favoritos, recientes y aliases de voz.
- Resolución multilingüe de `abre`, `abrir`, `open`, `launch`, `ouvre` y `ouvrir`.
- Apertura mediante `ShellExecuteW`; solo se registra como reciente cuando Windows acepta la operación.
- Prueba real: Character Map fue detectado, abierto, verificado por PID y cerrado sin residuo.
- Favoritos y aliases se sincronizan por nombre normalizado y tipo, nunca por rutas o IDs locales.

## Ghost radial

- Menú circular nativo alrededor del orbe.
- Reposo: ARCHEON completo, escucha, Apps, Juegos, Favoritos y configuración.
- Música: anterior, reproducir/pausar, siguiente, volumen, selector musical y ARCHEON completo.
- Submenús nativos para Apps, Juegos y Favoritos.
- Un solo proceso; sin WebView2.

## Sincronización Supabase

Portables por cuenta:

- idioma y contexto lingüístico;
- tema y accesibilidad;
- wake name y preferencias del asistente;
- opciones visuales que no son rutas;
- reloj y apariencia del Ghost;
- favoritos y aliases del Launcher.

Específicos del dispositivo:

- micrófono, altavoz y voz instalada;
- posición del orbe;
- rutas de fondo y logo;
- opciones de arranque y rendimiento local.

Seguridad y conflicto:

- tablas `account_settings` y `device_settings` protegidas por RLS y propiedad `auth.uid()`;
- resolución determinista por versión y fecha;
- upsert por usuario y por usuario/dispositivo;
- refresh de JWT interno sin invalidar el token local de la UI;
- acceso sin JWT rechazado por Supabase con código Postgres `42501`;
- cambios offline guardados en `sync-pending.json` mediante reemplazo atómico.

## Benchmarks finales

Mediciones de `benchmarks/latest.json`; RAM RSS suma procesos y puede duplicar páginas compartidas de WebView2. La memoria privada es la referencia más conservadora para compromiso real.

| Escenario | Inicio Core | UI lista | RAM RSS prom. | RAM privada prom. | CPU prom. | GPU muestra | Procesos |
|---|---:|---:|---:|---:|---:|---:|---:|
| Core idle | 14.5 ms | — | 30.5 MB | 18.7 MB | 0.00% | 0.00% | 1 |
| Full UI | 17.8 ms | 909.8 ms | 494.3 MB | 312.8 MB | 0.19% | 0.00% | 7 |
| Ghost | 10.1 ms | — | 40.7 MB | 23.3 MB | 0.00% | 0.00% | 1 |
| Ghost radial | 19.8 ms | — | 44.2 MB | 25.9 MB | 0.00% | 0.00% | 1 |
| Launcher | 8.6 ms | — | 30.6 MB | 18.6 MB | 0.00% | 0.00% | 1 |
| Música + UI | 9.0 ms | 874.8 ms | 508.7 MB | 320.9 MB | 1.18% | 0.00% | 7 |
| Fondo imagen | 16.7 ms | 837.6 ms | 495.4 MB | 341.0 MB | 0.77% | 0.00% | 7 |
| Fondo video | 16.6 ms | 854.0 ms | 551.3 MB | 348.5 MB | 5.84% | 5.07% | 8 |

Launcher real: 138 elementos en 24.9 ms.  
Escucha silenciosa: 41.9 MB RAM, 2.09% CPU promedio; terminó con `no_speech_detected` y descargó audio/modelo.  
Wake Word, 2 horas: 38,76 MB RSS promedio, 24,44 MB privados, 0,765% CPU, 0 falsos despertares, 843 candidatos rechazados y 0 errores.  
Sync offline: cola escrita en 533.9 ms y 351 bytes. Endpoint Supabase/RLS: 849.8 ms; acceso sin JWT rechazado.

## Resultado de pruebas

- Suite automatizada: 49/49 pruebas correctas.
- Compilación Python: correcta.
- Verificación de diff: sin errores de whitespace.
- RLS legado: 12/12 pruebas de seguridad correctas en la fase de migración.
- Respaldo lógico Supabase verificado con roles, esquema y datos.

## Empaquetado final

- Archivo principal compatible: `dist-dir\Archeo32n\Archeo32n.exe`.
- El archivo principal compone el Core nuevo y llama a configuración, Auth, Sync, audio, voz, Launcher, media, plugins y UI.
- Instalador v10: `Instalador_Final\Instalar_Archeon_v10.0_Final.exe`, 59.10 MB.
- Aplicación instalada: 155.76 MB, incluidos 57.49 MB del modelo acústico español.
- Distribución interna por carpeta: evita la extracción temporal de PyInstaller y su proceso padre. Frente al prototipo one-file, el ciclo empaquetado de 5 s bajó de 7.80 s a 6.06 s y el Core quedó en un único proceso real.
- El ejecutable lanzador ocupa 6.30 MB; sus bibliotecas se instalan lateralmente y se comparten sin descompresión en cada arranque.
- El modelo acústico se mantiene como recurso lateral; no se carga ni se copia temporalmente en cada arranque.
- Pillow conserva únicamente PNG/JPEG/WebP y raster básico; se excluyeron AVIF, FreeType, gestión de color y cálculo matricial no utilizados (9,88 MB menos instalados).
- ZIP redundante del modelo eliminado: ahorro de 39.8 MB en el workspace.
- Smoke test del EXE: Core y WebView abren/cierran con código 0.
- Instalador probado de extremo a extremo en una ruta temporal: instalación 0, Core instalado 0, Vosk efímero descargado al terminar, desinstalación 0 y carpeta eliminada.
- Smoke test de recursos: voz disponible; modelo instalado pero no cargado; backend de audio no cargado en reposo.
- Instancia única: un segundo lanzamiento sale en 290 ms y no crea procesos duplicados.
- El instalador usa el mismo mutex `Local\ARCHEON.Core.SingleInstance`; una instalación silenciosa mientras el Core estaba activo fue bloqueada (código 1, sin escribir archivos).
- SHA-256 lanzador: `4F6674E34A38299B077EEE7B8E1E00BEF779DB8E93BEF8C66F434227DFB143F8`.
- SHA-256 instalador: `D3170D9E9DD7222B588D763EB52CC1D752E409EA66F2282F70F9A88CB79E216E`.

## Riesgos y decisiones conscientes

- WebView2 domina la memoria de Full UI. Intentar desactivar GPU provocó cierre inestable y fue descartado. Ghost es el modo recomendado para reposo y equipos modestos.
- El fondo de video tiene un coste real; se carga solo si se selecciona y se pausa al ocultar/minimizar la página.
- No se sincronizan rutas como preferencias portables. Los medios no se suben automáticamente para evitar transferencias pesadas y exposición innecesaria.
- No se declara una tasa de falsos negativos sin ensayos hablados etiquetados.

## Validaciones pendientes con intervención del propietario

1. Registro con un correo controlado.
2. Pulsar el enlace de confirmación recibido.
3. Volver a ARCHEON e iniciar sesión.
4. Ejecutar sincronización, cambiar una preferencia, sincronizar nuevamente y validar restauración.
5. Pronunciar una serie etiquetada de activaciones correctas/incorrectas para calcular falsos positivos y falsos negativos reales.

## Bloques futuros conservados, no iniciados

- ARCHEON Local AI.
- Visión.
- Control autorizado del PC.
- Navegador.
- Dispositivos.

Estos bloques siguen fuera de alcance hasta cerrar las validaciones pendientes de esta capa.
