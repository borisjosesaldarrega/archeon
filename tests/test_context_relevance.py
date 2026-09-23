from archeon.context import ContextRelevanceGate


def _turn(user: str, assistant: str = "respuesta") -> list[dict[str, str]]:
    return [{"role": "user", "content": user}, {"role": "assistant", "content": assistant}]


def test_media_does_not_contaminate_translation() -> None:
    gate = ContextRelevanceGate()
    history = _turn("reproduce Julieta de Latin Mafia", "No encontré esa canción")
    assert gate.filter("cómo digo hola mi nombre es Boris en inglés", history) == ()


def test_media_reference_keeps_context() -> None:
    gate = ContextRelevanceGate()
    history = _turn("reproduce Julieta de Latin Mafia")
    assert gate.filter("pon otra de ella", history) == tuple(history)


def test_explicit_topic_switch_resets_context() -> None:
    gate = ContextRelevanceGate()
    history = _turn("resume este PDF")
    assert gate.filter("otra cosa, dime qué es DNS", history) == ()


def test_same_topic_keeps_context() -> None:
    gate = ContextRelevanceGate()
    history = _turn("cómo se dice buenos días en inglés")
    assert gate.filter("ahora traduce buenas noches", history) == tuple(history)
