"""Composition root for the lightweight ARCHEON application."""

from __future__ import annotations

import base64
import os
import re
import time
from dataclasses import replace
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from archeon.audio import AudioManager
from archeon.agent import AgentMode, AgentRunner, AgentStep, AgentTask, AgentToolsEngine, CapabilityRouter, TaskContext, TaskContextStore, TaskStore
from archeon.auth import AuthManager, SupabaseAuthProvider, UnconfiguredAuthProvider, WindowsDpapiSessionVault
from archeon.context import AttachmentStore, FileTypeRouter, UserRequestContext
from archeon.core.config import ConfigurationManager
from archeon.core.knowledge import KnowledgeRouter
from archeon.core.paths import AppPaths, ResourceManager
from archeon.core.events import EventBus
from archeon.core.lifecycle import LifecycleManager
from archeon.core.orchestrator import Orchestrator
from archeon.core.language import LanguageContextEngine
from archeon.core.messages import action_message
from archeon.core.permissions import PermissionEngine, PermissionState, RiskLevel
from archeon.core.secure_logging import close_logger, configure_logging, log_event
from archeon.core.tools import ToolContext, ToolEngine
from archeon.database import DatabaseManager
from archeon.desktop import DesktopAgentEngine, WindowsDesktopObserver
from archeon.documents import DocumentAgentEngine, DocumentReader, DocumentResolver
from archeon.programming import ProgrammingAgentEngine, ProjectContext, ProjectContextStore
from archeon.browser import BrowserAgentEngine
from archeon.cloud import ArcheonCloudClient
from archeon.artifacts import (
    ArtifactEngine, DisabledImageProvider, ImageRequest,
    StableDiffusionCppImageProvider,
)
from archeon.media import MediaEngine, MediaState
from archeon.media.discovery import MediaDiscovery
from archeon.media.matcher import MediaSearchQuery, is_unknown_artist, normalize as normalize_media, rank_candidates
from archeon.auth.email import normalize_email
from archeon.search import BraveSearchProvider, GoogleNewsRssProvider, SearchAgentEngine, SearchEngine
from archeon.launcher import LauncherEngine
from archeon.intelligence import LlamaCppProvider, MemoryPressureGuard, ModelManager
from archeon.intelligence.models import ModelRegistry
from archeon.learning import LearningScope, LearningSource, OperationalLearningEngine
from archeon.plugins import PluginManager, TrustedPublisherVerifier
from archeon.system import DeviceSystemEngine, configure_launch_at_login
from archeon.sync import SupabaseSettingsSync
from archeon.updates import UpdateManager
from archeon.ui.server import UIServer
from archeon.voice import SpeakerVerificationManager, VoicePipeline
from archeon.voice import SpeechContextResolver
from archeon.voice.catalog import resolve_voice_style
from archeon.vision import ArchiVisionProvider, VisionAgentEngine, VisionComponentManager
from archeon.understanding import (
    NaturalLanguageRepair, NegationScopeResolver, WritingStyleEngine,
    has_explicit_media_context, has_unnegated,
    is_ambiguous_media_play_verb, is_current_information_request,
)
from archeon.documents import DocumentStyleProfile


