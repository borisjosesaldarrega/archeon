# Known limitations

- Real Supabase Auth/RLS/online-sync E2E is blocked while the remote project is inactive and no controlled mailbox/account is available.
- Mail delivery is blocked by missing domain, SPF/DKIM/DMARC, provider API key, hook secret and inbox validation.
- Trusted production plugin publisher keys are not provisioned; arbitrary third-party sandboxing needs a future AppContainer/broker.
- Signed update backend is not configured.
- Wake word, STT/TTS and speaker verification depend on actual microphone, acoustic environment and installed local models/voices; automated tests cannot replace user calibration.
- `USER VERIFIED` remains `false` until the private user completes the manual checklist.
