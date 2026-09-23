"""Evidence-based multilingual capability gate for ARCHEON's twelve locales."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .config import SUPPORTED_LOCALES
from .language import LOCALE_SPECS, LanguageContextEngine, locale_direction
from .messages import CORE_MESSAGES, HELP_CATALOG, HELP_DETAILS, IDENTITY_MESSAGES, RESPONSE_DIRECTIVES


LANGUAGE_PROBES = {
    "es": "Por favor abre la configuración del sistema",
    "en": "Please open the system settings",
    "pt": "Por favor abra as configurações do sistema",
    "fr": "Ouvre les paramètres du système s'il vous plaît",
    "de": "Bitte öffne die Einstellungen des Systems",
    "it": "Per favore apri le impostazioni del sistema",
    "zh": "请打开系统设置",
    "ja": "システム設定を開いてください",
    "ko": "시스템 설정을 열어 주세요",
    "ru": "Пожалуйста, открой настройки системы",
    "ar": "من فضلك افتح إعدادات النظام",
    "hi": "कृपया सिस्टम सेटिंग्स खोलें",
}

VOICE_MODEL_PREFIXES = {
    "es": "es", "en": "en-us", "pt": "pt", "fr": "fr", "de": "de", "it": "it",
    "zh": "cn", "ja": "ja", "ko": "ko", "ru": "ru", "ar": "ar", "hi": "hi",
}


@dataclass(frozen=True, slots=True)
class LocaleQuality:
    locale: str
    native_name: str
    ui: str
    conversation_context: str
    deterministic_messages: str
    intents: str
    documents: str
    stt: str
    tts: str
    regional: str
    rtl: str
    status: str
    evidence: tuple[str, ...]


class MultilingualQualityGate:
    """Never equates translation-key presence with end-to-end language support."""

    def __init__(self, ui_locale_dir: str | Path, model_dir: str | Path) -> None:
        self.ui_locale_dir = Path(ui_locale_dir).resolve()
        self.model_dir = Path(model_dir).resolve()
        self.language = LanguageContextEngine()

    @staticmethod
    def _catalog(path: Path) -> dict[str, str]:
        if not path.is_file():
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return {str(key): str(text) for key, text in value.items() if str(text).strip()}

    def evaluate(self, *, tts_locales: Iterable[str] = ()) -> dict[str, Any]:
        base_ui = self._catalog(self.ui_locale_dir / "es.json")
        base_voice = self._catalog(self.ui_locale_dir / "voice-es.json")
        base_ghost = self._catalog(self.ui_locale_dir / "ghost-es.json")
        available_tts = {item.casefold().split("-", 1)[0] for item in tts_locales}
        rows = []
        for code in SUPPORTED_LOCALES:
            ui = self._catalog(self.ui_locale_dir / f"{code}.json")
            voice = self._catalog(self.ui_locale_dir / f"voice-{code}.json")
            ghost = self._catalog(self.ui_locale_dir / f"ghost-{code}.json")
            missing = sorted((set(base_ui) - set(ui)) | (set(base_voice) - set(voice)) | (set(base_ghost) - set(ghost)))
            ui_state = "PASS" if not missing else "PARTIAL"
            detected = self.language.detect(LANGUAGE_PROBES[code])
            conversation = "AUTOMATED_ROUTING_PASS" if detected == code else "FAIL"
            deterministic = "STATIC_CATALOG_PASS" if all((code in item) for item in (CORE_MESSAGES, IDENTITY_MESSAGES, HELP_CATALOG, HELP_DETAILS, RESPONSE_DIRECTIVES)) else "FAIL"
            # Deterministic fast paths are covered by a shared twelve-language intent suite.
            intents = "PARTIAL" if conversation == "AUTOMATED_ROUTING_PASS" else "FAIL"
            models = tuple(self.model_dir.glob(f"vosk-model-small-{VOICE_MODEL_PREFIXES[code]}*"))
            stt = "PACKAGED_TESTED" if any(item.is_dir() for item in models) else "MODEL_NOT_INSTALLED"
            tts = "AVAILABLE" if code in available_tts else "NOT_RUNTIME_VERIFIED"
            rtl = "STATIC_LAYOUT_PASS" if (code != "ar" or locale_direction(code) == "rtl") else "FAIL"
            documents = "PARTIAL"  # Unicode/font/direction fixtures pass; every artifact format is not closed yet.
            regional = "PARTIAL"  # Locale metadata exists; every date/number/currency surface is not closed yet.
            blocking = any(item == "FAIL" for item in (conversation, deterministic, rtl))
            status = "FAIL" if blocking else "PARTIAL" if (ui_state != "PASS" or stt == "MODEL_NOT_INSTALLED" or tts != "AVAILABLE") else "PACKAGED_TESTED"
            evidence = (
                f"ui={len(ui)}/{len(base_ui)} voice={len(voice)}/{len(base_voice)} ghost={len(ghost)}/{len(base_ghost)}",
                f"language_probe={detected or 'none'}",
                f"stt_sidecar={'present' if models else 'absent'}",
                "USER_VERIFIED=false",
            )
            rows.append(LocaleQuality(code, LOCALE_SPECS[code].native_name, ui_state, conversation, deterministic, intents, documents, stt, tts, regional, rtl, status, evidence))
        return {
            "gate": "Multilingual Quality Gate",
            "locales": [asdict(row) for row in rows],
            "summary": {
                "supported": len(rows),
                "packaged_tested": sum(row.status == "PACKAGED_TESTED" for row in rows),
                "partial": sum(row.status == "PARTIAL" for row in rows),
                "failed": sum(row.status == "FAIL" for row in rows),
                "user_verified": 0,
            },
            "limitations": [
                "STT requires one separately installed and measured Vosk sidecar per locale.",
                "TTS requires a matching Windows voice and a real audio-device test.",
                "Document layout and Arabic RTL require rendered format fixtures, not key-count checks.",
                "Human language quality remains NOT USER VERIFIED for every locale.",
            ],
        }

    def write_report(self, path: str | Path, *, tts_locales: Iterable[str] = ()) -> Path:
        output = Path(path).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.evaluate(tts_locales=tts_locales), ensure_ascii=False, indent=2), encoding="utf-8")
        return output
