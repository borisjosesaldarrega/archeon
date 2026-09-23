# M10 Mailer Deployment Report

## Actualización 2026-08-27 — OTP y remitente Gmail

- El registro de ARCHEON ya usa confirmación por **código de 8 dígitos** en la
  aplicación; el cliente no consume ni abre enlaces de confirmación.
- La plantilla alojada `Confirm sign up` fue sustituida por una plantilla
  ARCHEON que muestra `{{ .Token }}` y no contiene `{{ .ConfirmationURL }}`.
- Supabase Auth tiene `Confirm email` activo y longitud OTP `8`.
- El formulario exige repetir la contraseña y ambos valores deben coincidir;
  registro e inicio de sesión permiten mostrar/ocultar la contraseña.
- Recuperación ya tiene un flujo local completo y separado: solicitud, código
  de 8 dígitos, contraseña nueva repetida, actualización y cierre de la sesión
  temporal. La plantilla local `recovery.html` no contiene enlaces.
- La normalización impide registrar dos identidades Gmail equivalentes
  (`ej.emplo+tag@gmail.com` y `ejemplo@gmail.com`) y rechaza el catálogo local
  de dominios temporales, incluyendo sus subdominios.
- La migración `202608270001_auth_signup_policy.sql` fue aplicada de forma
  atómica mediante SQL Editor y el hook Postgres `Before User Created` figura
  `Enabled`. Una petición real con dominio temporal devolvió
  `disposable_email_not_allowed`, sin crear usuario ni enviar correo; la
  normalización remota convirtió `Ex.Ample+tag@googlemail.com` en
  `example@gmail.com`. Esta política queda `REMOTE VERIFIED`.
- El repositorio privado `archeon-mailer` contiene una plantilla de registro
  solo-código, logo CID real y envío SMTP por Gmail; sus 7 pruebas pasan. El
  servicio **no está desplegado ni tiene secretos SMTP disponibles localmente**.
  GitHub conserva correctamente las contraseñas fuera del repositorio y no
  permite recuperar el valor de un secreto.
- La plantilla alojada `Reset password` fue sustituida y guardada con el mismo
  diseño ARCHEON basado exclusivamente en `{{ .Token }}`; ya no contiene
  `{{ .ConfirmationURL }}` ni instrucciones para abrir enlaces.
- Por lo anterior, el remitente alojado sigue siendo el SMTP predeterminado de
  Supabase. `ARCHEON <...@gmail.com>` permanece `PENDING CONFIGURATION`, y la
  entrega real a un buzón controlado continúa `NOT USER VERIFIED`.

Esta actualización reemplaza cualquier lectura anterior que implicara que el
remitente Gmail o la verificación completa ya estaban cerrados.

Fecha: 2026-08-26  
Proyecto Supabase: `rcgipowzivogyqbuwzlv`

## Estado ejecutivo

La implementación de correo está desplegada y cerrada hasta el límite que permiten las credenciales y el dominio disponibles. La función se mantiene deliberadamente en modo seguro (`fail closed`) y el Send Email Hook sigue desconectado: activarlo ahora reemplazaría el correo de Supabase por un proveedor que todavía no tiene API key, remitente ni dominio verificado.

```text
Repositorio privado             = DEPLOYED (417a45a)
Edge Function                   = ACTIVE / version 2
12 catálogos × 13 flujos        = IMPLEMENTED
Validación automatizada         = 9 PASS / 168 subtests PASS
Supabase Send Email Hook        = NOT CONFIGURED
Resend                          = NOT CONFIGURED
Entrega a buzón controlado      = NOT CONFIGURED
Mailer                          = PARTIAL (no E2E)
USER VERIFIED                   = false
```

`DEPLOYED` no significa `WORKING`: falta completar la cadena hasta un buzón real y validar los códigos OTP de Auth.

## Despliegue verificado

- Repositorio privado: `borisjosesaldarrega/archeon-mailer`
- Commit desplegado: `417a45a`
- Función: `send-email`
- Endpoint: `https://rcgipowzivogyqbuwzlv.supabase.co/functions/v1/send-email`
- Estado remoto: `ACTIVE`
- Versión remota: `2`
- SHA-256 del bundle: `97a8526c242db0cfb5cfc07205ca80b31d73ecbcf470573ded48a8498af05214`
- `verify_jwt=false`: la autenticación obligatoria es la firma Standard Webhooks, no un JWT de usuario.
- `GET` remoto: `405 method_not_allowed`.
- `POST` sin configuración: `503 email_delivery_failed` (bloqueo seguro; no entrega).

## Arquitectura

```text
Supabase Auth
  → Send Email Hook firmado (pendiente de activar)
  → Supabase Edge Function send-email v2
  → selección de idioma y plantilla
  → Resend HTTPS con Idempotency-Key
  → buzón controlado (pendiente)
```