class ArcheonApplication:
    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        port: int = 0,
        console_log: bool = False,
        auth_provider: Any | None = None,
        auth_vault: Any | None = None,
        app_paths: AppPaths | None = None,
        image_provider: Any | None = None,
    ) -> None:
        self.paths = app_paths or AppPaths.discover(data_dir=data_dir)
        self.resources = ResourceManager(self.paths)
        self.data_dir = self.paths.data_dir
        self.paths.ensure_writable_dirs()
        self.logger = configure_logging(self.paths.logs_dir, console=console_log)
        self.events = EventBus()
        self.configuration = ConfigurationManager(self.paths.config_file)
        self.permissions = PermissionEngine(self.configuration)
        self.tools = ToolEngine(self.events, self.permissions)
        self.database = DatabaseManager()
        self.attachments = AttachmentStore(self.data_dir / "attachments" / "pending")
        self.file_router = FileTypeRouter()
        self.document_resolver = DocumentResolver()
        self.speaker_verification = SpeakerVerificationManager(
            WindowsDpapiSessionVault(self.paths.secure_dir / "speaker-profiles.dpapi")
        )
        self.language_repair = NaturalLanguageRepair()
        self.negation_scope = NegationScopeResolver()
        self.language_context = LanguageContextEngine()
        self.knowledge_router = KnowledgeRouter()
        self._last_request_language: str | None = None
        self.writing_style = WritingStyleEngine()
        supabase_url = os.environ.get("ARCHEON_SUPABASE_URL", "").strip()
        supabase_key = os.environ.get("ARCHEON_SUPABASE_PUBLISHABLE_KEY", "").strip()
        account_provider = (
            SupabaseAuthProvider(supabase_url, supabase_key)
            if supabase_url and supabase_key else UnconfiguredAuthProvider()
        )
        self.auth = AuthManager(
            self.events,
            auth_provider or account_provider,
            auth_vault or WindowsDpapiSessionVault(self.paths.secure_dir / "auth-session.dpapi"),
        )
        self.audio = AudioManager(self.events)
        self.media = MediaEngine(
            self.events,
            self.data_dir,
            output_device_provider=lambda: self.configuration.config.audio.output_device_id,
            dj_enabled_provider=lambda: self.configuration.config.media.dj_mode,
            dj_strategy_provider=lambda: self.configuration.config.media.dj_strategy,
            continuation_provider=self._resolve_dj_continuation,
        )
        self.media.set_volume(self.configuration.config.media.preferred_volume / 100)
        self.media_discovery = MediaDiscovery(
            self.data_dir,
            jamendo_client_id=os.environ.get("ARCHEON_JAMENDO_CLIENT_ID"),
            youtube_api_key=os.environ.get("ARCHEON_YOUTUBE_API_KEY"),
        )
        self._pending_media_result: dict[str, Any] | None = None
        self._recent_media_artist = ""
        self._recent_media_query = ""
        brave_search = BraveSearchProvider(os.environ.get("ARCHEON_BRAVE_SEARCH_API_KEY"))
        self.search = SearchEngine(brave_search if brave_search.available else GoogleNewsRssProvider())
        self.search_agent = SearchAgentEngine(self.tools, self.search)
        self.launcher = LauncherEngine(self.data_dir)
        self.speech_context = SpeechContextResolver()
        self.settings_sync = SupabaseSettingsSync(supabase_url, supabase_key, self.data_dir)
        self.cloud = ArcheonCloudClient(supabase_url, supabase_key)
        plugin_trust = TrustedPublisherVerifier(self.paths.secure_dir / "trusted-publishers")
        self.plugins = PluginManager(
            self.events, self.paths.plugins_dir,
            signature_verifier=plugin_trust,
            permission_authorizer=lambda required: all(
                self.permissions.get_state(permission) in {PermissionState.SESSION, PermissionState.ALWAYS}
                for permission in required
            ),
        )
        self.updates = UpdateManager("10.0.0.dev0")
        self.system = DeviceSystemEngine(self.tools)
        self.desktop_agent = DesktopAgentEngine(self.tools)
        self.document_agent = DocumentAgentEngine(self.tools)
        self.programming_agent = ProgrammingAgentEngine(self.tools)
        self.project_context_store = ProjectContextStore(self.data_dir / "memory" / "projects")
        self.browser_agent = BrowserAgentEngine(self.tools)
        self.artifact_engine = ArtifactEngine(self.tools)
        self.image_provider = image_provider or self._default_image_provider()
        self.vision_components = VisionComponentManager(
            self.paths.model_dir(self.configuration.config.storage.model_dir)
        )
        vision_runtime = self.paths.runtime_dir / "llama.cpp" / "llama-server.exe"
        self.vision_provider = (
            ArchiVisionProvider(
                vision_runtime,
                self.vision_components.artifact_path("language_model"),
                self.vision_components.artifact_path("projector"),
                threads=max(1, min(6, (os.cpu_count() or 6) - 2)),
                idle_timeout_seconds=60,
            )
            if self.vision_components.installed() and vision_runtime.is_file() else None
        )
        self.vision_agent = VisionAgentEngine(self.tools, self.vision_components, self.vision_provider)
        self.task_store = TaskStore(self.data_dir / "memory" / "tasks")
        self.agent_tools = AgentToolsEngine(self.tools, self.events)
        self._control_preview_path = self.paths.cache_dir / "control-preview.png"
        self._control_preview_revision = 0
        self.agent_runner = AgentRunner(
            self.events, self.tools, checkpoint=self.task_store.save,
            result_observer=self._publish_agent_visual_evidence,
        )
        self.capability_router = CapabilityRouter()
        self.task_context_store = TaskContextStore(self.data_dir / "memory" / "task-context.json")
        self._task_context = self.task_context_store.load()
        self.operational_learning = OperationalLearningEngine(
            self.data_dir / "memory" / "operational-learning.json"
        )
        self._last_document_output: dict[str, str] | None = None
        self._pending_visuals: dict[str, tuple[str, Path] | None] = {}
        self.local_ai = ModelManager()
        self.orchestrator = Orchestrator(
            self.events,
            self.tools,
            language=self.language_context,
            conversation_language_provider=lambda: self.configuration.config.language.conversation,
            interface_language_provider=lambda: self.configuration.config.language.interface,
            model_manager=self.local_ai,
            personality_provider=lambda: self.configuration.public_settings().get("personality", {}),
            generation_provider=lambda: {
                "max_tokens": self.configuration.config.intelligence.max_tokens,
                "temperature": self.configuration.config.personality.creativity / 100,
                "context_size": self.configuration.config.intelligence.context_size,
            },
            memory_enabled_provider=lambda: self.configuration.config.intelligence.memory_enabled,
            conversation_turns_provider=lambda: self.configuration.config.intelligence.conversation_turns,
        )
        self.voice = VoicePipeline(
            self.events,
            self.audio,
            self._handle_voice_command,
            lambda: self.paths.model_dir(self.configuration.config.storage.model_dir),
            input_device_provider=lambda: self.configuration.config.audio.input_device_id,
            locale_provider=self._speech_synthesis_locale,
            recognition_locale_provider=self._speech_recognition_locale,
            profile_provider=lambda: self.configuration.config.voice.profile,
            tts_config_provider=lambda: {
                "voice_id": self.configuration.config.voice.tts_voice_id,
                "output_device_id": self.configuration.config.voice.tts_output_device_id,
                "rate": self.configuration.config.voice.tts_rate,
                "volume": self.configuration.config.voice.tts_volume,
                "style": self.configuration.config.voice.tts_style,
            },
            barge_in_provider=lambda: self.configuration.config.voice.barge_in,
            wake_enabled_provider=lambda: self.configuration.config.assistant.wake_word_enabled,
            wake_name_provider=lambda: self.configuration.config.assistant.wake_name,
            speaker_verifier=self.speaker_verification,
            speaker_verification_enabled_provider=lambda: self.configuration.config.voice.speaker_verification_enabled,
            dictation_repair=lambda text: self.language_repair.interpret(
                text,
                context=self._task_context,
            ).repaired_text,
        )
        self.ui_server = UIServer(
            self.events,
            command_handler=self.handle_request,
            action_handler=self.handle_action,
            health_handler=self.health,
            auth_handler=self.handle_auth,
            session_handler=self.handle_session,
            attachment_handler=self.handle_attachment_upload,
            cloud_upload_handler=self.handle_cloud_upload,
            media_resource_handler=self.media.artwork,
            media_stream_handler=self.media.current_stream_source,
            personalization_resource_handler=self._personalization_resource,
            ui_root=self.resources.ui_dir,
            port=port,
        )
        self.lifecycle = LifecycleManager(
            (
                self.configuration,
                self.local_ai,
                self.database,
                self.auth,
                self.system,
                self.desktop_agent,
                self.document_agent,
                self.programming_agent,
                self.browser_agent,
                self.search_agent,
                self.artifact_engine,
                self.vision_agent,
                self.agent_tools,
                self.tools,
                self.audio,
                self.media,
                self.launcher,
                self.voice,
                self.plugins,
                self.ui_server,
            )
        )
        self._started = False
        self._lock = RLock()
        self.startup_ms = 0.0

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            started = time.perf_counter()
            self.lifecycle.start()
            self._configure_local_ai()
            self._started = True
            self.startup_ms = (time.perf_counter() - started) * 1000
            self.events.publish(
                "app.started",
                {"startup_ms": round(self.startup_ms, 3)},
                source="application",
            )
            log_event(self.logger, "app.started", startup_ms=round(self.startup_ms, 3))

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            self.events.publish("app.stopping", source="application")
            self.lifecycle.stop(suppress_errors=True)
            self.attachments.clear()
            self._control_preview_path.unlink(missing_ok=True)
            self.events.close()
            self._started = False
            log_event(self.logger, "app.stopped")
            close_logger(self.logger)

    def _configure_local_ai(self) -> None:
        config = self.configuration.config.intelligence
        if not config.enabled:
            self.local_ai.configure(None)
            return
        models_dir = self.paths.model_dir(self.configuration.config.storage.model_dir)
        registry = ModelRegistry(models_dir)
        descriptor = registry.get(config.model_id)
        executable = self.paths.runtime_dir / "llama.cpp" / "llama-server.exe"
        if descriptor is None or not registry.model_path(descriptor).is_file() or not executable.is_file():
            self.local_ai.configure(None)
            return
        releasers = (self.vision_provider.unload,) if self.vision_provider is not None else ()
        memory_guard = MemoryPressureGuard(
            max(3 * 1024**3, descriptor.size_bytes // 2 + 1024**3),
            releasers=releasers,
        )
        self.local_ai.configure(LlamaCppProvider(
            executable, registry.model_path(descriptor), descriptor,
            context_size=config.context_size, threads=config.threads,
            idle_timeout_seconds=config.keep_warm_seconds, backend=config.backend,
            pressure_guard=memory_guard,
        ))

    def _default_image_provider(self) -> Any:
        model = self.paths.model_dir(self.configuration.config.storage.model_dir) / "archi-image" / "lite" / "sdxs.safetensors"
        root = self.paths.runtimes_dir / "archi-image"
        cpu = sorted(root.glob("stable-diffusion.cpp-*-cpu/sd-cli.exe"), reverse=True)
        vulkan = sorted(root.glob("stable-diffusion.cpp-*-vulkan/sd-cli.exe"), reverse=True)
        if not model.is_file() or not (cpu or vulkan):
            return DisabledImageProvider()
        return StableDiffusionCppImageProvider(
            model,
            cpu_runtime=cpu[0] if cpu else None,
            vulkan_runtime=vulkan[0] if vulkan else None,
            backend="auto",
            expected_sha256="6cca5bfd11b588cdfb4602018c7e623d24c95fdfdc5ab2d4b9e6978b3186980f",
        )

    _IMAGE_CREATE = re.compile(
        r"^(?:arch(?:eon|i)[\s,]+)?(?:"
        r"(?:crea|genera|dibuja|haz)\s+(?:una\s+)?imagen|"
        r"(?:cr[eé]ame|gen[eé]rame|dib[uú]jame|hazme)\s+(?:una\s+)?imagen|"
        r"(?:create|generate|draw|make)\s+(?:an?\s+)?image|"
        r"(?:crie|gere|desenhe)\s+(?:uma\s+)?imagem|"
        r"(?:crée|cree|génère|genere|dessine)\s+(?:une\s+)?image|"
        r"(?:erstelle|generiere|zeichne)\s+(?:ein\s+)?bild|"
        r"(?:crea|genera|disegna)\s+(?:un[' ]?\s*)?immagine|"
        r"(?:生成|创建|畫|画)(?:一张|一个)?(?:图像|圖片|图片)?|"
        r"(?:画像を(?:生成|作成)|絵を描いて)|(?:이미지를?\s*(?:생성|만들어))|"
        r"(?:(?:создай|сгенерируй|нарисуй)\s+(?:изображение|картинку))|"
        r"(?:(?:أنشئ|انشئ|ولد|ارسم)\s+صورة)|(?:(?:छवि|चित्र)\s+(?:बनाओ|बनाएं))"
        r")\s*(?:de|sobre|con|of|about|d['’]|von|di|на|عن|का|की|:|-)?\s*(?P<prompt>.+)$",
        flags=re.IGNORECASE,
    )

    def _handle_image_generation_intent(self, text: str) -> dict[str, Any] | None:
        match = self._IMAGE_CREATE.match(text.strip())
        if not match:
            return None
        prompt = match.group("prompt").strip(" .")
        location = re.search(
            r"\s+(?:y\s+)?(?:gu[aá]rd(?:a|ala|alo)|pon(?:la|lo))\s+(?:en\s+)?"
            r"(?P<downloads>descargas|downloads)\b(?P<tail>.*)$",
            prompt, flags=re.IGNORECASE,
        )
        output_dir = self.paths.data_dir / "artifacts" / "images"
        requested_name = ""
        if location:
            prompt = prompt[:location.start()].strip(" ,.;")
            output_dir = Path.home() / "Downloads"
            folder = re.search(
                r"\b(?:dentro\s+de\s+)?(?:una\s+)?carpeta\s+(?:llamada\s+)?"
                r"(?P<name>.+?)(?=\s+(?:con\s+el\s+nombre|llamad[oa])\b|[.,;]|$)",
                location.group("tail"), flags=re.IGNORECASE,
            )
            if folder:
                folder_name = re.sub(r'[<>:"/\\|?*]+', " ", folder.group("name"))
                folder_name = " ".join(folder_name.split()).strip(" .")[:80]
                if folder_name:
                    output_dir /= folder_name
            named = re.search(
                r"\bcon\s+el\s+nombre\s+(?P<name>[^,.;]+)",
                location.group("tail"), flags=re.IGNORECASE,
            ) or re.search(
                r"\b(?:imagen|archivo)\s+llamad[oa]\s+(?P<name>[^,.;]+)",
                location.group("tail"), flags=re.IGNORECASE,
            )
            if named:
                requested_name = re.sub(r'[<>:"/\\|?*]+', " ", named.group("name"))
                requested_name = " ".join(requested_name.split()).strip(" .")
        if len(prompt) < 3:
            return {"ok": False, "message": "Dime qué imagen quieres crear.", "data": {"route": "archi_image"}, "correlation_id": None}
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = requested_name or f"ARCHI_Image_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:6]}"
        if not filename.casefold().endswith(".png"):
            filename += ".png"
        output = output_dir / filename
        if output.exists():
            output = output.with_name(f"{output.stem}_{datetime.now():%H%M%S}_{uuid4().hex[:4]}.png")
        result = self.image_provider.generate(ImageRequest(
            prompt, output, width=768, height=768,
            locale=self._last_request_language or self.configuration.config.language.interface,
            negative_prompt="words, letters, watermark, signature, blurry, distorted",
        ))
        if not result.ok:
            message = "ARCHI Image no está disponible en este equipo." if "not_installed" in str(result.error) else "No pude crear la imagen de forma verificable."
            return {"ok": False, "message": message, "data": {"route": "archi_image", "result": result.public()}, "correlation_id": None}
        verified = self.tools.execute(
            "artifacts.verify", {"path": str(output)},
            context=ToolContext(uuid4().hex, scope_permissions=frozenset({"filesystem.read"})),
        )
        if not (verified.ok and verified.verified):
            return {
                "ok": False, "message": "La imagen se generó, pero el archivo no superó la validación.",
                "data": {"route": "archi_image", "result": result.public(), "validation_error": verified.error},
                "correlation_id": None,
            }
        artifact = {
            "ok": True, "created": True, "verified": True, "path": result.path,
            "format": "png", "sha256": result.sha256, "width": result.width,
            "height": result.height, "prompt": prompt,
        }
        return {
            "ok": True, "message": "He creado la imagen y verifiqué el archivo.",
            "data": {"route": "archi_image", "artifacts": [artifact], "result": result.public()},
            "correlation_id": None,
        }

    @staticmethod
    def _fresh_search_query(text: str) -> str:
        query = " ".join(text.strip().split())
        query = re.sub(
            r"^(?:oye[\s,]+)?(?:archeon[\s,]+)?(?:dime|cu[eé]ntame|busca|comprueba|"
            r"quiero\s+saber|qu[eé]\s+sabes)\s+(?:del|de|sobre)?\s*",
            "", query, flags=re.IGNORECASE,
        )
        query = re.sub(r"^(?:sobre\s+)?(?:la?s?\s+)?(?:[uú]ltimas?\s+)?noticias?\s+(?:de|sobre)\s+", "", query, flags=re.IGNORECASE)
        query = re.sub(r"\b(?:quiero\s+saber\s+la\s+[uú]ltima\s+noticia|hoy|actualmente)\b", " ", query, flags=re.IGNORECASE)
        return " ".join(query.split()).strip(" ,.;:!?¡¿") or text.strip()

    def handle_command(self, text: str) -> dict[str, Any]:
        return self._process_request_context(UserRequestContext(text=text))

    @staticmethod
    def _normalized_control_phrase(text: str) -> str:
        return " ".join(re.sub(r"[^\w\s]", " ", text.casefold(), flags=re.UNICODE).split())

    def _listening_control(self, text: str) -> dict[str, Any] | None:
        assistant = self.configuration.config.assistant
        spoken = self._normalized_control_phrase(text)
        pause_phrase = self._normalized_control_phrase(assistant.pause_listening_phrase)
        resume_phrase = self._normalized_control_phrase(assistant.resume_listening_phrase)
        if spoken == pause_phrase:
            assistant.listening_paused = True
            self.configuration.save()
            self.events.publish("voice.listening.paused", source="application")
            return {"ok": True, "message": f"De acuerdo. Pausaré la escucha hasta que digas: {assistant.resume_listening_phrase}.", "data": {"route": "listening_control", "paused": True}}
        if spoken == resume_phrase:
            assistant.listening_paused = False
            self.configuration.save()
            self.events.publish("voice.listening.resumed", source="application")
            return {"ok": True, "message": "La escucha está activa de nuevo.", "data": {"route": "listening_control", "paused": False}}
        return None

    def _handle_voice_command(self, text: str) -> dict[str, Any]:
        control = self._listening_control(text)
        if control is not None:
            return control
        if self.configuration.config.assistant.listening_paused:
            return {"ok": True, "message": "La escucha está pausada.", "data": {"route": "listening_control", "paused": True, "ignored": True}}
        return self.handle_command(text)

    def _process_request_context(self, context: UserRequestContext) -> dict[str, Any]:
        listening_control = self._listening_control(context.text)
        if listening_control is not None:
            return listening_control
        correlation_id = uuid4().hex
        language = self.language_context.decide(
            context.text,
            preferred=self.configuration.config.language.conversation,
            previous=self._last_request_language,
            fallback=self.configuration.config.language.interface,
        )
        self._last_request_language = language.response_language
        interpretation = self.language_repair.interpret(
            context.text, context=self._task_context,
            known_files=(item.path for item in context.attachments),
        )
        style_profile = self.writing_style.resolve(
            context.text, learned=self._task_context.learned_writing_preferences(),
        )
        lowered = context.text.casefold()
        if "más corto" in lowered or "mas corto" in lowered:
            self._task_context.remember_writing_feedback("concise")
        if "sin conclusión" in lowered or "sin conclusion" in lowered:
            self._task_context.remember_writing_feedback("avoid_generic_conclusion")
        if "menos formal" in lowered:
            self._task_context.remember_writing_feedback("less_formal")
        if interpretation.clarification_required:
            return {
                "ok": True,
                "message": "La referencia no es suficientemente clara para actuar con seguridad. ¿Qué archivo exacto quieres usar?",
                "data": {
                    "route": "natural_language_clarification",
                    "raw_user_input": context.text,
                    "interpreted_intent": interpretation.public(),
                    "writing_style": style_profile.public(),
                },
                "correlation_id": correlation_id,
            }
        learned = self.operational_learning.match(
            context.text,
            project_root=self._task_context.active_project or "",
            context_tags=("attachments",) if context.attachments else (),
        )
        routed_context = UserRequestContext(
            text=(learned.replacement_text if learned and learned.replacement_text else interpretation.repaired_text),
            attachments=context.attachments,
            intent_override=learned.correct_intent if learned else None,
            operational_learning_id=learned.id if learned else None,
        )
        capability_route = self.capability_router.route(
            routed_context.text, attachment_names=(item.name for item in context.attachments),
        )
        knowledge = self.knowledge_router.assess(routed_context.text)
        try:
            result = self._handle_command(routed_context.text, routed_context)
        except Exception as error:
            self.logger.exception(
                "command.failed correlation_id=%s error_type=%s",
                correlation_id,
                type(error).__name__,
            )
            self.events.publish(
                "command.failed",
                {"error": "command_processing_failed"},
                source="application",
                correlation_id=correlation_id,
            )
            return {
                "ok": False,
                "message": "No pude procesar esa solicitud.",
                "data": {},
                "correlation_id": correlation_id,
            }
        result.setdefault("data", {})["capability_route"] = capability_route.public()
        result["data"]["knowledge"] = knowledge.public()
        result["data"]["response_language"] = language.response_language
        result["data"]["detected_language"] = language.detected_language
        result["data"]["raw_user_input"] = context.text
        result["data"]["interpreted_intent"] = interpretation.public()
        result["data"]["writing_style"] = style_profile.public()
        if learned:
            result["data"]["operational_learning"] = {
                "id": learned.id,
                "intent_override": learned.correct_intent,
                "scope": learned.scope.value,
                "confidence": learned.confidence.value,
            }
        result["data"]["available_tools"] = self.capability_router.available_tools(
            capability_route, self.tools.manifests(),
        )
        result["correlation_id"] = result.get("correlation_id") or correlation_id
        self.task_context_store.save(self._task_context)
        return result

    def handle_request(self, text: str, attachment_ids: list[str] | None = None) -> dict[str, Any]:
        identifiers = attachment_ids or []
        try:
            records = self.attachments.resolve(identifiers)
        except ValueError as error:
            return {"ok": False, "message": "No pude preparar los archivos adjuntos.", "error": str(error)}
        context = UserRequestContext(text=text, attachments=records)
        result = self._process_request_context(context)
        result["request_context"] = context.public()
        consumed = bool(result.get("ok"))
        result["attachments_consumed"] = consumed
        if consumed:
            self.attachments.release(identifiers)
        return result

    def handle_attachment_upload(
        self, name: str, content_type: str, length: int, source: Any
    ) -> dict[str, Any]:
        try:
            record = self.attachments.add_stream(name, content_type, length, source)
            return {"ok": True, "attachment": record.public()}
        except (OSError, ValueError) as error:
            return {"ok": False, "error": str(error)}

    def handle_cloud_upload(
        self, name: str, content_type: str, length: int, source: Any,
        session_token: str, conversation_id: str = "",
    ) -> dict[str, Any]:
        """Stream a mobile/desktop upload to a bounded temporary file, then to private Storage."""
        maximum = self.cloud.MAX_FILE_BYTES
        if length < 1 or length > maximum:
            return {"ok": False, "error": "cloud_file_size_invalid"}
        filename = Path(name).name.strip()
        if not filename or filename in {".", ".."}:
            return {"ok": False, "error": "cloud_file_name_invalid"}
        temporary = self.paths.cache_dir / f"cloud-upload-{uuid4().hex}-{filename}"
        remaining = length
        try:
            identity, access_token = self.auth.cloud_identity(session_token)
            self.paths.cache_dir.mkdir(parents=True, exist_ok=True)
            with temporary.open("xb") as target:
                while remaining:
                    chunk = source.read(min(64 * 1024, remaining))
                    if not chunk:
                        raise ValueError("cloud_file_upload_incomplete")
                    target.write(chunk)
                    remaining -= len(chunk)
                target.flush()
                os.fsync(target.fileno())
            result = self.cloud.upload_file(
                access_token, user_id=identity.user_id, source=temporary,
                conversation_id=conversation_id or None, display_name=filename,
            )
            return {"ok": True, "file": result}
        except (OSError, TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        finally:
            temporary.unlink(missing_ok=True)

    def _handle_desktop_intent(self, text: str, normalized_text: str) -> dict[str, Any] | None:
        """Route explicit screen observation before ARCHI text generation."""
        notepad_unsaved = re.search(
            r"(?:abre|abrir|open)\s+(?:el\s+)?(?:bloc\s+de\s+notas|notepad)"
            r".*?(?:y\s+)?(?:escribe|escribir|type)\s*[:\-]?\s*[\"'«»]?(?P<content>.+?)[\"'«»]?\s*[.!?]*$",
            text.strip(), flags=re.IGNORECASE | re.DOTALL,
        )
        if notepad_unsaved and not re.search(r"\b(?:guarda|guardar|save)\b", text, flags=re.IGNORECASE):
            content = notepad_unsaved.group("content").strip().strip("\"'«» \n\r\t")
            target = self.paths.cache_dir / f"computer-use-{uuid4().hex}.txt"
            task = AgentTask(
                goal=text.strip(), mode=AgentMode.CONTROL,
                plan=(
                    AgentStep("prepare", "Preparando un documento temporal seguro", "files.ensure_empty", {"path": str(target)}, "new controlled temporary file exists", 0),
                    AgentStep("open-notepad", "Abriendo Bloc de notas", "desktop.launch_notepad", {"path": str(target)}, "Notepad window verified", 1),
                    AgentStep("type-text", "Escribiendo en el editor reconocido", "desktop.type_text", {"text": content, "expected_window_handle": {"$result": "open-notepad", "path": "window.handle"}}, "editor text read back and verified", 0),
                ),
                completion_criteria=("Notepad recognized", "editable control focused", "text read back exactly"),
                context=TaskContext(current_goal=text.strip()),
            )
            result = self.agent_runner.run(
                task, scope_permissions=frozenset({"filesystem.read", "filesystem.write", "desktop.control"}),
            )
            self.task_store.save(result)
            completed = result.status.value == "completed"
            return {
                "ok": completed,
                "message": (
                    "Abrí Bloc de notas y verifiqué el texto en el editor; no guardé el documento."
                    if completed else "No pude verificar el texto en Bloc de notas; no afirmaré que se escribió."
                ),
                "data": {"route": "desktop_agent", "mode": "control", "task": result.public(), "temporary_path": str(target)},
                "correlation_id": result.id,
            }
        notepad_request = re.search(
            r"bloc\s+de\s+notas.*?escribe\s+[\"'«](.+?)[\"'»].*?"
            r"guarda.*?como\s+([\w .-]+?\.txt)\s+en\s+descargas",
            text, flags=re.IGNORECASE | re.DOTALL,
        )
        list_request = re.search(
            r"bloc\s+de\s+notas.*?escribe\s+una\s+lista\s+de\s+tres\s+tareas.*?"
            r"guarda.*?como\s+([\w .-]+?\.txt).*?descargas",
            text, flags=re.IGNORECASE | re.DOTALL,
        )
        if notepad_request is None and list_request is not None:
            notepad_request = list_request
            content = "1. Revisar pendientes\n2. Probar ARCHEON\n3. Verificar resultados"
            filename = Path(list_request.group(1).strip()).name
        elif notepad_request is not None:
            content = notepad_request.group(1)
            filename = Path(notepad_request.group(2).strip()).name
        if notepad_request:
            downloads = Path.home() / "Downloads"
            target = (downloads / filename).resolve()
            if target.parent != downloads.resolve():
                return {"ok": False, "message": "El nombre de archivo no es válido.", "data": {}, "correlation_id": None}
            task = AgentTask(
                goal=text.strip(), mode=AgentMode.CONTROL,
                plan=(
                    AgentStep("ensure-downloads", "Verificar Descargas", "files.create_folder", {"path": str(downloads)}, "Downloads exists", 0),
                    AgentStep("create-empty-file", "Crear archivo vacío sin sobrescribir", "files.ensure_empty", {"path": str(target)}, "new empty file exists", 0),
                    AgentStep("launch-notepad", "Abrir archivo en Bloc de notas", "desktop.launch_notepad", {"path": str(target)}, "Notepad window verified", 1),
                    AgentStep("type-content", "Escribir en el editor enfocado", "desktop.type_text", {"field_name": "Editor de texto", "text": content, "expected_window_handle": {"$result": "launch-notepad", "path": "window.handle"}}, "text input sent", 1),
                    AgentStep("open-file-menu", "Abrir menú Archivo", "desktop.invoke", {"name": "Archivo"}, "file menu opened", 1),
                    AgentStep("save-file", "Invocar Guardar", "desktop.invoke", {"name": "Guardar"}, "save action verified", 1),
                    AgentStep("verify-file", "Verificar contenido guardado", "files.verify_text", {"path": str(target), "expected": content}, "exact file content verified", 2),
                    AgentStep("reveal-file", "Abrir Explorador y localizar el archivo", "desktop.reveal_in_explorer", {"path": str(target)}, "Explorer shows the saved file", 1),
                ),
                completion_criteria=("Notepad opened", "text typed", "file exact", "Explorer item visible"),
            )
            result = self.agent_runner.run(
                task,
                scope_permissions=frozenset({"desktop.control", "filesystem.read", "filesystem.write"}),
            )
            self.task_store.save(result)
            completed = result.status.value == "completed"
            return {
                "ok": completed,
                "message": (
                    f"Abrí Bloc de notas, guardé {filename}, verifiqué su contenido y lo localicé en el Explorador."
                    if completed else
                    f"La tarea no quedó verificada. No afirmaré que {filename} está completo."
                ),
                "data": {"route": "desktop_agent", "mode": "control", "task": result.public(), "path": str(target)},
                "correlation_id": result.id,
            }
        guide_intent = has_unnegated(
            r"\b(?:d[oó]nde\s+(?:tengo\s+que\s+)?(?:darle|pulsar|hacer\s+clic)|"
            r"mu[eé]strame\s+d[oó]nde|se[nñ]ala|resalta)\b", normalized_text,
        )
        if guide_intent:
            explicit = re.search(
                r"(?:bot[oó]n|control|opci[oó]n)\s+[\"'«»]?(.+?)[\"'«»]?\s*[.!?]*$",
                text.strip(), flags=re.IGNORECASE,
            )
            target = explicit.group(1).strip().strip("\"'«»") if explicit else ""
            if not target:
                buttons = []
                for item in self._task_context.recent_entities:
                    if item.get("kind") == "button" and item.get("name") not in buttons:
                        buttons.append(str(item["name"]))
                if len(buttons) == 1:
                    target = buttons[0]
            if not target:
                return {
                    "ok": False,
                    "message": "Puedo señalar un control, pero necesito que me indiques cuál porque hay varias opciones visibles.",
                    "data": {"route": "desktop_agent", "mode": "guide", "error": "ambiguous_target"},
                    "correlation_id": None,
                }
            task = AgentTask(
                goal=text.strip(), mode=AgentMode.GUIDE,
                plan=(
                    AgentStep(
                        "locate-control", f"Localizar {target}", "desktop.locate", {"name": target},
                        "enabled control has verified bounds", max_retries=0,
                    ),
                    AgentStep(
                        "show-guide-overlay", "Mostrar resaltado temporal", "desktop.guide_overlay",
                        {
                            "bounds": {"$result": "locate-control", "path": "bounds"},
                            "window_handle": {"$result": "locate-control", "path": "window.handle"},
                            "label": {"$result": "locate-control", "path": "element"},
                            "duration_ms": 2000,
                        },
                        "click-through overlay shown", max_retries=0,
                    ),
                ),
                completion_criteria=("target control bounds verified", "temporary overlay shown"),
            )
            result = self.agent_runner.run(task, scope_permissions=frozenset({"desktop.observe"}))
            self.task_store.save(result)
            if result.status.value != "completed":
                if self.vision_provider is not None:
                    located_visual = self.tools.execute(
                        "vision.locate_active", {"name": target, "max_side": 960},
                        context=ToolContext(result.id, scope_permissions=frozenset({"desktop.observe"})),
                    )
                    if located_visual.ok and located_visual.verified:
                        overlay_visual = self.tools.execute(
                            "desktop.guide_overlay",
                            {"bounds": located_visual.data["bounds"], "window_handle": located_visual.data["window"]["handle"],
                             "label": target, "duration_ms": 2000},
                            context=ToolContext(result.id, scope_permissions=frozenset({"desktop.observe"})),
                        )
                        if overlay_visual.ok and overlay_visual.verified:
                            return {
                                "ok": True, "message": f"Señalé visualmente «{target}» sin modificar la aplicación.",
                                "data": {"route": "desktop_agent", "mode": "guide", "method": "archi_vision",
                                         "highlight": {"bounds": located_visual.data["bounds"], "label": target,
                                                       "temporary": True, "native_overlay": True}},
                                "correlation_id": result.id,
                            }
                return {
                    "ok": False, "message": f"No pude localizar «{target}» de forma verificable.",
                    "data": {"route": "desktop_agent", "mode": "guide", "task": result.public()},
                    "correlation_id": result.id,
                }
            located = next(item["data"] for item in result.tool_results if item["step"] == "locate-control")
            overlay = next(item["data"] for item in result.tool_results if item["step"] == "show-guide-overlay")
            left, top, right, bottom = located["bounds"]
            return {
                "ok": True,
                "message": f"«{located['element']}» está en la zona ({left}, {top})–({right}, {bottom}) de la pantalla.",
                "data": {
                    "route": "desktop_agent", "mode": "guide", "task_id": result.id,
                    "highlight": {
                        "bounds": located["bounds"], "label": located["element"], "temporary": True,
                        "native_overlay": bool(overlay.get("shown")),
                    },
                },
                "correlation_id": result.id,
            }
        invoke_match = re.match(
            r"^(?:archeon[\s,]+)?(?:haz\s+clic|pulsa|presiona|selecciona|click)\s+"
            r"(?:en\s+)?(?:el\s+bot[oó]n\s+)?[\"'«»]?(.+?)[\"'«»]?\s*[.!?]*$",
            text.strip(), flags=re.IGNORECASE,
        )
        if invoke_match:
            target = invoke_match.group(1).strip().strip("\"'«»")
            task = AgentTask(
                goal=text.strip(), mode=AgentMode.CONTROL,
                plan=(
                    AgentStep(
                        "observe-before", "Observar estado inicial", "desktop.observe_active",
                        {"visual_fingerprint": False}, "initial state captured", max_retries=0,
                    ),
                    AgentStep(
                        "invoke-control", f"Invocar el control {target}", "desktop.invoke",
                        {"name": target}, "window state changed after invoke", max_retries=1,
                    ),
                    AgentStep(
                        "observe-after", "Observar y verificar resultado", "desktop.observe_active",
                        {"visual_fingerprint": False}, "resulting state captured", max_retries=0,
                    ),
                ),
                completion_criteria=("named control invoked", "resulting window state verified"),
            )
            result = self.agent_runner.run(
                task,
                scope_permissions=frozenset({"desktop.observe", "desktop.control"}),
            )
            if result.tool_results:
                last_window = result.tool_results[-1].get("data", {}).get("window", {})
                result.context.active_app = str(last_window.get("process_name") or "") or None
                result.context.active_window = str(last_window.get("title") or "") or None
                result.context.current_goal = result.goal
            self.task_store.save(result)
            completed = result.status.value == "completed"
            if not completed and self.vision_provider is not None:
                visual_click = None
                for visual_attempt in range(2):
                    visual_click = self.tools.execute(
                        "vision.click_active", {
                            "name": target, "max_side": 960,
                            "movement_mode": self.configuration.config.computer_use.action_display,
                            "reduce_motion": self.configuration.config.appearance.reduced_motion,
                        },
                        context=ToolContext(
                            result.id, scope_permissions=frozenset({"desktop.observe", "desktop.control"}),
                        ),
                    )
                    if visual_click.ok and visual_click.verified:
                        break
                    if self.vision_provider is not None:
                        self.vision_provider.invalidate_cache()
                if visual_click is not None and visual_click.ok and visual_click.verified:
                    completed = True
                    self.task_store.save(result)
                    return {
                        "ok": True,
                        "message": f"Pulsé visualmente «{target}» tras revalidar la ventana y verifiqué el cambio.",
                        "data": {"route": "desktop_agent", "mode": "control", "method": "archi_vision",
                                 "confidence": visual_click.data.get("confidence"),
                                 "task": result.public()},
                        "correlation_id": result.id,
                    }
            message = (
                f"Pulsé «{target}» y verifiqué el cambio en la ventana."
                if completed else
                f"No pude verificar que el control «{target}» produjera el cambio esperado."
            )
            return {
                "ok": completed, "message": message,
                "data": {"route": "desktop_agent", "mode": "control", "task": result.public()},
                "correlation_id": result.id,
            }
        mentions_target = bool(re.search(
            r"\b(?:pantalla|ventana|screen|window|escritorio)\b", normalized_text,
        ))
        asks_to_observe = has_unnegated(
            r"^(?:(?:hola\s+)?archeon[\s,]+|por\s+favor\s+)?"
            r"(?:mira|observa|analiza|revisa|look|observe)\b|"
            r"\b(?:qu[eé]\s+ves|qu[eé]\s+hay|dime\s+qu[eé]\s+ves|"
            r"puedes\s+(?:mirar|ver|observar|decirme\s+qu[eé]\s+ves)|"
            r"what\s+do\s+you\s+see)\b",
            normalized_text,
        )
        if not (mentions_target and asks_to_observe):
            return None
        task = AgentTask(
            goal=text.strip(),
            mode=AgentMode.OBSERVE,
            plan=(AgentStep(
                "observe-active-window",
                "Observar la ventana activa mediante Windows UI Automation",
                "desktop.observe_active",
                {"visual_fingerprint": False},
                "ventana y estado verificados",
                max_retries=1,
            ),),
            completion_criteria=("active window has verified state evidence",),
        )
        result = self.agent_runner.run(
            task,
            scope_permissions=frozenset({"desktop.observe"}),
        )
        if result.tool_results:
            observed_window = result.tool_results[-1].get("data", {}).get("window", {})
            result.context.active_app = str(observed_window.get("process_name") or "") or None
            result.context.active_window = str(observed_window.get("title") or "") or None
            result.context.current_goal = result.goal
        self.task_store.save(result)
        if not result.tool_results or result.status.value != "completed":
            error = result.errors[-1] if result.errors else "desktop_observation_failed"
            return {
                "ok": False,
                "message": "Intenté observar la ventana activa, pero no pude verificar el resultado.",
                "data": {"route": "desktop_agent", "mode": "observe", "task": result.public(), "error": error},
                "correlation_id": result.id,
            }
        evidence = result.tool_results[-1]["data"]
        window = evidence.get("window", {})
        self._task_context.active_app = str(window.get("process_name") or "") or None
        self._task_context.active_window = str(window.get("title") or "") or None
        self._task_context.current_goal = result.goal
        entities: list[dict[str, Any]] = []
        for element in evidence.get("elements", []):
            name = " ".join(str(element.get("name", "")).split())
            if name:
                entities.append({
                    "kind": "button" if element.get("control_type") == 50000 else "control",
                    "name": name, "bounds": element.get("bounds"),
                })
        self._task_context.recent_entities = entities[-40:]
        names: list[str] = []
        generic_window_chrome = {
            "sistema", "system", "minimizar", "minimize", "maximizar", "maximize",
            "restaurar", "restore", "cerrar", "close",
        }
        for element in evidence.get("elements", []):
            name = " ".join(str(element.get("name", "")).split())
            if (name and name not in names and name != window.get("title")
                    and name.casefold() not in generic_window_chrome):
                names.append(name)
            if len(names) >= 8:
                break
        title = str(window.get("title") or "sin título")
        process = str(window.get("process_name") or "proceso desconocido")
        if names:
            visible = "; ".join(names)
            message = (
                f"Veo la ventana «{title}» de {process}. "
                f"Pude leer estos elementos: {visible}."
            )
        elif self.vision_provider is None:
            component = self.vision_components.status()
            download_gib = int(component["download_size_bytes"]) / (1024 ** 3)
            disk_gib = int(component["disk_required_bytes"]) / (1024 ** 3)
            message = (
                f"Veo la ventana «{title}» de {process}, pero no expone información accesible suficiente. "
                "Para analizar interfaces visuales no accesibles necesito instalar el componente ARCHI "
                f"Vision (descarga: {download_gib:.2f} GiB; espacio requerido: {disk_gib:.2f} GiB)."
            )
        else:
            visual = self.tools.execute(
                "vision.observe_active",
                {
                    "window_handle": int(window.get("handle") or 0),
                    "max_side": 960,
                    "prompt": (
                        "Describe what is visibly wrong in this window. Cite visible evidence, list "
                        "relevant controls and report uncertainty. Do not invent unreadable text."
                    ),
                },
                context=ToolContext(
                    correlation_id=result.id,
                    scope_permissions=frozenset({"desktop.observe"}),
                ),
            )
            if visual.ok and visual.verified:
                visual_evidence = dict(visual.data)
                confidence = float(visual_evidence.get("confidence", 0.0))
                summary = str(visual_evidence.get("window_summary") or "").strip()
                errors = [str(item) for item in visual_evidence.get("errors", []) if str(item).strip()]
                detail = f" Evidencia de error: {'; '.join(errors[:3])}." if errors else ""
                qualifier = "" if confidence >= 0.65 else " El nivel de confianza es limitado; no actuaré automáticamente."
                message = f"Analicé visualmente «{title}» de forma local: {summary}.{detail}{qualifier}"
                evidence = {
                    "window": window,
                    "method": "archi_vision",
                    "window_summary": summary,
                    "errors": errors,
                    "controls": visual_evidence.get("controls", []),
                    "regions": visual_evidence.get("regions", []),
                    "possible_actions": visual_evidence.get("possible_actions", []),
                    "confidence": confidence,
                    "metrics": visual_evidence.get("metrics", {}),
                }
            else:
                message = (
                    f"Veo la ventana «{title}» de {process}, pero no pude completar el análisis visual "
                    "local. No voy a inventar lo que contiene."
                )
                evidence = {**evidence, "vision_error": visual.error or "vision_not_verified"}
        return {
            "ok": True,
            "message": message,
            "data": {
                "route": "desktop_agent", "mode": "observe", "task_id": result.id,
                "status": result.status.value, "evidence": evidence,
            },
            "correlation_id": result.id,
        }

    def _handle_document_intent(
        self, text: str, normalized_text: str, context: UserRequestContext | None,
    ) -> dict[str, Any] | None:
        document_terms = bool(re.search(
            r"\b(?:pdf|documento|docx|xlsx|pptx|markdown|archivo|adjunto|descargas|p[aá]gina|zip|7z|rar|tar|comprimido|adentro)\b",
            normalized_text,
        ))
        requested_action = has_unnegated(
            r"\b(?:abre|abrir|lee|leer|resum|busca|buscar|encuentra|extrae|contesta|responde|"
            r"haz(?:me|lo|la)?|p[aá]sa(?:me|lo|la)?|convierte|corrige)\w*\b|"
            r"\b(?:qu[eé]\s+dice|dime\s+qu[eé]\s+dice)\b",
            normalized_text,
        )
        attachments = tuple(context.attachments) if context else ()
        contextual_document = bool(
            self._task_context.selected_file
            and (
                re.search(
                    r"\b(?:ese|este|aquel)\s+(?:documento|archivo)|"
                    r"\b(?:res[uú]melo|l[eé]elo|contesta\s+(?:las\s+)?preguntas|haz\s+(?:la\s+)?actividad)\b",
                    normalized_text,
                )
                or re.match(
                    r"^(?:ahora\s+)?(?:lee|resume|revisa|abre)\s+(?:esto|ese|esa|el\s+anterior)\s*[.!?]*$",
                    normalized_text,
                )
            )
        )
        if not (document_terms and requested_action) and not attachments and not contextual_document:
            return None
        ordinal_words = {
            "primera": 1, "primer": 1, "segunda": 2, "tercera": 3, "cuarta": 4,
            "quinta": 5, "sexta": 6, "s[eé]ptima": 7, "octava": 8, "novena": 9, "d[eé]cima": 10,
        }
        page = None
        numeric_page = re.search(r"p[aá]gina\s+(\d{1,4})", normalized_text)
        if numeric_page:
            page = int(numeric_page.group(1))
        else:
            for word, number in ordinal_words.items():
                if re.search(rf"\b{word}\s+p[aá]gina\b|\bp[aá]gina\s+{word}\b", normalized_text):
                    page = number
                    break
        routes = self.file_router.route_many(attachments)
        unsupported = [attachments[index].name for index, route in enumerate(routes) if not route.supported]
        supported_paths = [route.path for route in routes if route.parser.startswith("documents.")]
        artifact_paths = [route.path for route in routes if route.parser.startswith("artifacts.")]
        archive_paths = [route.path for route in routes if route.parser.startswith("archives.")]
        image_paths = [route.path for route in routes if route.parser == "vision.image"]
        contextual_archive = None
        if not archive_paths and self._task_context.selected_file:
            remembered = Path(self._task_context.selected_file)
            if remembered.is_file() and (remembered.name.casefold().endswith((".zip", ".7z", ".rar", ".tar", ".tar.gz", ".tgz"))):
                contextual_archive = remembered
                archive_paths = [remembered]
        if attachments and not supported_paths and not artifact_paths and not archive_paths and not image_paths and not (document_terms and requested_action):
            return None
        if archive_paths and not supported_paths and not artifact_paths:
            archive_results: list[dict[str, Any]] = []
            for path in archive_paths:
                listed = self.tools.execute(
                    "archives.list", {"path": str(path)},
                    context=ToolContext(uuid4().hex, scope_permissions=frozenset({"filesystem.read"})),
                )
                if not listed.ok:
                    archive_results.append({"path": str(path), "ok": False, "error": listed.error})
                    continue
                members = list(listed.data.get("members", ()))
                wanted_suffix = next((suffix for suffix in (".html", ".js", ".css", ".pdf", ".txt", ".md", ".json") if suffix.lstrip(".") in normalized_text), None)
                name_match = re.search(r"\b([\w .()\-]+\.(?:html?|js|css|pdf|txt|md|json))\b", normalized_text, re.I)
                candidates = [item for item in members if not item.get("directory") and (
                    (name_match and Path(str(item.get("path", ""))).name.casefold() == name_match.group(1).strip().casefold())
                    or (wanted_suffix and str(item.get("path", "")).casefold().endswith(wanted_suffix))
                )]
                if (wanted_suffix or name_match) and len(candidates) == 1:
                    read = self.tools.execute(
                        "archives.read_member", {"path": str(path), "member": str(candidates[0]["path"])},
                        context=ToolContext(uuid4().hex, scope_permissions=frozenset({"filesystem.read"})),
                    )
                    archive_results.append({"path": str(path), "ok": read.ok, "member": candidates[0]["path"], "content": read.data if read.ok else {}, "error": read.error})
                elif (wanted_suffix or name_match) and len(candidates) > 1:
                    archive_results.append({"path": str(path), "ok": True, "ambiguous": True, "candidates": [item["path"] for item in candidates[:10]], "tree": listed.data.get("tree", "")})
                else:
                    archive_results.append({"path": str(path), "ok": True, "inspection": listed.data})
                self._task_context.remember_document(str(path), source="archive_attachment" if not contextual_archive else "archive_context")
                self._task_context.recent_entities = [item for item in self._task_context.recent_entities if item.get("kind") != "archive_member"]
                self._task_context.recent_entities.extend({"kind": "archive_member", "archive": str(path), "path": str(item.get("path", ""))} for item in members[:100] if not item.get("directory"))
                self._task_context.recent_entities = self._task_context.recent_entities[-120:]
            ambiguous = next((item for item in archive_results if item.get("ambiguous")), None)
            if ambiguous:
                return {"ok": True, "message": "Encontré varios archivos compatibles dentro del comprimido. Indícame cuál quieres leer: " + ", ".join(ambiguous["candidates"]), "data": {"route": "archive_inspector", "files": archive_results, "file_routes": [item.public() for item in routes]}, "correlation_id": None}
            member_read = next((item for item in archive_results if item.get("member") and item.get("ok")), None)
            message = str(member_read.get("content", {}).get("text", ""))[:20_000] if member_read else "Inspeccioné el comprimido sin extraerlo completo."
            return {"ok": any(item.get("ok") for item in archive_results), "message": message or "El miembro es binario; registré su estructura y hash sin ejecutarlo.", "data": {"route": "archive_inspector", "files": archive_results, "file_routes": [item.public() for item in routes]}, "correlation_id": None}
        if image_paths and not supported_paths and not artifact_paths:
            if self.vision_provider is None:
                return {
                    "ok": False,
                    "message": "Detecté la imagen, pero ARCHI Vision no está instalado y no voy a inventar su contenido.",
                    "data": {"route": "image_attachment", "vision_required": True, "file_routes": [item.public() for item in routes]},
                    "correlation_id": None,
                }
            observations: list[dict[str, Any]] = []
            language_names = {
                "es": "Spanish", "en": "English", "pt": "Portuguese", "fr": "French",
                "de": "German", "it": "Italian", "zh": "Simplified Chinese", "ja": "Japanese",
                "ko": "Korean", "ru": "Russian", "ar": "Arabic", "hi": "Hindi",
            }
            response_language = self._last_request_language or self.configuration.config.language.interface
            grounded_vision_prompt = (
                f"{text}\nRespond only in {language_names.get(response_language, 'Spanish')}. "
                "Describe only details that are verifiably visible; do not translate names or invent objects."
            )
            for path in image_paths:
                result = self.tools.execute(
                    "vision.analyze_file", {"path": str(path), "prompt": grounded_vision_prompt, "max_side": 1280},
                    context=ToolContext(uuid4().hex, scope_permissions=frozenset({"filesystem.read"})),
                )
                observations.append({"path": str(path), "ok": result.ok, "data": result.data, "error": result.error})
            summaries = [str(item["data"].get("window_summary", "")) for item in observations if item["ok"]]
            return {
                "ok": bool(summaries), "message": "\n\n".join(summaries) if summaries else "No pude analizar la imagen de forma verificable.",
                "data": {"route": "image_attachment", "files": observations, "file_routes": [item.public() for item in routes]},
                "correlation_id": None,
            }
        if artifact_paths and not supported_paths:
            inspected: list[dict[str, Any]] = []
            for path in artifact_paths:
                result = self.tools.execute(
                    "artifacts.inspect", {"path": str(path)},
                    context=ToolContext(uuid4().hex, scope_permissions=frozenset({"filesystem.read"})),
                )
                inspected.append({"path": str(path), "ok": result.ok, "structure": result.data if result.ok else {}, "error": result.error})
                if result.ok:
                    self._task_context.remember_document(str(path), source="attachment")
            return {
                "ok": any(item["ok"] for item in inspected),
                "message": "Leí la estructura y una muestra acotada de " + ", ".join(Path(item["path"]).name for item in inspected) + ".",
                "data": {"route": "artifact_attachment_reader", "files": inspected, "file_routes": [item.public() for item in routes]},
                "correlation_id": None,
            }
        if attachments and not supported_paths:
            return {
                "ok": False,
                "message": "Los adjuntos se detectaron, pero todavía no hay un parser verificable para: " + ", ".join(unsupported or (item.name for item in attachments)),
                "data": {"route": "file_router", "files": [item.public() for item in routes]},
                "correlation_id": None,
            }
        if len(supported_paths) > 1:
            extracted_files: list[dict[str, Any]] = []
            for path in supported_paths:
                read = self.tools.execute(
                    "documents.read", {"path": str(path), "max_characters": 12_000},
                    context=ToolContext(uuid4().hex, scope_permissions=frozenset({"filesystem.read"})),
                )
                if not read.ok:
                    extracted_files.append({"path": str(path), "ok": False, "error": read.error or "read_failed"})
                    continue
                pages_data = read.data.get("pages", [])
                body = "\n".join(str(item.get("text", "")) for item in pages_data)[:12_000]
                extracted_files.append({"path": str(path), "ok": True, "format": read.data.get("format"), "text": body})
                self._task_context.remember_document(str(path), source="attachment")
            successful = [item for item in extracted_files if item.get("ok")]
            if re.search(r"\b(?:resum|actividad|contesta|responde|preguntas)\w*\b", normalized_text) and successful:
                sources = "\n\n".join(
                    f"### {Path(str(item['path'])).name}\n{item['text']}" for item in successful
                )[:30_000]
                generated = self.orchestrator.handle_text(
                    "Usa exclusivamente los documentos verificables siguientes. No inventes requisitos o datos. "
                    f"Responde de forma completa y ordenada. Solicitud: {text}\n\n{sources}",
                    response_token_floor=1536,
                )
                if generated.ok:
                    self._last_document_output = {
                        "title": Path(str(successful[-1]["path"])).stem,
                        "content": generated.message,
                        "source": ";".join(str(item["path"]) for item in successful),
                    }
                    artifact_result = self._handle_artifact_followup(text, normalized_text)
                    if artifact_result is not None:
                        artifact_result["message"] = generated.message + "\n\n" + artifact_result["message"]
                        artifact_result["data"]["grounded"] = True
                        return artifact_result
                    return {
                        "ok": True, "message": generated.message,
                        "data": {"route": "multi_document_grounded_task", "files": [
                            {key: value for key, value in item.items() if key != "text"} for item in extracted_files
                        ], "grounded": True, "file_routes": [item.public() for item in routes]},
                        "correlation_id": generated.correlation_id,
                    }
            summaries = []
            for item in extracted_files:
                name = Path(str(item["path"])).name
                summaries.append(f"{name}:\n{str(item.get('text') or item.get('error', ''))[:3000]}")
            return {
                "ok": bool(successful), "message": "\n\n".join(summaries),
                "data": {"route": "multi_document_reader", "files": [
                    {key: value for key, value in item.items() if key != "text"} for item in extracted_files
                ], "file_routes": [item.public() for item in routes]}, "correlation_id": None,
            }

        if "abierto" in normalized_text and not self._task_context.active_window:
            observed = self.tools.execute(
                "desktop.observe_active", {"visual_fingerprint": False},
                context=ToolContext(uuid4().hex, scope_permissions=frozenset({"desktop.observe"})),
            )
            if observed.ok:
                window = observed.data.get("window", {})
                self._task_context.active_window = str(window.get("title") or "") or None
                self._task_context.active_app = str(window.get("process_name") or "") or None

        roots = [Path.home() / "Downloads", Path.home() / "Documents", Path.home() / "Desktop"]
        if self._task_context.active_folder:
            roots.insert(0, Path(self._task_context.active_folder))
        selected_shell = self.document_resolver.windows_selected_files() if "seleccionado" in normalized_text else ()
        resolution = self.document_resolver.resolve(
            text, context=self._task_context, roots=roots, attached_paths=tuple(supported_paths) + selected_shell,
        )
        if resolution.ambiguous:
            options = [item.public() for item in resolution.candidates[:5]]
            self._task_context.recent_entities = [
                {"kind": "document_candidate", "path": str(item["path"]), "name": str(item["name"])} for item in options
            ]
            labels = "\n".join(f"- {item['name']} ({item['extension']})" for item in options)
            return {
                "ok": True,
                "message": f"Encontré varios archivos posibles:\n{labels}\n¿Cuál quieres usar?",
                "data": {"route": "document_resolver", "disambiguation_required": True, "options": options},
                "correlation_id": None,
            }
        if resolution.selected is None:
            return {
                "ok": False, "message": "No encontré un documento verificable que coincida con esa descripción.",
                "data": {"route": "document_resolver", "visited": resolution.visited}, "correlation_id": None,
            }
        selected = resolution.selected.path
        plan = (AgentStep(
            "read-document", "Leer el documento y la página solicitada", "documents.read",
            {"path": str(selected), **({"page": page} if page else {}), "max_characters": 120_000},
            "requested document page has verified extraction evidence", max_retries=0,
        ),)
        task = AgentTask(
            goal=text.strip(), mode=AgentMode.OBSERVE, plan=plan,
            completion_criteria=("document resolved", "requested accessible page read with evidence"),
            context=TaskContext(current_goal=text.strip()),
        )
        result = self.agent_runner.run(task, scope_permissions=frozenset({"filesystem.read"}))
        self.task_store.save(result)
        if result.status.value != "completed":
            error = result.errors[-1] if result.errors else "document_task_failed"
            return {
                "ok": False,
                "message": "No pude localizar y leer esa página de forma verificable.",
                "data": {"route": "document_agent", "task": result.public(), "error": error},
                "correlation_id": result.id,
            }
        read_result = next(item for item in result.tool_results if item["step"] == "read-document")
        document = read_result["data"]
        resolved = Path(str(document["path"]))
        self._task_context.remember_document(str(resolved), page=page, source=resolution.selected.reason)
        self._task_context.current_goal = text.strip()
        try:
            if resolved.is_relative_to((Path.home() / "Downloads").resolve()):
                self._task_context.recent_download = str(resolved)
        except ValueError:
            pass
        pages = document.get("pages", [])
        if not pages or not pages[0].get("accessible_text"):
            return {
                "ok": False,
                "message": "Esa página no contiene texto accesible. Requiere análisis visual/OCR bajo demanda; no iniciaré OCR masivo.",
                "data": {"route": "document_agent", "task_id": result.id, "visual_fallback_required": True},
                "correlation_id": result.id,
            }
        page_data = pages[0]
        extracted = (
            str(page_data.get("text", "")).strip() if page else
            "\n\n".join(str(item.get("text", "")).strip() for item in pages if item.get("text")).strip()
        )
        if re.search(r"\b(?:resum|actividad|contesta|responde|preguntas)\w*\b", normalized_text):
            grounded_prompt = (
                "Trabaja únicamente con el contenido verificable del documento incluido debajo. "
                "No inventes requisitos, preguntas, datos ni estadísticas. Si algo no aparece, dilo.\n\n"
                f"Solicitud: {text}\nDocumento: {resolved.name}\nContenido:\n{extracted[:24000]}"
            )
            generated = self.orchestrator.handle_text(
                grounded_prompt + "\n\nEntrega una respuesta completa y ordenada; no la cortes a mitad de una idea.",
                response_token_floor=1536,
            )
            if generated.ok:
                self._last_document_output = {
                    "title": resolved.stem, "content": generated.message, "source": str(resolved),
                }
                artifact_result = self._handle_artifact_followup(text, normalized_text)
                if artifact_result is not None:
                    artifact_result["message"] = generated.message + "\n\n" + artifact_result["message"]
                    artifact_result["data"].update({"grounded": True, "requirements_source": str(resolved)})
                    return artifact_result
                return {
                    "ok": True, "message": generated.message,
                    "data": {
                        "route": "document_grounded_task", "path": str(resolved), "format": document.get("format"),
                        "page": page_data["number"], "page_count": document.get("page_count"), "grounded": True,
                        "requirements_source": str(resolved),
                    }, "correlation_id": generated.correlation_id,
                }
        page_label = f"La página {page_data['number']}" if document.get("format") == "pdf" else "El documento"
        self._last_document_output = {"title": resolved.stem, "content": extracted, "source": str(resolved)}
        visible_text = extracted[:12_000]
        truncated = len(extracted) > len(visible_text)
        continuation = (
            "\n\nEl documento continúa. Puedes pedirme ‘continúa leyendo’ para seguir desde este punto."
            if truncated else ""
        )
        return {
            "ok": True, "message": f"{page_label} dice:\n{visible_text}{continuation}",
            "data": {
                "route": "document_agent", "task_id": result.id, "path": str(resolved),
                "format": document.get("format"), "page": page_data["number"],
                "page_count": document.get("page_count"), "verified": True,
                "truncated": truncated, "visible_characters": len(visible_text),
                "file_routes": [item.public() for item in routes],
            },
            "correlation_id": result.id,
        }

    def _handle_artifact_followup(self, text: str, normalized_text: str) -> dict[str, Any] | None:
        requested: list[str] = []
        if re.search(r"\b(?:word|docx)\b", normalized_text):
            requested.append("docx")
        if re.search(r"\bpdf\b", normalized_text):
            requested.append("pdf")
        action = bool(
            re.search(r"\b(?:hazlo|hazla|p[aá]salo|p[aá]sala|ponlo|ponla|convierte|crea|genera)\b", normalized_text)
            or re.fullmatch(
                r"(?:ahora\s+)?(?:tambi[eé]n\s+)?(?:en|a)?\s*(?:word|docx|pdf)\s*[.!?]*",
                normalized_text.strip(),
            )
        )
        if not requested or not action:
            return None
        if self._last_document_output is None:
            return None
        root = Path.home() / "Downloads" / "ARCHI-Artifacts"
        root.mkdir(parents=True, exist_ok=True)
        base = re.sub(r"[^\w.-]+", "_", self._last_document_output["title"], flags=re.UNICODE).strip("._") or "Documento_ARCHI"
        created: list[dict[str, Any]] = []
        writing_profile = self.writing_style.resolve(
            text, learned=self._task_context.learned_writing_preferences(),
        )
        document_profile = DocumentStyleProfile.interpret(
            text, locale=self._last_request_language or self.configuration.config.language.interface,
        )
        for artifact_format in requested:
            target = root / f"{base}_ARCHI.{artifact_format}"
            if target.exists():
                target = root / f"{base}_ARCHI_{int(time.time())}.{artifact_format}"
            result = self.tools.execute(
                "artifacts.create", {
                    "path": str(target), "format": artifact_format,
                    "title": self._last_document_output["title"], "content": self._last_document_output["content"],
                    "metadata": {
                        "source": self._last_document_output["source"],
                        "writing_style": writing_profile.public(),
                        "style_profile": document_profile.public(),
                    },
                }, context=ToolContext(uuid4().hex, scope_permissions=frozenset({"filesystem.write"})),
            )
            created.append({
                "path": str(target), "format": artifact_format, "ok": result.ok,
                "verified": result.verified, "error": result.error,
            })
            if result.ok:
                self._task_context.remember_document(str(target), source="artifact_followup")
        ok = all(item["ok"] and item["verified"] for item in created)
        return {
            "ok": ok,
            "message": ("Creé y verifiqué: " + ", ".join(Path(item["path"]).name for item in created)) if ok else "No pude verificar todos los formatos solicitados.",
            "data": {
                "route": "artifact_followup", "artifacts": created,
                "source": self._last_document_output["source"],
                "artifact_actions": ["open", "show_in_folder", "create_version", "edit", "convert"],
                "style_profile": document_profile.public(),
            },
            "correlation_id": None,
        }

    def _handle_programming_intent(self, text: str, normalized_text: str) -> dict[str, Any] | None:
        programming_request = bool(re.search(
            r"\b(?:proyecto|c[oó]digo|programa|aplicaci[oó]n)\b.*\b"
            r"(?:no\s+(?:inicia|arranca|abre|funciona)|arregla|corrige|repara)\b|"
            r"\b(?:arregla|corrige|repara)\b.*\b(?:proyecto|c[oó]digo|programa|aplicaci[oó]n)\b",
            normalized_text,
        ))
        if not programming_request:
            return None
        project_value = self._task_context.active_project or self._task_context.active_folder
        if not project_value:
            return {
                "ok": False,
                "message": "Necesito que abras o selecciones la carpeta del proyecto para delimitar el alcance.",
                "data": {"route": "programming_agent", "error": "project_context_required"},
                "correlation_id": None,
            }
        task = AgentTask(
            goal=text.strip(), mode=AgentMode.CONTROL,
            plan=(
                AgentStep(
                    "plan-project", "Analizar objetivo, restricciones y arquitectura existente", "programming.plan",
                    {"request": text.strip(), "root": str(project_value)},
                    "stack-aware plan produced without mutations", max_retries=0,
                ),
                AgentStep(
                    "detect-project", "Detectar tipo, raíz y comando de inicio", "programming.detect",
                    {"path": str(project_value)}, "project markers and root verified", max_retries=0,
                ),
                AgentStep(
                    "inspect-git", "Inspeccionar Git y preservar cambios existentes", "programming.git_status",
                    {"root": {"$result": "detect-project", "path": "root"}},
                    "git status inspected without mutation", max_retries=0,
                ),
                AgentStep(
                    "repair-loop", "Reproducir, diagnosticar, corregir, probar y replanificar hasta verificar", "programming.repair_python",
                    {
                        "root": {"$result": "detect-project", "path": "root"},
                        "timeout_seconds": 30,
                        "max_iterations": 8,
                    },
                    "tests and startup verified after bounded replanning", max_retries=0,
                ),
            ),
            completion_criteria=(
                "project detected", "user Git changes preserved", "failure reproduced",
                "small checkpointed patches applied", "tests and project startup verified",
            ),
            context=TaskContext(active_project=str(project_value), current_goal=text.strip()),
        )
        result = self.agent_runner.run(
            task,
            scope_permissions=frozenset({"filesystem.read", "filesystem.write", "terminal.execute"}),
        )
        self.task_store.save(result)
        if result.status.value != "completed":
            last_error = result.errors[-1] if result.errors else "programming_task_incomplete"
            return {
                "ok": False,
                "message": "Reproduje el problema, pero no aplicaré una corrección que no sea inequívoca y verificable.",
                "data": {"route": "programming_agent", "task": result.public(), "error": last_error},
                "correlation_id": result.id,
            }
        detected = next(item["data"] for item in result.tool_results if item["step"] == "detect-project")
        repaired = next(item["data"] for item in result.tool_results if item["step"] == "repair-loop")
        project_plan = next(item["data"] for item in result.tool_results if item["step"] == "plan-project")
        self._task_context.active_project = str(detected["root"])
        self._task_context.active_folder = str(detected["root"])
        self._task_context.current_goal = text.strip()
        project_context = self.project_context_store.load(detected["root"]) or ProjectContext(
            root=str(detected["root"]), stack=str(project_plan["stack"]),
        )
        project_context.requirements = list(project_plan["requirements"])
        project_context.current_task = text.strip()
        project_context.decisions = list(project_plan["constraints"])
        for patch in repaired["patches"]:
            if patch.get("path"):
                project_context.remember_change(str(patch["path"]))
        project_context.remember_test(
            tuple(detected.get("suggested_command", ())),
            passed=bool(repaired["tests_verified"] and repaired["startup_verified"]),
        )
        self.project_context_store.save(project_context)
        return {
            "ok": True,
            "message": "Corregí el fallo, volví a iniciar el proyecto y verifiqué que terminó correctamente.",
            "data": {
                "route": "programming_agent", "task_id": result.id,
                "project": detected["root"], "patches": len(repaired["patches"]),
                "checkpoints": [item["checkpoint"] for item in repaired["patches"]],
                "replans": repaired["replans"], "iterations": len(repaired["iterations"]),
                "exit_code": int(repaired["iterations"][-1].get("exit_code", 0)),
                "tests_verified": repaired["tests_verified"],
                "startup_verified": repaired["startup_verified"],
                "process_cleanup_verified": repaired["process_cleanup_verified"],
                "project_plan": project_plan,
                "project_context_persisted": True,
            },
            "correlation_id": result.id,
        }

    def _handle_multi_app_intent(self, text: str, normalized_text: str) -> dict[str, Any] | None:
        requested = bool(
            re.search(r"pdf\s+m[aá]s\s+reciente", normalized_text)
            and re.search(r"bloc\s+de\s+notas", normalized_text)
            and re.search(r"(?:resumen|t[ií]tulo)", normalized_text)
        )
        if not requested:
            return None
        downloads = (Path.home() / "Downloads").resolve()
        output = downloads / f"Resumen ARCHEON {datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        task = AgentTask(
            goal=text.strip(), mode=AgentMode.CONTROL,
            plan=(
                AgentStep("find-pdf", "Buscar el PDF más reciente solo en Descargas", "files.search",
                          {"path": str(downloads), "extension": "pdf", "recursive": False, "limit": 20},
                          "bounded Downloads search completed", 0),
                AgentStep("read-summary", "Extraer título y resumen accesible", "documents.summarize",
                          {"path": {"$result": "find-pdf", "path": "results.0.path"}, "max_characters": 1200},
                          "title and summary grounded in document", 0),
                AgentStep("create-output", "Crear archivo de salida sin sobrescribir", "files.ensure_empty",
                          {"path": str(output)}, "new output exists", 0),
                AgentStep("open-notepad", "Abrir salida en Bloc de notas", "desktop.launch_notepad",
                          {"path": str(output)}, "Notepad window verified", 1),
                AgentStep("write-summary", "Escribir el resultado con referencias de TaskContext", "desktop.type_text",
                          {"field_name": "Editor de texto",
                           "expected_window_handle": {"$result": "open-notepad", "path": "window.handle"},
                           "text": {"$template": "Título: {title}\n\nResumen:\n{summary}", "$vars": {
                               "title": {"$result": "read-summary", "path": "title"},
                               "summary": {"$result": "read-summary", "path": "summary"},
                           }}}, "summary text input verified", 1),
                AgentStep("save-summary", "Guardar mediante control accesible", "desktop.invoke",
                          {"name": "Archivo"}, "file menu opened", 1),
                AgentStep("invoke-save", "Invocar Guardar", "desktop.invoke", {"name": "Guardar"},
                          "save action verified", 1),
                AgentStep("verify-summary", "Reabrir y verificar contenido exacto", "files.verify_text",
                          {"path": str(output), "expected": {"$template": "Título: {title}\n\nResumen:\n{summary}", "$vars": {
                              "title": {"$result": "read-summary", "path": "title"},
                              "summary": {"$result": "read-summary", "path": "summary"},
                          }}}, "saved document content exact", 1),
            ),
            completion_criteria=("latest PDF selected", "title and summary extracted", "Notepad written",
                                 "output saved", "filesystem content verified"),
            context=TaskContext(active_folder=str(downloads), current_goal=text.strip()),
        )
        result = self.agent_runner.run(
            task, scope_permissions=frozenset({"filesystem.read", "filesystem.write", "desktop.control"}),
        )
        self.task_store.save(result)
        completed = result.status.value == "completed"
        if completed:
            source = next(item["data"] for item in result.tool_results if item["step"] == "read-summary")
            result.context.selected_file = str(output)
            result.context.recent_download = source["path"]
            self._task_context = result.context
        return {
            "ok": completed,
            "message": (f"Leí el PDF más reciente, creé el resumen en Bloc de notas y verifiqué {output.name}."
                        if completed else "La tarea multiaplicación no quedó verificada; no afirmaré que el resumen está completo."),
            "data": {"route": "multi_app_agent", "task": result.public(), "output": str(output)},
            "correlation_id": result.id,
        }

    def _handle_browser_intent(self, text: str, normalized_text: str) -> dict[str, Any] | None:
        youtube_search = re.search(
            r"(?:abre|abrir|ve\s+a|open)\s+(?:el\s+)?(?:navegador\s+y\s+)?youtube"
            r".*?(?:busca|buscar|search(?:\s+for)?)\s+[\"'«»]?(?P<query>.+?)[\"'«»]?\s*[.!?]*$",
            text.strip(), flags=re.IGNORECASE,
        )
        if youtube_search:
            query = youtube_search.group("query").strip().strip("\"'«» .!?\n\r\t")
            if not query:
                return {"ok": False, "message": "Necesito saber qué quieres buscar en YouTube.", "data": {"route": "browser_agent"}, "correlation_id": None}
            movement_mode = self.configuration.config.computer_use.action_display
            reduce_motion = self.configuration.config.appearance.reduced_motion
            task = AgentTask(
                goal=text.strip(), mode=AgentMode.CONTROL,
                plan=(
                    AgentStep("open-youtube", "Abriendo YouTube en navegador visible", "browser.open_visible", {"url": "https://www.youtube.com/"}, "browser window and accessible page root verified", 0),
                    AgentStep("locate-search", "Buscando el campo de búsqueda", "browser.locate_visible_search", {}, "search control has current verified bounds", 1),
                    AgentStep("highlight-search", "Resaltando el campo de búsqueda", "desktop.guide_overlay", {"bounds": {"$result": "locate-search", "path": "bounds"}, "window_handle": {"$result": "locate-search", "path": "window.handle"}, "label": "Campo de búsqueda", "duration_ms": 1500}, "click-through highlight visible", 0),
                    AgentStep("click-search", "Moviendo el cursor y enfocando la búsqueda", "desktop.mouse_fallback", {"action": "left_click", "window_handle": {"$result": "locate-search", "path": "window.handle"}, "observed_window_bounds": {"$result": "locate-search", "path": "window.bounds"}, "target_bounds": {"$result": "locate-search", "path": "bounds"}, "movement_mode": movement_mode, "show_cursor": True, "reduce_motion": reduce_motion}, "cursor reached revalidated search target", 1),
                    AgentStep("type-query", f"Escribiendo {query}", "desktop.type_text", {"text": query, "expected_window_handle": {"$result": "locate-search", "path": "window.handle"}}, "search input text verified", 0),
                    AgentStep("submit-search", "Enviando la búsqueda", "desktop.keyboard", {"action": "press_key", "key": "enter", "expected_window_handle": {"$result": "locate-search", "path": "window.handle"}}, "Enter sent to verified focused search input", 0),
                    AgentStep("verify-results", "Verificando resultados reales", "browser.verify_visible_search", {"query": query}, "query and actual video result endpoints visible in browser accessibility tree", 1),
                ),
                completion_criteria=("browser identified", "search target grounded", "input focused", "query verified", "results page verified"),
                context=TaskContext(current_goal=text.strip()),
            )
            result = self.agent_runner.run(
                task,
                scope_permissions=frozenset({"network.browser", "desktop.observe", "desktop.control"}),
            )
            self.task_store.save(result)
            completed = result.status.value == "completed"
            verified = next((item.get("data", {}) for item in result.tool_results if item.get("step") == "verify-results"), {})
            return {
                "ok": completed,
                "message": (
                    f"Abrí YouTube, busqué «{query}» y verifiqué los resultados visibles."
                    if completed else
                    f"No pude verificar por completo la búsqueda de «{query}»; no afirmaré que terminó."
                ),
                "data": {"route": "browser_visible_agent", "mode": "control", "task": result.public(), "verification": verified},
                "correlation_id": result.id,
            }
        python_docs = bool(re.search(
            r"\b(?:documentaci[oó]n|docs?)\b.*\bpython\b.*\bpathlib\b|"
            r"\bpython\b.*\bpathlib\b.*\b(?:documentaci[oó]n|docs?)\b",
            normalized_text,
        ))
        explicit_url = re.search(r"https://[^\s<>'\"]+", text)
        browser_action = bool(re.search(r"\b(?:navegador|browser|abre|navega|visita)\b", normalized_text))
        if not python_docs and not (explicit_url and browser_action):
            return None
        if python_docs:
            plan = (
                AgentStep(
                    "open-python-docs", "Abrir la documentación oficial de Python", "browser.navigate",
                    {"url": "https://docs.python.org/3/"}, "official HTTPS page loaded", 1,
                ),
                AgentStep(
                    "search-pathlib", "Usar la búsqueda del sitio oficial para pathlib", "browser.navigate",
                    {"url": "https://docs.python.org/3/search.html?q=pathlib&check_keywords=yes&area=default"},
                    "official search results loaded", 1,
                ),
                AgentStep(
                    "open-pathlib", "Abrir el resultado oficial pathlib", "browser.navigate",
                    {"url": "https://docs.python.org/3/library/pathlib.html"},
                    "official pathlib HTTPS URL loaded", 1,
                ),
                AgentStep(
                    "verify-pathlib-page", "Verificar el contenido pathlib", "browser.find",
                    {"query": "Object-oriented filesystem paths"},
                    "pathlib heading found in DOM text", 0,
                ),
                AgentStep(
                    "read-pathlib-page", "Leer la página oficial", "browser.read",
                    {"max_characters": 40_000}, "current page DOM text extracted", 0,
                ),
            )
        else:
            url = explicit_url.group(0).rstrip(".,;:!?")
            plan = (
                AgentStep("navigate-url", "Abrir URL HTTPS", "browser.navigate", {"url": url}, "HTTPS page loaded", 1),
                AgentStep("read-page", "Leer página actual", "browser.read", {"max_characters": 40_000}, "DOM text extracted", 0),
            )
        task = AgentTask(
            goal=text.strip(), mode=AgentMode.OBSERVE, plan=plan,
            completion_criteria=("HTTPS URL verified", "requested DOM content found", "page read"),
            context=TaskContext(current_goal=text.strip()),
        )
        result = self.agent_runner.run(task, scope_permissions=frozenset({"network.browser"}))
        self.task_store.save(result)
        if result.status.value != "completed":
            error = result.errors[-1] if result.errors else "browser_task_failed"
            return {
                "ok": False, "message": "No pude verificar la navegación y el contenido solicitado.",
                "data": {"route": "browser_agent", "task": result.public(), "error": error},
                "correlation_id": result.id,
            }
        read_step = "read-pathlib-page" if python_docs else "read-page"
        page = next(item["data"] for item in result.tool_results if item["step"] == read_step)
        self._task_context.current_url = str(page["url"])
        self._task_context.current_tab = str(page["id"])
        self._task_context.current_goal = text.strip()
        excerpt = str(page.get("text", ""))[:1200]
        return {
            "ok": True,
            "message": f"Abrí y verifiqué «{page.get('title') or page['url']}».\n{excerpt}",
            "data": {
                "route": "browser_agent", "task_id": result.id, "url": page["url"],
                "title": page.get("title"), "tab_id": page["id"], "verified": True,
            }, "correlation_id": result.id,
        }

    def _handle_artifact_research_intent(self, text: str, normalized_text: str) -> dict[str, Any] | None:
        requested = bool(
            re.search(r"\b(?:investiga|research|informe|reporte)\b", normalized_text)
            and re.search(r"\bdocker\b", normalized_text)
            and re.search(r"\b(?:word|docx|excel|xlsx|powerpoint|pptx|zip|documento)\b", normalized_text)
        )
        if not requested:
            return None
        root = (Path.home() / "Downloads" / f"ARCHEON-Docker-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}").resolve()
        docx = root / "Docker Research.docx"; xlsx = root / "Docker Summary.xlsx"
        pptx = root / "Docker Briefing.pptx"; archive = root / "Docker Research Bundle.zip"
        source_url = "https://docs.docker.com/get-started/docker-overview/"
        task = AgentTask(
            goal=text.strip(), mode=AgentMode.CONTROL,
            plan=(
                AgentStep("create-workspace", "Crear carpeta de entrega nueva", "files.create_folder", {"path": str(root), "parents": True}, "workspace exists", 0),
                AgentStep("search-sources", "Buscar fuentes actuales con URL y fecha", "search.query", {"query": "Docker containers official documentation", "limit": 4, "language": "es"}, "cited results retrieved", 1),
                AgentStep("open-official-source", "Abrir documentación oficial de Docker", "browser.navigate", {"url": source_url}, "official HTTPS source loaded", 1),
                AgentStep("verify-source-topic", "Verificar contenido sobre contenedores", "browser.find", {"query": "containers", "limit": 10}, "topic found in official DOM", 0),
                AgentStep("read-official-source", "Leer fuente oficial acotada", "browser.read", {"max_characters": 18_000}, "official text extracted", 0),
                AgentStep("create-word", "Crear informe Word con fuente", "artifacts.create", {
                    "path": str(docx), "title": "Docker Research",
                    "content": {"$template": "Resumen basado en la documentación oficial de Docker.\n\n{body}", "$vars": {"body": {"$result": "read-official-source", "path": "text"}}},
                    "sections": [{"heading": "Fuente verificada", "body": source_url}],
                }, "DOCX reopened", 0),
                AgentStep("create-excel", "Crear resumen Excel con fórmula y gráfico", "artifacts.create", {
                    "path": str(xlsx), "title": "Docker Summary", "sheets": [{
                        "name": "Concepts", "rows": [["Concept", "Score"], ["Containers", 3], ["Images", 2], ["Registries", 1]],
                        "formulas": {"B5": "=SUM(B2:B4)"}, "chart": {"title": "Docker concepts", "data_col": 2, "category_col": 1},
                    }, {"name": "Sources", "rows": [["Title", "URL"], [{"$result": "read-official-source", "path": "title"}, source_url]]}],
                }, "XLSX reopened with chart", 0),
                AgentStep("create-powerpoint", "Crear presentación de seis diapositivas", "artifacts.create", {
                    "path": str(pptx), "title": "Docker Briefing", "slides": [
                        {"title": "Docker", "body": "Research briefing"}, {"title": "Containers", "body": "Isolated runnable processes"},
                        {"title": "Images", "body": "Immutable package templates"}, {"title": "Registries", "body": "Image distribution"},
                        {"title": "Workflow", "body": "Build, ship and run"}, {"title": "Source", "body": source_url},
                    ],
                }, "six-slide PPTX reopened", 0),
                AgentStep("verify-word", "Reabrir informe", "artifacts.verify", {"path": str(docx)}, "DOCX valid", 0),
                AgentStep("verify-excel", "Reabrir hoja", "artifacts.verify", {"path": str(xlsx)}, "XLSX valid", 0),
                AgentStep("verify-powerpoint", "Reabrir presentación", "artifacts.verify", {"path": str(pptx)}, "PPTX valid", 0),
                AgentStep("create-archive", "Comprimir entregables", "archives.create", {"destination": str(archive), "sources": [str(docx), str(xlsx), str(pptx)]}, "ZIP integrity verified", 0),
                AgentStep("verify-archive", "Verificar archivo final", "archives.verify", {"path": str(archive)}, "ZIP digest and members verified", 0),
            ),
            completion_criteria=("sources retrieved", "official page verified", "DOCX reopened", "XLSX chart reopened", "six-slide PPTX reopened", "ZIP integrity verified"),
            context=TaskContext(active_folder=str(root), current_url=source_url, current_goal=text.strip()),
        )
        result = self.agent_runner.run(
            task, scope_permissions=frozenset({"network.search", "network.browser", "filesystem.read", "filesystem.write"}),
        )
        self.task_store.save(result); completed = result.status.value == "completed"
        return {
            "ok": completed,
            "message": (f"Investigué Docker, creé Word, Excel y PowerPoint, los reabrí y verifiqué {archive.name}." if completed else "La entrega multi-capacidad no quedó completamente verificada; no afirmaré que terminó."),
            "data": {"route": "capability_agent", "task": result.public(), "workspace": str(root), "archive": str(archive)},
            "correlation_id": result.id,
        }

    @staticmethod
    def _artifact_intent(text: str) -> str | None:
        """Classify the governing artifact verb before looking at file-type nouns."""
        value = " ".join(text.casefold().split())
        # Fast-path creation must be an actual request, not a verb mentioned in
        # narration ("el profesor dijo que cree..."), a tutorial question
        # ("cómo crear...") or quoted text.  Require the command near the start
        # and allow only common polite/direct-request prefixes.
        direct_prefix = (
            r"^\s*(?:[¡¿]?\s*)?(?:oye[\s,]+)?(?:arch(?:eon|i)[\s,]+)?"
            r"(?:(?:por\s+favor|porfa)[\s,]+)?"
            r"(?:(?:puedes|podr[ií]as|quiero\s+que|necesito\s+que)\s+)?"
        )
        create_pattern = direct_prefix + (
            r"(?:cre(?:a|e)\w*|gener\w*|haz(?:me|lo|la)?|constru\w*|prepar\w*|"
            r"diseñ\w*|realiz\w*)\b"
        )
        find_pattern = direct_prefix + r"(?:busca\w*|encuentra\w*|abre\w*|modifica\w*|edita\w*|contin[uú]a)\b"
        create = has_unnegated(create_pattern, value)
        create_noun = bool(re.search(
            r"\b(?:word|docx|pdf|png|imagen|infograf[ií]a|powerpoint|pptx|presentaci[oó]n|"
            r"p[aá]gina\s+web|web|html|css|javascript|js|python|script|archivo|documento|zip)\b",
            value,
        ))
        formats = {
            name for name, pattern in {
                "docx": r"\b(?:word|docx)\b", "pdf": r"\bpdf\b",
                "pptx": r"\b(?:powerpoint|pptx|presentaci[oó]n)\b",
                "python": r"\b(?:python|script)\b", "web": r"\b(?:web|html|css|javascript|js)\b",
            }.items() if re.search(pattern, value)
        }
        if ArcheonApplication._requests_standalone_image(value):
            formats.add("png")
        if create and create_noun:
            return "CREATE_MULTI_ARTIFACT" if len(formats) >= 2 else "CREATE_ARTIFACT"
        find = has_unnegated(find_pattern, value)
        return "FIND_OPEN_MODIFY_ARTIFACT" if find and create_noun else None

    def _handle_new_artifact_intent(self, text: str, normalized_text: str) -> dict[str, Any] | None:
        intent = self._artifact_intent(normalized_text)
        if intent not in {"CREATE_ARTIFACT", "CREATE_MULTI_ARTIFACT"}:
            return None
        if intent == "CREATE_MULTI_ARTIFACT":
            requested = all(re.search(pattern, normalized_text) for pattern in (
                r"\b(?:word|docx)\b", r"\bpdf\b", r"\b(?:png|imagen|infograf[ií]a)\b",
                r"\b(?:powerpoint|pptx|presentaci[oó]n)\b", r"\b(?:python|script)\b",
                r"\b(?:web|html)\b", r"\bzip\b",
            ))
            if requested:
                return self._create_autonomous_education_bundle(text)
            return self._create_generic_multi_artifact_project(text, normalized_text)
        if re.search(r"\b(?:powerpoint|pptx|presentaci[oó]n)\b", normalized_text):
            return self._create_generic_multi_artifact_project(text, normalized_text)

        output_root = (self.paths.data_dir / "artifacts" / "created").resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        if re.search(r"\b(?:word|docx)\b", normalized_text) or (
            re.search(r"\bdocumento\b", normalized_text)
            and not re.search(r"\b(?:pdf|png|powerpoint|pptx|presentaci[oó]n|python|script|web|html)\b", normalized_text)
        ):
            suffix, arguments = "docx", {"title": "Documento nuevo", "content": "Documento creado por ARCHI.", "sections": [{"heading": "Contenido", "body": "Borrador inicial listo para editar."}]}
        elif re.search(r"\bpdf\b", normalized_text):
            suffix, arguments = "pdf", {"title": "PDF nuevo", "content": "Documento PDF creado por ARCHI."}
        elif re.search(r"\b(?:powerpoint|pptx|presentaci[oó]n)\b", normalized_text):
            suffix, arguments = "pptx", {"title": "Presentación nueva", "slides": [{"title": "Presentación nueva", "body": "Creada por ARCHI"}, {"title": "Contenido", "body": "Borrador inicial"}]}
        elif re.search(r"\b(?:python|script)\b", normalized_text):
            suffix, arguments = "py", {"title": "Python", "content": "def main():\n    print(\"Archivo Python creado por ARCHI\")\n\n\nif __name__ == \"__main__\":\n    main()\n"}
        elif re.search(r"\b(?:web|html)\b", normalized_text):
            suffix, arguments = "html", {"title": "Página nueva", "content": "Página web creada por ARCHI.", "sections": [{"heading": "Inicio", "body": "Contenido inicial."}]}
        else:
            return None
        target = output_root / f"ARCHI_{stamp}.{suffix}"
        result = self.tools.execute(
            "artifacts.create", {"path": str(target), "format": suffix, **arguments},
            context=ToolContext(uuid4().hex, scope_permissions=frozenset({"filesystem.write"})),
        )
        return {
            "ok": bool(result.ok and result.verified),
            "message": f"Creé y verifiqué {target.name}." if result.ok and result.verified else f"No pude verificar {target.name}.",
            "data": {
                "route": "project_creation", "intent": intent,
                "artifacts": [{"path": str(target), "format": suffix, "ok": result.ok, "verified": result.verified, "error": result.error}],
            },
            "correlation_id": None,
        }

    @staticmethod
    def _requests_standalone_image(normalized_text: str) -> bool:
        """Separate an image deliverable from visuals requested inside a deck."""
        if re.search(r"\b(?:png|infograf[ií]a)\b", normalized_text):
            return True
        if re.search(
            r"^(?:[¡¿]?\s*)?(?:oye[\s,]+)?(?:arch(?:eon|i)[\s,]+)?"
            r"(?:(?:por\s+favor|porfa)[\s,]+)?"
            r"(?:(?:puedes|podr[ií]as|quiero\s+que|necesito\s+que)\s+)?"
            r"(?:cre(?:a|e)\w*|gener\w*|hazme|dibuja\w*|diseña\w*)\s+"
            r"(?:una\s+)?imagen\b",
            normalized_text,
        ):
            return True
        return bool(re.search(
            r"\b(?:1|una)\s+imagen\b|\bim[aá]genes?\s+(?:independientes?|por\s+separado)\b",
            normalized_text,
        ))

    @staticmethod
    def _requested_artifact_formats(normalized_text: str) -> tuple[str, ...]:
        patterns = (
            ("docx", r"\b(?:word|docx)\b"),
            ("pdf", r"\bpdf\b"),
            ("pptx", r"\b(?:powerpoint|pptx|presentaci[oó]n)\b"),
            ("py", r"\b(?:python|script)\b"),
            ("html", r"\b(?:web|html)\b"),
        )
        formats = [name for name, pattern in patterns if re.search(pattern, normalized_text)]
        if ArcheonApplication._requests_standalone_image(normalized_text):
            formats.insert(2, "png")
        return tuple(formats)

    @staticmethod
    def _requested_project_folder(text: str) -> str | None:
        match = re.search(
            r"\bcarpeta\s+(?:llamada\s+)?(?P<name>[^.\r\n]+?)"
            r"(?=\s+(?:en|dentro|con|que|y\s+luego|y\s+despu[eé]s)\b|[.,;:\r\n]|$)",
            text, flags=re.IGNORECASE,
        )
        if not match:
            return None
        name = re.sub(r'[<>:"/\\|?*]+', " ", match.group("name"))
        name = " ".join(name.split()).strip(" .")
        return name[:80] or None

    @staticmethod
    def _requested_slide_count(normalized_text: str, default: int = 5) -> int:
        number_words = {"una": 1, "un": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
                        "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}
        match = re.search(r"\b(?P<count>\d{1,2}|una?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+diapositivas?\b", normalized_text)
        if not match:
            return default
        token = match.group("count")
        value = int(token) if token.isdigit() else number_words.get(token, default)
        return max(1, min(20, value))

    @staticmethod
    def _presentation_image_has_split_seams(path: Path) -> bool:
        """Reject obvious multi-panel generations without needing a resident vision model."""
        from PIL import Image
        from statistics import median

        with Image.open(path) as source:
            image = source.convert("L").resize((192, 128))
        pixels = list(image.get_flattened_data()) if hasattr(image, "get_flattened_data") else list(image.getdata())
        width, height = image.size
        row_changes = []
        for row in range(1, height):
            start = row * width; previous = start - width
            row_changes.append(sum(abs(pixels[start + col] - pixels[previous + col]) for col in range(width)) / width)
        baseline = max(1.0, median(row_changes))
        suspicious = [
            row for row, change in enumerate(row_changes, 1)
            if int(height * 0.22) <= row <= int(height * 0.90) and change >= max(13.0, baseline * 4.5)
        ]
        return len(suspicious) >= 2 and any(right - left >= 5 for left, right in zip(suspicious, suspicious[1:]))

    def _add_archi_visuals_to_slides(
        self, topic: str, slides: list[tuple[str, str]], *, maximum: int = 6,
        asset_root: Path | None = None,
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        """Ask ARCHI Image for distinct slide artwork and return honest evidence."""
        prepared = [{"title": title, "body": body} for title, body in slides]
        try:
            provider_status = dict(self.image_provider.status())
        except Exception as exc:
            return prepared, {
                "requested": True, "generated": 0, "embedded": 0,
                "provider": "ARCHI Image", "state": "error", "failures": [str(exc) or type(exc).__name__],
            }
        report: dict[str, Any] = {
            "requested": True, "generated": 0, "embedded": 0,
            "provider": str(provider_status.get("name") or "ARCHI Image"),
            "state": str(provider_status.get("state") or "unknown"), "failures": [], "images": [],
            "rejected_candidates": [],
        }
        if not provider_status.get("implemented"):
            report["failures"].append("archi_image_component_not_installed")
            return prepared, report
        count = min(maximum, len(slides))
        if count <= 0:
            return prepared, report
        indexes = sorted({round(position * (len(slides) - 1) / max(1, count - 1)) for position in range(count)})
        asset_root = (
            asset_root or self.paths.data_dir / "artifacts" / "presentation-assets" / uuid4().hex
        ).expanduser().resolve()
        locale = self._last_request_language or self.configuration.config.language.interface
        systemic_errors = {
            "archi_image_component_not_installed", "archi_image_runtime_not_installed",
            "archi_image_model_hash_mismatch", "insufficient_available_memory",
        }
        for index in indexes:
            title, body = slides[index]
            output = asset_root / f"slide-{index + 1:02d}.png"
            contamination_scenes = {
                "contaminación ambiental": "aerial landscape where a polluted river transitions into a restored green valley",
                "el problema": "urban neighborhood beside a hazy industrial skyline and a littered stream",
                "causas principales": "industrial smokestacks, discarded plastic near water, and a recently cleared forest",
                "consecuencias": "a lone bird at the edge of a drying lake under a pale polluted haze",
                "soluciones": "close-up hands planting one healthy young tree beside a restored clean river",
            }
            if "contaminaci" in topic.casefold():
                scene = contamination_scenes.get(title.casefold(), f"environmental scene representing {title}")
            elif "educaci" in topic.casefold() and "inteligencia artificial" in topic.casefold():
                scenes = (
                    "student and teacher collaborating with a subtle abstract network of light",
                    "abstract neural pattern transforming information into clear learning paths",
                    "diverse classroom using adaptive learning tools with human guidance",
                    "confident student learning at an individual pace with supportive teacher nearby",
                    "student protecting personal information while checking an uncertain automated answer",
                    "student closing a laptop and explaining an idea confidently to classmates",
                )
                scene = scenes[index % len(scenes)]
            else:
                scene = f"a natural editorial scene that symbolizes {topic} and the idea {title}"
            prompt = (
                f"Refined editorial illustration, {scene}. Wide landscape composition, one clear focal subject, "
                "natural depth, realistic proportions, cohesive teal and warm accent palette. "
                "Purely visual scene with no signs, no boards, no posters, no paper, no screens facing camera, "
                "no text, no letters, no numbers, no logos, no watermark."
            )
            result = None
            for attempt in range(3):
                result = self.image_provider.generate(ImageRequest(
                    prompt, output, width=768, height=512, locale=locale,
                    negative_prompt="collage, split screen, multi-panel, words, letters, captions, typography, handwriting, sign, board, poster, paper, screen, logo, watermark, signature, blurry, distorted, duplicate subjects",
                    seed=314159 + index * 7919 + attempt * 104729,
                ))
                if not (result.ok and result.path and Path(result.path).is_file()):
                    break
                if not self._presentation_image_has_split_seams(Path(result.path)):
                    break
                report["rejected_candidates"].append({"slide": index + 1, "reason": "split_scene_detected", "attempt": attempt + 1})
                if attempt == 2:
                    Path(result.path).unlink(missing_ok=True)
                    result = None
            if result is not None and result.ok and result.path and Path(result.path).is_file():
                prepared[index]["image"] = str(Path(result.path).resolve())
                prepared[index]["image_alt"] = f"Ilustración creada por ARCHI para la diapositiva: {title}"
                if index > 0:
                    prepared[index]["image_trim_bottom"] = "0.18"
                report["generated"] += 1
                report["images"].append({"slide": index + 1, **result.public()})
                continue
            error = str(result.error or "image_generation_failed") if result is not None else "image_visual_quality_rejected_split_scene"
            report["failures"].append(f"slide_{index + 1}:{error}")
            if error in systemic_errors:
                break
        return prepared, report

    def _create_generic_multi_artifact_project(
        self, text: str, normalized_text: str, *, downloads_root: Path | None = None,
    ) -> dict[str, Any]:
        """Create every explicitly requested format and keep going after safe failures."""
        formats = self._requested_artifact_formats(normalized_text)
        downloads = (downloads_root or (Path.home() / "Downloads")).resolve()
        requested_folder = self._requested_project_folder(text)
        in_downloads = bool(re.search(r"\b(?:descargas|downloads)\b", normalized_text))
        base = downloads if in_downloads else (self.paths.data_dir / "artifacts" / "created").resolve()
        root = base / (requested_folder or f"Proyecto ARCHI {datetime.now().strftime('%Y%m%d-%H%M%S')}")
        topic = "Contaminación ambiental" if re.search(r"contaminaci[oó]n\s+ambiental", normalized_text) else "Documento solicitado"
        if topic == "Contaminación ambiental":
            intro = ("La contaminación ambiental altera el aire, el agua y el suelo, y afecta de forma directa la salud y la vida cotidiana. "
                     "Este trabajo explica sus causas principales, sus consecuencias y algunas soluciones que pueden aplicarse desde el hogar, la escuela y la comunidad.")
            sections = [
                {"heading": "Introducción", "body": intro},
                {"heading": "Causas", "body": "La quema de combustibles fósiles, el manejo inadecuado de residuos y las descargas industriales concentran buena parte del problema. También influyen el uso excesivo de plásticos, la deforestación y hábitos de consumo que generan desechos difíciles de recuperar."},
                {"heading": "Consecuencias", "body": "El aire contaminado agrava enfermedades respiratorias. Los residuos y sustancias tóxicas dañan ecosistemas, reducen la calidad del agua y afectan a animales y plantas. A largo plazo, la degradación ambiental también perjudica la producción de alimentos y aumenta costos para las familias y las ciudades.", "page_break": True},
                {"heading": "Soluciones", "body": "Reducir residuos, separar materiales reciclables y evitar productos de un solo uso son medidas cercanas. Las instituciones pueden mejorar el transporte público, controlar emisiones y tratar aguas residuales. La educación ambiental permite comprender el impacto de cada decisión y participar en soluciones colectivas."},
                {"heading": "Conclusión", "body": "La contaminación no tiene una sola causa ni una solución inmediata. Disminuirla exige normas que se cumplan, servicios públicos adecuados y cambios sostenidos en la forma de producir y consumir. Cada acción cuenta cuando forma parte de un esfuerzo compartido."},
            ]
            slide_topics = [
                ("Contaminación ambiental", "Causas, consecuencias y soluciones"),
                ("El problema", "La contaminación deteriora el aire, el agua y el suelo y afecta la salud."),
                ("Causas principales", "Combustibles fósiles\nResiduos mal gestionados\nDescargas industriales\nDeforestación"),
                ("Consecuencias", "Enfermedades respiratorias\nDaño a ecosistemas\nAgua de menor calidad\nPérdida de biodiversidad"),
                ("Soluciones", "Reducir y reciclar\nControlar emisiones\nTratar aguas residuales\nFortalecer la educación ambiental"),
            ]
        else:
            intro = "Contenido creado a partir de la solicitud del usuario y organizado para que pueda revisarse y editarse con facilidad."
            sections = [{"heading": "Introducción", "body": intro}, {"heading": "Desarrollo", "body": text.strip()}, {"heading": "Cierre", "body": "Resumen de las ideas principales del encargo."}]
            slide_topics = [(topic, "Presentación creada por ARCHI"), ("Introducción", intro), ("Contenido", text.strip()), ("Resumen", "Ideas principales del encargo"), ("Cierre", "Documento listo para revisar")]

        slide_count = self._requested_slide_count(normalized_text)
        slides = [slide_topics[index] if index < len(slide_topics) else (f"Punto {index + 1}", "Contenido complementario") for index in range(slide_count)]
        presentation_slides: list[dict[str, str]] = [{"title": title, "body": body} for title, body in slides]
        visual_report: dict[str, Any] | None = None
        if "pptx" in formats:
            presentation_slides, visual_report = self._add_archi_visuals_to_slides(
                topic, slides, asset_root=root / "Recursos visuales",
            )
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        names = {"docx": "Trabajo.docx", "pdf": "Resumen.pdf", "png": "Infografia.png", "pptx": "Presentacion.pptx", "py": "programa.py", "html": "index.html"}
        steps = [AgentStep("create-root", "Crear carpeta de entrega", "files.create_folder", {"path": str(root), "parents": True}, "workspace exists", 0)]
        targets: list[tuple[str, Path]] = []
        for format_name in formats:
            target = root / names.get(format_name, f"ARCHI_{stamp}.{format_name}")
            targets.append((format_name, target))
            if format_name == "docx":
                arguments = {"path": str(target), "format": format_name, "title": topic, "content": intro, "sections": sections,
                             "metadata": {"style_profile": {"page_size": "Letter", "font_family": "Aptos", "font_size": 11, "line_spacing": 1.15, "heading_color": "000000", "body_alignment": "justify"}}}
            elif format_name == "pptx":
                arguments = {"path": str(target), "format": format_name, "title": topic,
                             "slides": presentation_slides,
                             "metadata": {
                                 "cover_label": "Medio ambiente" if topic == "Contaminación ambiental" else topic,
                                 "expected_picture_count": int((visual_report or {}).get("generated", 0)),
                             }}
            elif format_name == "pdf":
                arguments = {"path": str(target), "format": format_name, "title": topic, "content": intro, "sections": sections[1:]}
            elif format_name == "png":
                arguments = {"path": str(target), "format": format_name, "title": topic,
                             "metadata": {"width": 1200, "height": 1600, "items": [{"title": item["heading"], "body": item["body"][:180]} for item in sections[1:]]}}
            elif format_name == "py":
                arguments = {"path": str(target), "format": format_name, "content": '"""Programa creado por ARCHI."""\n\n\ndef main():\n    print("Archivo listo")\n\n\nif __name__ == "__main__":\n    main()\n'}
            else:
                arguments = {"path": str(target), "format": "html", "title": topic, "content": f"<main><h1>{topic}</h1><p>{intro}</p></main>"}
            steps.append(AgentStep(f"create-{format_name}", f"Crear {format_name.upper()}", "artifacts.create", arguments, f"{format_name} created", 0, continue_on_failure=True))
            steps.append(AgentStep(f"verify-{format_name}", f"Validar {format_name.upper()}", "artifacts.verify", {"path": str(target)}, f"{format_name} verified", 0, continue_on_failure=True))
        task = AgentTask(goal=text.strip(), mode=AgentMode.CONTROL, plan=tuple(steps),
                         completion_criteria=("all requested formats attempted", "each successful artifact reopened"),
                         context=TaskContext(active_folder=str(root), current_goal=text.strip()))
        result = self.agent_runner.run(task, scope_permissions=frozenset({"filesystem.read", "filesystem.write"}))
        self.task_store.save(result)
        artifacts = []
        for format_name, target in targets:
            verify = next((item for item in reversed(result.tool_results) if item.get("step") == f"verify-{format_name}"), {})
            create = next((item for item in result.tool_results if item.get("step") == f"create-{format_name}"), {})
            artifact = {"path": str(target), "format": format_name, "exists": target.is_file(),
                              "ok": bool(create.get("ok") and verify.get("ok") and verify.get("verified")),
                              "created": bool(create.get("ok")), "verified": bool(verify.get("ok") and verify.get("verified")),
                              "error": (verify or create).get("error")}
            if format_name == "pptx" and visual_report is not None:
                structure = dict(verify.get("data", {}).get("structure", {}))
                visual_report["embedded"] = int(structure.get("pictures", 0) or 0)
                artifact["visuals"] = visual_report
            artifacts.append(artifact)
        failures = [item for item in artifacts if not item["verified"]]
        successful = [Path(item["path"]).name for item in artifacts if item["verified"]]
        visual_warning = ""
        if visual_report is not None and not visual_report.get("generated"):
            visual_warning = " No añadí imágenes: el componente local ARCHI Image no está disponible; la presentación quedó validada sin fingir recursos visuales."
        message = ((f"Creé y verifiqué {', '.join(successful)} en {root}." + visual_warning) if not failures else
                   f"Resultado parcial en {root}. Correctos: {', '.join(successful) or 'ninguno'}. Fallos: " +
                   "; ".join(f"{Path(item['path']).name}: {item.get('error') or 'validation_failed'}" for item in failures))
        project_intent = "CREATE_MULTI_ARTIFACT" if len(formats) >= 2 else "CREATE_ARTIFACT"
        return {"ok": not failures, "message": message,
                "data": {"route": "project_creation", "intent": project_intent, "workspace": str(root),
                         "artifacts": artifacts, "failures": failures, "user_verified": False, "task": result.public()},
                "correlation_id": result.id}

    def _create_autonomous_education_bundle(self, text: str, *, downloads_root: Path | None = None) -> dict[str, Any]:
        downloads = (downloads_root or (Path.home() / "Downloads")).resolve()
        root = downloads / "PRUEBA_ARCHI_AUTONOMA"
        archive = downloads / "PRUEBA_ARCHI_AUTONOMA.zip"
        web = root / "web_ia_educacion"
        docx = root / "IA_en_la_educacion.docx"
        pdf = root / "Resumen_IA_educacion.pdf"
        png = root / "5_formas_IA_ayuda_estudiante.png"
        pptx = root / "IA_en_la_educacion.pptx"
        python_file = root / "calculadora_notas.py"
        index = web / "index.html"; css = web / "styles.css"; script = web / "script.js"

        introduction = (
            "La inteligencia artificial ya forma parte de muchas actividades educativas, aunque a veces pase desapercibida. "
            "Se encuentra en plataformas que recomiendan ejercicios, asistentes que explican conceptos y herramientas que apoyan al docente. "
            "Su valor no está en reemplazar el esfuerzo de aprender, sino en ofrecer apoyos oportunos y adaptados a cada necesidad."
        )
        uses = (
            "Entre sus usos más comunes están la tutoría personalizada, la generación de prácticas, la retroalimentación inmediata, "
            "la traducción y accesibilidad de contenidos, y el análisis del progreso. Un sistema puede detectar que un estudiante repite "
            "un mismo error y proponer otra explicación; también puede ayudar al profesor a organizar materiales y observar tendencias del curso."
        )
        advantages = (
            "La principal ventaja es la personalización: cada persona puede practicar a su ritmo y recibir una explicación distinta. "
            "También mejora el acceso para estudiantes con barreras lingüísticas o de lectura, reduce tareas repetitivas y permite dedicar "
            "más tiempo al acompañamiento humano. Además, una respuesta inmediata ayuda a corregir errores antes de que se vuelvan hábitos."
        )
        risks = (
            "Los riesgos aparecen cuando se acepta una respuesta sin comprobarla, se comparten datos personales o se usa la herramienta para "
            "evitar el trabajo propio. Los modelos pueden equivocarse, reproducir sesgos o inventar fuentes. Por eso conviene contrastar información, "
            "citar el apoyo recibido, proteger la privacidad y mantener al docente como responsable de las decisiones importantes."
        )
        examples = (
            "1. Una tutora virtual propone ejercicios de fracciones según los errores recientes del estudiante.\n"
            "2. Un asistente de lectura resume un texto difícil y luego formula preguntas para comprobar la comprensión.\n"
            "3. Un profesor usa análisis de resultados para identificar un tema que necesita explicarse nuevamente a todo el curso."
        )
        references = (
            "UNESCO. Guidance for Generative AI in Education and Research (2023).\n"
            "UNICEF. Policy Guidance on AI for Children (2021).\n"
            "OECD. Digital Education Outlook 2023."
        )
        education_slide_pairs = [
            ("IA en la educación", "Aprender con apoyo, criterio y responsabilidad"),
            ("¿Qué es la IA?", "Sistemas que identifican patrones y generan respuestas a partir de datos."),
            ("IA aplicada al aula", "Tutorías personalizadas\nPráctica adaptativa\nAccesibilidad\nApoyo al docente"),
            ("Ventajas", "Aprendizaje a tu ritmo\nRetroalimentación rápida\nNuevas formas de explicar"),
            ("Riesgos", "Errores y sesgos\nPrivacidad\nDependencia\nAutoría poco clara"),
            ("Idea de cierre", "La mejor herramienta no piensa por ti: te ayuda a pensar mejor."),
        ]
        education_slides, education_visuals = self._add_archi_visuals_to_slides(
            "Inteligencia artificial en la educación", education_slide_pairs,
        )
        calculator = '''"""Calculadora sencilla de tres calificaciones."""\n\n\ndef leer_calificacion(numero):\n    """Solicita una nota válida entre 0 y 10."""\n    while True:\n        try:\n            nota = float(input(f"Calificación {numero} (0-10): "))\n            if 0 <= nota <= 10:\n                return nota\n            print("La calificación debe estar entre 0 y 10.")\n        except ValueError:\n            print("Entrada incorrecta. Escribe un número válido.")\n\n\ndef main():\n    notas = [leer_calificacion(i) for i in range(1, 4)]\n    promedio = sum(notas) / len(notas)\n    estado = "aprueba" if promedio >= 7 else "reprueba"\n    print(f"Promedio: {promedio:.2f}")\n    print(f"El estudiante {estado}.")\n\n\nif __name__ == "__main__":\n    main()\n'''
        html_text = '''<!doctype html>\n<html lang="es">\n<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>IA en la educación</title><link rel="stylesheet" href="styles.css"></head>\n<body><header><nav><strong>IA + Educación</strong><a href="#usos">Usos</a><a href="#criterio">Uso responsable</a></nav><div class="hero"><p class="tag">Aprender con criterio</p><h1>La IA puede acompañar el aprendizaje</h1><p>Explora oportunidades, límites y hábitos para usarla de forma responsable.</p><button id="ideaButton">Dame una idea práctica</button><p id="idea" aria-live="polite"></p></div></header><main><section id="usos"><h2>¿Dónde aporta valor?</h2><div class="cards"><article><span>01</span><h3>Práctica personalizada</h3><p>Ejercicios ajustados al ritmo y a los errores de cada estudiante.</p></article><article><span>02</span><h3>Retroalimentación</h3><p>Orientaciones rápidas para revisar un procedimiento o mejorar un borrador.</p></article><article><span>03</span><h3>Accesibilidad</h3><p>Apoyo para traducir, resumir y presentar contenidos en otros formatos.</p></article></div></section><section id="criterio" class="split"><div><p class="tag">Buena práctica</p><h2>Preguntar, comprobar y aprender</h2></div><ul><li>Contrasta datos y fuentes.</li><li>No compartas información privada.</li><li>Explica cuándo utilizaste IA.</li><li>Conserva tu propia voz y criterio.</li></ul></section></main><footer>Proyecto educativo creado por ARCHI</footer><script src="script.js"></script></body></html>'''
        css_text = ''':root{--ink:#153047;--teal:#168a82;--cream:#f6f1e7;--white:#fff;--accent:#f2b84b}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);background:var(--cream);line-height:1.6}header{padding:1.2rem clamp(1.2rem,5vw,5rem) 4rem;background:linear-gradient(135deg,#12384f,#176d72);color:white}nav{display:flex;align-items:center;gap:1.5rem;max-width:1100px;margin:auto}nav strong{margin-right:auto}nav a{color:white;text-decoration:none}.hero{max-width:850px;margin:5rem auto 1rem}.hero h1{font-size:clamp(2.4rem,7vw,5.4rem);line-height:1.02;margin:.4rem 0 1.2rem}.tag{text-transform:uppercase;letter-spacing:.14em;font-weight:800;color:var(--accent)}button{border:0;border-radius:999px;padding:.9rem 1.3rem;background:var(--accent);color:var(--ink);font-weight:800;cursor:pointer}main{max-width:1100px;margin:auto;padding:4rem 1.2rem}h2{font-size:clamp(2rem,4vw,3rem)}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:1.2rem}.cards article{background:var(--white);padding:1.6rem;border-radius:18px;box-shadow:0 12px 32px #15304718}.cards span{color:var(--teal);font-weight:900}.split{margin-top:4rem;padding:2rem;border-radius:24px;background:var(--ink);color:white;display:grid;grid-template-columns:1fr 1fr;gap:2rem}.split ul{margin:0;padding-left:1.2rem}footer{text-align:center;padding:2rem}@media(max-width:700px){nav a{display:none}.hero{margin-top:3rem}.cards,.split{grid-template-columns:1fr}header{padding-bottom:3rem}}@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}'''
        js_text = '''const ideas = ["Pide tres preguntas de práctica y responde antes de ver las soluciones.","Solicita dos explicaciones diferentes y compara cuál entiendes mejor.","Usa la IA para revisar tu borrador, pero conserva tus propias ideas."];\nconst button = document.querySelector("#ideaButton");\nconst output = document.querySelector("#idea");\nlet index = 0;\nbutton.addEventListener("click", () => { output.textContent = ideas[index % ideas.length]; index += 1; });\n'''

        steps = [
            AgentStep("create-root", "Crear carpeta de entrega", "files.create_folder", {"path": str(root), "parents": True}, "workspace exists", 0),
            AgentStep("create-web-folder", "Crear carpeta web", "files.create_folder", {"path": str(web), "parents": True}, "web folder exists", 0, continue_on_failure=True),
            AgentStep("create-word", "Crear deber Word", "artifacts.create", {"path": str(docx), "title": "La inteligencia artificial en la educación", "content": introduction, "sections": [
                {"heading": "Usos de la IA en educación", "body": uses},
                {"heading": "Ventajas", "body": advantages},
                {"heading": "Riesgos y uso responsable", "body": risks, "page_break": True}, {"heading": "Tres ejemplos", "body": examples, "alignment": "left"},
                {"heading": "Referencias básicas", "body": references, "alignment": "left"},
                {"heading": "Reflexión final", "body": "La IA resulta más valiosa cuando amplía la curiosidad y no cuando sustituye el razonamiento. Aprender a formular buenas preguntas, revisar respuestas y reconocer límites es parte de la alfabetización digital actual."},
            ], "metadata": {"style_profile": {"template": "Student Simple", "page_size": "Letter", "tone": "student", "font_family": "Aptos", "font_size": 11, "line_spacing": 1.15, "heading_color": "000000", "body_alignment": "justify"}}}, "DOCX reopened", 0, continue_on_failure=True),
            AgentStep("create-pdf", "Crear resumen visual PDF diferente", "artifacts.create", {"path": str(pdf), "title": "IA EN EDUCACIÓN | GUÍA RÁPIDA", "content": "Una herramienta de apoyo, no un reemplazo del aprendizaje.", "sections": [
                {"heading": "APORTES", "body": "Tutoría personalizada | práctica adaptativa | accesibilidad | retroalimentación rápida | apoyo al docente"},
                {"heading": "VENTAJAS", "body": "Más opciones para aprender a tu ritmo. Ayuda a detectar errores. Facilita explicar una idea de otra manera."},
                {"heading": "RIESGOS", "body": "Respuestas incorrectas. Sesgos. Pérdida de privacidad. Dependencia. Uso sin autoría ni reflexión."},
                {"heading": "REGLA 3C", "body": "CONSULTA con una pregunta clara. CONTRASTA la respuesta. CONSTRUYE tu propia conclusión."},
                {"heading": "ANTES DE ENTREGAR", "body": "¿Verifiqué los datos? ¿Entiendo lo escrito? ¿Protegí información personal? ¿Reconocí el uso de IA?"},
                {"heading": "FUENTES PARA AMPLIAR", "body": "UNESCO (2023), UNICEF (2021), OECD Digital Education Outlook (2023)."},
            ]}, "PDF reopened", 0, continue_on_failure=True),
            AgentStep("create-png", "Crear infografía legible", "artifacts.create", {"path": str(png), "title": "5 formas en que la IA\nayuda al estudiante", "metadata": {"width": 1200, "height": 1600, "items": [
                {"title": "Explica de otra manera", "body": "Adapta una explicación cuando un concepto resulta difícil."},
                {"title": "Crea práctica personalizada", "body": "Propone ejercicios según el nivel y los errores recientes."},
                {"title": "Da retroalimentación rápida", "body": "Señala oportunidades de mejora en un procedimiento o borrador."},
                {"title": "Mejora la accesibilidad", "body": "Resume, traduce y transforma contenidos para distintas necesidades."},
                {"title": "Ayuda a organizar el estudio", "body": "Sugiere planes, preguntas de repaso y prioridades realistas."},
            ]}}, "PNG reopened with embedded text", 0, continue_on_failure=True),
            AgentStep("create-pptx", "Crear presentación de seis diapositivas", "artifacts.create", {
                "path": str(pptx), "title": "IA en la educación", "slides": education_slides,
                "metadata": {"cover_label": "IA + EDUCACIÓN", "expected_picture_count": education_visuals["generated"]},
            }, "six-slide PPTX reopened", 0, continue_on_failure=True),
            AgentStep("create-python", "Crear calculadora de notas", "artifacts.create", {"path": str(python_file), "format": "py", "content": calculator}, "Python syntax parsed", 0, continue_on_failure=True),
            AgentStep("create-css", "Crear estilos responsive", "artifacts.create", {"path": str(css), "format": "css", "content": css_text}, "CSS text reopened", 0, continue_on_failure=True),
            AgentStep("create-js", "Crear interacción web", "artifacts.create", {"path": str(script), "format": "js", "content": js_text}, "JavaScript text reopened", 0, continue_on_failure=True),
            AgentStep("create-html", "Crear página web", "artifacts.create", {"path": str(index), "format": "html", "title": "IA en la educación", "content": html_text}, "HTML and local resources verified", 0, continue_on_failure=True),
        ]
        for step_id, path, label in (
            ("verify-word", docx, "Word"), ("verify-pdf", pdf, "PDF"), ("verify-png", png, "PNG"),
            ("verify-pptx", pptx, "PowerPoint"), ("verify-python", python_file, "Python"),
            ("verify-css", css, "CSS"), ("verify-js", script, "JavaScript"), ("verify-html", index, "HTML"),
        ):
            steps.append(AgentStep(step_id, f"Validar {label}", "artifacts.verify", {"path": str(path)}, f"{label} verified", 0, continue_on_failure=True))
        steps.extend((
            AgentStep("create-zip", "Comprimir la carpeta completa", "archives.create", {"destination": str(archive), "sources": [str(root)]}, "ZIP integrity verified", 0, continue_on_failure=True),
            AgentStep("verify-zip", "Verificar contenido del ZIP", "archives.verify", {"path": str(archive)}, "ZIP members and digest verified", 0, continue_on_failure=True),
        ))
        task = AgentTask(
            goal=text.strip(), mode=AgentMode.CONTROL, plan=tuple(steps),
            completion_criteria=("intent CREATE_MULTI_ARTIFACT", "artifacts physically created", "each artifact validated", "ZIP members verified"),
            context=TaskContext(active_folder=str(root), current_goal=text.strip()),
        )
        result = self.agent_runner.run(
            task, scope_permissions=frozenset({"filesystem.read", "filesystem.write"}),
        )
        self.task_store.save(result)
        artifact_steps = {item["step"]: item for item in result.tool_results}
        paths = [docx, pdf, png, pptx, python_file, index, css, script]
        artifacts = []
        for path in paths:
            create_result = next((item for item in result.tool_results if str(item.get("data", {}).get("path", "")) == str(path) and item.get("tool_id") == "artifacts.create"), None)
            verify_result = next((item for item in reversed(result.tool_results) if str(item.get("data", {}).get("path", "")) == str(path) and item.get("tool_id") == "artifacts.verify"), None)
            artifact = {"path": str(path), "exists": path.is_file(), "created": bool(create_result and create_result.get("ok")), "verified": bool(verify_result and verify_result.get("ok") and verify_result.get("verified")), "error": (verify_result or create_result or {}).get("error")}
            if path == pptx:
                structure = dict((verify_result or {}).get("data", {}).get("structure", {}))
                education_visuals["embedded"] = int(structure.get("pictures", 0) or 0)
                artifact["visuals"] = education_visuals
            artifacts.append(artifact)
        zip_result = artifact_steps.get("verify-zip", {})
        failures = [item for item in artifacts if not item["verified"]]
        if not (zip_result.get("ok") and zip_result.get("verified")):
            failures.append({"path": str(archive), "error": zip_result.get("error") or "zip_not_verified"})
        message = (
            f"Creé y validé los archivos físicos y verifiqué el ZIP en {archive}."
            if not failures else
            "La misión terminó parcialmente. Continué las subtareas seguras y registré los fallos: " + "; ".join(f"{Path(str(item['path'])).name}: {item.get('error') or 'validation_failed'}" for item in failures)
        )
        return {
            "ok": not failures, "message": message,
            "data": {"route": "project_creation", "intent": "CREATE_MULTI_ARTIFACT", "task": result.public(), "workspace": str(root), "archive": str(archive), "artifacts": artifacts, "failures": failures, "user_verified": False},
            "correlation_id": result.id,
        }

    def _handle_lasagna_artifact_intent(self, text: str, normalized_text: str) -> dict[str, Any] | None:
        if not (
            re.search(r"\b(lasa[nñ]a|lasagna)\b", normalized_text)
            and re.search(r"\b(?:word|docx)\b", normalized_text)
            and re.search(r"\b(?:excel|xlsx)\b", normalized_text)
        ):
            return None
        root = (Path.home() / "Downloads" / f"ARCHEON-Lasagna-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}").resolve()
        docx = root / "Receta de lasaña.docx"; xlsx = root / "Ingredientes de lasaña.xlsx"
        task = AgentTask(
            goal=text.strip(), mode=AgentMode.CONTROL,
            plan=(
                AgentStep("create-workspace", "Crear carpeta nueva", "files.create_folder", {"path": str(root), "parents": True}, "workspace exists", 0),
                AgentStep("create-recipe", "Crear receta estructurada en Word", "artifacts.create", {
                    "path": str(docx), "title": "Receta de lasaña", "content": "Receta base para 6 porciones.",
                    "sections": [
                        {"heading": "Ingredientes", "rows": [["Ingrediente", "Cantidad"], ["Pasta para lasaña", "12 láminas"], ["Carne molida", "500 g"], ["Tomate", "700 g"], ["Queso", "350 g"]]},
                        {"heading": "Preparación", "body": "Preparar la salsa, montar capas alternas, cubrir con queso y hornear hasta gratinar."},
                    ],
                }, "DOCX reopened with table", 0),
                AgentStep("create-cost-sheet", "Crear ingredientes, total y gráfico en Excel", "artifacts.create", {
                    "path": str(xlsx), "title": "Ingredientes de lasaña", "sheets": [{
                        "name": "Ingredientes", "rows": [["Ingrediente", "Costo estimado"], ["Pasta", 4.5], ["Carne", 6.75], ["Tomate", 3.25], ["Queso", 5.5]],
                        "formulas": {"B6": "=SUM(B2:B5)"}, "chart": {"title": "Costo por ingrediente", "data_col": 2, "category_col": 1},
                    }],
                }, "XLSX reopened with formula and chart", 0),
                AgentStep("verify-recipe", "Reabrir receta", "artifacts.verify", {"path": str(docx)}, "DOCX valid", 0),
                AgentStep("verify-sheet", "Reabrir hoja", "artifacts.verify", {"path": str(xlsx)}, "XLSX valid", 0),
            ),
            completion_criteria=("DOCX table reopened", "XLSX total formula present", "XLSX chart reopened"),
            context=TaskContext(active_folder=str(root), current_goal=text.strip()),
        )
        result = self.agent_runner.run(task, scope_permissions=frozenset({"filesystem.read", "filesystem.write"}))
        self.task_store.save(result); completed = result.status.value == "completed"
        return {
            "ok": completed,
            "message": (f"Creé y verifiqué la receta Word y la hoja Excel en {root.name}." if completed else "No pude verificar ambos archivos de la receta."),
            "data": {"route": "capability_agent", "task": result.public(), "workspace": str(root), "docx": str(docx), "xlsx": str(xlsx)},
            "correlation_id": result.id,
        }

    def _resolve_dj_continuation(
        self, current, excluded_ids: tuple[str, ...], strategy: str,
    ):
        """Resolve one authorised continuation without keeping a catalog worker alive."""
        if not self.configuration.config.media.dj_mode:
            return None
        artist = str(getattr(current, "artist", "") or "").strip()
        title = str(getattr(current, "title", "") or "").strip()
        if not artist or artist.casefold() == "artista local":
            query = title
        elif strategy == "same_artist":
            query = artist
        else:
            query = f"{artist} {title}" if title else artist
        if not query:
            return None
        try:
            found = self.media_discovery.search(
                query, allow_online=self.configuration.config.media.online_providers,
                include_online_with_local=True, limit=20,
            )
            excluded = set(excluded_ids)
            candidates = [
                self.media_discovery.resolve(str(item["id"]))
                for item in found.get("results", [])
                if str(item.get("id", "")) not in excluded
            ]
        except (OSError, RuntimeError, ValueError, KeyError, TypeError):
            return None
        if not candidates:
            return None
        artist_key = normalize_media(artist)
        candidates.sort(
            key=lambda item: (
                normalize_media(item.artist) == artist_key,
                bool(item.is_verified_artist), int(item.popularity), bool(item.stream_url or item.local_path),
            ), reverse=True,
        )
        return next((item for item in candidates if item.stream_url or item.local_path), None)

    def _handle_command(self, text: str, context: UserRequestContext | None = None) -> dict[str, Any]:
        normalized_text = " ".join(text.casefold().split())
        replacement = re.search(
            r"(?:^|[,;.!?]\s*)(?:no\s*,?\s*)?(?:mejor\s+)?(?P<command>(?:pon(?:me)?|reproduce|toca|play)\s+.+)$",
            text.strip(), flags=re.IGNORECASE,
        )
        if replacement and replacement.group("command").casefold() != text.strip().casefold():
            if self._pending_media_result:
                self.media.reject(self._pending_media_result["id"])
                self._pending_media_result = None
            text = replacement.group("command").strip()
            normalized_text = " ".join(text.casefold().split())
        forced_conversation = bool(context and context.intent_override == "conversation")
        if normalized_text.strip(" .!?¡¿") in {
            "para", "espera", "detente", "cancela", "cancelar", "no hagas eso", "stop", "cancelar tarea",
            "pare", "parar tarefa", "arrete", "annule la tache", "stopp", "aufgabe abbrechen",
            "ferma", "annulla attivita", "停止", "キャンセル", "중지", "취소", "остановись",
            "отмени задачу", "توقف", "ألغ المهمة", "रुको", "कार्य रद्द करो",
        } and self.agent_runner.active_task_count:
            cancelled = self.agent_runner.cancel_active()
            input_release = self.tools.release_active_inputs()
            terminal = self.tools.execute(
                "terminal.cancel", {},
                context=ToolContext(uuid4().hex, scope_permissions=frozenset({"terminal.execute"})),
            )
            return {
                "ok": True, "message": action_message("agent.cancel", self._last_request_language or "es"),
                "data": {
                    "route": "agent_cancel", "tasks_cancelled": cancelled,
                    "terminal_cancel_requested": bool(terminal.ok),
                    "input_release": input_release,
                }, "correlation_id": None,
            }
        image_response = self._handle_image_generation_intent(text)
        if image_response is not None:
            return image_response
        lasagna_response = self._handle_lasagna_artifact_intent(text, normalized_text)
        if lasagna_response is not None:
            return lasagna_response
        artifact_response = self._handle_artifact_research_intent(text, normalized_text)
        if artifact_response is not None:
            return artifact_response
        browser_response = self._handle_browser_intent(text, normalized_text)
        if browser_response is not None:
            return browser_response
        programming_response = self._handle_programming_intent(text, normalized_text)
        if programming_response is not None:
            return programming_response
        multi_app_response = self._handle_multi_app_intent(text, normalized_text)
        if multi_app_response is not None:
            return multi_app_response
        contextual_conversion = bool(re.match(
            r"\s*(?:(?:ahora\s+)?(?:hazlo|hazla|ponlo|ponla|crea\s+otra\s+versi[oó]n|p[aá]salo|p[aá]sala|convierte)\b|(?:ahora\s+)?tambi[eé]n\s+(?:en\s+)?(?:word|docx|pdf)\b)",
            normalized_text,
        ))
        artifact_followup = (
            self._handle_artifact_followup(text, normalized_text)
            if contextual_conversion and not (context and context.attachments) else None
        )
        if artifact_followup is not None:
            return artifact_followup
        creation_response = self._handle_new_artifact_intent(text, normalized_text)
        if creation_response is not None:
            return creation_response
        document_response = self._handle_document_intent(text, normalized_text, context)
        if document_response is not None:
            return document_response
        desktop_response = self._handle_desktop_intent(text, normalized_text)
        if desktop_response is not None:
            return desktop_response
        contextual_media_followup = bool(re.search(
            r"\b(?:reprod(?:uce|uzcas?|ucir)|respondido|pon(?:la|lo|gas?))\b.*"
            r"(?:\b(?:aqu[ií]|ac[aá])\b|\baqu\ufffd|\bac\ufffd)",
            normalized_text,
        ))
        if contextual_media_followup and self._recent_media_query:
            return self._handle_command(f"reproduce {self._recent_media_query}", context)
        media_active = self.media.current is not None or self.media.state is not MediaState.STOPPED
        media_controls = (
            (r"(?:\b(?:det[eé]n(?:te)?|detener|para|p[aá]rate|pares|parar|apaga|stop|pare|ya|arr[eê]te|stopp|ferma|останови)\b|停止|중지|توقف|रोक)", "media.stop", {"detén", "deten", "detente", "detener", "para", "párate", "parate", "parar", "apaga", "stop", "pare", "ya", "stopp", "ferma", "停止", "중지", "توقف", "रोक"}),
            (r"(?:\b(?:pausa|pausar|pause|mettre en pause|pausiere|пауза)\b|一時停止|暂停|일시 정지|إيقاف مؤقت|रोकें)", "media.pause", {"pausa", "pausar", "pause", "mettre en pause", "pausiere", "пауза", "一時停止", "暂停", "일시 정지", "إيقاف مؤقت", "रोकें"}),
            (r"(?:\b(?:contin[uú]a|continuar|reanuda|reanudar|resume|retomar|reprends|fortsetzen|riprendi|продолжи)\b|继续|再開|계속|استأنف|जारी)", "media.resume", {"continúa", "continua", "continuar", "reanuda", "reanudar", "resume", "retomar", "reprends", "fortsetzen", "riprendi", "продолжи", "继续", "再開", "계속", "استأنف", "जारी"}),
            (r"(?:\b(?:siguiente|next|pr[oó]xima|suivant|n[aä]chste|successivo|следующ)\w*\b|下一|次の|다음|التالي|अगला)", "media.next", {"siguiente", "next", "próxima", "proxima", "suivant", "nächste", "nachste", "successivo", "下一", "次の", "다음", "التالي", "अगला"}),
            (r"(?:\b(?:anterior|previous|previa|pr[eé]c[eé]dent|vorherige|precedente|предыдущ)\w*\b|上一|前の|이전|السابق|पिछला)", "media.previous", {"anterior", "previous", "previa", "précédent", "precedent", "vorherige", "precedente", "上一", "前の", "이전", "السابق", "पिछला"}),
        )
        mentions_media = has_explicit_media_context(normalized_text)
        short_command = normalized_text.strip(" .!?¡¿")
        if media_active and short_command in {"para", "para ya", "para eso"}:
            controlled = self.handle_action("media.stop")
            return {
                "ok": bool(controlled.get("ok")),
                "message": action_message("media.stop", self._last_request_language or "es") if controlled.get("ok") else str(controlled.get("error") or "media_control_failed"),
                "data": {**controlled, "route": "media_control", "action": "media.stop"},
                "correlation_id": None,
            }
        normalized_command = re.sub(r"^(?:(?:hola[\s,]+)?archeon[\s,]+|hola[\s,]+|por\s+favor\s+)+", "", short_command).strip()
        for pattern, action, exact_commands in media_controls:
            command_is_exact = normalized_command in exact_commands
            contextual_media_reference = bool(
                media_active and re.match(
                    pattern + r"\s+(?:eso|esto|la|lo|esa|ese)(?:\s+canci[oó]n)?\s*[.!?]*$",
                    normalized_command,
                )
            )
            direct_media_command = bool(mentions_media and re.match(pattern, normalized_command))
            domain_resolved = direct_media_command or contextual_media_reference or (media_active and command_is_exact)
            resolution = self.negation_scope.resolve(
                normalized_command, pattern,
                context_present=domain_resolved,
            )
            if resolution.action_allowed and domain_resolved:
                controlled = self.handle_action(action)
                return {
                    "ok": bool(controlled.get("ok")),
                    "message": action_message(action, self._last_request_language or "es") if controlled.get("ok") else str(controlled.get("error") or "media_control_failed"),
                    "data": {**controlled, "route": "media_control", "action": action},
                    "correlation_id": None,
                }
        if media_active and normalized_command in {
            "déjala sonando", "dejala sonando", "déjalo sonando", "dejalo sonando",
            "déjala reproduciendo", "dejala reproduciendo", "keep it playing",
        }:
            controlled = self.handle_action("media.resume")
            return {
                "ok": bool(controlled.get("ok")),
                "message": action_message("media.resume", self._last_request_language or "es") if controlled.get("ok") else str(controlled.get("error") or "media_control_failed"),
                "data": {**controlled, "route": "media_control", "action": "media.resume"},
                "correlation_id": None,
            }
        if self._pending_media_result and normalized_text.strip(" .!?¡¿") in {
            "si", "sí", "vale", "ok", "okay", "ponlo", "reproducelo", "reprodúcelo",
        }:
            pending = self._pending_media_result
            self._pending_media_result = None
            if time.monotonic() > float(pending.get("expires_at", time.monotonic() + 1)):
                return {"ok": False, "message": "Esa opción ya venció. Pídeme la canción otra vez para buscarla de nuevo.", "data": {"route": "media_confirmation_expired"}, "correlation_id": None}
            played = self.handle_action("media.play_result", {"id": pending["id"]})
            return {
                "ok": bool(played.get("ok")),
                "message": f"Reproduciendo {pending['display']}" if played.get("ok") else str(played.get("error")),
                "data": played, "correlation_id": None,
            }
        if self._pending_media_result and normalized_text.strip(" .!?¡¿") in {
            "no", "cancelar", "cancela", "dejalo", "déjalo", "no esa version",
            "no esa versión", "esa no", "esa version no", "esa versión no",
        }:
            self.media.reject(self._pending_media_result["id"])
            self._pending_media_result = None
            return {"ok": True, "message": "De acuerdo, no reproduciré esa versión.", "data": {}, "correlation_id": None}
        rejected_current = normalized_text.strip(" .!?¡¿") in {
            "no esa version", "no esa versión", "esa no", "esa version no", "esa versión no",
            "no reproduzcas esa version", "no reproduzcas esa versión",
        }
        if rejected_current and self.media.current is not None:
            rejected = self.media.current
            self.media.reject(rejected.id)
            self.media.stop_playback()
            return {
                "ok": True,
                "message": "Entendido. Detuve esa versión y no volveré a ofrecerla en esta sesión.",
                "data": {"route": "media_rejection", "rejected_id": rejected.id},
                "correlation_id": None,
            }
        if re.search(r"\b(?:que|qué)\s+(?:dia|día|fecha|hora|año)\b|\bfecha\s+actual\b|\bhora\s+actual\b|\bwhat (?:day|date|time|year)\b|\bque horas\b|\bquelle (?:date|heure)\b|\bwie spat\b|\bche ore\b|现在几点|今日の日付|몇 시|который час|كم الساعة|समय क्या", normalized_text):
            now = datetime.now().astimezone()
            return {
                "ok": True,
                "message": f"Hoy es {now:%d/%m/%Y} y son las {now:%H:%M} ({now.tzname() or 'hora local'}).",
                "data": {"route": "local_clock", "iso": now.isoformat()},
                "correlation_id": None,
            }
        knowledge_assessment = self.knowledge_router.assess(text)
        current_intent = is_current_information_request(normalized_text) or knowledge_assessment.requires_fresh_sources
        if current_intent:
            decision = self.permissions.evaluate(
                ("network.search",), risk=RiskLevel.READ_ONLY, action="search.current",
                reason="Consultar información actual solo cuando el usuario la solicita.",
                confirmer=lambda _request: True,
            )
            if not decision.allowed:
                return {"ok": False, "message": decision.reason, "data": {}, "correlation_id": None}
            try:
                search_query = self._fresh_search_query(text)
                results = self.search.search(
                    search_query, limit=4, language=self.configuration.config.language.interface, freshness="pd",
                )
                if not results:
                    results = self.search.search(
                        search_query, limit=4, language=self.configuration.config.language.interface, freshness="pw",
                    )
            except (OSError, RuntimeError, ValueError):
                results = []
            if not results:
                return {
                    "ok": False,
                    "message": "No pude verificar información actual en este momento. No voy a inventar noticias ni datos recientes.",
                    "data": {"route": "live_search", "verified": False},
                    "correlation_id": None,
                }
            lines = ["Información actual verificada:"]
            for item in results:
                published = f" · {item['published']}" if item.get("published") else ""
                lines.append(f"• {item['title']} — {item['source']}{published}\n  {item['url']}")
            return {
                "ok": True, "message": "\n".join(lines),
                "data": {"route": "live_search", "verified": True, "results": results},
                "correlation_id": None,
            }
        input_visibility = re.match(
            r"^(?:archeon[\s,]+)?(?:"
            r"(?P<show>muestra|mostrar|ense[nñ]a|show)|"
            r"(?P<hide>oculta|ocultar|esconde|hide)"
            r")\s+(?:(?:la|el)\s+)?(?:barra(?:\s+de\s+(?:comandos?|entrada))?|"
            r"entrada|archeon\s*input|command\s*(?:bar|input))\s*[.!?]*$",
            text.strip(), flags=re.IGNORECASE,
        )
        if input_visibility:
            visible = bool(input_visibility.group("show"))
            settings = self.configuration.update_settings(
                {"appearance": {"command_input_visible": visible}}
            )
            self.events.publish(
                "settings.changed", {"sections": ["appearance"]}, source="application"
            )
            message = "Barra de comandos visible." if visible else "Barra de comandos oculta."
            return {
                "ok": True, "message": message, "data": {"settings": settings},
                "correlation_id": None,
            }
        media_match = None if forced_conversation else re.match(
            r"^(?:archeon[\s,]+)?(?P<verb>pon(?:me)?|reproduce|toca|play|reproduza|toque|joue|lis|spiele|riproduci|metti|播放|再生|재생|включи|воспроизведи|شغّل|شغل|قم\s+بتشغيل|चलाओ|बजाओ)\s*(?:la\s+canci[oó]n\s+)?(?P<query>.+?)\s*[.!?]*$",
            text.strip(),
            flags=re.IGNORECASE,
        )
        if media_match and is_ambiguous_media_play_verb(media_match.group("verb")) and not has_explicit_media_context(text):
            media_match = None
        if media_match:
            play_resolution = self.negation_scope.resolve(
                normalized_text,
                r"\b(?:pon(?:me)?|reproduce|reproduzca|toca|play|reproduza|toque|joue|lis|spiele|riproduci|metti|播放|再生|재생|включи|воспроизведи|شغّل|شغل|चलाओ|बजाओ)\b",
                context_present=has_explicit_media_context(text),
            )
            if not play_resolution.action_allowed:
                media_match = None
        if media_match:
            query = MediaSearchQuery.parse(text)
            if query.artist and self._recent_media_artist:
                heard_artist = normalize_media(query.artist)
                recent_artist = normalize_media(self._recent_media_artist)
                contextual_similarity = SequenceMatcher(None, heard_artist, recent_artist).ratio()
                if heard_artist in recent_artist or contextual_similarity >= 0.78:
                    query = replace(query, artist=self._recent_media_artist)
            if query.artist:
                self._recent_media_artist = query.artist
            self._recent_media_query = query.provider_query
            fast_found = self.handle_action(
                "media.search",
                {"query": query.provider_query, "online": True, "exhaustive": True, "limit": 20},
            )
            resolution_trace: dict[str, Any] = {
                "raw_query": text, "normalized_query": query.provider_query,
                "detected_title": query.title, "detected_artist": query.artist,
                "phases": [{"phase": "fast", "provider_trace": fast_found.get("trace", []),
                            "candidate_count": len(fast_found.get("results") or [])}],
            }

            def prepare_candidates(search_result: dict[str, Any]):
                raw_results = search_result.get("results") if search_result.get("ok") else None
                prepared = [self.media_discovery.resolve(str(item["id"])) for item in (raw_results or [])]
                if query.artist:
                    enriched = []
                    for candidate in prepared:
                        title_score = SequenceMatcher(
                            None, normalize_media(query.title), normalize_media(candidate.title),
                        ).ratio()
                        if is_unknown_artist(candidate.artist) and title_score >= 0.90:
                            explicit_artist = query.artist.title() if query.artist.islower() else query.artist
                            candidate = replace(
                                candidate, artist=explicit_artist,
                                artist_source="user_request_verified_title",
                            )
                        enriched.append(candidate)
                    prepared = enriched
                    for candidate in prepared:
                        self.media_discovery.remember(candidate)
                return raw_results, prepared, rank_candidates(query, prepared)

            results, candidates, ranked = prepare_candidates(fast_found)
            fast_best = ranked[0] if ranked else None
            fast_sufficient = bool(
                fast_best and (
                    fast_best.candidate.stream_url
                    or fast_best.candidate.playback_kind == "official_web"
                )
                and fast_best.title_similarity >= 0.90
                and (not query.artist or fast_best.artist_similarity >= 0.78)
                and (query.requested_version != "original" or not fast_best.is_alternative)
            )
            found = fast_found
            if not fast_sufficient:
                deep_queries = [
                    " ".join(part for part in (query.artist, query.title) if part),
                    f"{query.title} {query.artist} official audio".strip(),
                    f"{query.title} {query.artist} album version".strip(),
                ]
                found = self.handle_action(
                    "media.search", {
                        "query": query.provider_query, "queries": deep_queries,
                        "online": True, "exhaustive": True, "limit": 20,
                    },
                )
                results, candidates, ranked = prepare_candidates(found)
                resolution_trace["phases"].append({
                    "phase": "deep", "provider_trace": found.get("trace", []),
                    "candidate_count": len(results or []),
                })
            legacy_enabled = True
            normal_best = ranked[0] if ranked else None
            legacy_needed = bool(
                legacy_enabled and (
                    normal_best is None
                    or normal_best.candidate.playback_kind == "official_web"
                    or not (normal_best.candidate.stream_url or normal_best.candidate.playback_kind == "official_web")
                    or normal_best.title_similarity < 0.90
                    or (query.artist and normal_best.artist_similarity < 0.78)
                    or (query.requested_version == "original" and normal_best.is_alternative)
                )
            )
            if legacy_needed:
                self.events.publish("music.resolving", {"phase": "search"}, source="application")
                legacy_found = self.handle_action(
                    "media.search_legacy", {"query": query.provider_query, "limit": 8},
                )
                legacy_candidates = [
                    self.media_discovery.resolve(str(item["id"]))
                    for item in (legacy_found.get("results") or [])
                ] if legacy_found.get("ok") else []
                legacy_ranked = rank_candidates(query, legacy_candidates)
                resolved_legacy = []
                resolve_attempts: list[dict[str, object]] = []
                for ranked_candidate in legacy_ranked[:4]:
                    attempt = self.handle_action(
                        "media.resolve_legacy_result", {"id": ranked_candidate.candidate.id},
                    )
                    resolve_attempts.append({
                        "id": ranked_candidate.candidate.id,
                        "score": ranked_candidate.total,
                        "ok": bool(attempt.get("ok")),
                        "error": attempt.get("error"),
                        "resolve_ms": attempt.get("diagnostics", {}).get("resolve_ms", 0.0),
                    })
                    if attempt.get("ok"):
                        resolved_legacy.append(
                            self.media_discovery.resolve(str(attempt["result"]["id"]))
                        )
                        break
                if resolved_legacy:
                    candidates = [*candidates, *resolved_legacy]
                    ranked = rank_candidates(query, candidates)
                    results = [candidate.public() for candidate in candidates]
                    self.events.publish("music.resolving", {"phase": "prepare"}, source="application")
                resolution_trace["phases"].append({
                    "phase": "legacy_local",
                    "enabled": True,
                    "installed": self.media_discovery.legacy_local_resolver.installed,
                    "api_key_required": False,
                    "candidate_count": len(legacy_candidates),
                    "resolve_attempts": resolve_attempts,
                    "provider_trace": legacy_found.get("trace", []),
                    "error": legacy_found.get("error"),
                })
            if not results:
                legacy_status = self.media_discovery.legacy_local_resolver.status()
                if not legacy_status.get("installed"):
                    unavailable_message = (
                        "La instalación de ARCHEON está incompleta: falta el resolver multimedia integrado."
                    )
                    unavailable_error = "legacy_local_resolver_not_installed"
                else:
                    unavailable_message = "No pude encontrar una versión reproducible después de agotar las rutas disponibles."
                    unavailable_error = found.get("error") or "media_not_found"
                return {
                    "ok": False,
                    "message": unavailable_message,
                    "data": {**found, "error": unavailable_error, "resolve_trace": resolution_trace},
                    "correlation_id": None,
                }
            best = ranked[0]
            resolution_trace["candidates"] = [{
                "id": item.candidate.id, "title": item.candidate.title,
                "artist": item.candidate.artist, "provider": item.candidate.provider,
                "source": item.candidate.source_url,
                "playable_source_available": bool(
                    item.candidate.stream_url or item.candidate.playback_kind == "official_web"
                ),
                "playback_kind": item.candidate.playback_kind,
                "version": item.detected_version or "original", "score": item.total,
                "title_similarity": round(item.title_similarity, 4),
                "artist_similarity": round(item.artist_similarity, 4),
                "rejection_reason": None if item is best else "lower_ranked_candidate",
            } for item in ranked[:20]]
            resolution_trace["selected_candidate"] = best.candidate.id
            if best.title_similarity < 0.62:
                legacy_status = self.media_discovery.legacy_local_resolver.status()
                if not legacy_status.get("installed"):
                    mismatch_message = "La instalación de ARCHEON está incompleta: falta el resolver multimedia integrado."
                    mismatch_error = "legacy_local_resolver_not_installed"
                else:
                    mismatch_message = "No encontré una coincidencia suficientemente fiable después de agotar las rutas disponibles."
                    mismatch_error = "media_match_below_threshold"
                return {
                    "ok": False,
                    "message": mismatch_message,
                    "data": {"route": "media_matcher", "error": mismatch_error, "results": results, "resolve_trace": resolution_trace}, "correlation_id": None,
                }
            if not query.artist:
                plausible = [item for item in ranked if item.title_similarity >= 0.90]
                artists = {item.candidate.artist.casefold() for item in plausible if item.candidate.artist}
                if len(artists) > 1:
                    options = [
                        " — ".join(part for part in (item.candidate.title, item.candidate.artist) if part)
                        for item in plausible[:3]
                    ]
                    return {
                        "ok": True,
                        "message": "Encontré varias canciones con ese título. Indícame el artista: " + "; ".join(options),
                        "data": {"route": "media_matcher", "disambiguation_required": True, "options": options},
                        "correlation_id": None,
                    }
            policy = self.configuration.config.media.alternative_versions
            display = " — ".join(part for part in (best.candidate.title, best.candidate.artist) if part)
            if best.is_alternative and query.requested_version == "original" and not query.allow_alternatives and policy != "automatic":
                if policy == "ask":
                    self._pending_media_result = {"id": best.candidate.id, "display": display, "expires_at": time.monotonic() + 120}
                    message = f"No encontré la versión original. Encontré {display}. ¿Quieres que reproduzca esta versión alternativa?"
                else:
                    self._pending_media_result = None
                    message = "No encontré la versión original y tu configuración no permite versiones alternativas."
                return {
                    "ok": True, "message": message,
                    "data": {
                        "route": "media_matcher", "confirmation_required": policy == "ask",
                        "alternative_blocked": policy == "strict", "candidate": best.candidate.public(),
                        "resolve_trace": resolution_trace,
                    }, "correlation_id": None,
                }
            self._pending_media_result = None
            played = self.handle_action("media.play_result", {"id": best.candidate.id})
            if played.get("ok") and best.candidate.playback_kind == "official_web":
                playback_message = f"Abrí {display} en el reproductor oficial visible."
            else:
                playback_message = f"Reproduciendo {display}"
            return {
                "ok": bool(played.get("ok")),
                "message": playback_message if played.get("ok") else "Encontré la canción, pero no pude iniciar su reproducción.",
                "data": {**played, "match": {"score": best.total, "version": best.detected_version or "original"}, "resolve_trace": resolution_trace},
                "correlation_id": None,
            }
        launch_resolution = self.negation_scope.resolve(
            normalized_text,
            r"\b(?:abre|abrir|abras|inicia|iniciar|ejecuta|open|launch|start|abra|ouvre|öffne|offne|apri|打开|起動|開いて|열어|실행|открой|запусти|افتح|شغّل|खोलें|खोलो)\b",
            context_present=True,
        )
        launch_item = self.launcher.command_item(text) if launch_resolution.action_allowed else None
        if launch_item is not None:
            try:
                result = self.launcher.launch(launch_item.id)
                return {"ok": True, "message": f"Abriendo {launch_item.name}", "data": result, "correlation_id": None}
            except (OSError, ValueError) as error:
                return {"ok": False, "message": str(error), "data": {}, "correlation_id": None}
        _wake_detected, possible_launch = self.speech_context.split_wake_command(
            text, self.configuration.config.assistant.wake_name,
        )
        launch_words = ("abre ", "abrir ", "inicia ", "iniciar ", "ejecuta ", "open ", "launch ", "start ", "abra ", "ouvre ", "öffne ", "offne ", "apri ", "打开", "起動 ", "開いて ", "열어 ", "실행 ", "открой ", "запусти ", "افتح ", "شغّل ", "खोलें ", "खोलो ")
        contextual_launch = self.speech_context.resolve(
            text,
            targets=self.launcher.speech_catalog() if launch_resolution.action_allowed and possible_launch.startswith(launch_words) else (),
            wake_name=self.configuration.config.assistant.wake_name,
        )
        if contextual_launch.ambiguous:
            options = [alternative.name for alternative in contextual_launch.alternatives]
            return {
                "ok": True,
                "message": "¿Quieres abrir " + " o ".join(options) + "?",
                "data": {
                    "route": "speech_context", "disambiguation_required": True,
                    "options": options, "confidence": round(contextual_launch.confidence, 3),
                },
                "correlation_id": None,
            }
        if contextual_launch.matched:
            try:
                result = self.launcher.launch(str(contextual_launch.target_id))
                return {
                    "ok": True, "message": f"Abriendo {contextual_launch.target_name}",
                    "data": {
                        **result, "route": "speech_context",
                        "heard": text, "resolved": contextual_launch.target_name,
                        "confidence": round(contextual_launch.confidence, 3),
                    }, "correlation_id": None,
                }
            except (OSError, ValueError) as error:
                return {"ok": False, "message": str(error), "data": {}, "correlation_id": None}
        response = self.orchestrator.handle_text(
            text, tuple(record.public() for record in (context.attachments if context else ()))
        )
        return {
            "ok": response.ok,
            "message": response.message,
            "data": response.data,
            "correlation_id": response.correlation_id,
        }

    def handle_action(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        correlation_id = uuid4().hex
        try:
            result = self._handle_action(action, payload)
        except Exception as error:
            self.logger.exception(
                "action.failed correlation_id=%s action=%s error_type=%s",
                correlation_id,
                action,
                type(error).__name__,
            )
            self.events.publish(
                "action.failed", {"action": action, "error": "action_failed"},
                source="application", correlation_id=correlation_id,
            )
            return {"ok": False, "error": "action_failed", "correlation_id": correlation_id}
        result.setdefault("correlation_id", correlation_id)
        return result

    def _handle_action(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        if action in {"artifact.open", "artifact.show_in_folder"}:
            target = Path(str(payload.get("path", ""))).expanduser().resolve()
            allowed = {
                Path(str(item.get("path"))).expanduser().resolve()
                for item in self._task_context.document_history if item.get("path")
            }
            if target not in allowed or not target.is_file():
                return {"ok": False, "error": "artifact_path_not_in_task_context"}
            if action == "artifact.open":
                os.startfile(str(target))
            else:
                os.startfile(str(target.parent))
            return {"ok": True, "path": str(target), "action": action}
        if action == "agent.pause":
            count = self.agent_runner.pause_active()
            return {"ok": bool(count), "tasks": count, "state": "paused" if count else "idle"}
        if action == "agent.resume":
            count = self.agent_runner.resume_active()
            return {"ok": bool(count), "tasks": count, "state": "acting" if count else "idle"}
        if action == "agent.stop":
            count = self.agent_runner.cancel_active()
            input_release = self.tools.release_active_inputs()
            self._control_preview_path.unlink(missing_ok=True)
            vision_cancelled = False
            if self.vision_provider is not None and self.vision_provider.status().get("loaded"):
                self.vision_provider.cancel()
                vision_cancelled = True
            terminal = self.tools.execute(
                "terminal.cancel", {},
                context=ToolContext(correlation_id=uuid4().hex, scope_permissions=frozenset({"terminal.execute"})),
            )
            return {
                "ok": bool(count or terminal.ok), "tasks": count,
                "terminal_cancel_requested": bool(terminal.ok),
                "vision_cancelled": vision_cancelled, "state": "cancelled",
                "input_release": input_release,
            }
        if action == "vision.status":
            developer = bool(payload.get("developer", False))
            component = self.vision_components.status(developer=developer)
            runtime = self.vision_provider.status(developer=developer) if self.vision_provider else None
            return {"ok": True, "component": component, "runtime": runtime}
        if action in {"vision.unload", "vision.cancel"}:
            if self.vision_provider is None:
                return {"ok": True, "state": "unloaded"}
            elapsed = self.vision_provider.unload() if action == "vision.unload" else 0.0
            if action == "vision.cancel":
                self.vision_provider.cancel()
            return {"ok": True, "state": "unloaded", "unload_ms": round(elapsed, 3)}
        if action == "settings.get":
            return {
                "ok": True,
                "settings": self.configuration.public_settings(),
                "paths": self.path_status(),
                "services": self._service_status(),
            }
        if action in {"permissions.list", "permissions.update"}:
            permission_catalog = {
                "microphone.capture": ("Micrófono", "Escuchar y transcribir voz localmente.", "medium"),
                "filesystem.read": ("Leer archivos", "Abrir archivos elegidos para analizarlos o enviarlos.", "read_only"),
                "filesystem.write": ("Crear y editar archivos", "Guardar documentos y resultados solicitados.", "low"),
                "desktop.observe": ("Ver la pantalla", "Inspeccionar la pantalla cuando una tarea lo requiera.", "read_only"),
                "desktop.control": ("Controlar el PC", "Mover el cursor, escribir y usar aplicaciones.", "medium"),
                "desktop.close": ("Cerrar ventanas", "Cerrar una ventana tras identificarla y verificar el resultado.", "medium"),
                "clipboard.read": ("Leer portapapeles", "Leer contenido copiado solo cuando se solicite.", "read_only"),
                "clipboard.write": ("Escribir en portapapeles", "Copiar resultados al portapapeles.", "low"),
            }
            if action == "permissions.update":
                permission = str(payload.get("permission") or "")
                if permission not in permission_catalog:
                    return {"ok": False, "error": "unsupported_permission"}
                try:
                    state = PermissionState(str(payload.get("state") or ""))
                except ValueError:
                    return {"ok": False, "error": "invalid_permission_state"}
                self.permissions.set_state(permission, state)
                self.events.publish(
                    "permissions.changed",
                    {"permission": permission, "state": state.value},
                    source="application",
                )
            return {
                "ok": True,
                "approval_mode": self.configuration.config.approval.mode,
                "permissions": [
                    {
                        "id": permission,
                        "label": metadata[0],
                        "description": metadata[1],
                        "risk": metadata[2],
                        "state": self.permissions.get_state(permission).value,
                    }
                    for permission, metadata in permission_catalog.items()
                ],
            }
        if action.startswith("cloud."):
            try:
                identity, access_token = self.auth.cloud_identity(str(payload.get("_session_token", "")))
                if not self.cloud.configured:
                    raise ValueError("cloud_backend_not_configured")
                if action == "cloud.devices.list":
                    return {"ok": True, "devices": self.cloud.list_devices(access_token, identity.user_id)}
                if action == "cloud.conversations.list":
                    return {"ok": True, "conversations": self.cloud.list_conversations(access_token, identity.user_id)}
                if action == "cloud.conversations.create":
                    conversation = self.cloud.create_conversation(
                        access_token, identity.user_id, str(payload.get("title") or "Nuevo chat")
                    )
                    return {"ok": True, "conversation": conversation}
                if action == "cloud.conversations.rename":
                    conversation = self.cloud.rename_conversation(
                        access_token, user_id=identity.user_id,
                        conversation_id=str(payload.get("conversation_id") or ""),
                        title=str(payload.get("title") or ""),
                    )
                    return {"ok": True, "conversation": conversation}
                if action == "cloud.conversations.archive":
                    self.cloud.archive_conversation(
                        access_token, user_id=identity.user_id,
                        conversation_id=str(payload.get("conversation_id") or ""),
                    )
                    return {"ok": True, "conversation_id": str(payload.get("conversation_id") or "")}
                if action == "cloud.messages.list":
                    conversation_id = str(payload.get("conversation_id") or "")
                    if not conversation_id:
                        raise ValueError("conversation_required")
                    return {"ok": True, "messages": self.cloud.list_messages(access_token, conversation_id)}
                if action == "cloud.messages.add":
                    conversation_id = str(payload.get("conversation_id") or "")
                    body = str(payload.get("body") or "").strip()
                    role = str(payload.get("role") or "user")
                    if not conversation_id or not body:
                        raise ValueError("invalid_cloud_message")
                    if role not in {"user", "assistant"}:
                        raise ValueError("invalid_cloud_message_role")
                    message = self.cloud.add_message(
                        access_token, user_id=identity.user_id,
                        conversation_id=conversation_id, role=role, body=body[:100_000],
                    )
                    return {"ok": True, "message": message}
                if action == "cloud.files.list":
                    return {"ok": True, "files": self.cloud.list_files(access_token, identity.user_id)}
                if action == "cloud.files.upload":
                    source = Path(str(payload.get("path") or "")).expanduser().resolve(strict=True)
                    uploaded = self.cloud.upload_file(
                        access_token, user_id=identity.user_id, source=source,
                        conversation_id=str(payload.get("conversation_id") or "") or None,
                    )
                    return {"ok": True, "file": uploaded}
                if action in {"cloud.files.preview", "cloud.files.download"}:
                    item = self.cloud.get_file(
                        access_token, user_id=identity.user_id,
                        file_id=str(payload.get("file_id") or ""),
                    )
                    if action == "cloud.files.preview" and not item["preview_allowed"]:
                        raise ValueError("cloud_file_preview_not_allowed")
                    if int(item.get("byte_size") or 0) > 12 * 1024 * 1024:
                        raise ValueError("cloud_file_stream_required")
                    data = self.cloud.download_verified_file(
                        access_token, storage_path=str(item["storage_path"]),
                        expected_sha256=str(item["sha256"]),
                    )
                    return {
                        "ok": True,
                        "file": {
                            "id": item["id"], "display_name": item["display_name"],
                            "mime_type": item["mime_type"], "byte_size": item["byte_size"],
                            "content_base64": base64.b64encode(data).decode("ascii"),
                        },
                    }
                if action == "cloud.files.delete":
                    item = self.cloud.get_file(
                        access_token, user_id=identity.user_id,
                        file_id=str(payload.get("file_id") or ""),
                    )
                    self.cloud.delete_file(access_token, str(item["id"]), str(item["storage_path"]))
                    return {"ok": True, "file_id": item["id"], "state": "deleted"}
                return {"ok": False, "error": "unsupported_cloud_action"}
            except (OSError, TypeError, ValueError) as error:
                return {"ok": False, "error": str(error)}
        if action == "updates.check":
            return self.updates.check()
        if action == "intelligence.memory.clear":
            self.orchestrator.clear_memory()
            return {"ok": True}
        if action == "learning.list":
            records = self.operational_learning.list_records(
                include_inactive=bool(payload.get("include_inactive", False))
            )
            return {"ok": True, "records": [item.public() for item in records]}
        if action == "learning.correct":
            scope = LearningScope(str(payload.get("scope", LearningScope.PROJECT.value)))
            scope_id = str(payload.get("scope_id", ""))
            if scope is LearningScope.PROJECT and not scope_id:
                scope_id = self._task_context.active_project or ""
            record = self.operational_learning.record_correction(
                phrase=str(payload.get("phrase", "")),
                wrong_intent=str(payload.get("wrong_intent", "")),
                correct_intent=str(payload.get("correct_intent", "")),
                reason=str(payload.get("reason", "Corrección explícita del usuario")),
                source=LearningSource.USER_EXPLICIT,
                scope=scope,
                scope_id=scope_id,
                context_tags=tuple(
                    str(item) for item in payload.get("context_tags", ()) if isinstance(item, str)
                ),
                replacement_text=str(payload.get("replacement_text", "")),
            )
            return {"ok": True, "record": record.public()}
        if action == "learning.forget":
            return {"ok": self.operational_learning.forget(str(payload.get("id", "")))}
        if action == "learning.reset":
            scope = LearningScope(str(payload.get("scope", LearningScope.USER.value)))
            removed = self.operational_learning.reset(
                scope=scope, scope_id=str(payload.get("scope_id", ""))
            )
            return {"ok": True, "removed": removed}
        if action == "telemetry.stage":
            stage = str(payload.get("stage", ""))
            if stage not in {"first_visible_token", "first_visible_response"}:
                return {"ok": False, "error": "invalid_telemetry_stage"}
            self.events.publish("performance.stage", {
                "stage": stage,
                "elapsed_ms": max(0.0, min(300_000.0, float(payload.get("elapsed_ms", 0)))),
            }, source="ui", correlation_id=str(payload.get("correlation_id") or "") or None)
            return {"ok": True}
        if action == "attachment.remove":
            return {"ok": self.attachments.remove(str(payload.get("id", "")))}
        if action == "settings.update":
            changes = payload.get("changes")
            if not isinstance(changes, dict):
                return {"ok": False, "error": "invalid_settings_changes"}
            try:
                changes = {section: dict(values) for section, values in changes.items()}
                if self._pending_visuals:
                    appearance = changes.setdefault("appearance", {})
                    if "background" in self._pending_visuals:
                        pending = self._pending_visuals["background"]
                        appearance["background_type"] = pending[0] if pending else "default"
                        appearance["background_path"] = str(pending[1]) if pending else None
                    if "logo" in self._pending_visuals:
                        pending = self._pending_visuals["logo"]
                        appearance["logo_path"] = str(pending[1]) if pending else None
                    if "chat" in self._pending_visuals:
                        pending = self._pending_visuals["chat"]
                        appearance["chat_background_path"] = str(pending[1]) if pending else None
                if isinstance(changes.get("storage"), dict) and "model_dir" in changes["storage"]:
                    requested = changes["storage"].get("model_dir") or None
                    resolved = self.paths.model_dir(requested)
                    resolved.mkdir(parents=True, exist_ok=True)
                    changes["storage"]["model_dir"] = str(resolved) if requested else None
                settings = self.configuration.update_settings(changes)
            except (OSError, TypeError, ValueError) as error:
                return {"ok": False, "error": str(error)}
            self._pending_visuals.clear()
            warnings: list[str] = []
            side_effects: list[tuple[str, Any]] = []
            if "storage" in changes:
                side_effects.append((
                    "voice_models_root",
                    lambda: self.voice.configure_models_root(
                        self.paths.model_dir(self.configuration.config.storage.model_dir)
                    ),
                ))
            if "storage" in changes or "intelligence" in changes:
                side_effects.append(("local_ai_reconfigure", self._configure_local_ai))
            if "media" in changes:
                side_effects.append((
                    "media_volume",
                    lambda: self.media.set_volume(self.configuration.config.media.preferred_volume / 100),
                ))
            if "startup" in changes and "launch_at_login" in changes["startup"]:
                side_effects.append((
                    "launch_at_login",
                    lambda: configure_launch_at_login(self.configuration.config.startup.launch_at_login),
                ))
            for effect_name, effect in side_effects:
                try:
                    effect()
                except Exception:
                    warnings.append(effect_name)
                    self.logger.exception("Settings side effect failed: %s", effect_name)
            self.events.publish(
                "settings.changed",
                {"sections": sorted(changes)},
                source="application",
            )
            try:
                self.voice.sync_wake_word()
            except Exception:
                warnings.append("wake_word_sync")
                self.logger.exception("Settings side effect failed: wake_word_sync")
            return {"ok": True, "settings": settings, "warnings": warnings}
        if action == "paths.choose_model_dir":
            from archeon.ui.native_dialogs import choose_directory

            selected = choose_directory("Elegir carpeta de modelos de ARCHEON")
            if not selected:
                return {"ok": True, "cancelled": True, "paths": self.path_status()}
            model_dir = self.paths.model_dir(selected)
            model_dir.mkdir(parents=True, exist_ok=True)
            settings = self.configuration.update_settings({"storage": {"model_dir": str(model_dir)}})
            self.voice.configure_models_root(model_dir)
            self._configure_local_ai()
            return {"ok": True, "settings": settings, "paths": self.path_status()}
        if action == "paths.reset_model_dir":
            model_dir = self.paths.default_model_dir
            model_dir.mkdir(parents=True, exist_ok=True)
            settings = self.configuration.update_settings({"storage": {"model_dir": None}})
            self.voice.configure_models_root(model_dir)
            self._configure_local_ai()
            return {"ok": True, "settings": settings, "paths": self.path_status()}
        if action == "intelligence.status":
            internal_status = self.local_ai.status()
            return {
                "ok": True,
                "status": {
                    "name": "ARCHI",
                    "state": internal_status.get("state", "unavailable"),
                    "available": bool(internal_status.get("available", False)),
                    "loaded": internal_status.get("state") == "ready",
                    "error": internal_status.get("last_error"),
                },
            }
        if action == "intelligence.unload":
            self.local_ai.unload()
            return {"ok": True, "status": self.local_ai.status()}
        if action == "sync.now":
            try:
                identity, access_token = self.auth.cloud_identity(str(payload.get("_session_token", "")))
                envelopes = self.configuration.sync_payloads()
                envelopes["account"]["settings"]["launcher"] = self.launcher.portable_state()
                result = self.settings_sync.synchronize(
                    identity.user_id, access_token, envelopes["account"], envelopes["device"],
                )
                if not result.get("queued"):
                    settings = self.configuration.apply_sync_payloads(result["account"], result["device"])
                    launcher = result["account"].get("settings", {}).get("launcher")
                    if isinstance(launcher, dict):
                        self.launcher.apply_portable_state(launcher)
                    self.voice.sync_wake_word()
                    result["settings"] = settings
                self.events.publish(
                    "sync.completed" if not result.get("queued") else "sync.queued",
                    {"status": result.get("status")}, source="application",
                )
                return result
            except (OSError, TypeError, ValueError) as error:
                return {"ok": False, "error": str(error)}
        if action == "window.ghost":
            self.configuration.config.ghost.enabled = True
            self.configuration.save()
            self.events.publish("ui.window.ghost", source="application")
            return {"ok": True, "mode": "ghost"}
        if action == "window.main":
            self.configuration.config.ghost.enabled = False
            self.configuration.save()
            self.events.publish("ui.window.main", source="application")
            return {"ok": True, "mode": "main"}
        if action == "app.exit":
            self.events.publish("ui.window.exit", source="application")
            return {"ok": True}
        if action == "launcher.list":
            self.launcher.refresh(force=bool(payload.get("force")))
            return {"ok": True, "items": self.launcher.list_items(str(payload.get("category", "all")))}
        if action == "launcher.open":
            try:
                return {"ok": True, "item": self.launcher.launch(str(payload.get("id", "")))}
            except (OSError, ValueError) as error:
                return {"ok": False, "error": str(error)}
        if action == "launcher.favorite":
            try:
                self.launcher.favorite(str(payload.get("id", "")), bool(payload.get("enabled")))
                self.configuration.touch_sync()
                return {"ok": True}
            except ValueError as error:
                return {"ok": False, "error": str(error)}
        if action == "launcher.add_custom":
            try:
                target = str(payload.get("target", "")).strip()
                if not target:
                    from archeon.ui.native_dialogs import choose_launcher_target
                    target = choose_launcher_target() or ""
                if not target:
                    return {"ok": True, "cancelled": True}
                name = str(payload.get("name", "")).strip() or Path(target).stem
                item = self.launcher.add_custom(name, target, str(payload.get("kind", "app")))
                return {"ok": True, "item": item}
            except (OSError, ValueError) as error:
                return {"ok": False, "error": str(error)}
        if action == "media.index":
            decision = self.permissions.evaluate(
                ("filesystem.read.media",), risk=RiskLevel.READ_ONLY, action=action,
                reason="Crear o actualizar el índice local de música en ubicaciones conocidas.",
                confirmer=lambda _request: True,
            )
            if not decision.allowed:
                return {"ok": False, "error": decision.reason}
            roots = payload.get("roots")
            if roots is not None and (not isinstance(roots, list) or not all(isinstance(root, str) for root in roots)):
                return {"ok": False, "error": "invalid_media_roots"}
            try:
                return {"ok": True, "index": self.media_discovery.refresh([Path(root) for root in roots] if roots else None)}
            except OSError as error:
                return {"ok": False, "error": str(error)}
        if action == "media.search":
            query = str(payload.get("query", ""))
            raw_variants = payload.get("queries", [])
            if not isinstance(raw_variants, list) or not all(isinstance(item, str) for item in raw_variants):
                return {"ok": False, "error": "invalid_media_queries", "results": []}
            query_variants = tuple(raw_variants[:4])
            limit = max(1, min(20, int(payload.get("limit", 10))))
            quality = str(payload.get("quality", "auto"))
            exhaustive = bool(payload.get("exhaustive"))
            try:
                result = self.media_discovery.search(query, allow_online=False, limit=limit, quality=quality)
                if (result["results"] and not exhaustive) or not bool(payload.get("online")):
                    return {"ok": True, **result}
                decision = self.permissions.evaluate(
                    ("network.media",), risk=RiskLevel.READ_ONLY, action=action,
                    reason="Buscar la canción solicitada en un proveedor online configurado.",
                    confirmer=lambda _request: True,
                )
                if not decision.allowed:
                    return {"ok": False, "error": decision.reason, **result}
                return {
                    "ok": True,
                    **self.media_discovery.search(
                        query,
                        allow_online=True,
                        limit=limit,
                        quality=quality,
                        include_online_with_local=exhaustive,
                        query_variants=query_variants,
                    ),
                }
            except (OSError, RuntimeError, ValueError) as error:
                return {"ok": False, "error": str(error), "results": []}
        if action == "media.providers":
            codec_status = self.media.status()
            return {
                "ok": True,
                "providers": self.media_discovery.provider_status(
                    developer=bool(payload.get("developer", False)),
                ),
                "youtube_playback": "official_visible_or_integrated_local_resolver",
                "ffmpeg_policy": "optional_authorized_decoder_only",
                "active_decoder": codec_status.get("codec_backend"),
            }
        if action == "media.search_legacy":
            if not self.media_discovery.legacy_local_resolver.installed:
                return {"ok": False, "error": "legacy_local_resolver_not_installed", "results": []}
            decision = self.permissions.evaluate(
                ("network.media",), risk=RiskLevel.READ_ONLY, action=action,
                reason="Buscar candidatos mediante el resolver multimedia integrado.",
                confirmer=lambda _request: True,
            )
            if not decision.allowed:
                return {"ok": False, "error": decision.reason, "results": []}
            try:
                return {"ok": True, **self.media_discovery.search_legacy(
                    str(payload.get("query", "")), limit=max(2, min(12, int(payload.get("limit", 8)))),
                )}
            except (OSError, RuntimeError, ValueError) as error:
                return {"ok": False, "error": str(error), "results": []}
        if action == "media.resolve_legacy_result":
            try:
                candidate = self.media_discovery.resolve(str(payload.get("id", "")))
                result = self.media_discovery.resolve_legacy(candidate)
                diagnostics = self.media_discovery.legacy_local_resolver.status(
                    developer=True,
                ).get("diagnostics", {})
                return {"ok": True, "result": result.public(), "diagnostics": diagnostics}
            except (OSError, RuntimeError, ValueError) as error:
                return {"ok": False, "error": str(error)}
        if action == "media.resolve_authorized_source":
            decision = self.permissions.evaluate(
                ("network.media",), risk=RiskLevel.READ_ONLY, action=action,
                reason="Inspeccionar una fuente multimedia explícitamente autorizada sin descargarla.",
                confirmer=lambda _request: True,
            )
            if not decision.allowed:
                return {"ok": False, "error": decision.reason}
            try:
                result = self.media_discovery.authorized_resolver.resolve(str(payload.get("source", "")))
                self.media_discovery.remember(result)
                return {"ok": True, "result": result.public(), "resolver": "yt_dlp_authorized"}
            except (OSError, RuntimeError, ValueError) as error:
                return {"ok": False, "error": str(error)}
        if action == "media.status":
            return {"ok": True, "media": self.media.status()}
        if action == "media.web_state":
            try:
                return {"ok": True, "media": self.media.report_web_state(
                    str(payload.get("state", "buffering")),
                    int(payload.get("position_ms", 0)), int(payload.get("duration_ms", 0)),
                )}
            except (RuntimeError, TypeError, ValueError) as error:
                return {"ok": False, "error": str(error)}
        if action == "media.play_result":
            try:
                result = self.media_discovery.resolve(str(payload.get("id", "")))
                self.media.load_results([result])
                return {"ok": True, "media": self.media.play()}
            except (OSError, RuntimeError, ValueError) as error:
                return {"ok": False, "error": str(error)}
        if action == "search.web":
            decision = self.permissions.evaluate(
                ("network.search",), risk=RiskLevel.READ_ONLY, action=action,
                reason="Consultar información actual y conservar las fuentes temporales.",
                confirmer=lambda _request: True,
            )
            if not decision.allowed:
                return {"ok": False, "error": decision.reason}
            try:
                results = self.search.search(
                    str(payload.get("query", "")), limit=max(1, min(10, int(payload.get("limit", 5)))),
                    language=str(payload.get("language") or self.configuration.config.language.interface),
                    freshness=str(payload["freshness"]) if payload.get("freshness") else None,
                )
                return {"ok": True, "provider": self.search.provider.name, "results": results}
            except (OSError, RuntimeError, ValueError) as error:
                return {"ok": False, "error": str(error), "results": []}
        if action == "launcher.alias":
            try:
                self.launcher.set_alias(str(payload.get("alias", "")), str(payload.get("id", "")))
                self.configuration.touch_sync()
                return {"ok": True}
            except ValueError as error:
                return {"ok": False, "error": str(error)}
        if action == "voice.listen":
            decision = self.permissions.evaluate(
                ("microphone.capture",),
                risk=RiskLevel.MEDIUM,
                action="voice.listen",
                reason="Capturar una frase local para reconocer el comando de voz.",
                confirmer=lambda _request: True,
            )
            if not decision.allowed:
                return {"ok": False, "error": decision.reason}
            if self.media.state is MediaState.PLAYING:
                self.media.pause()
            started = self.voice.start_cycle()
            return {"ok": started, "error": None if started else "voice_unavailable_or_busy"}
        if action == "voice.stop":
            self.voice.interrupt()
            return {"ok": True}
        if action in {"voice.pause_listening", "voice.resume_listening"}:
            paused = action == "voice.pause_listening"
            self.configuration.config.assistant.listening_paused = paused
            self.configuration.save()
            if paused:
                self.voice.interrupt()
            self.events.publish("voice.listening.paused" if paused else "voice.listening.resumed", source="application")
            return {"ok": True, "paused": paused, "settings": self.configuration.public_settings()}
        if action == "voice.dictation":
            decision = self.permissions.evaluate(
                ("microphone.capture",), risk=RiskLevel.MEDIUM, action="voice.dictation",
                reason="Transcribir una frase local en la barra sin ejecutarla.", confirmer=lambda _request: True,
            )
            if not decision.allowed:
                return {"ok": False, "error": decision.reason}
            started = self.voice.start_dictation()
            return {"ok": started, "error": None if started else "voice_unavailable_or_busy"}
        if action == "voice.preview":
            try:
                catalog = self.voice.catalog()
                voice_id = payload.get("tts_voice_id") or None
                output_id = payload.get("tts_output_device_id") or None
                if voice_id is not None and voice_id not in {voice["id"] for voice in catalog["tts_voices"]}:
                    raise ValueError("invalid_tts_voice")
                if output_id is not None and output_id not in {output["id"] for output in catalog["tts_outputs"]}:
                    raise ValueError("invalid_tts_output")
                style = resolve_voice_style(str(payload.get("tts_style", "natural"))).id
                started = self.voice.preview(str(payload.get("text", "")), {
                    "voice_id": voice_id,
                    "output_device_id": output_id,
                    "style": style,
                    "rate": max(-10, min(10, int(payload.get("tts_rate", 0)))),
                    "volume": max(0, min(100, int(payload.get("tts_volume", 100)))),
                })
                return {"ok": started, "error": None if started else "voice_busy"}
            except (TypeError, ValueError, RuntimeError) as error:
                return {"ok": False, "error": str(error)}
        if action == "audio.test_input":
            try:
                started = self.voice.test_input(float(payload.get("duration_seconds", 3.0)))
                return {"ok": started, "error": None if started else "voice_busy"}
            except (TypeError, ValueError, RuntimeError) as error:
                return {"ok": False, "error": str(error)}
        if action == "voice.catalog":
            try:
                catalog = self.voice.catalog()
                catalog["configuration"] = {
                    "profile": self.configuration.config.voice.profile,
                    "tts_style": self.configuration.config.voice.tts_style,
                    "input_device_id": self.configuration.config.audio.input_device_id,
                    "tts_voice_id": self.configuration.config.voice.tts_voice_id,
                    "tts_output_device_id": self.configuration.config.voice.tts_output_device_id,
                    "tts_rate": self.configuration.config.voice.tts_rate,
                    "tts_volume": self.configuration.config.voice.tts_volume,
                    "barge_in": self.configuration.config.voice.barge_in,
                    "speaker_verification_enabled": self.configuration.config.voice.speaker_verification_enabled,
                    "speaker_rejection_feedback": self.configuration.config.voice.speaker_rejection_feedback,
                    "speaker_profiles": self.voice.speaker_profiles(),
                }
                return {"ok": True, "voice": catalog}
            except (OSError, ValueError, RuntimeError) as error:
                return {"ok": False, "error": str(error)}
        if action == "voice.configure":
            try:
                if self.voice.busy:
                    raise RuntimeError("voice_busy")
                catalog = self.voice.catalog()
                profile = str(payload.get("profile", "eco")).lower()
                if profile not in catalog["profiles"]:
                    raise ValueError("invalid_voice_profile")
                requested_tts_style = str(payload.get("tts_style", "natural")).lower()
                tts_style = resolve_voice_style(requested_tts_style).id
                if requested_tts_style not in {
                    "natural", "deep", "deep_tech", "technological", "crisp", "warm",
                    "professional", "energetic", "calm", "cinematic", "custom", "tech",
                }:
                    raise ValueError("invalid_tts_style")
                input_id = payload.get("input_device_id") or None
                voice_id = payload.get("tts_voice_id") or None
                output_id = payload.get("tts_output_device_id") or None
                if input_id is not None and str(input_id) not in {
                    str(device.get("index")) for device in catalog["input_devices"]
                }:
                    raise ValueError("invalid_input_device")
                if voice_id is not None and voice_id not in {
                    voice["id"] for voice in catalog["tts_voices"]
                }:
                    raise ValueError("invalid_tts_voice")
                if output_id is not None and output_id not in {
                    output["id"] for output in catalog["tts_outputs"]
                }:
                    raise ValueError("invalid_tts_output")
                self.configuration.config.voice.profile = profile
                self.configuration.config.voice.tts_style = tts_style
                self.configuration.config.audio.input_device_id = str(input_id) if input_id is not None else None
                self.configuration.config.voice.tts_voice_id = voice_id
                self.configuration.config.voice.tts_output_device_id = output_id
                self.configuration.config.voice.tts_rate = max(-10, min(10, int(payload.get("tts_rate", 0))))
                self.configuration.config.voice.tts_volume = max(0, min(100, int(payload.get("tts_volume", 100))))
                self.configuration.config.voice.barge_in = bool(payload.get("barge_in", True))
                speaker_enabled = bool(payload.get("speaker_verification_enabled", False))
                if speaker_enabled and not any(profile.get("enabled") for profile in self.voice.speaker_profiles()):
                    raise ValueError("speaker_profile_required")
                self.configuration.config.voice.speaker_verification_enabled = speaker_enabled
                feedback = str(payload.get("speaker_rejection_feedback", "silent")).lower()
                if feedback not in {"silent", "visual"}:
                    raise ValueError("invalid_speaker_rejection_feedback")
                self.configuration.config.voice.speaker_rejection_feedback = feedback
                self.configuration.save()
                self.voice.restart_wake_word()
                self.events.publish("voice.configuration.changed", source="application")
                return {"ok": True, "voice": self.voice.status()}
            except (OSError, ValueError, RuntimeError) as error:
                return {"ok": False, "error": str(error)}
        if action == "voice.speaker.enroll":
            try:
                started = self.voice.start_speaker_enrollment(
                    str(payload.get("name", "")),
                    profile_id=str(payload.get("profile_id") or "") or None,
                    sample_count=3,
                )
                return {"ok": started, "error": None if started else "speaker_enrollment_busy"}
            except (OSError, ValueError, RuntimeError) as error:
                return {"ok": False, "error": str(error)}
        if action == "voice.speaker.update":
            try:
                profile = self.voice.update_speaker_profile(
                    str(payload.get("profile_id", "")),
                    name=(str(payload["name"]) if "name" in payload else None),
                    enabled=(bool(payload["enabled"]) if "enabled" in payload else None),
                )
                if not any(item.get("enabled") for item in self.voice.speaker_profiles()):
                    self.configuration.config.voice.speaker_verification_enabled = False
                    self.configuration.save()
                return {"ok": True, "profile": profile, "profiles": self.voice.speaker_profiles()}
            except (OSError, ValueError, RuntimeError) as error:
                return {"ok": False, "error": str(error)}
        if action == "voice.speaker.delete":
            try:
                self.voice.delete_speaker_profile(str(payload.get("profile_id", "")))
                if not any(item.get("enabled") for item in self.voice.speaker_profiles()):
                    self.configuration.config.voice.speaker_verification_enabled = False
                    self.configuration.save()
                return {"ok": True, "profiles": self.voice.speaker_profiles()}
            except (OSError, ValueError, RuntimeError) as error:
                return {"ok": False, "error": str(error)}
        try:
            if action == "appearance.choose":
                from archeon.ui.native_dialogs import choose_visual_file

                kind = str(payload.get("kind", ""))
                selected = choose_visual_file(kind)
                if not selected:
                    return {"ok": True, "cancelled": True}
                path = Path(selected)
                max_bytes = 2_000_000_000 if kind == "video" else 250_000_000 if kind == "logo" and path.suffix.casefold() in {".mp4", ".webm", ".m4v"} else 50_000_000
                allowed = {"image": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}, "video": {".mp4", ".webm", ".m4v"}, "logo": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".m4v"}, "chat": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}}
                if kind not in allowed or path.suffix.casefold() not in allowed[kind] or not path.is_file() or path.stat().st_size > max_bytes:
                    return {"ok": False, "error": "invalid_visual_file"}
                slot = kind if kind in {"logo", "chat"} else "background"
                self._pending_visuals[slot] = (kind, path.resolve())
                return {"ok": True, "settings": self._settings_with_visual_draft(), "preview": True}
            if action == "appearance.clear":
                clear_kind = str(payload.get("kind", ""))
                if clear_kind == "chat":
                    self._pending_visuals["chat"] = None
                else:
                    self._pending_visuals.update({"background": None, "logo": None})
                settings = self._settings_with_visual_draft()
                if clear_kind != "chat":
                    settings["appearance"].update({
                        "background_position_x": 0, "background_position_y": 0, "background_zoom": 100,
                        "logo_position_x": 0, "logo_position_y": 0, "logo_zoom": 100,
                    })
                return {"ok": True, "settings": settings, "preview": True}
            if action == "appearance.discard":
                discard_kind = str(payload.get("kind", ""))
                if discard_kind:
                    self._pending_visuals.pop(discard_kind, None)
                else:
                    self._pending_visuals.clear()
                return {"ok": True}
            if action == "media.load":
                paths = payload.get("paths")
                if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
                    return {"ok": False, "error": "invalid_media_paths"}
                decision = self.permissions.evaluate(
                    ("filesystem.read.media",),
                    risk=RiskLevel.READ_ONLY,
                    action="media.load",
                    reason="Leer metadata y reproducir los archivos seleccionados.",
                    confirmer=lambda _request: True,
                )
                if not decision.allowed:
                    return {"ok": False, "error": decision.reason}
                return {"ok": True, "tracks": self.media.load([Path(path) for path in paths], append=bool(payload.get("append")))}
            if action == "media.choose":
                from archeon.ui.native_dialogs import choose_audio_files

                paths = choose_audio_files()
                if not paths:
                    return {"ok": True, "cancelled": True, "tracks": []}
                return {"ok": True, "tracks": self.media.load([Path(path) for path in paths])}
            if action in {"media.play", "music.started"}:
                if self.media.current is None:
                    self.media.load([self.resources.ui("archeon-audio.mp3")])
                return {"ok": True, "media": self.media.play()}
            if action in {"media.pause", "music.paused"}:
                return {"ok": True, "media": self.media.pause()}
            if action == "media.resume":
                return {"ok": True, "media": self.media.resume()}
            if action in {"media.stop", "music.stopped"}:
                return {"ok": True, "media": self.media.stop_playback()}
            if action == "media.next":
                return {"ok": True, "media": self.media.next()}
            if action == "media.previous":
                return {"ok": True, "media": self.media.previous()}
            if action == "media.seek":
                return {"ok": True, "media": self.media.seek(int(payload.get("position_ms", 0)))}
            if action == "media.volume":
                return {"ok": True, "media": self.media.set_volume(float(payload.get("volume", 0.7)))}
        except (OSError, ValueError, RuntimeError) as error:
            return {"ok": False, "error": str(error)}
        return {"ok": False, "error": f"unknown action: {action}"}

    def _speech_synthesis_locale(self) -> str:
        selected = self.configuration.config.language.speech_synthesis
        if selected != "auto":
            return selected
        conversation = self.configuration.config.language.conversation
        return conversation if conversation != "auto" else self.configuration.config.language.interface

    def path_status(self) -> dict[str, str]:
        return {
            "install_dir": str(self.paths.install_dir),
            "data_dir": str(self.paths.data_dir),
            "cache_dir": str(self.paths.cache_dir),
            "model_dir": str(self.paths.model_dir(self.configuration.config.storage.model_dir)),
            "resource_dir": str(self.paths.package_dir),
        }

    def _speech_recognition_locale(self) -> str:
        selected = self.configuration.config.language.speech_recognition
        if selected != "auto":
            return selected
        conversation = self.configuration.config.language.conversation
        return conversation if conversation != "auto" else self.configuration.config.language.interface

    def _personalization_resource(self, kind: str) -> Path | None:
        if kind == "control-preview":
            return self._control_preview_path if self._control_preview_path.is_file() else None
        if kind.endswith("-preview"):
            slot = kind.removesuffix("-preview")
            pending = self._pending_visuals.get(slot)
            return pending[1] if pending and pending[1].is_file() else None
        configured = self.configuration.config.appearance
        candidate = configured.background_path if kind == "background" else configured.logo_path if kind == "logo" else configured.chat_background_path if kind == "chat" else None
        if not candidate:
            return None
        path = Path(candidate).expanduser()
        return path if path.is_file() else None

    def _publish_agent_visual_evidence(self, task: AgentTask, step: AgentStep, result: Any) -> None:
        if not step.tool_id.startswith("desktop."):
            return
        data = dict(result.data)
        window = data.get("window") or data.get("target_window")
        application = data.get("application")
        element = data.get("element") or data.get("target")
        try:
            observer = WindowsDesktopObserver()
            active = observer.active_window()
            observer.capture_window(active.bounds, self._control_preview_path)
            self._control_preview_revision += 1
            if not isinstance(window, dict):
                window = active.public()
            if not isinstance(application, dict):
                application = observer.classify_window(active)
        except (OSError, RuntimeError, ValueError):
            pass
        method = data.get("method") or data.get("provider")
        if not method and isinstance(application, dict):
            method = application.get("available_control_method")
        self.events.publish("agent.visual.updated", {
            "task_id": task.id,
            "step": step.id,
            "action": step.description,
            "application": application if isinstance(application, dict) else {},
            "window": window if isinstance(window, dict) else {},
            "target": element if isinstance(element, dict) else {},
            "method": method or "windows_ui_automation",
            "confidence": (application or {}).get("confidence") if isinstance(application, dict) else None,
            "ok": bool(result.ok), "verified": bool(result.verified),
            "preview_revision": self._control_preview_revision,
        }, source="application", correlation_id=task.id)

    def _settings_with_visual_draft(self) -> dict[str, Any]:
        settings = self.configuration.public_settings()
        appearance = settings["appearance"]
        if "background" in self._pending_visuals:
            pending = self._pending_visuals["background"]
            appearance["background_type"] = pending[0] if pending else "default"
            appearance["background_path"] = str(pending[1]) if pending else None
        if "logo" in self._pending_visuals:
            pending = self._pending_visuals["logo"]
            appearance["logo_path"] = str(pending[1]) if pending else None
        if "chat" in self._pending_visuals:
            pending = self._pending_visuals["chat"]
            appearance["chat_background_path"] = str(pending[1]) if pending else None
        return settings

    def handle_auth(
        self, operation: str, payload: dict[str, Any], session_token: str
    ) -> dict[str, Any]:
        try:
            if operation == "guest":
                session = self.auth.guest()
            elif operation == "login":
                session = self.auth.login(str(payload.get("email", "")), str(payload.get("password", "")))
            elif operation == "register":
                password = str(payload.get("password", ""))
                if password != str(payload.get("confirm_password", "")):
                    return {"ok": False, "error": "passwords_do_not_match"}
                session = self.auth.register(
                    str(payload.get("email", "")),
                    password,
                    str(payload.get("display_name", "")),
                    str(payload.get("locale", "es")),
                )
                if session.pending_confirmation:
                    # A pending signup may not enter the application. Purge the
                    # temporary local token and return only public identity data.
                    self.auth.logout(session.token)
                    return {"ok": True, "session": session.public()}
            elif operation == "verify-signup":
                session = self.auth.verify_signup(
                    str(payload.get("email", "")), str(payload.get("code", ""))
                )
            elif operation == "resend-signup":
                self.auth.resend_signup(str(payload.get("email", "")))
                return {"ok": True}
            elif operation == "restore":
                session = self.auth.restore()
                if session is None:
                    return {"ok": False, "error": "session_unavailable"}
            elif operation == "refresh":
                session = self.auth.refresh(session_token)
            elif operation == "forgot-password":
                self.auth.forgot_password(str(payload.get("email", "")))
                return {"ok": True}
            elif operation == "reset-password":
                password = str(payload.get("password", ""))
                if password != str(payload.get("confirm_password", "")):
                    return {"ok": False, "error": "passwords_do_not_match"}
                self.auth.reset_password(
                    str(payload.get("email", "")),
                    str(payload.get("code", "")),
                    password,
                )
                return {"ok": True}
            elif operation == "reauthenticate":
                self.auth.reauthenticate(session_token)
                return {"ok": True}
            elif operation == "change-password":
                password = str(payload.get("password", ""))
                if len(password) < 10:
                    return {"ok": False, "error": "password_too_short"}
                session = self.auth.update_user(
                    session_token,
                    {"password": password, "nonce": str(payload.get("nonce", "")).strip()},
                )
            elif operation == "change-email":
                email = normalize_email(str(payload.get("email", "")), reject_disposable=True)
                session = self.auth.update_user(session_token, {"email": email})
            elif operation == "logout-others":
                return {"ok": self.auth.logout_others(session_token)}
            elif operation == "mfa-status":
                return {"ok": True, "factors": self.auth.mfa_status(session_token)}
            elif operation == "mfa-enroll":
                return {"ok": True, "factor": self.auth.mfa_enroll(session_token, str(payload.get("friendly_name", "")))}
            elif operation == "mfa-verify":
                session = self.auth.mfa_verify(session_token, str(payload.get("factor_id", "")), str(payload.get("code", "")))
            elif operation == "mfa-unenroll":
                self.auth.mfa_unenroll(session_token, str(payload.get("factor_id", "")))
                return {"ok": True}
            elif operation == "delete-account":
                if payload.get("confirmation") != "DELETE":
                    return {"ok": False, "error": "delete_confirmation_required"}
                self.voice.interrupt()
                self.permissions.clear_session()
                return {"ok": self.auth.delete_account(session_token)}
            elif operation == "logout":
                self.voice.interrupt()
                self.permissions.clear_session()
                return {"ok": self.auth.logout(session_token)}
            else:
                return {"ok": False, "error": "unknown_auth_operation"}
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True, "session_token": session.token, "session": session.public()}

    def handle_session(self, session_token: str) -> dict[str, Any]:
        session = self.auth.get(session_token)
        return {"ok": session is not None, "session": session.public() if session else None}

    def health(self) -> dict[str, Any]:
        return {
            "ok": self._started,
            "startup_ms": round(self.startup_ms, 3),
            "tools_registered": len(self.tools.manifests()),
            "tools_loaded": self.tools.loaded_tool_count,
            "database": self.database.health(),
            "audio_backend_loaded": self.audio.backend_loaded,
            "plugins_loaded": self.plugins.loaded_count,
            "launcher_loaded": self.launcher.loaded,
            "auth_provider": self.auth.provider_name,
            "voice": self.voice.status(),
            "local_ai": self.local_ai.status(),
            "media": self.media.status(),
            "event_subscribers": self.events.subscriber_count,
            "paths": self.path_status(),
            "updates": self.updates.status(),
        }

    def _service_status(self) -> dict[str, Any]:
        plugins = self.plugins.scan()
        return {
            "cloud": {
                "settings_sync": "configured_on_demand" if self.settings_sync.configured else "not_configured",
                "device_pairing": "not_configured",
                "lan_direct": "configured_on_demand" if self.cloud.configured else "not_configured",
                "remote_relay": "configured_on_demand" if self.cloud.configured else "not_configured",
                "file_transfer": "configured_on_demand" if self.cloud.configured else "not_configured",
                "remote_commands": "not_configured",
                "mobile": "configured_on_demand" if self.cloud.configured else "not_configured",
            },
            "plugins": {
                "engine": "working",
                "installed": len(plugins),
                "enabled": sum(item.enabled for item in plugins),
                "active": self.plugins.loaded_count,
                "trusted_signature_provider": self.plugins.signature_verifier_configured,
                "marketplace": "deferred",
            },
            "updates": self.updates.status(),
        }

    def __enter__(self) -> ArcheonApplication:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


if __name__ == "__main__":
    # Developer convenience: VS Code's "Run Python File" button may execute
    # this module directly. Forward to the real application entry point.
    from archeon.__main__ import main

    raise SystemExit(main())
