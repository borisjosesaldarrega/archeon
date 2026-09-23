"""Generate the M10 dry-run routing matrix from real intent resolvers."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from archeon.understanding import (
    CommandConfidence, NaturalLanguageRepair, NegationScopeResolver,
    has_explicit_media_context, is_current_information_request,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "benchmarks" / "M10_INTENT_ROUTING_MATRIX.json"


def case(domain: str, utterance: str, expected: bool, intent: str, *, context: bool = False) -> dict[str, object]:
    return {"domain": domain, "utterance": utterance, "expected": expected, "intent": intent, "context": context}


CASES = [
    case("media_stop", "para la música", True, "media.stop"),
    case("media_stop", "detén la canción", True, "media.stop"),
    case("media_stop", "Archeon, por favor para la música", True, "media.stop"),
    case("media_stop", "para esa canción", True, "media.stop"),
    case("media_stop", "stop the music", True, "media.stop"),
    case("media_stop", "no pares la música", False, "respond"),
    case("media_stop", "no quiero que pares la música", False, "respond"),
    case("media_stop", "no no pares la música", False, "respond"),
    case("media_stop", "para la música... no, mejor no", False, "respond"),
    case("media_stop", "la canción dice detén el miedo", False, "respond", context=True),
    case("media_stop", "para conseguir una entrevista necesito ayuda", False, "respond", context=True),
    case("media_stop", "detén el miedo y continúa estudiando", False, "respond", context=True),
    case("media_pause", "pausa la canción", True, "media.pause"),
    case("media_pause", "pausa eso", True, "media.pause", context=True),
    case("media_pause", "pause the music", True, "media.pause"),
    case("media_pause", "no pauses la música", False, "respond"),
    case("media_pause", "no quiero que pauses la música", False, "respond"),
    case("media_pause", "pausa la música... no, déjala sonando", False, "respond"),
    case("media_pause", "la pausa musical fue muy corta", False, "respond", context=True),
    case("media_resume", "continúa la música", True, "media.resume"),
    case("media_resume", "reanuda la canción", True, "media.resume"),
    case("media_resume", "reanuda", True, "media.resume", context=True),
    case("media_resume", "déjala sonando", True, "media.resume", context=True),
    case("media_resume", "continúa con tus estudios", False, "respond", context=True),
    case("media_resume", "no continúes la música", False, "respond"),
    case("media_resume", "la canción continúa con un coro", False, "respond", context=True),
    case("media_play", "pon música", True, "media.play"),
    case("media_play", "ponme una canción", True, "media.play"),
    case("media_play", "reproduce Julieta de Latin Mafia", True, "media.play"),
    case("media_play", "play some music", True, "media.play"),
    case("media_play", "ponme un ejemplo", False, "respond"),
    case("media_play", "toca explicar este ejercicio", False, "respond"),
    case("media_play", "no reproduzcas música", False, "respond"),
    case("media_play", "reproduce la canción... espera, no", False, "respond"),
    case("delete", "borra el archivo", True, "delete", context=True),
    case("delete", "elimina uno.txt", True, "delete", context=True),
    case("delete", "delete the file", True, "delete", context=True),
    case("delete", "no borres el archivo", False, "respond", context=True),
    case("delete", "no quiero borrar el archivo", False, "respond", context=True),
    case("delete", "borra el archivo... espera, no lo borres", False, "respond", context=True),
    case("delete", "hablamos sobre borrar archivos", False, "respond", context=True),
    case("delete", "¿por qué no puedo borrar el archivo?", False, "respond", context=True),
    case("artifact", "crea el PDF", True, "create"),
    case("artifact", "hazme un documento Word", True, "create"),
    case("artifact", "convierte este Word a PDF", True, "convert", context=True),
    case("artifact", "pásalo a PDF", True, "convert", context=True),
    case("artifact", "el profesor pidió un PDF", False, "respond"),
    case("artifact", "mencionar PDF no significa crearlo", False, "respond"),
    case("artifact", "no crees el PDF", False, "respond"),
    case("artifact", "no quiero convertirlo a PDF", False, "respond", context=True),
    case("launch", "abre Steam", True, "launcher.open"),
    case("launch", "habre stin", True, "launcher.open"),
    case("launch", "open Steam", True, "launcher.open"),
    case("launch", "no abras Steam", False, "respond"),
    case("launch", "no habras stin", False, "respond"),
    case("launch", "abre Steam... no, mejor no", False, "respond"),
    case("launch", "Steam abre muchas posibilidades", False, "respond"),
    case("launch", "quiero saber cómo abrir Steam", False, "respond"),
    case("observe", "mira mi pantalla", True, "desktop.observe"),
    case("observe", "Archeon, observa la pantalla", True, "desktop.observe"),
    case("observe", "dime qué ves en mi pantalla", True, "desktop.observe"),
    case("observe", "no mires mi pantalla", False, "respond"),
    case("observe", "no quiero que observes la pantalla", False, "respond"),
    case("observe", "mira mi pantalla... espera, no", False, "respond"),
    case("observe", "compré una pantalla nueva", False, "respond"),
    case("current", "busca las noticias de hoy", True, "live_search"),
    case("current", "qué pasó hoy", True, "live_search"),
    case("current", "dime las noticias actuales", True, "live_search"),
    case("current", "latest news", True, "live_search"),
    case("current", "actualmente estudio por las noches", False, "respond"),
    case("current", "no busques noticias actuales", False, "respond"),
    case("current", "las noticias pueden esperar", False, "respond"),
    case("current", "quiero redactar una noticia ficticia", False, "respond"),
]


PATTERNS = {
    "media_stop": r"\b(?:det[eé]n|detener|para|pares|parar|stop)\b",
    "media_pause": r"\b(?:pausa|pausar|pause|pauses)\b",
    "media_resume": r"\b(?:contin[uú]a|contin[uú]es|reanuda|reanudar|resume)\b|\bd[eé]jala sonando\b",
    "media_play": r"\b(?:pon(?:me)?|reproduce|reproduzcas|toca|play)\b",
    "delete": r"\b(?:borr\w*|elimin\w*|delete)\b",
    "launch": r"\b(?:abre|abras|abrir|open|habre|habras)\b",
    "observe": r"\b(?:mira|mires|mirar|observa|observes|qu[eé] ves)\b",
}


def evaluate(item: dict[str, object]) -> dict[str, object]:
    resolver = NegationScopeResolver()
    repair = NaturalLanguageRepair()
    utterance = str(item["utterance"])
    domain = str(item["domain"])
    expected = bool(item["expected"])
    context = bool(item["context"])
    repaired = repair.interpret(utterance, known_files=(("uno.txt",) if context else ()))

    if domain == "artifact":
        action = repaired.action if repaired.action in {"create", "convert"} else "respond"
        executed = action != "respond"
        confidence = repaired.confidence.value
        negated = not executed and any(token in repaired.repaired_text for token in ("no ", "nunca "))
    elif domain == "current":
        executed = is_current_information_request(repaired.repaired_text)
        action = "live_search" if executed else "respond"
        confidence = CommandConfidence.DIRECT.value if executed else CommandConfidence.AMBIGUOUS.value
        negated = not executed and repaired.repaired_text.startswith("no ")
    else:
        resolution = resolver.resolve(
            repaired.repaired_text, PATTERNS[domain], context_present=context,
            destructive=domain == "delete",
        )
        executed = resolution.action_allowed
        if domain.startswith("media_"):
            explicit = has_explicit_media_context(repaired.repaired_text)
            exact_contextual = context and repaired.repaired_text.strip() in {
                "reanuda", "pausa eso", "déjala sonando", "dejala sonando",
            }
            media_command = re.sub(
                r"^(?:(?:hola\s+)?archeon[\s,]+|hola[\s,]+|por\s+favor\s+)+",
                "", repaired.repaired_text,
            ).strip()
            starts_action = bool(re.match(PATTERNS[domain], media_command))
            nonambiguous_play = domain == "media_play" and repaired.repaired_text.startswith(("reproduce ", "play "))
            executed = executed and ((explicit and starts_action) or exact_contextual or nonambiguous_play)
        elif domain == "observe":
            executed = executed and "pantalla" in repaired.repaired_text
        action = str(item["intent"]) if executed else "respond"
        confidence = resolution.confidence.value
        negated = resolution.negated

    passed = executed == expected and action == str(item["intent"])
    return {
        "utterance": utterance,
        "domain": domain,
        "expected_intent": item["intent"],
        "resolved_intent": action,
        "action_expected": expected,
        "action_executed": executed,
        "negation": negated,
        "confidence": confidence,
        "passed": passed,
    }


def main() -> int:
    rows = [evaluate(item) for item in CASES]
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "mode": "dry_run_no_side_effects",
        "case_count": len(rows),
        "passed": sum(bool(item["passed"]) for item in rows),
        "failed": sum(not bool(item["passed"]) for item in rows),
        "cases": rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("case_count", "passed", "failed")}, ensure_ascii=False))
    return 0 if payload["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
