# Sanitized legacy entry point

`Archeo32n.py` is a mechanically sanitized recovery copy of the supplied root entry point. The original root file is intentionally excluded from Git because it embeds Firebase private credential material. Its immutable original remains in the supplied `asistente.zip`, whose SHA-256 is recorded in `docs/RECOVERY_REPORT.md`.

The sanitized copy replaces only the `FIREBASE_KEY_DICT` assignment with `None`; it is evidence for recovery and must not be treated as a production-ready entry point.

