# ARCHEON Mobile Android

Cliente Android independiente de ARCHEON. La interfaz viaja dentro del APK y usa el backend autenticado de ARCHEON para ARCHI, Vision y Cloud; no requiere que el PC esté encendido. Integra permisos del SO, Android Keystore, notificaciones, selector de archivos, lifecycle, botón Atrás y share intents.

## Build de prueba

1. Configurar `sdk.dir` en `local.properties`. El URL y la clave publicable de Supabase se leen de `.env.local` (o de `archeon.supabaseUrl` y `archeon.supabasePublishableKey`).
2. Ejecutar Gradle 8.9 con `:app:assembleDebug`.
3. Instalar `app/build/outputs/apk/debug/app-debug.apk` mediante ADB.

La clave incluida en el APK es únicamente la clave publicable protegida por RLS. Nunca se deben confirmar `local.properties`, tokens, sesiones, claves de dispositivo ni secretos del proveedor de IA.
