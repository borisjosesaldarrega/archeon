"""Lightweight semantic conversation state for text and post-STT input.

The interpreter proposes meaning.  It never grants permissions or executes a
tool.  Domain knowledge is registry data so capabilities can extend the engine
without adding product-specific branches to the resolver.
"""

from __future__ import annotations

import math
import re
import time
import unicodedata
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from threading import RLock
from typing import Any, Iterable, Mapping, Sequence


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).casefold())
    return " ".join("".join(char for char in normalized if not unicodedata.combining(char)).split())


def _words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#]{2,}", _fold(value)))


class EvidenceStatus(StrEnum):
    KNOWN = "KNOWN"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class ThreadResolution(StrEnum):
    CONTINUE_ACTIVE_THREAD = "CONTINUE_ACTIVE_THREAD"
    SWITCH_TO_RECENT_THREAD = "SWITCH_TO_RECENT_THREAD"
    CREATE_NEW_THREAD = "CREATE_NEW_THREAD"
    RELATE_MULTIPLE_THREADS = "RELATE_MULTIPLE_THREADS"


@dataclass(frozen=True, slots=True)
class EntityDefinition:
    entity_id: str
    entity_type: str
    name: str
    aliases: tuple[str, ...]
    topic_hints: tuple[str, ...] = ()
    compatible_intents: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IntentDefinition:
    name: str
    patterns: tuple[str, ...]
    compatible_entity_types: tuple[str, ...] = ()
    sensitive: bool = False
    implicit_active_target: bool = False


@dataclass(frozen=True, slots=True)
class TopicDefinition:
    topic_id: str
    name: str
    concepts: tuple[str, ...]
    compatible_intents: tuple[str, ...] = ()


