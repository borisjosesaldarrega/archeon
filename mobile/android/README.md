# ARCHEON Mobile Android

Cliente Android privado para validar el port móvil en hardware real. Integra la interfaz móvil con permisos del SO, Android Keystore, notificaciones, selector de archivos, lifecycle, botón Atrás y share intents.

La build privada actual se conecta al runtime local de ARCHEON mediante `adb reverse`; no es todavía una distribución independiente.

## Build de prueba

1. Crear `local.properties` con `sdk.dir` y `archeon.devToken` temporal.
2. Ejecutar Gradle 8.9 con `:app:assembleDebug`.
3. Instalar `app/build/outputs/apk/debug/app-debug.apk` mediante ADB.

Nunca se debe confirmar `local.properties`, tokens, sesiones ni claves de dispositivo.
