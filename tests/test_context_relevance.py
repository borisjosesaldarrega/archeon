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


def test_device_action_does_not_replace_research_topic() -> None:
    gate = ContextRelevanceGate()
    history = [
        *_turn("sabes quien es Alan Turing", "Alan Turing fue un matemático británico"),
        *_turn("Bodoque abre Discord", "Envié la orden a Bodoque"),
    ]
    selected = gate.filter("sabes algo más sobre Alan, algún dato curioso", history)
    assert tuple(history[:2]) == selected


def test_new_image_request_cuts_previous_research_context() -> None:
    gate = ContextRelevanceGate()
    history = _turn("sabes quien es Alan Turing", "Alan Turing fue un matemático británico")
    assert gate.filter("créame una imagen de un dinosaurio", history) == ()