class ContextRegistry:
    """Registrable vocabulary shared by the deterministic interpretation layer."""

    def __init__(self) -> None:
        self.entities: dict[str, EntityDefinition] = {}
        self.intents: dict[str, IntentDefinition] = {}
        self.topics: dict[str, TopicDefinition] = {}
        self.normalizations: dict[str, str] = {}

    def register_entity(self, definition: EntityDefinition) -> None:
        self.entities[definition.entity_id] = definition

    def register_intent(self, definition: IntentDefinition) -> None:
        self.intents[definition.name] = definition

    def register_topic(self, definition: TopicDefinition) -> None:
        self.topics[definition.topic_id] = definition

    def register_normalization(self, heard: str, canonical: str) -> None:
        self.normalizations[_fold(heard)] = canonical

    @classmethod
    def defaults(cls) -> "ContextRegistry":
        registry = cls()
        topics = (
            TopicDefinition("minecraft_server", "Servidor Minecraft", ("minecraft", "server", "servidor", "java", "puerto", "25565"), ("diagnose", "inspect_version", "check_network_port", "restart")),
            TopicDefinition("media_playback", "Música y reproducción", ("musica", "cancion", "artista", "reproduccion", "volumen"), ("open", "close", "play_media", "pause_media", "adjust_volume")),
            TopicDefinition("system_hardware", "Sistema y hardware", ("ram", "cpu", "gpu", "disco", "espacio", "temperatura", "memoria"), ("inspect_system", "close")),
            TopicDefinition("web_browsing", "Navegación web", ("navegador", "web", "pagina", "youtube"), ("open", "close", "navigate")),
            TopicDefinition("applications", "Aplicaciones", ("aplicacion", "programa", "proceso"), ("open", "close", "restart")),
            TopicDefinition("network_security", "Red y seguridad", ("red", "ip", "puerto", "router", "firewall", "cortafuegos"), ("check_network_port", "diagnose")),
            TopicDefinition("documents", "Archivos y documentos", ("archivo", "documento", "pdf", "carpeta", "proyecto"), ("open", "close", "find", "delete")),
            TopicDefinition("programming", "Programación", ("codigo", "programar", "proyecto", "python", "java", "c++"), ("open", "inspect_version", "create")),
        )
        for topic in topics:
            registry.register_topic(topic)
        entities = (
            EntityDefinition("app.spotify", "application", "Spotify", ("spotify", "spoti", "espotifai"), ("media_playback",), ("open", "close", "play_media")),
            EntityDefinition("app.discord", "application", "Discord", ("discord",), ("applications",), ("open", "close")),
            EntityDefinition("app.chrome", "application", "Chrome", ("chrome", "google chrome"), ("web_browsing", "applications"), ("open", "close", "navigate")),
            EntityDefinition("app.vscode", "application", "Visual Studio Code", ("visual studio code", "vscode", "el editor donde programamos"), ("programming", "applications"), ("open", "close")),
            EntityDefinition("service.minecraft.local", "server", "Minecraft Server", ("minecraft", "server de minecraft", "servidor de minecraft", "server", "servidor"), ("minecraft_server",), ("diagnose", "restart", "check_network_port"), {"port": 25565}),
            EntityDefinition("runtime.java", "runtime", "Java", ("java",), ("minecraft_server", "programming"), ("inspect_version", "diagnose")),
            EntityDefinition("network.firewall", "security_control", "Firewall", ("firewall", "cortafuegos"), ("network_security",), ("diagnose",)),
            EntityDefinition("media.song.numb", "song", "Numb", ("numb",), ("media_playback",), ("play_media",)),
            EntityDefinition("media.artist.linkin_park", "artist", "Linkin Park", ("linkin park", "linkin", "likin par", "likin"), ("media_playback",), ("play_media",)),
            EntityDefinition("website.youtube", "website", "YouTube", ("youtube", "you tube"), ("web_browsing",), ("open", "navigate")),
            EntityDefinition("hardware.ram", "hardware", "RAM", ("ram", "memoria ram"), ("system_hardware",), ("inspect_system",)),
            EntityDefinition("hardware.cpu", "hardware", "CPU", ("cpu", "procesador"), ("system_hardware",), ("inspect_system",)),
            EntityDefinition("hardware.gpu", "hardware", "GPU", ("gpu", "tarjeta grafica"), ("system_hardware",), ("inspect_system",)),
            EntityDefinition("hardware.disk", "hardware", "Disco", ("disco", "almacenamiento"), ("system_hardware",), ("inspect_system",)),
        )
        for entity in entities:
            registry.register_entity(entity)
        intents = (
            IntentDefinition("open", (r"\b(?:abre|inicia|ejecuta|lanza)\b",), ("application", "website", "file", "project")),
            IntentDefinition("close", (r"\b(?:cierra|cerralo|cierralo|terminalo)\b",), ("application", "process", "file"), True),
            IntentDefinition("play_media", (r"\b(?:pon|reproduce|toca|musica|cancion)\b",), ("application", "song", "artist")),
            IntentDefinition("pause_media", (r"\b(?:pausa|pausala|deten la musica)\b",), ("application", "song"), False, True),
            IntentDefinition("adjust_volume", (r"\b(?:sube|subele|baja|bajale|bajito|volumen|mas bajo|mas alto)\b",), ("application", "song", "artist"), False, True),
            IntentDefinition("inspect_version", (r"\b(?:que version|version tengo|version)\b",), ("runtime", "application")),
            IntentDefinition("check_network_port", (r"\b(?:puerto|port)\b", r"\b\d{2,5}\b"), ("server", "network_port")),
            IntentDefinition("inspect_system", (r"\b(?:cuanto|cuanta|temperatura|uso|espacio)\b",), ("hardware",)),
            IntentDefinition("diagnose", (r"\b(?:no inicia|no abre|no funciona|falla|problema|esta mal|ta mal|bloqueando)\b",), ("server", "runtime", "security_control", "application")),
            IntentDefinition("restart", (r"\b(?:reinicia|reinicialo|reiniciar)\b",), ("server", "application"), True),
            IntentDefinition("delete", (r"\b(?:borra|elimina|formatea|desinstala)\b",), ("file", "application"), True),
            IntentDefinition("find", (r"\b(?:busca|encuentra|localiza)\b",), ("file", "project")),
            IntentDefinition("create", (r"\b(?:crea|genera|programa)\b",), ("file", "project")),
        )
        for intent in intents:
            registry.register_intent(intent)
        for heard, canonical in {
            "spoti": "Spotify", "espotifai": "Spotify", "likin par": "Linkin Park",
            "likin": "Linkin Park", "cansion": "canción", "ta mal": "está mal",
        }.items():
            registry.register_normalization(heard, canonical)
        return registry


