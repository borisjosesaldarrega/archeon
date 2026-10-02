from __future__ import annotations

from archeon.context import (
    ContextInterpreter,
    ConversationContextManager,
    EvidenceStatus,
    ThreadResolution,
)


def run(interpreter: ContextInterpreter, *messages: str):
    result = None
    for message in messages:
        result = interpreter.interpret(message)
    assert result is not None
    return result


def test_keeps_raw_normalized_and_interpreted_separate() -> None:
    result = ContextInterpreter().interpret("archi pon la de likin q taba antes")
    assert result.raw_input == "archi pon la de likin q taba antes"
    assert "Linkin Park" in result.normalized_input
    assert result.interpreted_request != result.raw_input
    assert result.intent["name"] == "play_media"


def test_contaminated_keyboard_input_is_only_cleaned_outside_raw_diagnostics() -> None:
    result = ContextInterpreter().interpret("mi%server%de%minecraft%no%inicia")
    assert result.raw_input == "mi%server%de%minecraft%no%inicia"
    assert result.normalized_input == "mi server de minecraft no inicia"
    assert "%" not in result.interpreted_request


def test_immediate_reference_uses_compatible_application() -> None:
    result = run(ContextInterpreter(), "abre spotify", "ciérralo")
    assert result.interpreted_request == "cierra Spotify"
    assert result.references[0]["entity_id"] == "app.spotify"
    assert not result.requires_clarification


def test_ordinal_reference_preserves_mention_order() -> None:
    result = run(ContextInterpreter(), "abre discord y spotify", "cierra el primero")
    assert result.interpreted_request == "cierra Discord"
    assert result.references[0]["source"] == "ordinal_reference"


def test_topic_score_reactivates_minecraft_instead_of_recent_spotify() -> None:
    result = run(
        ContextInterpreter(),
        "el servidor minecraft no inicia",
        "abre spotify",
        "pon música",
        "y el puerto?",
    )
    assert result.topic["id"] == "minecraft_server"
    assert result.resolution in {ThreadResolution.SWITCH_TO_RECENT_THREAD, ThreadResolution.RELATE_MULTIPLE_THREADS}
    assert "Minecraft Server" in result.interpreted_request


def test_long_mixed_conversation_returns_to_java_version() -> None:
    result = run(
        ContextInterpreter(),
        "mi server minecraft no inicia",
        "creo que java ta mal",
        "abre spotify",
        "pon linkin park",
        "más bajo",
        "cuánta ram tengo",
        "y cpu",
        "regresa a minecraft",
        "qué versión tengo",
    )
    assert result.topic["id"] == "minecraft_server"
    assert result.intent["name"] == "inspect_version"
    assert result.interpreted_request == "consulta la versión de Java"


def test_implicit_topic_change_and_return() -> None:
    interpreter = ContextInterpreter()
    run(interpreter, "el servidor sigue sin iniciar", "cuánta RAM tengo?")
    assert interpreter.snapshot()["active_thread"] == "system_hardware"
    result = interpreter.interpret("y el puerto?")
    assert result.topic["id"] == "minecraft_server"


def test_related_topics_are_not_permanently_merged() -> None:
    interpreter = ContextInterpreter()
    run(interpreter, "mi servidor minecraft no inicia")
    result = interpreter.interpret("puede ser que el firewall esté bloqueando minecraft?")
    assert result.topic["id"] == "minecraft_server"
    assert "network_security" in result.related_topics
    snapshot = interpreter.snapshot()
    minecraft = next(item for item in snapshot["topic_threads"] if item["topic_id"] == "minecraft_server")
    assert "network_security" in minecraft["related_threads"]


def test_verb_less_song_continuation_infers_prior_media_action() -> None:
    result = run(ContextInterpreter(), "abre spotify", "pon música", "Numb")
    assert result.intent["name"] == "play_media"
    assert "Numb" in result.interpreted_request


def test_incomplete_temporal_phrase_extends_current_problem() -> None:
    result = run(ContextInterpreter(), "mi servidor minecraft no funciona", "desde ayer")
    assert result.intent["name"] == "diagnose"
    assert result.interpreted_request.endswith("desde ayer")
    assert "incomplete_continuation" in result.context_sources


def test_stt_aliases_are_resolved_after_transcription() -> None:
    result = ContextInterpreter().interpret("abre espotifai y pon la cansion de likin par")
    names = {item.name for item in result.entities}
    assert {"Spotify", "Linkin Park"} <= names
    assert "Spotify" in result.normalized_input
    assert result.intent["name"] == "play_media"


def test_structured_tool_entities_support_later_ordinal_reference() -> None:
    interpreter = ContextInterpreter()
    interpreter.interpret("busca archivos llamados proyecto")
    interpreter.observe_entities(
        [
            {"entity_id": "file.project.v1", "entity_type": "file", "name": "proyecto_v1.zip"},
            {"entity_id": "file.project.final", "entity_type": "file", "name": "proyecto_final.zip"},
            {"entity_id": "file.project.backup", "entity_type": "file", "name": "proyecto_backup.zip"},
        ],
        source="tool_result",
    )
    result = interpreter.interpret("abre el segundo")
    assert result.interpreted_request == "abre proyecto_final.zip"
    assert result.references[0]["entity_id"] == "file.project.final"


def test_unknown_reference_does_not_invent_context() -> None:
    result = ContextInterpreter().interpret("abre eso")
    assert result.references[0]["status"] == EvidenceStatus.UNKNOWN.value
    assert result.requires_clarification
    assert not result.entities


def test_ambiguous_destructive_reference_requires_confirmation() -> None:
    result = run(ContextInterpreter(), "abre discord y spotify", "cierra eso")
    assert result.requires_confirmation
    assert result.requires_clarification
    assert result.references[0]["candidates"] == ["Discord", "Spotify"]


def test_conversation_manager_isolates_session_threads() -> None:
    manager = ConversationContextManager()
    manager.for_conversation("A").interpret("mi server minecraft no inicia")
    result = manager.for_conversation("B").interpret("y el puerto?")
    assert result.topic["id"] != "minecraft_server"
    assert "service.minecraft.local" not in {item.entity_id for item in result.entities}


def test_context_decay_does_not_block_explicit_old_topic_reactivation() -> None:
    interpreter = ContextInterpreter()
    run(interpreter, "mi server minecraft no inicia", "abre spotify", "pon música")
    for _ in range(8):
        interpreter.interpret("más bajo")
    result = interpreter.interpret("regresa a minecraft")
    assert result.topic["id"] == "minecraft_server"
    assert result.resolution == ThreadResolution.SWITCH_TO_RECENT_THREAD


def test_snapshot_is_ready_for_context_inspector() -> None:
    interpreter = ContextInterpreter(conversation_id="abc123")
    run(interpreter, "mi server minecraft no inicia", "abre spotify")
    snapshot = interpreter.snapshot()
    assert snapshot["conversation_id"] == "abc123"
    assert snapshot["active_thread"] == "media_playback"
    assert "minecraft_server" in snapshot["suspended_threads"]
    assert snapshot["topic_threads"]
