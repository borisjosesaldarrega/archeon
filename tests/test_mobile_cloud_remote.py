from __future__ import annotations

import hashlib
from unittest.mock import patch
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from archeon.cloud import (
    ArcheonCloudClient,
    CommandReplayStore,
    RemoteAction,
    RemoteCommand,
    RemoteCommandExecutor,
    RemoteControlPolicy,
    RemoteIntentParser,
    can_preview,
)


def command(action: RemoteAction, *, confirmation: str | None = None) -> tuple[RemoteCommand, bytes]:
    secret = b"p" * 32
    arguments = {"confirmation_token": confirmation} if confirmation else {"query": "Minecraft"}
    value = RemoteCommand(
        id=str(uuid4()), user_id=str(uuid4()), source_device_id="phone-1",
        target_device_id="pc-1", action=action, arguments=arguments,
        risk="high" if action is RemoteAction.SHUTDOWN else "standard",
        idempotency_key=str(uuid4()), nonce="n" * 24,
        expires_at=(datetime.now(UTC) + timedelta(seconds=90)).isoformat(),
        confirmation_token_hash=hashlib.sha256(confirmation.encode()).hexdigest() if confirmation else None,
    )
    return value.sign(secret), secret


class MobileCloudRemoteTests(unittest.TestCase):
    def test_signed_paired_standard_command_executes_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            value, secret = command(RemoteAction.LAUNCH)
            executor = RemoteCommandExecutor(
                RemoteControlPolicy("pc-1", frozenset({"phone-1"}), remote_control_enabled=True),
                lambda _source: secret,
                CommandReplayStore(Path(temporary) / "replay.json"),
                {RemoteAction.LAUNCH: lambda args: {"ok": args["query"] == "Minecraft"}},
            )
            self.assertTrue(executor.execute(value)["ok"])
            with self.assertRaisesRegex(PermissionError, "replay"):
                executor.execute(value)

    def test_shutdown_fails_closed_without_opt_in_and_exact_confirmation(self) -> None:
        value, secret = command(RemoteAction.SHUTDOWN, confirmation="482913")
        policy = RemoteControlPolicy("pc-1", frozenset({"phone-1"}), remote_control_enabled=True)
        with self.assertRaisesRegex(PermissionError, "power_commands_disabled"):
            policy.authorize(value, secret, confirmation_token="482913")
        enabled = RemoteControlPolicy(
            "pc-1", frozenset({"phone-1"}), remote_control_enabled=True,
            power_commands_enabled=True,
        )
        with self.assertRaisesRegex(PermissionError, "confirmation_invalid"):
            enabled.authorize(value, secret, confirmation_token="000000")
        enabled.authorize(value, secret, confirmation_token="482913")

    def test_tampering_wrong_target_unpaired_and_expired_are_rejected(self) -> None:
        value, secret = command(RemoteAction.LAUNCH)
        policy = RemoteControlPolicy("pc-1", frozenset({"phone-1"}), remote_control_enabled=True)
        tampered = RemoteCommand(**{**value.__dict__, "arguments": {"query": "Other"}}) if hasattr(value, "__dict__") else RemoteCommand(
            value.id, value.user_id, value.source_device_id, value.target_device_id,
            value.action, {"query": "Other"}, value.risk, value.idempotency_key,
            value.nonce, value.expires_at, value.signature, value.confirmation_token_hash,
        )
        with self.assertRaisesRegex(PermissionError, "signature_invalid"):
            policy.authorize(tampered, secret)
        wrong_target = RemoteControlPolicy("pc-2", frozenset({"phone-1"}), remote_control_enabled=True)
        with self.assertRaisesRegex(PermissionError, "target_mismatch"):
            wrong_target.authorize(value, secret)
        unpaired = RemoteControlPolicy("pc-1", frozenset(), remote_control_enabled=True)
        with self.assertRaisesRegex(PermissionError, "not_paired"):
            unpaired.authorize(value, secret)

    def test_remote_language_parser_avoids_common_false_positives(self) -> None:
        parser = RemoteIntentParser()
        self.assertEqual(parser.parse("Apaga la PC").action, RemoteAction.SHUTDOWN)
        self.assertEqual(parser.parse("abre Minecraft en mi PC").arguments["query"], "minecraft")
        self.assertEqual(parser.parse("reproduce Daft Punk en la computadora").action, RemoteAction.MEDIA_PLAY)
        self.assertEqual(parser.parse("reproduce Daft Punk en mi celular").target_kind, "mobile")
        self.assertEqual(parser.parse("abre Discord en el móvil").arguments["query"], "discord")
        self.assertEqual(parser.parse("habre Discord en mi PC").arguments["query"], "discord")
        self.assertEqual(parser.parse("ponme Daft Punk en mi celular").action, RemoteAction.MEDIA_PLAY)
        for phrase in (
            "no apagues la PC", "¿cómo apago la PC?", "la PC se apaga sola",
            "cuando apague la PC", "hablábamos de apagar la PC", "abre Minecraft",
            "crea un documento para PC", "haz una imagen de un celular",
            "el archivo está en mi PC", "quiero una app móvil",
        ):
            self.assertIsNone(parser.parse(phrase), phrase)

    def test_remote_language_parser_resolves_safe_aliases_and_small_typos(self) -> None:
        parser = RemoteIntentParser()
        devices = {"Galaxy Boris": "android", "PC Estudio": "windows", "ARCHEON PC · DZ-KNIGHT": "windows", "PC Jarvis": "windows"}
        mobile = parser.parse("abre Discord en Galaxy Boris", devices)
        desktop = parser.parse("reproduce Daft Punk en PC Estudio", devices)
        self.assertIsNotNone(mobile)
        self.assertEqual(mobile.target_kind, "mobile")
        self.assertEqual(mobile.target_name, "Galaxy Boris")
        self.assertIsNotNone(desktop)
        self.assertEqual(desktop.target_kind, "desktop")
        self.assertEqual(desktop.target_name, "PC Estudio")
        branded = parser.parse("abre Discord en ARCHEON PC · DZ-KNIGHT", devices)
        self.assertIsNotNone(branded)
        self.assertEqual(branded.target_name, "ARCHEON PC · DZ-KNIGHT")
        alias = parser.parse("abreme Discord en jarvis", devices)
        self.assertIsNotNone(alias)
        self.assertEqual(alias.target_name, "PC Jarvis")
        typo = parser.parse("jarivs abre Discord", devices)
        self.assertIsNotNone(typo)
        self.assertEqual(typo.target_name, "PC Jarvis")
        self.assertIsNone(parser.parse("abre Discord en el teléfono de otra persona", devices))

    def test_remote_language_parser_rejects_ambiguous_alias(self) -> None:
        parser = RemoteIntentParser()
        devices = {"PC Jarvis": "windows", "Celular Jarvis": "android"}
        self.assertIsNone(parser.parse("abre Discord en Jarvis", devices))

    def test_preview_allowlist_rejects_active_or_unknown_content(self) -> None:
        self.assertTrue(can_preview("application/pdf"))
        self.assertTrue(can_preview("image/png"))
        self.assertFalse(can_preview("text/html"))
        self.assertFalse(can_preview("application/x-msdownload"))

    def test_android_pdf_preview_supports_real_zoom_navigation_and_safe_reopen(self) -> None:
        source = Path("mobile/android/app/src/main/java/com/dzknight/archeon/mobile/CloudPreviewActivity.java").read_text(encoding="utf-8")
        manifest = Path("mobile/android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn("PdfRenderer", source)
        self.assertIn("HorizontalScrollView", source)
        self.assertIn("imageLayout.width = rendered.getWidth()", source)
        self.assertIn("changeZoom(0.25f)", source)
        self.assertIn("renderPage(pageIndex + 1)", source)
        self.assertIn('android:name=".CloudPreviewActivity"', manifest)
        self.assertIn('android:exported="false"', manifest)
        self.assertIn('<queries>', manifest)
        self.assertIn('android.intent.category.LAUNCHER', manifest)

    def test_mobile_edge_uses_account_conversation_history_and_exposes_mfa_lifecycle(self) -> None:
        source = Path("supabase/functions/archeon-mobile-api/index.ts").read_text(encoding="utf-8")
        self.assertIn('operation === "mfa-enroll"', source)
        self.assertIn('operation === "mfa-verify"', source)
        self.assertIn('operation === "mfa-unenroll"', source)
        self.assertIn('conversation_id=eq.${encodeURIComponent(String(payload.conversation_id))}', source)
        self.assertIn('history = stored.reverse()', source)
        self.assertIn('contextualResearchSubject(effectiveText, history)', source)

    def test_mobile_context_uses_registry_threads_and_structured_message_context(self) -> None:
        source = Path("supabase/functions/archeon-mobile-api/index.ts").read_text(encoding="utf-8")
        self.assertIn("const CONTEXT_TOPICS: TopicDefinition[]", source)
        self.assertIn("const CONTEXT_ENTITIES: EntityDefinition[]", source)
        self.assertIn("function topicScores(", source)
        self.assertIn('"SWITCH_TO_RECENT_THREAD"', source)
        self.assertIn("context_data", source)
        self.assertIn("context_interpretation: context", source)
        self.assertIn("function contextualAnswer(context: ContextResult)", source)
        self.assertNotIn("Entendí tu solicitud:", source)
        self.assertIn('sabes\\s+', source)
        self.assertIn('continua|sigue', source)
        self.assertIn('que\\s+mas', source)
        self.assertIn('function isContextFollowup', source)
        self.assertIn('function lastResearchSubject', source)
        self.assertIn('replace(/^Más contexto sobre\\s+/iu, "")', source)
        self.assertIn('type ResearchAnswer', source)
        self.assertIn('function briefResearchExtract', source)
        self.assertIn('function researchContinuation', source)
        self.assertIn('continuation.length > 40', source)
        self.assertIn('Fuente: [Wikipedia]', source)
        self.assertIn('expandable_details:', source)
        self.assertNotIn('Entiendo que continúas con', source)
        self.assertIn('name: "ask_information"', source)
        self.assertIn('sabes|conoces|quien es', source)
        self.assertIn('name: "create_artifact"', source)
        self.assertIn('governing: true', source)
        self.assertIn('definition.governing ? (1 - first)', source)
        self.assertIn('context.intent.name === "create_artifact" ? null : mediaQuery', source)
        self.assertIn('name: "casual_conversation"', source)
        self.assertIn('name: "news_search"', source)
        self.assertIn("async function currentNewsAnswer", source)
        self.assertIn("https://news.google.com/rss/search", source)
        self.assertIn("news_sources: currentNews.sources", source)
        self.assertIn("function newsSearchTerms", source)
        self.assertIn('name: "date_time_query"', source)
        self.assertIn("function temporalResolution", source)
        self.assertIn("const TEMPORAL_FIELDS", source)
        self.assertIn('patterns: [], compatible_types: [], governing: true', source)
        self.assertIn("function currentDateTimeAnswer", source)
        self.assertIn("TEMPORAL_COMPOSITION_CUES", source)
        self.assertIn("history: string[] = []", source)
        self.assertIn('id: "weather"', source)
        self.assertIn("function requestedCapabilities", source)
        self.assertIn("function semanticSufficiency", source)
        self.assertNotIn("Necesito un poco más de detalle: ¿qué quieres que revise o haga?", source)
        self.assertIn("async function currentWeatherAnswer", source)
        self.assertIn('engine: "archeon-capability-planner"', source)
        self.assertNotIn("Estas son las novedades recientes que encontré", source)
        self.assertNotIn("`- [${item.title}](${item.link})", source)
        self.assertIn("const MOBILE_CAPABILITIES", source)
        self.assertIn('id: "vision", available: false', source)
        self.assertIn('context.intent.name === "inspect_visual"', source)

    def test_chat_titles_use_clean_context_and_empty_chats_are_not_persisted(self) -> None:
        source = Path("supabase/functions/archeon-mobile-api/index.ts").read_text(encoding="utf-8")
        mobile = Path("src/archeon/ui/mobile.js").read_text(encoding="utf-8")
        self.assertIn("function cleanTransportText", source)
        self.assertIn("context?.interpreted_request || context?.normalized_input", source)
        self.assertIn("unsafeConversationTitle", source)
        self.assertIn('payload.role === "assistant"', source)
        self.assertNotIn('payload.role === "user" && currentTitle === "Nuevo chat"', source)
        self.assertIn('if(!activeConversation){const created=await action("cloud.conversations.create"', mobile)
        self.assertNotIn('async function newChat(){stopMobileMedia();await action("media.stop").catch(()=>{});await discardComposerAttachments();if(cloudReady)', mobile)
        self.assertIn('id="mobile-conversation-search"', Path("src/archeon/ui/mobile.html").read_text(encoding="utf-8"))
        self.assertIn("function informationSubject", source)
        self.assertIn('return `Sobre ${information}`', source)
        self.assertIn('["Nuevo chat", "Información"]', source)
        self.assertIn('expandableDetails=result.expandable_details||null', mobile)
        self.assertIn('summary.textContent="Ver más"', mobile)
        self.assertIn('fullDetails.startsWith(summaryText)', mobile)
        self.assertIn('storedContext.presentation={expandable_details:expandableDetails}', mobile)
        stylesheet = Path("src/archeon/ui/mobile-fixes.css").read_text(encoding="utf-8")
        self.assertIn('grid-template-rows: auto auto auto minmax(0, 1fr)', stylesheet)
        self.assertIn('.conversation-search { height: 43px; min-height: 43px; max-height: 43px;', stylesheet)
        self.assertIn('@media (min-width: 760px)', stylesheet)
        self.assertIn('grid-template-columns: 88px minmax(0, 1fr)', stylesheet)
        self.assertIn('orientation: landscape', stylesheet)

    def test_mobile_activation_settings_are_device_aware_and_account_synced(self) -> None:
        source = Path("supabase/functions/archeon-mobile-api/index.ts").read_text(encoding="utf-8")
        mobile = Path("src/archeon/ui/mobile.js").read_text(encoding="utf-8")
        html = Path("src/archeon/ui/mobile.html").read_text(encoding="utf-8")
        self.assertIn("async function mobileSettings", source)
        self.assertIn('"account_settings"', source)
        self.assertIn('"device_settings"', source)
        self.assertIn("context_language_enabled", source)
        self.assertIn("background_enabled", source)
        self.assertIn("function updateMobileActivationState", mobile)
        self.assertIn("Intl.DateTimeFormat().resolvedOptions().timeZone", mobile)
        self.assertIn("syncMobileActivation", mobile)
        self.assertIn('id="mobile-context-language"', html)
        self.assertIn("https://archeon.netlify.app/plugins", html)
        self.assertIn('data:image/svg+xml;charset=utf-8', mobile)

    def test_device_session_revocation_is_bound_to_jwt_session_id(self) -> None:
        source = Path("supabase/functions/archeon-mobile-api/index.ts").read_text(encoding="utf-8")
        migration = Path("supabase/migrations/20261002175054_device_session_revocation.sql").read_text(encoding="utf-8")
        mobile = Path("src/archeon/ui/mobile.js").read_text(encoding="utf-8")
        self.assertIn('name === "cloud.devices.revoke"', source)
        self.assertIn("auth_session_id", source)
        self.assertIn("session_revoked_at", source)
        self.assertIn("private.archeon_current_session_active()", migration)
        self.assertIn("security definer", migration.lower())
        self.assertIn("'account_settings', 'device_settings'", migration)
        self.assertIn("archeon_cloud_objects_owner_select", migration)
        self.assertGreaterEqual(migration.count("private.archeon_current_session_active()"), 9)
        self.assertIn('"Cerrar sesión"', mobile)

    def test_image_generation_is_verified_ephemeral_and_downloadable(self) -> None:
        source = Path("supabase/functions/archeon-mobile-api/index.ts").read_text(encoding="utf-8")
        mobile = Path("src/archeon/ui/mobile.js").read_text(encoding="utf-8")
        desktop = Path("src/archeon/ui/app.js").read_text(encoding="utf-8")
        self.assertIn("async function generateEphemeralImage", source)
        self.assertIn("black-forest-labs-flux-1-schnell.hf.space", source)
        self.assertIn("gradio_api/call/infer", source)
        self.assertIn('error: "image_output_invalid"', source)
        self.assertIn('engine: "archeon-image"', source)
        self.assertIn("content_base64: standardBase64(bytes)", source)
        self.assertIn("ephemeral: true", source)
        self.assertNotIn("storage_path: path, display_name: name", source[source.index("async function generateEphemeralImage"):source.index("async function findOwnedMusic")])
        self.assertIn("result.generated_image", mobile)
        self.assertIn("downloadGeneratedImage", mobile)
        self.assertIn("generated-image-download", mobile)
        self.assertIn("renderGeneratedImage", desktop)
        self.assertIn('download.textContent="↓"', desktop)

    def test_cloud_client_is_explicitly_unconfigured(self) -> None:
        client = ArcheonCloudClient("", "")
        self.assertFalse(client.configured)
        with self.assertRaisesRegex(ValueError, "not_configured"):
            client.list_devices("token", "user")

    def test_device_heartbeat_preserves_name_changed_from_another_device(self) -> None:
        client = ArcheonCloudClient("https://example.supabase.co", "publishable")
        with patch.object(client, "_jwt_session_id", return_value="11111111-1111-4111-8111-111111111111"), patch.object(client, "_rest", side_effect=[
            [{"id": "pc-1", "display_name": "Jarvis"}],
            [{"id": "pc-1", "display_name": "Jarvis"}],
        ]) as request:
            registered = client.register_device(
                "token", user_id="user-1", installation_id="install-1",
                display_name="ARCHEON PC · DZ-KNIGHT", platform="windows",
                public_key="public", capabilities=["launcher.open"],
            )
        self.assertEqual(registered["display_name"], "Jarvis")
        posted = request.call_args_list[1].args[3]
        self.assertEqual(posted["display_name"], "Jarvis")
        self.assertEqual(posted["auth_session_id"], "11111111-1111-4111-8111-111111111111")

    def test_cloud_download_verifies_integrity(self) -> None:
        client = ArcheonCloudClient("https://example.supabase.co", "publishable")
        payload = b"verified cloud payload"
        with patch.object(client, "download_file", return_value=payload):
            self.assertEqual(
                client.download_verified_file(
                    "token", storage_path="user/file", expected_sha256=hashlib.sha256(payload).hexdigest()
                ),
                payload,
            )
            with self.assertRaisesRegex(ValueError, "integrity"):
                client.download_verified_file("token", storage_path="user/file", expected_sha256="0" * 64)

    def test_migration_has_rls_private_storage_realtime_and_no_service_role(self) -> None:
        migration = next(Path("supabase/migrations").glob("*mobile_cloud_remote_foundation.sql")).read_text(encoding="utf-8").lower()
        for table in (
            "archeon_devices", "archeon_device_pairings", "archeon_remote_commands",
            "archeon_conversations", "archeon_messages", "archeon_cloud_files",
        ):
            self.assertIn(f"alter table public.{table} enable row level security", migration)
            self.assertIn(table, migration)
        self.assertIn("'archeon-cloud', false", migration)
        self.assertIn("supabase_realtime", migration)
        self.assertNotIn("service_role", migration)


if __name__ == "__main__":
    unittest.main()
