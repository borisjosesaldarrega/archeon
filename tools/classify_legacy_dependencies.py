"""Generate the auditable Phase 1 classification of the recovered environment."""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "LEGACY_DEPENDENCIES.csv"
TARGET = ROOT / "docs" / "LEGACY_DEPENDENCIES_CLASSIFIED.csv"

REQUIRED = {
    "bottle", "cffi", "clr_loader", "proxy_tools", "pycparser", "pythonnet",
    "pywebview", "typing_extensions",
}
OPTIONAL = {
    "beautifulsoup4", "certifi", "charset-normalizer", "comtypes", "cryptography",
    "idna", "numpy", "oauthlib", "pillow", "psutil", "pyjwt", "pyperclip",
    "pypiwin32", "pywin32", "pywin32-ctypes", "python-dotenv", "requests",
    "requests-oauthlib", "sounddevice", "soupsieve", "speechrecognition", "urllib3",
    "websockets", "wikipedia", "yt-dlp",
}
REPLACE = {
    "cachecontrol", "cachetools", "firebase_admin", "flask", "flask-cors",
    "google-ai-generativelanguage", "google-api-core", "google-api-python-client",
    "google-auth", "google-auth-httplib2", "google-cloud-core", "google-cloud-firestore",
    "google-cloud-storage", "google-crc32c", "google-generativeai",
    "google-resumable-media", "googleapis-common-protos", "grpcio", "grpcio-status",
    "httplib2", "markupsafe", "jinja2", "pyaudio", "pyautogui", "pygetwindow",
    "pymsgbox", "pyqt5", "pyqt5_sip", "pyqt5-qt5", "pyqtwebengine",
    "pyqtwebengine-qt5", "pyrect", "pyscreeze", "pyttsx3", "pytweening",
    "requests-toolbelt", "rsa", "uritemplate", "werkzeug",
}
REMOVE = {
    "altgraph", "babel", "blinker", "colorama", "mouseinfo", "pefile", "pip",
    "pyarmor", "pyarmor.cli.core", "pyinstaller", "pyinstaller-hooks-contrib",
    "setuptools", "tqdm",
}

RATIONALE = {
    "REQUIRED": "Used by the selected minimal WebView2 desktop runtime (direct or transitive).",
    "OPTIONAL": "Install only with the owning feature or development/benchmark extra.",
    "REPLACE": "Legacy coupling or heavy stack; replace with the new provider/stdlib architecture.",
    "REMOVE": "Packaging, cosmetic, obsolete, or development-only residue; exclude from production.",
    "UNKNOWN": "No verified Phase 1 owner; keep excluded until a feature and measurement justify it.",
}


def classify(name: str) -> str:
    normalized = name.lower()
    for status, group in (
        ("REQUIRED", REQUIRED),
        ("OPTIONAL", OPTIONAL),
        ("REPLACE", REPLACE),
        ("REMOVE", REMOVE),
    ):
        if normalized in group:
            return status
    return "UNKNOWN"


def main() -> None:
    with SOURCE.open(newline="", encoding="utf-8-sig") as source:
        rows = list(csv.DictReader(source))
    output = []
    for row in rows:
        status = classify(row["name"])
        output.append({**row, "classification": status, "rationale": RATIONALE[status]})
    with TARGET.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(
            target, fieldnames=("name", "version", "classification", "rationale")
        )
        writer.writeheader()
        writer.writerows(output)
    counts = {status: sum(row["classification"] == status for row in output) for status in RATIONALE}
    print(f"classified={len(output)} counts={counts}")


if __name__ == "__main__":
    main()
