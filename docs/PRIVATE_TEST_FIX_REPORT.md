# Private test fix report

Date: 2026-09-15. `USER VERIFIED = false`.

## Completed locally

- CREATE vs FIND routing has a dedicated `create_vs_find_artifact_intent` regression. New Word, PDF, presentation, web and Python requests enter artifact creation rather than `DocumentResolver`; multi-artifact execution continues safe subtasks after an isolated failure.
- UI service labels and states in Cloud, Extensions and Updates are localized for all 12 interface locales. Critical Personalization, Accessibility, Privacy and authorized-voice safety copy also has locale-specific coverage instead of falling back to Spanish. Unconfigured update/signature/cloud states are honest. ARCHEON is transliterated for Chinese, Japanese, Korean, Russian, Arabic and Hindi, and Arabic switches to RTL.
- The voice dialog was widened, bounded to the viewport, given stable scrolling and sticky header/save controls. Speaker profiles support multiple authorized voices; raw enrollment audio is discarded and the encrypted acoustic signature is protected locally.
- Wake/STT/TTS real-provider benchmark passed: microphone release true, Vosk recognized the deterministic phrase, model released true, Windows SAPI completed, full cycle completed and audio released.
- Ten-second real ambient wake-word check: 0 detections, 0 rejected candidates, 0 errors. This is not enough to claim a false-negative rate.
- Plugins remain fail-closed with trusted Ed25519 publisher verification, known-permission allowlist, explicit grants, startup re-verification, lifecycle cleanup and package integrity checks.
- Updates report `NOT CONFIGURED` when a signed provider is absent; no update is simulated.

## Auth and mailer truth

Local/provider-contract tests cover registration validation, 8-digit signup OTP, login/session restore, 8-digit recovery, TOTP challenge/verification input, logout, DPAPI, RLS migration structure and online/offline sync behavior. The linked Supabase project was inactive/unreachable during this run, Docker was unavailable for a local stack, and no controlled mailbox/account was supplied. Therefore remote registration, OTP, login, recovery, MFA, RLS and online sync are `BLOCKED EXTERNALLY`, not PASS.

Mailer code/templates can be structurally validated locally, but domain, SPF, DKIM, DMARC, provider API key, hook secret and inbox delivery are missing. Mailer E2E is `BLOCKED EXTERNALLY`.

## Manual voice checklist

1. In a quiet room, enroll the owner with three natural phrases; verify the app lists only an encrypted profile and no recordings.
2. Say the wake name 20 times at normal distance. Record accepted and missed trials.
3. Play unrelated speech/TV for 10 minutes without saying the wake name. Record accidental activations.
4. Enable “authorized voices only”; repeat 10 owner trials, 10 unauthorized-person trials and 10 playback/recording trials.
5. Add a second authorized person, repeat both sets, then disable/remove that profile and confirm it stops authorizing.
6. Test “ignore silently” and “show local notice”, pause/resume phrases, microphone disconnect/reconnect, STT, TTS interruption and app shutdown.

Do not mark Voice fully user-verified until the measured false-positive and false-negative results are recorded.