@dataclass(frozen=True, slots=True)
class ContextEntity:
    entity_id: str
    entity_type: str
    name: str
    aliases: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    status: EvidenceStatus = EvidenceStatus.KNOWN
    confidence: float = 1.0
    source: str = "current_message"
    position: int = 0

    @property
    def kind(self) -> str:  # compatibility with earlier internal callers
        return self.entity_type

    def public(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


@dataclass(frozen=True, slots=True)
class ContextFact:
    key: str
    value: Any
    status: EvidenceStatus
    confidence: float
    source: str

    def public(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


@dataclass(slots=True)
class TopicThread:
    topic_id: str
    topic_name: str
    topic_summary: str = ""
    entities: list[ContextEntity] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    relevant_facts: list[ContextFact] = field(default_factory=list)
    pending_actions: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    last_active_turn: int = 0
    last_active_at: float = field(default_factory=time.time)
    activation_score: float = 0.0
    suspended: bool = False
    related_threads: list[str] = field(default_factory=list)

    def remember(self, text: str, intent: str, entities: Iterable[ContextEntity], turn: int) -> None:
        self.messages = [*self.messages[-11:], text[:600]]
        if intent and intent != "respond":
            self.intents = [*self.intents[-7:], intent]
        merged = {item.entity_id: item for item in self.entities}
        for entity in entities:
            previous = merged.get(entity.entity_id)
            if previous is None or previous.status != EvidenceStatus.KNOWN or entity.status == EvidenceStatus.KNOWN:
                merged[entity.entity_id] = entity
        self.entities = list(merged.values())[-24:]
        self.last_active_turn = turn
        self.last_active_at = time.time()
        self.suspended = False
        names = ", ".join(item.name for item in self.entities[-7:])
        recent = "; ".join(self.messages[-3:])
        self.topic_summary = f"{self.topic_name}: {recent}"[:750] + (f". Entidades: {names}" if names else "")

    def public(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "topic_name": self.topic_name,
            "topic_summary": self.topic_summary,
            "entities": [item.public() for item in self.entities],
            "intents": list(self.intents),
            "relevant_facts": [item.public() for item in self.relevant_facts],
            "pending_actions": list(self.pending_actions),
            "last_active_turn": self.last_active_turn,
            "activation_score": round(self.activation_score, 3),
            "suspended": self.suspended,
            "related_threads": list(self.related_threads),
        }


@dataclass(slots=True)
class ConversationState:
    conversation_id: str
    active_thread: str | None = None
    threads: dict[str, TopicThread] = field(default_factory=dict)
    recent_threads: list[str] = field(default_factory=list)
    active_entities: list[ContextEntity] = field(default_factory=list)
    unresolved_references: list[str] = field(default_factory=list)
    recent_actions: list[str] = field(default_factory=list)
    turn: int = 0


@dataclass(frozen=True, slots=True)
class ContextInterpretation:
    raw_input: str
    normalized_input: str
    interpreted_request: str
    intent: Mapping[str, Any]
    topic: Mapping[str, Any]
    entities: tuple[ContextEntity, ...]
    references: tuple[Mapping[str, Any], ...]
    related_topics: tuple[str, ...]
    context_sources: tuple[str, ...]
    confidence: float
    requires_confirmation: bool
    requires_clarification: bool
    resolution: ThreadResolution
    facts: tuple[ContextFact, ...] = ()

    @property
    def clarification_required(self) -> bool:
        return self.requires_clarification

    @property
    def referenced_entities(self) -> tuple[ContextEntity, ...]:
        return self.entities

    @property
    def context_source(self) -> tuple[str, ...]:
        return self.context_sources

    @property
    def evidence(self) -> str:
        statuses = {fact.status for fact in self.facts}
        return EvidenceStatus.UNKNOWN.value if EvidenceStatus.UNKNOWN in statuses else (
            EvidenceStatus.INFERRED.value if EvidenceStatus.INFERRED in statuses else EvidenceStatus.KNOWN.value
        )

    def public(self) -> dict[str, Any]:
        return {
            "raw_input": self.raw_input,
            "normalized_input": self.normalized_input,
            "interpreted_request": self.interpreted_request,
            "intent": dict(self.intent),
            "topic": dict(self.topic),
            "entities": [item.public() for item in self.entities],
            "references": [dict(item) for item in self.references],
            "related_topics": list(self.related_topics),
            "context_sources": list(self.context_sources),
            "confidence": round(self.confidence, 3),
            "requires_confirmation": self.requires_confirmation,
            "requires_clarification": self.requires_clarification,
            "resolution": self.resolution.value,
            "facts": [item.public() for item in self.facts],
        }


class TopicManager:
    def __init__(self, registry: ContextRegistry) -> None:
        self.registry = registry

    def _topic_signal(self, topic: TopicDefinition, tokens: set[str], entities: Sequence[ContextEntity], intent: str) -> float:
        concepts = set().union(*(_words(value) for value in topic.concepts))
        lexical = len(tokens & concepts) / max(1, min(4, len(tokens)))
        hints = sum(topic.topic_id in self.registry.entities.get(entity.entity_id, EntityDefinition("", "", "", ())).topic_hints for entity in entities)
        compatible = 1.0 if intent in topic.compatible_intents else 0.0
        return lexical * 0.48 + min(1.0, hints / 2) * 0.38 + compatible * 0.14

    def _thread_signal(self, thread: TopicThread, tokens: set[str], entities: Sequence[ContextEntity], intent: str, turn: int, active: bool) -> float:
        topic = self.registry.topics.get(thread.topic_id, TopicDefinition(thread.topic_id, thread.topic_name, ()))
        base = self._topic_signal(topic, tokens, entities, intent)
        thread_tokens = _words(" ".join([thread.topic_summary, *(item.name for item in thread.entities)]))
        lexical = len(tokens & thread_tokens) / max(1, min(4, len(tokens)))
        entity_ids = {item.entity_id for item in entities}
        overlap = len(entity_ids & {item.entity_id for item in thread.entities}) / max(1, len(entity_ids))
        distance = max(0, turn - thread.last_active_turn)
        decay = math.exp(-distance / 8.0)
        intent_bonus = 1.0 if intent in thread.intents[-4:] or intent in topic.compatible_intents else 0.0
        return base * 0.32 + lexical * 0.25 + overlap * 0.24 + decay * 0.08 + intent_bonus * 0.07 + (0.04 if active else 0.0)

    def resolve_thread(
        self,
        text: str,
        entities: Sequence[ContextEntity],
        intent: str,
        state: ConversationState,
    ) -> tuple[str, ThreadResolution, float, tuple[str, ...], dict[str, float]]:
        tokens = _words(text)
        scores: dict[str, float] = {}
        for topic in self.registry.topics.values():
            scores[topic.topic_id] = self._topic_signal(topic, tokens, entities, intent)
        for thread in state.threads.values():
            scores[thread.topic_id] = max(scores.get(thread.topic_id, 0.0), self._thread_signal(
                thread, tokens, entities, intent, state.turn, thread.topic_id == state.active_thread,
            ))
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best_topic, best_score = ranked[0] if ranked else (state.active_thread or "general", 0.0)
        active_score = scores.get(state.active_thread or "", 0.0)
        ambiguous_new_topic = (
            not state.threads and not entities and len(ranked) > 1
            and best_score > 0 and abs(best_score - ranked[1][1]) < 0.025
        )
        if ambiguous_new_topic:
            best_topic, best_score = "general", 0.35
        elif best_score < 0.16 and state.active_thread:
            best_topic, best_score = state.active_thread, max(active_score, 0.42)
        elif best_score < 0.16:
            best_topic, best_score = "general", 0.35
        existing = best_topic in state.threads
        if best_topic == state.active_thread:
            resolution = ThreadResolution.CONTINUE_ACTIVE_THREAD
        elif existing:
            resolution = ThreadResolution.SWITCH_TO_RECENT_THREAD
        else:
            resolution = ThreadResolution.CREATE_NEW_THREAD
        related = tuple(topic for topic, score in ranked[1:4] if score >= 0.43 and score >= best_score * 0.72)
        if related:
            resolution = ThreadResolution.RELATE_MULTIPLE_THREADS
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = max(0.0, best_score - second_score)
        confidence = min(0.99, 0.58 + best_score * 0.42 + margin * 0.22) if best_score >= 0.16 else max(0.35, best_score)
        return best_topic, resolution, confidence, related, scores


class ReferenceResolver:
    _REFERENCE = re.compile(r"\b(?:eso|esto|ese|esa|aquel|aquella|ahi|alli|lo de antes|lo anterior|el anterior|la anterior|coso|vaina|cierralo|cerralo|pausala|reinicialo)\b|\b(?:el|la)\s+(?:primero|primera|segundo|segunda|tercero|tercera)(?=$|[?.!,])|^(?:lo|la)$")
    _ORDINAL = re.compile(r"\b(?:el|la)\s+(primero|primera|segundo|segunda|tercero|tercera)(?=$|[?.!,])")

    def __init__(self, registry: ContextRegistry) -> None:
        self.registry = registry

    def resolve(self, text: str, intent: str, thread: TopicThread | None, state: ConversationState) -> tuple[list[ContextEntity], list[dict[str, Any]], bool]:
        folded = _fold(text)
        if not self._REFERENCE.search(folded):
            return [], [], False
        definition = self.registry.intents.get(intent)
        compatible = set(definition.compatible_entity_types if definition else ())
        candidates: list[ContextEntity] = []
        seen: set[str] = set()
        ordered_threads = ([thread] if thread else []) + [state.threads[key] for key in reversed(state.recent_threads) if key in state.threads and state.threads[key] is not thread]
        for candidate_thread in ordered_threads:
            for entity in candidate_thread.entities:
                if entity.entity_id in seen or (compatible and entity.entity_type not in compatible):
                    continue
                seen.add(entity.entity_id)
                candidates.append(entity)
        ordinal = self._ORDINAL.search(folded)
        selected: ContextEntity | None = None
        reason = "compatible_entity"
        if ordinal:
            index = {"primero": 0, "primera": 0, "segundo": 1, "segunda": 1, "tercero": 2, "tercera": 2}[ordinal.group(1)]
            selected = candidates[index] if index < len(candidates) else None
            reason = "ordinal_reference"
        elif len(candidates) == 1:
            selected = candidates[0]
        elif candidates and thread:
            local_ids = {item.entity_id for item in thread.entities}
            local = [item for item in candidates if item.entity_id in local_ids]
            selected = local[-1] if len(local) == 1 else None
            reason = "active_thread_compatible_entity"
        if not selected:
            return [], [{
                "text": text,
                "status": EvidenceStatus.UNKNOWN.value,
                "confidence": 0.35,
                "candidates": [item.name for item in candidates[:4]],
            }], True
        inferred = ContextEntity(
            selected.entity_id, selected.entity_type, selected.name, selected.aliases,
            selected.attributes, EvidenceStatus.INFERRED, 0.92, reason, selected.position,
        )
        return [inferred], [{"text": text, "entity_id": inferred.entity_id, "status": EvidenceStatus.INFERRED.value, "confidence": 0.92, "source": reason}], False


class SemanticReconstructor:
    """Generic reconstruction by intent and entity type; domain names stay in registry data."""

    def reconstruct(self, normalized: str, intent: str, entities: Sequence[ContextEntity], thread: TopicThread | None) -> tuple[str, tuple[str, ...]]:
        sources: list[str] = ["current_message"]
        by_type: dict[str, list[ContextEntity]] = {}
        for entity in entities:
            by_type.setdefault(entity.entity_type, []).append(entity)
        request = normalized
        target = next(iter(by_type.get("application", ()) or by_type.get("server", ()) or by_type.get("website", ()) or by_type.get("file", ())), None)
        if intent == "open" and target and sum(len(by_type.get(kind, ())) for kind in ("application", "website", "file", "project")) == 1:
            request = f"abre {target.name}"
        elif intent == "close" and target and sum(len(by_type.get(kind, ())) for kind in ("application", "process", "file")) == 1:
            request = f"cierra {target.name}"
        elif intent == "restart" and target:
            request = f"reinicia {target.name}"
        elif intent == "play_media":
            song = next(iter(by_type.get("song", ())), None)
            artist = next(iter(by_type.get("artist", ())), None)
            app = next(iter(by_type.get("application", ())), None)
            if song or artist:
                detail = song.name if song else f"música de {artist.name}"
                request = f"reproduce {detail}" + (f" en {app.name}" if app else "")
        elif intent == "pause_media":
            request = "pausa la reproducción actual"
        elif intent == "adjust_volume":
            direction = "baja" if re.search(r"\b(?:baja|bajale|bajito|mas bajo)\b", _fold(normalized)) else "sube"
            request = f"{direction} un poco el volumen de la reproducción actual"
        elif intent == "inspect_version":
            version_target = next(iter(by_type.get("runtime", ()) or by_type.get("application", ())), None)
            if version_target:
                request = f"consulta la versión de {version_target.name}"
        elif intent == "check_network_port":
            server = next(iter(by_type.get("server", ())), None)
            if server:
                port = server.attributes.get("port")
                request = f"revisa el puerto{f' {port}' if port else ''} de {server.name}"
        if request != normalized:
            sources.append("structured_reconstruction")
        if re.fullmatch(r"(?:desde ayer|desde anoche|hace rato|otra vez|nuevamente)", _fold(normalized)) and thread and thread.messages:
            request = f"{thread.messages[-1].rstrip('.')} {normalized}"
            sources.append("incomplete_continuation")
        return request, tuple(sources)


class ContextInterpreter:
    """Incremental, bounded semantic state for one isolated conversation."""

    def __init__(self, *, conversation_id: str = "desktop-default", max_threads: int = 10, registry: ContextRegistry | None = None) -> None:
        self.registry = registry or ContextRegistry.defaults()
        self.max_threads = max(3, min(20, int(max_threads)))
        self.state = ConversationState(conversation_id=conversation_id)
        self.topic_manager = TopicManager(self.registry)
        self.reference_resolver = ReferenceResolver(self.registry)
        self.reconstructor = SemanticReconstructor()
        self._lock = RLock()

    def _normalize_input(self, text: str) -> str:
        normalized = " ".join(unicodedata.normalize("NFKC", str(text)).strip().split())
        normalized = re.sub(r"%20", " ", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"(?<=[^\W\d_])%(?=[^\W\d_])", " ", normalized)
        normalized = " ".join(normalized.split())
        for heard, canonical in sorted(self.registry.normalizations.items(), key=lambda item: len(item[0]), reverse=True):
            normalized = re.sub(rf"(?<!\w){re.escape(heard)}(?!\w)", canonical, normalized, flags=re.IGNORECASE)
        return normalized

    def _extract_entities(self, text: str) -> list[ContextEntity]:
        folded = _fold(text)
        matches: list[ContextEntity] = []
        occupied: list[tuple[int, int]] = []
        aliases: list[tuple[str, EntityDefinition]] = []
        for definition in self.registry.entities.values():
            aliases.extend((alias, definition) for alias in definition.aliases)
        for alias, definition in sorted(aliases, key=lambda item: len(item[0]), reverse=True):
            found = re.search(rf"(?<!\w){re.escape(_fold(alias))}(?!\w)", folded)
            if not found or any(found.start() < end and found.end() > start for start, end in occupied):
                continue
            exact = _fold(alias) in {_fold(definition.name), *(_fold(value) for value in definition.aliases[:1])}
            matches.append(ContextEntity(
                definition.entity_id, definition.entity_type, definition.name, definition.aliases,
                dict(definition.attributes), EvidenceStatus.KNOWN if exact else EvidenceStatus.INFERRED,
                1.0 if exact else 0.9, "current_message", found.start(),
            ))
            occupied.append((found.start(), found.end()))
        port = re.search(r"\b(?:puerto\s*)?(\d{2,5})\b", folded)
        if port:
            matches.append(ContextEntity(f"network.port.{port.group(1)}", "network_port", f"Port {port.group(1)}", (), {"port": int(port.group(1))}, EvidenceStatus.KNOWN, 1.0, "current_message", port.start()))
        return sorted(matches, key=lambda item: item.position)

    def _detect_intent(self, text: str, entities: Sequence[ContextEntity], thread: TopicThread | None) -> tuple[str, float]:
        folded = _fold(text)
        scored: list[tuple[str, float]] = []
        entity_types = {item.entity_type for item in entities}
        for definition in self.registry.intents.values():
            matches = [match for pattern in definition.patterns if (match := re.search(pattern, folded))]
            if not matches:
                continue
            hits = len(matches)
            compatibility = bool(entity_types & set(definition.compatible_entity_types))
            last_position = max(match.start() for match in matches) / max(1, len(folded))
            scored.append((definition.name, min(1.0, 0.78 + hits * 0.08 + (0.08 if compatibility else 0.0) + last_position * 0.06)))
        if scored:
            return max(scored, key=lambda item: item[1])
        if entities and thread and thread.intents:
            previous = thread.intents[-1]
            definition = self.registry.intents.get(previous)
            if definition and entity_types & set(definition.compatible_entity_types):
                return previous, 0.76
        if thread and thread.intents and re.fullmatch(r"(?:desde ayer|desde anoche|hace rato|otra vez|nuevamente)", folded):
            return thread.intents[-1], 0.88
        return "respond", 0.55

    @staticmethod
    def _seed_entities(items: Iterable[Mapping[str, Any]]) -> list[ContextEntity]:
        result: list[ContextEntity] = []
        for index, item in enumerate(items):
            name = str(item.get("name") or item.get("value") or "").strip()
            if not name:
                continue
            entity_type = str(item.get("entity_type") or item.get("kind") or "entity")
            identifier = str(item.get("entity_id") or f"external.{entity_type}.{_fold(name).replace(' ', '_')}")
            result.append(ContextEntity(identifier, entity_type, name, tuple(item.get("aliases") or ()), dict(item.get("attributes") or {}), EvidenceStatus.KNOWN, 1.0, "system_state", index))
        return result

    def interpret(
        self,
        text: str,
        *,
        normalized_input: str | None = None,
        known_entities: Iterable[Mapping[str, Any]] = (),
    ) -> ContextInterpretation:
        raw = str(text)
        normalized = self._normalize_input(normalized_input if normalized_input is not None else raw)
        with self._lock:
            self.state.turn += 1
            explicit_entities = [*self._seed_entities(known_entities), *self._extract_entities(normalized)]
            active = self.state.threads.get(self.state.active_thread or "")
            intent, intent_confidence = self._detect_intent(normalized, explicit_entities, active)
            topic_id, resolution, topic_confidence, related, scores = self.topic_manager.resolve_thread(normalized, explicit_entities, intent, self.state)
            topic_definition = self.registry.topics.get(topic_id, TopicDefinition(topic_id, topic_id.replace("_", " ").title(), ()))
            thread = self.state.threads.get(topic_id)
            if thread is None:
                thread = TopicThread(topic_id, topic_definition.name)
            resolved_entities, references, unresolved = self.reference_resolver.resolve(normalized, intent, thread, self.state)
            attachment_entities = [item for item in explicit_entities if item.source == "system_state" and item.entity_type == "file"]
            if unresolved and attachment_entities:
                resolved_entities = [
                    ContextEntity(item.entity_id, item.entity_type, item.name, item.aliases, item.attributes, EvidenceStatus.INFERRED, 0.98, "attached_to_request", item.position)
                    for item in attachment_entities
                ]
                references = [
                    {"text": normalized, "entity_id": item.entity_id, "status": EvidenceStatus.INFERRED.value, "confidence": 0.98, "source": "attached_to_request"}
                    for item in resolved_entities
                ]
                unresolved = False
            combined: dict[str, ContextEntity] = {item.entity_id: item for item in [*explicit_entities, *resolved_entities]}
            if intent in {"inspect_version", "check_network_port", "diagnose"}:
                definition = self.registry.intents.get(intent)
                compatible = set(definition.compatible_entity_types if definition else ())
                for item in reversed(thread.entities):
                    if item.entity_type in compatible and item.entity_id not in combined:
                        combined[item.entity_id] = ContextEntity(item.entity_id, item.entity_type, item.name, item.aliases, item.attributes, EvidenceStatus.INFERRED, 0.9, "topic_thread", item.position)
            entities = list(combined.values())
            request, sources = self.reconstructor.reconstruct(normalized, intent, entities, thread)
            if resolution == ThreadResolution.SWITCH_TO_RECENT_THREAD:
                sources = (*sources, "reactivated_thread")
            elif resolution == ThreadResolution.RELATE_MULTIPLE_THREADS:
                sources = (*sources, "related_threads")
            if resolved_entities:
                sources = (*sources, "resolved_reference")
            definition = self.registry.intents.get(intent)
            sensitive = bool(definition and definition.sensitive)
            implicit_active_target = bool(definition and definition.implicit_active_target)
            overall = min(intent_confidence, max(0.35, topic_confidence + 0.2))
            if resolved_entities:
                overall = min(overall, min(item.confidence for item in resolved_entities))
            if unresolved:
                overall = min(overall, 0.42)
            requires_clarification = unresolved and not implicit_active_target and (sensitive or overall < 0.60)
            requires_confirmation = sensitive and (unresolved or overall < 0.60)
            facts = [ContextFact("resolved_topic", topic_id, EvidenceStatus.INFERRED if resolution != ThreadResolution.CONTINUE_ACTIVE_THREAD else EvidenceStatus.KNOWN, max(0.35, topic_confidence), "topic_scores")]
            for item in entities:
                facts.append(ContextFact(f"entity:{item.entity_id}", item.name, item.status, item.confidence, item.source))
            previous = self.state.active_thread
            if previous and previous != topic_id and previous in self.state.threads:
                self.state.threads[previous].suspended = True
            for related_topic in related:
                if related_topic not in thread.related_threads:
                    thread.related_threads.append(related_topic)
            thread.activation_score = topic_confidence
            thread.remember(normalized, intent, entities, self.state.turn)
            self.state.threads[topic_id] = thread
            self.state.active_thread = topic_id
            self.state.recent_threads = [key for key in self.state.recent_threads if key != topic_id] + [topic_id]
            self.state.active_entities = list(thread.entities)
            self.state.recent_actions = [*self.state.recent_actions[-11:], intent]
            self.state.unresolved_references = ([*self.state.unresolved_references[-5:], normalized] if unresolved else [])
            self._trim_threads()
            return ContextInterpretation(
                raw, normalized, request,
                {"name": intent, "confidence": round(intent_confidence, 3)},
                {"id": topic_id, "confidence": round(topic_confidence, 3), "scores": {key: round(value, 3) for key, value in scores.items() if value > 0}},
                tuple(entities), tuple(references), related, tuple(dict.fromkeys(sources)),
                overall, requires_confirmation, requires_clarification, resolution, tuple(facts),
            )

    def _trim_threads(self) -> None:
        while len(self.state.threads) > self.max_threads:
            candidates = [item for key, item in self.state.threads.items() if key != self.state.active_thread]
            if not candidates:
                return
            oldest = min(candidates, key=lambda item: (item.last_active_turn, item.last_active_at))
            self.state.threads.pop(oldest.topic_id, None)
            self.state.recent_threads = [key for key in self.state.recent_threads if key != oldest.topic_id]

    def observe_entities(self, entities: Iterable[Mapping[str, Any]], *, source: str = "tool_result", topic_id: str | None = None) -> None:
        """Add only explicitly structured assistant/tool entities to context."""
        with self._lock:
            target_id = topic_id or self.state.active_thread
            if not target_id or target_id not in self.state.threads:
                return
            seeded = self._seed_entities(entities)
            observed = [ContextEntity(item.entity_id, item.entity_type, item.name, item.aliases, item.attributes, EvidenceStatus.KNOWN, 1.0, source, item.position) for item in seeded]
            thread = self.state.threads[target_id]
            thread.remember("", thread.intents[-1] if thread.intents else "respond", observed, self.state.turn)
            self.state.active_entities = list(thread.entities)

    def clear(self) -> None:
        with self._lock:
            self.state = ConversationState(conversation_id=self.state.conversation_id)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            active = self.state.threads.get(self.state.active_thread or "")
            return {
                "conversation_id": self.state.conversation_id,
                "active_thread": self.state.active_thread,
                "suspended_threads": [key for key, value in self.state.threads.items() if value.suspended],
                "recent_threads": list(reversed(self.state.recent_threads[-8:])),
                "active_entities": [item.public() for item in self.state.active_entities],
                "unresolved_references": list(self.state.unresolved_references),
                "recent_actions": list(self.state.recent_actions[-8:]),
                "conversation_summary": active.topic_summary if active else "",
                "topic_threads": [self.state.threads[key].public() for key in reversed(self.state.recent_threads) if key in self.state.threads],
            }


class ConversationContextManager:
    """Bounded in-memory isolation between chats; no session history is persisted globally."""

    def __init__(self, *, max_conversations: int = 24, registry: ContextRegistry | None = None) -> None:
        self.max_conversations = max(2, int(max_conversations))
        self.registry = registry or ContextRegistry.defaults()
        self._items: OrderedDict[str, ContextInterpreter] = OrderedDict()
        self._lock = RLock()

    def for_conversation(self, conversation_id: str) -> ContextInterpreter:
        key = str(conversation_id or "desktop-default")[:160]
        with self._lock:
            interpreter = self._items.pop(key, None)
            if interpreter is None:
                interpreter = ContextInterpreter(conversation_id=key, registry=self.registry)
            self._items[key] = interpreter
            while len(self._items) > self.max_conversations:
                self._items.popitem(last=False)
            return interpreter

    def snapshot(self, conversation_id: str) -> dict[str, Any]:
        return self.for_conversation(conversation_id).snapshot()
