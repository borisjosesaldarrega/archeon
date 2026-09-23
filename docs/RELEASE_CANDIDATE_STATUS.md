# Release candidate status

Candidate: `10.0.0rc1`  
Executable: `dist-release-candidate/ARCHEON/ARCHEON.exe`  
Executable SHA-256: `91AA26C5C88C92CDEA2956E33761A037AF32AB98FCB4F5DA0E5EED15534341BB`

## Gates

- Full suite: PASS — 389 tests and 128 subtests.
- JavaScript and locale JSON syntax: PASS.
- Source headless startup/shutdown: PASS, startup 10.522 ms.
- Packaged headless: PASS, 45.45 MiB sampled working set.
- Packaged normal UI: PASS, 90.27 MiB sampled working set.
- Packaged Ghost: PASS, 69.78 MiB sampled working set.
- Packaged artifact smoke: PASS; DOCX, XLSX, 6-slide PPTX and ZIP verified.
- Package scan: PASS; 1,271 files, 127.44 MiB, 0 secret-value matches, 0 secret-named files, 0 absolute workspace paths, 0 legacy imports.
- Shutdown: PASS; 0 residual candidate processes.
- Real voice provider benchmark: PASS locally; user acoustic verification still required.
- Auth/Mailer remote E2E: BLOCKED EXTERNALLY.
- Trusted publisher production key: NOT CONFIGURED.
- Signed update backend: NOT CONFIGURED.

This build is suitable for private user testing, but not a public release. `USER VERIFIED = false`.
