"""Exercise 50 deterministic multi-turn context relevance sequences."""

from __future__ import annotations

import json
from pathlib import Path

from archeon.context import ContextRelevanceGate


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "benchmarks" / "M10_CONTEXT_RELEVANCE_MATRIX.json"


SWITCHES = (
    ("reproduce Julieta de Latin Mafia", "cómo digo hola en inglés"),
    ("pon música de Julieta Venegas", "dime la última noticia de GTA 6"),
    ("resume este PDF", "reproduce Imagine de John Lennon"),
    ("mira mi pantalla", "explícame qué es DNS"),
    ("corrige este proyecto Python", "qué tiempo hace hoy"),
    ("traduce esta frase al inglés", "abre la configuración"),
    ("dime las noticias de Ecuador", "reproduce música tranquila"),
    ("abre Steam en mi PC", "resume el documento"),
    ("lee este archivo Word", "debug this JavaScript project"),
    ("play a jazz song", "what is a database index"),
    ("resume this document", "latest GTA 6 news"),
    ("open the settings window", "translate good morning"),
    ("noticias actuales de tecnología", "abre Steam"),
    ("cómo se dice gracias en francés", "lee este PDF"),
    ("reproduce una canción", "corrige mi proyecto"),
    ("debug this code", "play Imagine"),
    ("mira la ventana activa", "noticias de Ecuador hoy"),
    ("read this file", "open the settings"),
    ("play music", "summarize this document"),
    ("latest news today", "explain DNS"),
)

SAME_TOPIC = (
    ("cómo se dice buenos días en inglés", "ahora traduce buenas noches"),
    ("reproduce Imagine", "pon música de John Lennon"),
    ("resume este PDF", "lee la segunda página del documento"),
    ("mira mi pantalla", "haz clic en la ventana"),
    ("corrige este proyecto", "debug this code"),
    ("últimas noticias de Ecuador", "qué pasó ayer en Ecuador"),
    ("translate hello", "english practice please"),
    ("play jazz music", "reproduce otra canción"),
    ("open settings", "click the settings window"),
    ("read this document", "summarize the PDF"),
)

REFERENCES = (
    ("reproduce Julieta de Latin Mafia", "pon otra de ella"),
    ("reproduce una versión en vivo", "esa versión no"),
    ("pon la canción anterior", "sube eso"),
    ("play Imagine", "play another by her"),
    ("abre Steam", "cierra esa"),
    ("lee este PDF", "resume ese"),
    ("mira la pantalla", "haz clic en esa"),
    ("corrige el proyecto", "continúa con eso"),
    ("translate this paragraph", "do that one too"),
    ("latest GTA news", "tell me more about that one"),
)

EXPLICIT = (
    ("reproduce música", "otra cosa, explícame DNS"),
    ("lee el PDF", "cambiando de tema, abre Steam"),
    ("mira la pantalla", "dejando eso, traduce hola"),
    ("debug this code", "new topic, play jazz"),
    ("latest news", "changing topic, summarize this document"),
    ("translate hello", "otra cosa, noticias de Ecuador"),
    ("open settings", "cambiando de tema, qué es Python"),
    ("reproduce Imagine", "dejando eso, mira la ventana"),
    ("resume este PDF", "otra cosa, corrige mi proyecto"),
    ("play music", "anyway, explain DNS"),
)


def main() -> int:
    gate = ContextRelevanceGate(); rows = []
    for expected, cases in ((False, SWITCHES), (True, SAME_TOPIC), (True, REFERENCES), (False, EXPLICIT)):
        for history, current in cases:
            messages = ({"role": "user", "content": history}, {"role": "assistant", "content": "respuesta"})
            included = bool(gate.filter(current, messages))
            rows.append({"history": history, "current": current, "expected_context": expected, "included": included, "pass": included is expected})
    payload = {"schema_version": 1, "count": len(rows), "passed": sum(row["pass"] for row in rows), "ok": all(row["pass"] for row in rows), "rows": rows}
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": payload["ok"], "count": payload["count"], "passed": payload["passed"], "report": str(OUTPUT)}, ensure_ascii=False))
    return 0 if payload["ok"] and len(rows) >= 50 else 1


if __name__ == "__main__":
    raise SystemExit(main())
