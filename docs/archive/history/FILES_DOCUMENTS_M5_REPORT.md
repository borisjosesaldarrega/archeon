# ARCHEON Files / Documents M5

Date: 2026-08-25  
Status: WORKING / PACKAGED TESTED / NOT USER VERIFIED

## Implemented

- Streaming attachment storage remains bounded to 1 MiB read chunks and ten files per request.
- Compact UI chips now show icon, name, extension/type, human-readable size and remove action.
- Drag/drop, clipboard file paste, multi-select and bounded three-at-a-time upload use the existing request bar.
- `FileTypeRouter` separates Document, Data, Presentation, Image, Code and Archive parser routes without reading file bodies into the UI.
- Multiple attached documents are read independently with bounded output and can be supplied together to one grounded ARCHI request.
- `DocumentResolver` supports exact/fuzzy name, extension, Downloads, yesterday, recency, active-window title, Explorer selection when available, current/previous TaskContext and explicit disambiguation choices.
- Ambiguous candidates are returned to the user; no first-result selection is performed.
- `TaskContext` stores a bounded document history/current page and persists device-local references atomically without document bodies.
- Textual files are read incrementally and capped before prompt use; PDF page/page-range extraction remains lazy and bounded.
- XLSX/PPTX inspection provides bounded sample content rather than loading entire artifacts into a prompt.
- Attached images route to `vision.analyze_file` only when ARCHI Vision is installed; otherwise ARCHEON reports the missing capability instead of guessing.
- Contextual `hazlo/pásalo a Word/PDF` creates verified artifacts from the last grounded document result.
- Artifact PDF text is line-wrapped and section tables are represented without adding FFmpeg or a resident renderer.

## Real academic activity

Output directory:

`C:\Users\salda\Downloads\ARCHI-Actividad-Prueba`

- `Actividad_Planificacion_Optimizacion_Web_ARCHI.docx`
- `Actividad_Planificacion_Optimizacion_Web_ARCHI.pdf`
- `ARCHI-ACTIVITY-VALIDATION.json`

Final verification:

- title present: true
- introduction present: true
- questions answered: 5
- table data rows: 5
- best practices: 6
- practical example present: true
- generic conclusion absent: true
- DOCX valid: true
- PDF valid: true
- PDF pages: 3
- PDF extracted text characters: 7,157

The packaged LibreOffice renderer was unavailable because LibreOffice is not installed. The DOCX was exported by installed Microsoft Word, rasterized with bundled Poppler and all three final page PNGs were inspected at full resolution. The first render exposed an orphan fourth page; the document was corrected and re-rendered before acceptance.

## Regression and package evidence

- Tests: 189 passed + 3 subtests.
- Build: `dist-files-m5\Archeo32n\Archeo32n.exe`
- Package bytes: 114,943,281.
- GGUF bundled: 0.
- FFmpeg/avcodec bundled: 0.
- Idle: 47.383 MiB RSS, 0.0% sampled CPU, 1 process, 9 threads.
- Artifact load: 68.691 MiB RSS, 0.0% sampled CPU, 1 process, 9 threads.
- Startup: 10.660 ms.
- Lazy loaded tools before/after artifact task: 0 / 2.
- Residual child processes: 0.

## Honest status

The implemented flows and packaged smoke are verified by automated/local execution. Drag/drop, clipboard paste, voice phrasing, Explorer selection, ARCHI Vision on the user's installed model, Word/PDF follow-up UX and visual appearance in the user's normal ARCHEON window remain NOT USER VERIFIED until Boris tests them.