No se usa SMTP local, servidor residente ni `service_role`. El código valida la firma antes de renderizar o entregar, escapa valores HTML, sanea asuntos, limita el cuerpo a 64 KiB y aplica timeout de 6 segundos al proveedor.

## Idiomas y plantillas

Se implementaron catálogos reales para `es`, `en`, `pt`, `fr`, `de`, `it`, `zh`, `ja`, `ko`, `ru`, `ar` y `hi`.

Cada idioma incluye 13 rutas:

- confirmación/registro (la bienvenida está integrada en este flujo);
- invitación;
- magic link;
- recuperación de contraseña;
- cambio seguro de correo;
- reautenticación/OTP;
- cambio de contraseña, correo y teléfono;
- identidad vinculada/desvinculada;
- MFA añadido/eliminado.

Supabase Send Email Hook no expone un evento separado de bienvenida ni uno de eliminación de cuenta; por eso no se inventaron rutas que el hook nunca emitiría. Cada ruta genera `subject`, HTML responsivo y texto plano. Árabe usa `dir="rtl"`; chino, japonés, coreano e hindi incluyen fallbacks de fuentes de sistema adecuados. La matriz detallada está en `benchmarks/M10_MAILER_LANGUAGE_MATRIX.json`.

La validación actual es estructural/automatizada. No se declara QA visual humano ni entrega real de los 12 idiomas.

## Firma, idempotencia, fallos y logs

- Firma: `standardwebhooks`; firma inválida o ausente se rechaza cuando el secreto está configurado.
- Idempotencia: `webhook-id` + índice del mensaje en `Idempotency-Key`; Resend conserva la protección durante su ventana de idempotencia.
- Cambio doble de correo: se generan destinatarios/enlaces separados con el mapeo de hashes de Supabase.
- Errores cubiertos por código: configuración faltante, firma inválida, payload grande, destinatario inválido, acción/plantilla no soportada, placeholders sin resolver, timeout y rechazo del proveedor.
- Logs permitidos: event ID, plantilla, locale, proveedor, estado y resultado.
- Logs prohibidos: email, OTP, contraseña, token/hash, enlace completo, API key y hook secret.

## Estado de secretos y dominio

Supabase contiene únicamente sus secretos administrados de plataforma. No aparecen todavía los secretos propios del mailer:

```text
RESEND_API_KEY            = MISSING
SEND_EMAIL_HOOK_SECRET    = MISSING
PUBLIC_SITE_URL           = MISSING
ARCHEON_MAIL_FROM         = MISSING
ARCHEON_MAIL_ENV          = MISSING (default seguro: production)
```

```text
Sending domain = NOT CONFIGURED
SPF            = NOT CONFIGURED
DKIM           = NOT CONFIGURED
DMARC          = NOT CONFIGURED
From address   = NOT CONFIGURED
```

`PUBLIC_SITE_URL` debe ser una URL HTTPS pública final; la función rechaza `localhost`, `127.0.0.1` y `::1` en producción.

## E2E real

No se ha enviado ningún correo real. Registro, recuperación, cambio de correo,
notificaciones, entrega, verificación del código y cambio de estado Auth
permanecen `NOT CONFIGURED`. El detalle está en
`benchmarks/M10_MAILER_E2E_VALIDATION.json`.

## Únicas dependencias manuales restantes

1. Crear/usar una cuenta Resend y verificar un dominio remitente.
2. Publicar los DNS indicados por Resend (SPF y DKIM) y una política DMARC apropiada.
3. Crear una API key restringida a envío y definir un remitente real, por ejemplo `ARCHEON <no-reply@dominio-verificado>`.
4. Definir la URL HTTPS pública final de ARCHEON.
5. Introducir directamente —sin pegarlos en chat, Git ni frontend— `RESEND_API_KEY`, `ARCHEON_MAIL_FROM` y `PUBLIC_SITE_URL` como Supabase Secrets.
6. En Authentication → Hooks → Send Email, configurar el endpoint desplegado, generar el secreto, guardar ese mismo valor como `SEND_EMAIL_HOOK_SECRET` y solo entonces activar el hook.
7. Facilitar buzones controlados para las pruebas representativas `es`, `en`, `pt`, `ar`, `ja` y `hi` y dos buzones para cambio de correo.

Después se ejecutará: registro → recepción → confirmación → login; recuperación → nueva contraseña → login; cambio de correo doble; avisos de seguridad; repetición del mismo evento; firmas válida, inválida y ausente. Solo si toda la cadena pasa se marcará `Mailer = WORKING`; `USER VERIFIED` seguirá en `false` hasta la prueba personal de Boris Saldarrega.
