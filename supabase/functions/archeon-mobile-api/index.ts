const SUPABASE_URL = Deno.env.get("SUPABASE_URL")?.replace(/\/$/, "") ?? "";
const GUEST_SECRET = Deno.env.get("ARCHEON_MOBILE_GUEST_SECRET") ?? "";

function firstKey(jsonName: string, legacyName: string): string {
  const legacy = Deno.env.get(legacyName) ?? "";
  if (legacy) return legacy;
  try {
    const values = JSON.parse(Deno.env.get(jsonName) ?? "{}");
    return String(values.default ?? Object.values(values)[0] ?? "");
  } catch (_) {
    return "";
  }
}

const PUBLISHABLE_KEY = firstKey("SUPABASE_PUBLISHABLE_KEYS", "SUPABASE_ANON_KEY");
const SECRET_KEY = firstKey("SUPABASE_SECRET_KEYS", "SUPABASE_SERVICE_ROLE_KEY");
const encoder = new TextEncoder();
const decoder = new TextDecoder();
const allowedOrigins = new Set([
  "https://appassets.androidplatform.net",
  "http://127.0.0.1:56789",
  "http://localhost:56789",
]);

function cors(req: Request): Record<string, string> {
  const origin = req.headers.get("origin") ?? "";
  return {
    "Access-Control-Allow-Origin": allowedOrigins.has(origin) ? origin : "https://appassets.androidplatform.net",
    "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-archeon-token, x-archeon-route, x-archeon-session, x-archeon-installation, x-archeon-device-name, x-file-name, x-conversation-id",
    "Access-Control-Allow-Methods": "GET, HEAD, POST, OPTIONS",
    "Vary": "Origin",
  };
}

function reply(req: Request, value: unknown, status = 200): Response {
  return Response.json(value, { status, headers: { ...cors(req), "Cache-Control": "no-store" } });
}

function base64Url(bytes: Uint8Array): string {
  const chunks: string[] = [];
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    chunks.push(String.fromCharCode(...bytes.subarray(offset, offset + 0x8000)));
  }
  return btoa(chunks.join("")).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function fromBase64Url(value: string): Uint8Array {
  const raw = atob(value.replaceAll("-", "+").replaceAll("_", "/") + "=".repeat((4 - value.length % 4) % 4));
  return Uint8Array.from(raw, c => c.charCodeAt(0));
}

async function hmac(value: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", encoder.encode(GUEST_SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return base64Url(new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(value))));
}

async function guestToken(installation: string): Promise<string> {
  const payload = base64Url(encoder.encode(JSON.stringify({ i: installation, e: Date.now() + 30 * 86400_000 })));
  return `guest.${payload}.${await hmac(payload)}`;
}

async function validGuest(token: string): Promise<boolean> {
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== "guest" || !GUEST_SECRET) return false;
  if ((await hmac(parts[1])) !== parts[2]) return false;
  try {
    const value = JSON.parse(decoder.decode(fromBase64Url(parts[1])));
    return typeof value.i === "string" && value.i.length >= 16 && Number(value.e) > Date.now();
  } catch (_) {
    return false;
  }
}

async function supabase(path: string, init: RequestInit = {}, token = "", admin = false): Promise<Response> {
  const key = admin ? SECRET_KEY : PUBLISHABLE_KEY;
  const headers = new Headers(init.headers);
  headers.set("apikey", key);
  headers.set("Authorization", `Bearer ${token || key}`);
  if (!headers.has("Content-Type") && init.body) headers.set("Content-Type", "application/json");
  return fetch(`${SUPABASE_URL}${path}`, { ...init, headers });
}

async function jsonOrError(response: Response): Promise<any> {
  let value: any = {};
  try { value = await response.json(); } catch (_) { /* empty response */ }
  if (!response.ok) {
    const code = value?.error_code || value?.code || value?.msg || value?.message || "request_failed";
    throw new Error(response.status === 429 ? "auth_rate_limited" : String(code));
  }
  return value;
}

function publicSession(value: any): any {
  const user = value?.user ?? value ?? {};
  const metadata = user.user_metadata ?? {};
  const factors = Array.isArray(user.factors) ? user.factors : [];
  const hasVerifiedFactor = factors.some((factor: any) => String(factor?.status || "").toLowerCase() === "verified");
  let assurance = "";
  try {
    const token = String(value?.access_token || "");
    const claims = token ? JSON.parse(decoder.decode(fromBase64Url(token.split(".")[1] || ""))) : {};
    assurance = String(claims?.aal || "");
  } catch (_) { /* malformed or unavailable token */ }
  return {
    mode: "account",
    provider: "supabase",
    identity: {
      user_id: String(user.id ?? ""),
      email: String(user.email ?? ""),
      display_name: String(metadata.display_name ?? String(user.email ?? "Usuario").split("@")[0]),
    },
    email_verified: Boolean(user.email_confirmed_at || user.confirmed_at),
    mfa_required: hasVerifiedFactor && assurance !== "aal2",
  };
}

async function userFor(token: string): Promise<any | null> {
  if (!token || await validGuest(token)) return null;
  const response = await supabase("/auth/v1/user", { method: "GET" }, token);
  return response.ok ? response.json() : null;
}

async function auth(req: Request, operation: string, payload: any, token: string): Promise<Response> {
  try {
    if (operation === "guest") {
      const installation = req.headers.get("x-archeon-installation") ?? crypto.randomUUID();
      const sessionToken = await guestToken(installation);
      return reply(req, { ok: true, session_token: sessionToken, session: { mode: "guest", provider: "local", identity: null, email_verified: false, mfa_required: false } });
    }
    if (operation === "login") {
      const value = await jsonOrError(await supabase("/auth/v1/token?grant_type=password", { method: "POST", body: JSON.stringify({ email: payload.email, password: payload.password }) }));
      return reply(req, { ok: true, session_token: value.access_token, refresh_token: value.refresh_token, session: publicSession(value) });
    }
    if (operation === "refresh") {
      const value = await jsonOrError(await supabase("/auth/v1/token?grant_type=refresh_token", { method: "POST", body: JSON.stringify({ refresh_token: payload.refresh_token }) }));
      return reply(req, { ok: true, session_token: value.access_token, refresh_token: value.refresh_token, session: publicSession(value) });
    }
    if (operation === "register") {
      const value = await jsonOrError(await supabase("/auth/v1/signup", { method: "POST", body: JSON.stringify({ email: payload.email, password: payload.password, data: { display_name: payload.display_name, locale: payload.locale || "es" } }) }));
      if (!value.access_token) return reply(req, { ok: true, session_token: "", session: { ...publicSession(value), pending_confirmation: true } });
      return reply(req, { ok: true, session_token: value.access_token, refresh_token: value.refresh_token, session: publicSession(value) });
    }
    if (operation === "verify-signup") {
      const value = await jsonOrError(await supabase("/auth/v1/verify", { method: "POST", body: JSON.stringify({ email: payload.email, token: payload.code, type: "signup" }) }));
      return reply(req, { ok: true, session_token: value.access_token, refresh_token: value.refresh_token, session: publicSession(value) });
    }
    if (operation === "resend-signup") {
      await jsonOrError(await supabase("/auth/v1/resend", { method: "POST", body: JSON.stringify({ email: payload.email, type: "signup" }) }));
      return reply(req, { ok: true });
    }
    if (operation === "forgot-password") {
      await jsonOrError(await supabase("/auth/v1/recover", { method: "POST", body: JSON.stringify({ email: payload.email }) }));
      return reply(req, { ok: true });
    }
    if (operation === "reset-password") {
      const verified = await jsonOrError(await supabase("/auth/v1/verify", { method: "POST", body: JSON.stringify({ email: payload.email, token: payload.code, type: "recovery" }) }));
      await jsonOrError(await supabase("/auth/v1/user", { method: "PUT", body: JSON.stringify({ password: payload.password }) }, verified.access_token));
      return reply(req, { ok: true });
    }
    if (operation === "logout") {
      if (token && !await validGuest(token)) await supabase("/auth/v1/logout?scope=local", { method: "POST", body: "{}" }, token);
      return reply(req, { ok: true });
    }
    if (operation === "mfa-status") {
      const user = await userFor(token);
      if (!user) throw new Error("session_required");
      return reply(req, { ok: true, factors: Array.isArray(user.factors) ? user.factors : [] });
    }
    if (operation === "mfa-enroll") {
      if (!await userFor(token)) throw new Error("session_required");
      const friendlyName = String(payload.friendly_name || "ARCHEON Mobile").trim().slice(0, 40) || "ARCHEON Mobile";
      const factor = await jsonOrError(await supabase("/auth/v1/factors", {
        method: "POST", body: JSON.stringify({ factor_type: "totp", friendly_name: friendlyName }),
      }, token));
      return reply(req, { ok: true, factor });
    }
    if (operation === "mfa-verify") {
      const factorId = String(payload.factor_id || "");
      const code = String(payload.code || "");
      if (!/^[A-Za-z0-9_-]{1,128}$/.test(factorId)) throw new Error("invalid_mfa_factor");
      if (!/^\d{6}$/.test(code)) throw new Error("invalid_mfa_code");
      const challenge = await jsonOrError(await supabase(`/auth/v1/factors/${factorId}/challenge`, {
        method: "POST", body: "{}",
      }, token));
      const value = await jsonOrError(await supabase(`/auth/v1/factors/${factorId}/verify`, {
        method: "POST", body: JSON.stringify({ challenge_id: challenge.id, code }),
      }, token));
      return reply(req, { ok: true, session_token: value.access_token, refresh_token: value.refresh_token, session: publicSession(value) });
    }
    if (operation === "mfa-unenroll") {
      const factorId = String(payload.factor_id || "");
      if (!/^[A-Za-z0-9_-]{1,128}$/.test(factorId)) throw new Error("invalid_mfa_factor");
      await jsonOrError(await supabase(`/auth/v1/factors/${factorId}`, { method: "DELETE" }, token));
      return reply(req, { ok: true });
    }
    return reply(req, { ok: false, error: "auth_operation_not_supported" }, 400);
  } catch (error) {
    return reply(req, { ok: false, error: error instanceof Error ? error.message : "auth_request_failed" }, 400);
  }
}

async function rest(token: string, table: string, query: string, init: RequestInit = {}): Promise<any> {
  const response = await supabase(`/rest/v1/${table}${query}`, init, token);
  return jsonOrError(response);
}

function previewAllowed(mime: string): boolean {
  return mime.startsWith("image/") || mime.startsWith("text/") || mime === "application/pdf" || mime === "application/json";
}

function conversationTitle(body: string): string {
  let value = String(body || "").replace(/\s+/g, " ").trim().replace(/^(?:archi|archeon)[,:\s-]+/iu, "").replace(/^(?:por favor|oye|hola)[,:\s-]+/iu, "");
  const research = value.match(/^(?:investiga|busca(?:\s+informaci[oó]n)?(?:\s+sobre)?|expl[ií]came)\s+(.+)/iu);
  if (research?.[1]) value = `Investigación · ${research[1]}`;
  const music = value.match(/^(?:reproduce|pon(?:me)?)\s+(.+)/iu);
  if (music?.[1]) value = `Música · ${music[1]}`;
  const file = remoteFileIntent(value);
  if (file) value = `Archivo · ${file.query}`;
  const words = value.split(" ");
  const compact = words.slice(0, 9).join(" ").slice(0, 64).trim();
  return compact || "Nuevo chat";
}

async function ensureMobileDevice(req: Request, token: string, userId: string): Promise<any | null> {
  const installation = String(req.headers.get("x-archeon-installation") || "").slice(0, 128);
  if (installation.length < 16) return null;
  const requestedName = String(req.headers.get("x-archeon-device-name") || "Este teléfono").trim().slice(0, 120) || "Este teléfono";
  const existing = await rest(token, "archeon_devices", `?select=id,display_name&user_id=eq.${encodeURIComponent(userId)}&installation_id=eq.${encodeURIComponent(installation)}&limit=1`, { method: "GET" });
  // The cloud name is authoritative after first registration. This lets any
  // device in the same account rename another one without the target's next
  // heartbeat immediately overwriting that choice with a stale local value.
  const displayName = String(existing?.[0]?.display_name || requestedName).slice(0, 120);
  const rows = await rest(token, "archeon_devices", "?on_conflict=user_id,installation_id&select=id,installation_id,display_name,platform,capabilities,remote_control_enabled,power_commands_enabled,file_access_enabled,last_seen_at", {
    method: "POST", headers: { Prefer: "resolution=merge-duplicates,return=representation" },
    body: JSON.stringify({ user_id: userId, installation_id: installation, display_name: displayName, platform: "android", public_key: await hmac(`device:${userId}:${installation}`), capabilities: ["media.play", "launcher.open", "cloud.files"], remote_control_enabled: true, file_access_enabled: true, last_seen_at: new Date().toISOString(), updated_at: new Date().toISOString() }),
  });
  return rows[0] || null;
}

function desktopRemoteIntent(text: string): { action: string; query: string; targetLabel: string } | null {
  const value = text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("es").trim().replace(/[.!?¡¿]+$/g, "");
  if (/\b(?:no|nunca|jamas|sin|evita|evitar)\b/.test(value) || /^(?:como|puedo|podria|que pasa|sabes)\b/.test(value)) return null;
  const target = "(?:(?:mi|la|el)\\s+)?(?:pc|computadora|ordenador|equipo|desktop)";
  const launch = value.match(new RegExp(`^(?:abre|abreme|habre|inicia|ejecuta)\\s+(.+?)\\s+en\\s+${target}$`, "u"));
  if (launch?.[1]?.trim().length >= 2) return { action: "launcher.open", query: launch[1].trim(), targetLabel: "" };
  const media = value.match(new RegExp(`^(?:reproduce|reprodus|pon|ponme)\\s+(.+?)\\s+en\\s+${target}$`, "u"));
  if (media?.[1]?.trim().length >= 2) return { action: "media.play", query: media[1].trim(), targetLabel: "" };
  const named = value.match(/^(abre|abreme|habre|inicia|ejecuta|reproduce|reprodus|pon|ponme)\s+(.+?)\s+en\s+([\p{L}\p{N}][\p{L}\p{N} _.·-]{1,59})$/u);
  if (named?.[2] && named?.[3]) return {
    action: /^(?:reproduce|reprodus|pon|ponme)$/.test(named[1]) ? "media.play" : "launcher.open",
    query: named[2].trim(), targetLabel: named[3].trim(),
  };
  const prefixed = value.match(/^(?:en\s+)?([\p{L}\p{N}][\p{L}\p{N} _.·-]{1,59})\s+(abre|abreme|habre|inicia|ejecuta|reproduce|reprodus|pon|ponme)\s+(.+)$/u);
  if (prefixed?.[1] && prefixed?.[3]) return {
    action: /^(?:reproduce|reprodus|pon|ponme)$/.test(prefixed[2]) ? "media.play" : "launcher.open",
    query: prefixed[3].trim(), targetLabel: prefixed[1].trim(),
  };
  return null;
}

function deviceKey(value: string): string {
  const clean = value.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("es").replace(/[^\p{L}\p{N}]+/gu, " ").trim();
  const generic = new Set(["archeon", "pc", "computadora", "ordenador", "equipo", "desktop", "windows", "celular", "movil", "telefono", "android", "mi", "el", "la"]);
  const distinctive = clean.split(/\s+/).filter(part => part && !generic.has(part));
  return distinctive.join(" ") || clean;
}

function editDistance(left: string, right: string): number {
  const rows = Array.from({ length: left.length + 1 }, () => Array(right.length + 1).fill(0));
  for (let i = 0; i <= left.length; i += 1) rows[i][0] = i;
  for (let j = 0; j <= right.length; j += 1) rows[0][j] = j;
  for (let i = 1; i <= left.length; i += 1) for (let j = 1; j <= right.length; j += 1) {
    rows[i][j] = Math.min(rows[i - 1][j] + 1, rows[i][j - 1] + 1, rows[i - 1][j - 1] + (left[i - 1] === right[j - 1] ? 0 : 1));
    if (i > 1 && j > 1 && left[i - 1] === right[j - 2] && left[i - 2] === right[j - 1]) rows[i][j] = Math.min(rows[i][j], rows[i - 2][j - 2] + 1);
  }
  return rows[left.length][right.length];
}

function resolveNamedDevice(devices: any[], label: string): { device: any | null; ambiguous: boolean } {
  const wanted = deviceKey(label);
  if (wanted.length < 2) return { device: null, ambiguous: false };
  const scored = devices.flatMap(device => {
    const key = deviceKey(String(device.display_name || ""));
    const full = String(device.display_name || "").normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("es").replace(/[^\p{L}\p{N}]+/gu, " ").trim();
    if (wanted === key || wanted === full) return [{ score: 0, device }];
    if (key.split(/\s+/).includes(wanted) || (wanted.length >= 4 && key.includes(wanted))) return [{ score: 1, device }];
    const distance = editDistance(wanted, key);
    return distance <= (wanted.length >= 4 ? 1 : 0) ? [{ score: 2 + distance, device }] : [];
  }).sort((a, b) => a.score - b.score || String(a.device.display_name).localeCompare(String(b.device.display_name)));
  if (!scored.length) return { device: null, ambiguous: false };
  if (scored.length > 1 && scored[0].score === scored[1].score) return { device: null, ambiguous: true };
  return { device: scored[0].device, ambiguous: false };
}

function remoteFileIntent(text: string): { query: string; targetLabel: string } | null {
  const value = text.trim().replace(/[.!?¡¿]+$/g, "");
  const directed = value.match(/^(?:p[aá]same|m[aá]ndame|env[ií]ame|traeme|tr[aá]eme|transfiere)\s+(?:(?:el|la)\s+)?(?:(?:archivo|documento|pdf)\s+)?(?:con\s+nombre\s+)?["“”']?(.+?)["“”']?\s+(?:de|desde|que\s+(?:lo\s+)?tiene)\s+([\p{L}\p{N}][\p{L}\p{N} _.·-]{1,59})$/iu);
  if (directed?.[1] && directed?.[2]) return { query: directed[1].trim(), targetLabel: directed[2].trim() };
  const prefixed = value.match(/^([\p{L}\p{N}][\p{L}\p{N} _.·-]{1,59})\s+(?:p[aá]same|m[aá]ndame|env[ií]ame|traeme|tr[aá]eme)\s+(?:(?:el|la)\s+)?(?:(?:archivo|documento|pdf)\s+)?(?:con\s+nombre\s+)?["“”']?(.+?)["“”']?$/iu);
  return prefixed?.[1] && prefixed?.[2] ? { query: prefixed[2].trim(), targetLabel: prefixed[1].trim() } : null;
}

async function waitForRemoteResult(token: string, id: string): Promise<any | null> {
  for (let attempt = 0; attempt < 24; attempt += 1) {
    const rows = await rest(token, "archeon_remote_commands", `?id=eq.${encodeURIComponent(id)}&select=id,action,state,error_code,result&limit=1`, { method: "GET" });
    const command = rows?.[0];
    if (command && ["succeeded", "failed", "rejected", "expired", "cancelled"].includes(command.state)) return command;
    await new Promise(resolve => setTimeout(resolve, 750));
  }
  return null;
}

async function action(req: Request, payload: any, token: string): Promise<Response> {
  const name = String(payload.action ?? "");
  const user = await userFor(token);
  const guest = await validGuest(token);
  if (!user && !guest) return reply(req, { ok: false, error: "session_required" }, 401);
  try {
    if (name === "settings.get") return reply(req, { ok: true, settings: { intelligence: { profile: "balanced", context_size: 4096, max_tokens: 1024, conversation_turns: 4 } } });
    if (name === "settings.update") return reply(req, { ok: true, settings: payload.changes ?? {} });
    if (name === "permissions.list") return reply(req, { ok: true, permissions: [] });
    if (name === "permissions.update") return reply(req, { ok: true, permissions: [] });
    if (name.startsWith("media.") || name === "attachment.remove") return reply(req, { ok: true, media: { state: "stopped" } });
    if (!user) return reply(req, { ok: false, error: "account_session_required" }, 401);
    const userId = String(user.id);
    if (name === "cloud.conversations.list") {
      let rows = await rest(token, "archeon_conversations", "?select=id,title,created_at,updated_at&archived_at=is.null&order=updated_at.desc");
      const unnamed = rows.filter((item: any) => item.title === "Nuevo chat").slice(0, 20);
      await Promise.all(unnamed.map(async (item: any) => {
        const messages = await rest(token, "archeon_messages", `?conversation_id=eq.${encodeURIComponent(item.id)}&role=eq.user&select=body&order=created_at.asc&limit=1`);
        if (messages?.[0]?.body) await rest(token, "archeon_conversations", `?id=eq.${encodeURIComponent(item.id)}`, { method: "PATCH", body: JSON.stringify({ title: conversationTitle(messages[0].body), updated_at: new Date().toISOString() }) });
      }));
      if (unnamed.length) rows = await rest(token, "archeon_conversations", "?select=id,title,created_at,updated_at&archived_at=is.null&order=updated_at.desc");
      return reply(req, { ok: true, conversations: rows });
    }
    if (name === "cloud.conversations.create") {
      const rows = await rest(token, "archeon_conversations", "?select=id,title,created_at,updated_at", { method: "POST", headers: { Prefer: "return=representation" }, body: JSON.stringify({ user_id: userId, title: String(payload.title || "Nuevo chat").slice(0, 120) }) });
      return reply(req, { ok: true, conversation: rows[0] });
    }
    if (name === "cloud.conversations.rename") {
      const rows = await rest(token, "archeon_conversations", `?id=eq.${encodeURIComponent(payload.conversation_id)}&select=id,title,created_at,updated_at`, { method: "PATCH", headers: { Prefer: "return=representation" }, body: JSON.stringify({ title: String(payload.title || "Nuevo chat").slice(0, 120), updated_at: new Date().toISOString() }) });
      return reply(req, { ok: true, conversation: rows[0] });
    }
    if (name === "cloud.conversations.archive") {
      await rest(token, "archeon_conversations", `?id=eq.${encodeURIComponent(payload.conversation_id)}`, { method: "PATCH", body: JSON.stringify({ archived_at: new Date().toISOString(), updated_at: new Date().toISOString() }) });
      return reply(req, { ok: true });
    }
    if (name === "cloud.messages.list") {
      const rows = await rest(token, "archeon_messages", `?select=id,role,body,created_at&conversation_id=eq.${encodeURIComponent(payload.conversation_id)}&order=created_at.asc`);
      return reply(req, { ok: true, messages: rows });
    }
    if (name === "cloud.messages.add") {
      const rows = await rest(token, "archeon_messages", "?select=id,role,body,created_at", { method: "POST", headers: { Prefer: "return=representation" }, body: JSON.stringify({ user_id: userId, conversation_id: payload.conversation_id, role: payload.role, body: String(payload.body || "").slice(0, 100000), client_message_id: crypto.randomUUID() }) });
      const conversations = await rest(token, "archeon_conversations", `?id=eq.${encodeURIComponent(payload.conversation_id)}&select=id,title&limit=1`);
      const currentTitle = String(conversations?.[0]?.title || "");
      const nextTitle = payload.role === "user" && currentTitle === "Nuevo chat" ? conversationTitle(String(payload.body || "")) : currentTitle;
      await rest(token, "archeon_conversations", `?id=eq.${encodeURIComponent(payload.conversation_id)}`, { method: "PATCH", body: JSON.stringify({ title: nextTitle || "Nuevo chat", updated_at: new Date().toISOString() }) });
      return reply(req, { ok: true, message: rows[0], conversation_title: nextTitle || "Nuevo chat" });
    }
    if (name === "cloud.devices.list") {
      const installation = String(req.headers.get("x-archeon-installation") || "").slice(0, 128);
      await ensureMobileDevice(req, token, userId);
      const rows = await rest(token, "archeon_devices", "?select=id,installation_id,display_name,platform,capabilities,remote_control_enabled,power_commands_enabled,file_access_enabled,last_seen_at&order=last_seen_at.desc");
      return reply(req, { ok: true, devices: rows.map((device: any) => ({ ...device, current: device.installation_id === installation })) });
    }
    if (name === "cloud.devices.rename") {
      await ensureMobileDevice(req, token, userId);
      const deviceId = String(payload.device_id || "");
      const displayName = String(payload.display_name || "").trim().replace(/[\r\n\t]+/g, " ").slice(0, 60);
      if (!displayName) throw new Error("device_name_required");
      const rows = await rest(token, "archeon_devices", `?id=eq.${encodeURIComponent(deviceId)}&select=id,display_name`, { method: "PATCH", headers: { Prefer: "return=representation" }, body: JSON.stringify({ display_name: displayName, updated_at: new Date().toISOString() }) });
      if (!rows.length) throw new Error("device_not_found");
      return reply(req, { ok: true, device: rows[0] });
    }
    if (name === "remote.commands.pending") {
      const current = await ensureMobileDevice(req, token, userId);
      if (!current) throw new Error("current_device_not_registered");
      const rows = await rest(token, "archeon_remote_commands", `?select=id,action,arguments,state,expires_at&target_device_id=eq.${encodeURIComponent(current.id)}&state=eq.queued&expires_at=gt.${encodeURIComponent(new Date().toISOString())}&order=created_at.asc&limit=10`);
      return reply(req, { ok: true, commands: rows });
    }
    if (name === "remote.commands.complete") {
      const current = await ensureMobileDevice(req, token, userId);
      if (!current) throw new Error("current_device_not_registered");
      const succeeded = Boolean(payload.succeeded);
      await rest(token, "archeon_remote_commands", `?id=eq.${encodeURIComponent(payload.command_id)}&target_device_id=eq.${encodeURIComponent(current.id)}&state=eq.queued`, { method: "PATCH", body: JSON.stringify({ state: succeeded ? "succeeded" : "failed", completed_at: new Date().toISOString(), error_code: succeeded ? null : String(payload.error || "remote_action_failed").slice(0, 120), result: payload.result || {} }) });
      return reply(req, { ok: true });
    }
    if (name === "cloud.files.list") {
      const rows = await rest(token, "archeon_cloud_files", "?select=id,display_name,mime_type,byte_size,sha256,state,created_at&state=eq.available&order=created_at.desc");
      return reply(req, { ok: true, files: rows.map((file: any) => ({ ...file, preview_allowed: previewAllowed(file.mime_type) })) });
    }
    if (name === "cloud.files.delete") {
      const rows = await rest(token, "archeon_cloud_files", `?id=eq.${encodeURIComponent(payload.file_id)}&select=id,storage_path`, { method: "GET" });
      if (!rows[0]) throw new Error("cloud_file_not_found");
      await supabase(`/storage/v1/object/archeon-cloud/${rows[0].storage_path}`, { method: "DELETE" }, token);
      await rest(token, "archeon_cloud_files", `?id=eq.${encodeURIComponent(payload.file_id)}`, { method: "PATCH", body: JSON.stringify({ state: "deleted", deleted_at: new Date().toISOString() }) });
      return reply(req, { ok: true });
    }
    if (name === "cloud.files.preview" || name === "cloud.files.download") {
      const rows = await rest(token, "archeon_cloud_files", `?id=eq.${encodeURIComponent(payload.file_id)}&state=eq.available&select=id,storage_path,display_name,mime_type,byte_size,sha256`, { method: "GET" });
      const file = rows[0];
      if (!file || file.byte_size > 12 * 1024 * 1024) throw new Error("cloud_file_too_large_for_mobile_preview");
      const response = await supabase(`/storage/v1/object/authenticated/archeon-cloud/${file.storage_path}`, { method: "GET" }, token);
      if (!response.ok) throw new Error("cloud_download_failed");
      const bytes = new Uint8Array(await response.arrayBuffer());
      return reply(req, { ok: true, file: { ...file, content_base64: base64Url(bytes).replaceAll("-", "+").replaceAll("_", "/") + "=".repeat((4 - base64Url(bytes).length % 4) % 4) } });
    }
    return reply(req, { ok: false, error: "action_not_supported_on_mobile" }, 400);
  } catch (error) {
    return reply(req, { ok: false, error: error instanceof Error ? error.message : "cloud_unavailable" }, 400);
  }
}

async function uploadAttachment(req: Request, token: string): Promise<Response> {
  if (!await validGuest(token) && !await userFor(token)) return reply(req, { ok: false, error: "session_required" }, 401);
  const bytes = new Uint8Array(await req.arrayBuffer());
  if (!bytes.length || bytes.length > 12 * 1024 * 1024) return reply(req, { ok: false, error: "attachment_size_out_of_range" }, 400);
  const name = decodeURIComponent(req.headers.get("x-file-name") || "archivo").replace(/[\\/\0]/g, "_").slice(0, 180);
  const mime = (req.headers.get("content-type") || "application/octet-stream").split(";")[0];
  const path = `mobile-pending/${crypto.randomUUID()}`;
  const stored = await supabase(`/storage/v1/object/archeon-cloud/${path}`, { method: "POST", headers: { "Content-Type": mime, "x-upsert": "false" }, body: bytes }, "", true);
  if (!stored.ok) return reply(req, { ok: false, error: "attachment_upload_failed" }, 400);
  const payload = base64Url(encoder.encode(JSON.stringify({ p: path, n: name, m: mime, e: Date.now() + 3600_000 })));
  const id = `att.${payload}.${await hmac(payload)}`;
  return reply(req, { ok: true, attachment: { id, name, kind: mime.startsWith("image/") ? "image" : mime.startsWith("video/") ? "video" : "file" } });
}

async function readAttachment(id: string): Promise<{ content: any; path: string } | null> {
  const parts = id.split(".");
  if (parts.length !== 3 || parts[0] !== "att" || await hmac(parts[1]) !== parts[2]) return null;
  const meta = JSON.parse(decoder.decode(fromBase64Url(parts[1])));
  if (Number(meta.e) < Date.now()) return null;
  const response = await supabase(`/storage/v1/object/archeon-cloud/${meta.p}`, { method: "GET" }, "", true);
  if (!response.ok) return null;
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (String(meta.m).startsWith("image/")) {
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return { path: meta.p, content: { type: "image_url", image_url: { url: `data:${meta.m};base64,${btoa(binary)}` } } };
  }
  const textMime = String(meta.m).startsWith("text/") || ["application/json", "application/xml"].includes(String(meta.m));
  const excerpt = textMime ? decoder.decode(bytes.slice(0, 80_000)) : `[Archivo adjunto: ${meta.n}, tipo ${meta.m}, ${bytes.length} bytes]`;
  return { path: meta.p, content: { type: "text", text: excerpt } };
}

function requestsFileTransferToPc(text: string): boolean {
  const value = text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("es").trim().replace(/[.!?¡¿]+$/g, "");
  return /^(?:envia|pasa|manda|transfiere)\s+(?:este\s+|el\s+)?archivo(?:\s+adjunto)?\s+(?:a|al|para)\s+(?:mi\s+)?(?:pc|computadora|ordenador|equipo|desktop)$/.test(value);
}

async function persistAttachmentToCloud(id: string, token: string, userId: string, uploaderDeviceId: string | null): Promise<any | null> {
  const parts = id.split(".");
  if (parts.length !== 3 || parts[0] !== "att" || await hmac(parts[1]) !== parts[2]) return null;
  const meta = JSON.parse(decoder.decode(fromBase64Url(parts[1])));
  if (Number(meta.e) < Date.now()) return null;
  const response = await supabase(`/storage/v1/object/archeon-cloud/${meta.p}`, { method: "GET" }, "", true);
  if (!response.ok) return null;
  const bytes = new Uint8Array(await response.arrayBuffer());
  const name = String(meta.n || "archivo").replace(/[\\/\0]/g, "_").slice(0, 255);
  const mime = String(meta.m || "application/octet-stream").slice(0, 255);
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))).map(v => v.toString(16).padStart(2, "0")).join("");
  const path = `${userId}/${crypto.randomUUID()}/${encodeURIComponent(name)}`;
  const stored = await supabase(`/storage/v1/object/archeon-cloud/${path}`, { method: "POST", headers: { "Content-Type": mime, "x-upsert": "false" }, body: bytes }, token);
  if (!stored.ok) return null;
  const rows = await rest(token, "archeon_cloud_files", "?select=id,display_name,mime_type,byte_size,sha256,state,created_at", { method: "POST", headers: { Prefer: "return=representation" }, body: JSON.stringify({ user_id: userId, uploader_device_id: uploaderDeviceId, storage_path: path, display_name: name, mime_type: mime, byte_size: bytes.length, sha256: digest, state: "available" }) });
  await supabase(`/storage/v1/object/archeon-cloud/${meta.p}`, { method: "DELETE" }, "", true);
  return rows[0] || null;
}

function mediaQuery(text: string): string | null {
  const normalized = text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("es");
  if (/\b(?:crea|crear|haz|hacer|genera|generar|disena|elabora|redacta|escribe)\b/.test(normalized)
    && /\b(?:documento|docx|pdf|imagen|foto|presentacion|diapositivas|hoja de calculo|excel|archivo)\b/.test(normalized)) return null;
  const match = text.match(/\b(?:reproduce|reproducir|pon|poner|play|toca|escucha)\b\s*(?:la canci[oó]n|m[uú]sica|algo de)?\s*(.+)/iu);
  if (!match || /\b(?:pc|computadora|ordenador|desktop)\b/iu.test(text)) return null;
  return match[1].trim().slice(0, 160) || null;
}

async function findOwnedMusic(token: string, query: string): Promise<any[]> {
  const user = await userFor(token);
  if (!user) return [];
  const rows = await rest(token, "archeon_cloud_files", "?select=id,storage_path,display_name,mime_type,byte_size&state=eq.available&mime_type=like.audio%2F*&order=created_at.desc&limit=100", { method: "GET" });
  const terms = query.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("es").split(/\s+/).filter(Boolean);
  const matches = (Array.isArray(rows) ? rows : []).filter((item: any) => {
    const name = String(item.display_name || "").normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("es");
    return terms.every(term => name.includes(term));
  }).slice(0, 12);
  const tracks: any[] = [];
  for (const item of matches) {
    const signed = await supabase(`/storage/v1/object/sign/archeon-cloud/${item.storage_path}`, { method: "POST", body: JSON.stringify({ expiresIn: 3600 }) }, "", true);
    if (!signed.ok) continue;
    const value = await signed.json();
    const relative = String(value.signedURL || value.signedUrl || "");
    if (!relative) continue;
    tracks.push({
      title: String(item.display_name).replace(/\.[^.]+$/, ""), artist: "Biblioteca ARCHEON", album: "Cloud personal",
      source_url: relative.startsWith("http") ? relative : `${SUPABASE_URL}/storage/v1${relative}`,
      artwork_url: "", playback_kind: "native_audio", duration_ms: 0, provider: "archeon_cloud", ad_free: true,
    });
  }
  return tracks;
}

async function findMusic(query: string): Promise<any[]> {
  const youtubeHeaders = {
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Cookie": "CONSENT=YES+cb.20210328-17-p0.en+FX+667; SOCS=CAI",
  };
  const collectRenderers = (data: any, limit: number): any[] => {
    const output: any[] = [];
    const visit = (value: any): void => {
      if (!value || typeof value !== "object" || output.length >= limit) return;
      const renderer = value.videoRenderer || value.compactVideoRenderer;
      if (renderer) output.push(renderer);
      for (const child of Object.values(value)) visit(child);
    };
    visit(data);
    return output;
  };
  const searchYouTube = async (search: string, limit = 30): Promise<any[]> => {
    try {
      const response = await fetch(`https://www.youtube.com/results?search_query=${encodeURIComponent(search)}`, { headers: youtubeHeaders });
      if (!response.ok) return [];
      const html = await response.text();
      const initial = html.match(/(?:var ytInitialData = |ytInitialData"\s*:\s*)({.+?});?<\/script>/s)?.[1];
      if (!initial) return [];
      return collectRenderers(JSON.parse(initial), limit);
    } catch { return []; }
  };
  const exact = await searchYouTube(`${query} official music`, 36);
  if (!exact.length) return [];
  const firstTitle = String(exact[0]?.title?.runs?.[0]?.text || exact[0]?.title?.simpleText || "");
  const artistHint = firstTitle.split(/\s[-–—]\s/, 1)[0]?.trim() || "";
  let recommended: any[] = [];
  try {
    const firstId = String(exact[0]?.videoId || "");
    const response = await fetch(`https://www.youtube.com/watch?v=${encodeURIComponent(firstId)}`, { headers: youtubeHeaders });
    const html = response.ok ? await response.text() : "";
    const initial = html.match(/(?:var ytInitialData = |ytInitialData"\s*:\s*)({.+?});?<\/script>/s)?.[1];
    if (initial) recommended = collectRenderers(JSON.parse(initial), 48).filter(item => item.videoId !== firstId);
  } catch { /* Search-based related tracks remain available. */ }
  const related = /^[\p{L}\p{N} .&']{2,50}$/u.test(artistHint)
    ? (await Promise.all([
      searchYouTube(`${artistHint} radio mix canciones parecidas`, 30),
        searchYouTube(`artistas similares a ${artistHint} canciones oficiales -mix`, 30),
        searchYouTube(`${artistHint} feat official music`, 30),
        searchYouTube(`${artistHint} canciones oficiales`, 24),
      ])).flat()
    : [];
  const seedArtists = [...recommended, ...related].map(item => String(
    item.ownerText?.runs?.[0]?.text || item.longBylineText?.runs?.[0]?.text || "",
  )).filter((value, index, values) => {
    const normalized = value.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("es").trim();
    const hint = artistHint.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("es").trim();
    return /^[\p{L}\p{N} .&']{2,45}$/u.test(value) && normalized !== hint
      && !/records?|music|m[uú]sica|official|oficial|topic|vevo|youtube/iu.test(value)
      && values.findIndex(other => other.toLocaleLowerCase("es") === value.toLocaleLowerCase("es")) === index;
  }).slice(0, 4);
  const secondHop = (await Promise.all(seedArtists.map(seed => searchYouTube(`${seed} canciones oficiales`, 18)))).flat();
  const renderers = [exact[0], ...recommended, ...related, ...secondHop, ...exact.slice(1)];
  const normalizeWords = (value: string): string[] => value.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("es")
    .replace(/[([{].*?[)\]}]/g, " ")
    .replace(/\b(?:official|oficial|video|audio|lyrics?|lyric|letra|visualizer|hd|4k|remaster(?:ed|izada)?|live|en vivo|slowed|reverb|sped up|instrumental|karaoke|cover|remix|version|versiones?|subtitulado|subtitulos?|espanol|english|latino|topic|vevo)\b/g, " ")
    .match(/[\p{L}\p{N}]{2,}/gu) || [];
  const artistWords = new Set(normalizeWords(artistHint));
  const requestedCore = normalizeWords(query).filter(word => !artistWords.has(word));
  const seenVideos = new Set<string>(), seenSongs = new Set<string>();
  const candidates: any[] = [];
  for (const item of renderers) {
    const id = String(item.videoId || "");
    if (!/^[A-Za-z0-9_-]{11}$/.test(id) || seenVideos.has(id)) continue;
    const durationText = String(item.lengthText?.simpleText || item.lengthText?.runs?.[0]?.text || "");
    const parts = durationText.split(":").map(Number);
    const durationSeconds = parts.every(Number.isFinite) ? parts.reduce((total, part) => total * 60 + part, 0) : 0;
    if (durationSeconds && (durationSeconds < 60 || durationSeconds > 720)) continue;
    const rawTitle = String(item.title?.runs?.[0]?.text || item.title?.simpleText || query);
    if (/\b(?:mix(?:\s|$)|enganchad[oa]s?|grandes? [eé]xitos?|mejores? canciones?|compilaci[oó]n|playlist|top\s*\d+|versus|\d+\s+canciones|canciones? m[aá]s escuchadas?)\b/iu.test(rawTitle)) continue;
    const titleWords = normalizeWords(rawTitle);
    const owner = String(item.ownerText?.runs?.[0]?.text || item.longBylineText?.runs?.[0]?.text || "YouTube");
    const titleArtist = rawTitle.split(/\s[-–—|]\s/, 1)[0]?.trim() || owner;
    const titleArtistWords = normalizeWords(titleArtist), artistHintKey = [...artistWords].sort().join(" ");
    const ownerWords = new Set([...normalizeWords(owner), ...titleArtistWords]);
    const coreWords = titleWords.filter(word => !ownerWords.has(word));
    const songKey = [...new Set(coreWords.length ? coreWords : titleWords)].sort().join(" ");
    if (!songKey || seenSongs.has(songKey)) continue;
    const songWords = new Set(titleWords), sameRequestedSong = requestedCore.length > 0 && requestedCore.every(word => songWords.has(word));
    if (sameRequestedSong && candidates.some(candidate => candidate.sameRequestedSong)) continue;
    const artistKey = artistWords.size && [...artistWords].every(word => titleArtistWords.includes(word))
      ? artistHintKey
      : titleArtistWords.slice(0, 5).join(" ") || normalizeWords(owner).slice(0, 5).join(" ") || "youtube";
    seenVideos.add(id); seenSongs.add(songKey);
    const thumbnails = item.thumbnail?.thumbnails ?? [];
    candidates.push({ sameRequestedSong, artistKey, track: {
      title: rawTitle,
      artist: owner,
      album: "YouTube",
      source_url: `https://www.youtube.com/watch?v=${id}`,
      artwork_url: String(thumbnails.at(-1)?.url || ""),
      playback_kind: "official_web", external_id: id,
      duration_ms: durationSeconds ? durationSeconds * 1000 : 0, provider: "youtube", ad_free: false,
    }});
  }
  const queue: any[] = [];
  const artistCounts = new Map<string, number>();
  const first = candidates.find(candidate => candidate.sameRequestedSong) || candidates[0];
  if (first) {
    Object.defineProperty(first.track, "__artist_key", { value: first.artistKey, enumerable: false });
    queue.push(first.track); artistCounts.set(first.artistKey, 1);
  }
  const remaining = candidates.filter(candidate => candidate !== first && !candidate.sameRequestedSong);
  while (queue.length < 12 && remaining.length) {
    const lastArtist = queue.length ? String((queue.at(-1) as any).__artist_key || "") : "";
    let index = remaining.findIndex(candidate => candidate.artistKey !== lastArtist && (artistCounts.get(candidate.artistKey) || 0) < 2);
    if (index < 0) index = remaining.findIndex(candidate => (artistCounts.get(candidate.artistKey) || 0) < 2);
    if (index < 0) break;
    const selected = remaining.splice(index, 1)[0];
    Object.defineProperty(selected.track, "__artist_key", { value: selected.artistKey, enumerable: false });
    queue.push(selected.track);
    artistCounts.set(selected.artistKey, (artistCounts.get(selected.artistKey) || 0) + 1);
  }
  return queue;
}

function compactText(value: string, limit = 12000): string {
  return value.replace(/\s+/g, " ").trim().slice(0, limit);
}

function extractiveSummary(value: string): string {
  const clean = compactText(value, 80000);
  const sentences = clean.split(/(?<=[.!?])\s+/u).filter(item => item.length > 24);
  if (!sentences.length) return clean.slice(0, 900);
  const words = clean.toLocaleLowerCase("es").match(/[\p{L}\p{N}]{4,}/gu) ?? [];
  const frequency = new Map<string, number>();
  for (const word of words) frequency.set(word, (frequency.get(word) ?? 0) + 1);
  return sentences.map((sentence, index) => ({ sentence, index, score: (sentence.toLocaleLowerCase("es").match(/[\p{L}\p{N}]{4,}/gu) ?? []).reduce((sum, word) => sum + (frequency.get(word) ?? 0), 0) / Math.max(6, sentence.length) }))
    .sort((a, b) => b.score - a.score).slice(0, 5).sort((a, b) => a.index - b.index).map(item => item.sentence).join(" ");
}

function arithmetic(text: string): number | null {
  const match = text.replaceAll(",", ".").match(/(?:cu[aá]nto es|calcula|resultado de)\s+([\d\s.+*/()-]{3,})/iu);
  if (!match) return null;
  const expression = match[1].trim();
  if (!/^[\d\s.+*/()-]+$/.test(expression)) return null;
  const tokens = expression.match(/\d+(?:\.\d+)?|[()+\-*/]/g) ?? [];
  const output: (number | string)[] = [], operators: string[] = [];
  const priority: Record<string, number> = { "+": 1, "-": 1, "*": 2, "/": 2 };
  for (const token of tokens) {
    if (/^\d/.test(token)) output.push(Number(token));
    else if (token === "(") operators.push(token);
    else if (token === ")") { while (operators.length && operators.at(-1) !== "(") output.push(operators.pop()!); if (operators.pop() !== "(") return null; }
    else { while (operators.length && operators.at(-1) !== "(" && priority[operators.at(-1)!] >= priority[token]) output.push(operators.pop()!); operators.push(token); }
  }
  while (operators.length) { const op = operators.pop()!; if (op === "(") return null; output.push(op); }
  const stack: number[] = [];
  for (const token of output) {
    if (typeof token === "number") stack.push(token);
    else { const b = stack.pop(), a = stack.pop(); if (a === undefined || b === undefined || (token === "/" && b === 0)) return null; stack.push(token === "+" ? a + b : token === "-" ? a - b : token === "*" ? a * b : a / b); }
  }
  return stack.length === 1 && Number.isFinite(stack[0]) ? stack[0] : null;
}

function researchSubject(text: string): string {
  const normalized = text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("es").trim().replace(/[.!?¡¿]+$/g, "");
  const explicit = normalized.match(/^(?:investiga|investigar|busca|buscar|explicame|hablame)\s+(?:informacion\s+)?(?:sobre|de)?\s*(.{3,240})$/u);
  if (explicit?.[1]) return explicit[1].trim();
  const factual = normalized.match(/^(?:sabes\s+)?(?:quien|quienes|que)\s+(?:es|son|fue|eran)\s+(.{3,240})$/u);
  return factual?.[1]?.trim() || "";
}

function isContextFollowup(text: string): boolean {
  const normalized = text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("es").trim();
  return /^(?:dame|dime|cuentame|explicame)(?:\s+un\s+poco)?\s+mas(?:\s+(?:contexto|detalles|informacion))?(?:\s+(?:sobre|acerca\s+de)\s+(?:el|ella|eso|esa\s+persona|ese\s+tema))?$/u.test(normalized)
    || /^(?:y\s+)?que\s+mas(?:\s+(?:sabes|puedes\s+decirme))?(?:\s+(?:de|sobre)\s+(?:el|ella|eso|esa\s+persona|ese\s+tema))?$/u.test(normalized)
    || /^(?:puedes\s+)?(?:decirme|contarme|explicarme)(?:\s+algo)?\s+mas(?:\s+(?:de|sobre|acerca\s+de)\s+(?:el|ella|eso|esto|esa\s+persona|este\s+tema|el\s+tema))?$/u.test(normalized)
    || /^(?:sabes\s+)?(?:algo\s+)?mas\s+(?:de|sobre|acerca\s+de)\s+.{2,160}?(?:\s+algun(?:os)?\s+datos?\s+curiosos?)?$/u.test(normalized)
    || /^(?:dime|cuentame)?\s*algun(?:os)?\s+datos?\s+curiosos?(?:\s+(?:de|sobre)\s+.{2,160})?$/u.test(normalized)
    || /^(?:continua|sigue)(?:\s+(?:con|sobre)\s+(?:eso|el\s+tema|la\s+persona))?$/u.test(normalized)
    || /^(?:mas|amplia|profundiza)(?:\s+(?:contexto|detalles|informacion))?$/u.test(normalized);
}

function lastResearchSubject(history: any[]): string {
  for (const item of [...history].reverse()) {
    if (item?.role !== "assistant") continue;
    const body = String(item.body ?? item.content ?? "").trim();
    if (!body.includes("Fuente consultada: [Wikipedia]")) continue;
    const title = compactText(body.split(/\r?\n/, 1)[0] || "", 160).replace(/^Más contexto sobre\s+/iu, "");
    if (title) return title;
  }
  for (const item of [...history].reverse()) {
    if (item?.role !== "user") continue;
    const subject = researchSubject(String(item.body ?? item.content ?? ""));
    if (subject) return subject;
  }
  return "";
}

function contextualResearchSubject(text: string, history: any[]): string {
  if (!isContextFollowup(text)) return "";
  const recentSubject = lastResearchSubject(history);
  const normalized = text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("es").trim();
  const explicit = normalized.match(/(?:de|sobre|acerca\s+de)\s+(.{2,160})$/u)?.[1]
    ?.replace(/\s+algun(?:os)?\s+datos?\s+curiosos?$/u, "")
    .replace(/^(?:el|ella|eso|esto|esa\s+persona|este\s+tema|el\s+tema)$/u, "").trim() || "";
  if (explicit) {
    const foldedSubject = recentSubject.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("es");
    if (recentSubject && (foldedSubject.includes(explicit) || explicit.includes(foldedSubject))) return recentSubject;
    return explicit;
  }
  if (recentSubject) return recentSubject;
  const previous = String(history.filter(item => item.role === "user" && !isContextFollowup(String(item.body || item.content || ""))).at(-1)?.body || "").trim();
  const statement = previous.match(/^(.{2,120}?)\s+(?:es|fue|era|son|fueron|eran|se\s+trata\s+de)\b/iu);
  return compactText(statement?.[1] || "", 160);
}

async function researchedAnswer(text: string, followup = false): Promise<string | null> {
  const subject = researchSubject(text);
  if (!subject) return null;
  try {
    const parameters = new URLSearchParams({
      action: "query", generator: "search", gsrsearch: subject, gsrlimit: "1",
      prop: "extracts|info", explaintext: "1", inprop: "url",
      redirects: "1", format: "json", formatversion: "2", origin: "*",
    });
    if (!followup) parameters.set("exintro", "1");
    const response = await fetch(`https://es.wikipedia.org/w/api.php?${parameters}`, {
      headers: { "User-Agent": "ARCHEON/1.0 (independent research assistant)" },
      signal: AbortSignal.timeout(7000),
    });
    if (!response.ok) return null;
    const value = await response.json();
    const page = value?.query?.pages?.[0];
    const fullExtract = compactText(String(page?.extract || "")
      .replace(/={2,}\s*([^=]+?)\s*={2,}/g, "$1.").replace(/\s+/g, " ").trim(), followup ? 9000 : 1600);
    let extract = fullExtract;
    if (followup && fullExtract.length > 2200) {
      const offset = Math.min(fullExtract.length - 1200, 1700);
      const boundary = fullExtract.indexOf(". ", offset);
      extract = compactText(fullExtract.slice(boundary >= 0 ? boundary + 2 : offset), 1800);
    }
    const title = compactText(String(page?.title || subject), 160);
    const url = String(page?.fullurl || "");
    if (!extract || !/^https:\/\//.test(url)) return null;
    return `${followup ? `Más contexto sobre ${title}` : title}\n\n${extract}\n\nFuente consultada: [Wikipedia](${url})`;
  } catch (_) {
    return null;
  }
}

function nativeArchi(text: string, attachmentParts: any[], history: any[]): string {
  const normalized = text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("es");
  const calculation = arithmetic(text);
  if (calculation !== null) return `El resultado es ${Number.isInteger(calculation) ? calculation : Number(calculation.toFixed(8))}.`;
  const attachmentText = attachmentParts.filter(part => part.type === "text").map(part => String(part.text || "")).join("\n");
  const hasImage = attachmentParts.some(part => part.type === "image_url");
  if (/\b(resume|resumen|resumir|sintetiza)\b/.test(normalized) && attachmentText) return `Resumen:\n\n${extractiveSummary(attachmentText)}`;
  if (hasImage) return "Recibí la imagen correctamente en el mismo chat. El analizador visual propio de ARCHI aún no está desplegado en el runtime móvil, así que no voy a fingir una interpretación.";
  if (attachmentText) return `Leí el contenido adjunto. Sus puntos principales son:\n\n${extractiveSummary(attachmentText)}`;
  if (/\b(hola|buenas|buenos dias|buenas tardes|buenas noches)\b/.test(normalized)) return "Hola, soy ARCHI. Estoy funcionando desde el servicio independiente de ARCHEON; no necesito que tu PC esté encendida.";
  if (/\b(que puedes hacer|ayuda|capacidades)\b/.test(normalized)) return "Puedo mantener tus chats, trabajar con texto y archivos, reproducir música con modo DJ, usar dictado y conversación por voz, y sincronizar Cloud y dispositivos. Las acciones siempre informan su resultado real.";
  const imageRequest = text.match(/^\s*(?:crea(?:me)?|genera(?:me)?|haz(?:me)?|dibuja(?:me)?)\s+(?:una?\s+)?(?:imagen|foto|ilustraci[oó]n)\s+(?:de|sobre|con)?\s*(.{3,1000})$/iu);
  if (imageRequest) return `Entendí que quieres crear una imagen de “${compactText(imageRequest[1], 500)}”. Es una solicitud nueva, no una continuación del tema anterior. La generación de imágenes aún no está desplegada en el servicio móvil independiente; no voy a fingir que la creé.`;
  if (/\b(plan|pasos|organiza|organizar|lista)\b/.test(normalized)) return `Plan propuesto para “${compactText(text, 180)}”:\n\n1. Define el resultado exacto y el límite de tiempo.\n2. Reúne los datos o archivos necesarios.\n3. Divide el trabajo en una primera versión verificable.\n4. Ejecuta y comprueba cada resultado antes de continuar.\n5. Cierra con una revisión y una lista de pendientes reales.`;
  return `Entendí tu solicitud: ${compactText(text, 600)}. Puedo ayudarte a estructurarla, revisarla, convertirla en pasos o trabajar con un archivo concreto.`;
}

async function command(req: Request, payload: any, token: string): Promise<Response> {
  const user = await userFor(token);
  if (!await validGuest(token) && !user) return reply(req, { ok: false, error: "session_required" }, 401);
  const text = String(payload.text ?? "").trim();
  if (!text || text.length > 16000) return reply(req, { ok: false, error: "invalid_text" }, 400);
  if (requestsFileTransferToPc(text)) {
    if (!user) return reply(req, { ok: false, error: "account_session_required" }, 401);
    const ids = Array.isArray(payload.attachments) ? payload.attachments.slice(0, 10) : [];
    if (!ids.length) return reply(req, { ok: false, error: "attachment_required", message: "Adjunta el archivo exacto que quieres enviar a la PC." }, 400);
    const source = await ensureMobileDevice(req, token, String(user.id));
    const files = (await Promise.all(ids.map((id: any) => persistAttachmentToCloud(String(id), token, String(user.id), source?.id || null)))).filter(Boolean);
    if (!files.length) return reply(req, { ok: false, error: "cloud_upload_failed" }, 400);
    return reply(req, { ok: true, message: `Envié ${files.length === 1 ? files[0].display_name : `${files.length} archivos`} a ARCHEON Cloud; ya ${files.length === 1 ? "está" : "están"} disponible${files.length === 1 ? "" : "s"} en tu PC.`, files, attachments_consumed: true });
  }
  const remoteFile = remoteFileIntent(text);
  if (remoteFile) {
    if (!user) return reply(req, { ok: false, error: "account_session_required" }, 401);
    const source = await ensureMobileDevice(req, token, String(user.id));
    if (!source) return reply(req, { ok: false, error: "current_device_not_registered" }, 400);
    const targets = await rest(token, "archeon_devices", "?select=id,display_name,platform,remote_control_enabled,file_access_enabled&platform=eq.windows&remote_control_enabled=eq.true&file_access_enabled=eq.true&order=last_seen_at.desc");
    const resolution = resolveNamedDevice(targets, remoteFile.targetLabel);
    if (resolution.ambiguous) return reply(req, { ok: false, error: "target_device_ambiguous", message: `Hay más de un dispositivo que coincide con ${remoteFile.targetLabel}. Usa un nombre más específico.` }, 400);
    const target = resolution.device;
    if (!target) return reply(req, { ok: false, error: "target_device_not_found", message: `No encontré una PC llamada ${remoteFile.targetLabel} con acceso a archivos habilitado.` }, 400);
    const query = remoteFile.query.replace(/^["“”']+|["“”']+$/g, "").trim().slice(0, 255);
    if (!query || /[\\/\0]/.test(query)) return reply(req, { ok: false, error: "remote_file_name_required", message: "Indica únicamente el nombre exacto del archivo, sin una ruta." }, 400);
    const id = crypto.randomUUID(), idempotency = crypto.randomUUID(), nonce = crypto.randomUUID().replaceAll("-", ""), expires = new Date(Date.now() + 120_000).toISOString();
    const argumentsValue = { operation: "file.send", query, conversation_id: String(payload.conversation_id || "") };
    const signature = await hmac(JSON.stringify({ id, user_id: user.id, source_device_id: source.id, target_device_id: target.id, action: "media.stop", operation: "file.send", query, conversation_id: argumentsValue.conversation_id, idempotency, nonce, expires }));
    await rest(token, "archeon_remote_commands", "?select=id,state", { method: "POST", headers: { Prefer: "return=representation" }, body: JSON.stringify({ id, user_id: user.id, source_device_id: source.id, target_device_id: target.id, action: "media.stop", arguments: argumentsValue, risk: "standard", state: "queued", idempotency_key: idempotency, nonce, signature, expires_at: expires }) });
    const completed = await waitForRemoteResult(token, id);
    if (completed?.state === "succeeded" && completed.result?.file) {
      const file = completed.result.file;
      return reply(req, { ok: true, message: `${target.display_name} encontró y envió ${file.display_name} a tu ARCHEON Cloud.`, file, remote_command: { id, action: "file.send", state: "succeeded" }, attachments_consumed: true });
    }
    if (completed && completed.state !== "succeeded") {
      const messages: Record<string, string> = {
        remote_file_not_found: `${target.display_name} no encontró un archivo llamado ${query} en Escritorio, Documentos, Descargas u OneDrive.`,
        remote_file_ambiguous: `${target.display_name} encontró más de un archivo llamado ${query}; especifica un nombre único.`,
        remote_file_search_limit: `${target.display_name} tiene demasiados archivos para completar una búsqueda segura.`,
        remote_file_upload_failed: `${target.display_name} encontró el archivo, pero no pudo subirlo de forma verificada.`,
      };
      const error = String(completed.error_code || "remote_file_failed");
      return reply(req, { ok: false, error, message: messages[error] || `${target.display_name} no pudo enviar ${query}.`, remote_command: { id, action: "file.send", state: completed.state } }, 400);
    }
    return reply(req, { ok: true, message: `${target.display_name} sigue buscando ${query}. Te aparecerá en Cloud cuando termine.`, remote_command: { id, action: "file.send", state: "queued" }, attachments_consumed: true });
  }
  const remote = desktopRemoteIntent(text);
  if (remote) {
    if (!user) return reply(req, { ok: false, error: "account_session_required" }, 401);
    const source = await ensureMobileDevice(req, token, String(user.id));
    if (!source) return reply(req, { ok: false, error: "current_device_not_registered" }, 400);
    const targets = await rest(token, "archeon_devices", "?select=id,display_name,platform,remote_control_enabled&platform=eq.windows&remote_control_enabled=eq.true&order=last_seen_at.desc");
    const resolution = remote.targetLabel ? resolveNamedDevice(targets, remote.targetLabel) : { device: targets[0] || null, ambiguous: false };
    const target = resolution.device;
    if (resolution.ambiguous) return reply(req, { ok: false, error: "target_device_ambiguous", message: `Hay más de un dispositivo que coincide con ${remote.targetLabel}. Usa un nombre más específico.` }, 400);
    if (!target) return reply(req, { ok: false, error: "target_device_not_found", message: remote.targetLabel ? `No encontré un dispositivo llamado ${remote.targetLabel}.` : "No encontré una PC ARCHEON activa en esta cuenta." }, 400);
    const id = crypto.randomUUID(), idempotency = crypto.randomUUID(), nonce = crypto.randomUUID().replaceAll("-", ""), expires = new Date(Date.now() + 120_000).toISOString();
    const signature = await hmac(JSON.stringify({ id, user_id: user.id, source_device_id: source.id, target_device_id: target.id, action: remote.action, query: remote.query, idempotency, nonce, expires }));
    const rows = await rest(token, "archeon_remote_commands", "?select=id,state", { method: "POST", headers: { Prefer: "return=representation" }, body: JSON.stringify({ id, user_id: user.id, source_device_id: source.id, target_device_id: target.id, action: remote.action, arguments: { query: remote.query }, risk: "standard", state: "queued", idempotency_key: idempotency, nonce, signature, expires_at: expires }) });
    return reply(req, { ok: true, message: `Envié la orden a ${target.display_name}.`, remote_command: rows[0], attachments_consumed: true });
  }
  const music = mediaQuery(text);
  if (music) {
    const owned = await findOwnedMusic(token, music);
    const queue = owned.length ? owned : await findMusic(music);
    if (queue.length) {
      return reply(req, { ok: true, message: `Reproduciendo ${queue[0].title} de ${queue[0].artist}.`, media: { track: queue[0], queue }, attachments_consumed: true });
    }
  }
  const parts: any[] = [{ type: "text", text }];
  const cleanup: string[] = [];
  for (const id of Array.isArray(payload.attachments) ? payload.attachments.slice(0, 10) : []) {
    const attachment = await readAttachment(String(id));
    if (attachment) { parts.push(attachment.content); cleanup.push(attachment.path); }
  }
  let history = Array.isArray(payload.history) ? payload.history.slice(-12).filter((item: any) => ["user", "assistant"].includes(item?.role) && typeof item?.body === "string").map((item: any) => ({ role: item.role, body: item.body.slice(0, 16000) })) : [];
  if (user && payload.conversation_id) {
    const stored = await rest(token, "archeon_messages", `?conversation_id=eq.${encodeURIComponent(String(payload.conversation_id))}&select=role,body,created_at&order=created_at.desc&limit=25`);
    history = stored.reverse().filter((item: any) => ["user", "assistant"].includes(item?.role) && typeof item?.body === "string");
    const current = history.at(-1);
    if (current?.role === "user" && current.body.trim() === text) history.pop();
    history = history.slice(-24);
  }
  const followupSubject = contextualResearchSubject(text, history);
  const researched = await researchedAnswer(followupSubject ? `investiga ${followupSubject}` : text, Boolean(followupSubject));
  const answer = researched || nativeArchi(text, parts.slice(1), history);
  await Promise.allSettled(cleanup.map(path => supabase(`/storage/v1/object/archeon-cloud/${path}`, { method: "DELETE" }, "", true)));
  return reply(req, { ok: true, message: answer, engine: researched ? "archeon-native-research" : "archeon-native", intelligence: payload.intelligence || "medium", attachments_consumed: true });
}

async function cloudUpload(req: Request, token: string): Promise<Response> {
  const user = await userFor(token);
  if (!user) return reply(req, { ok: false, error: "account_session_required" }, 401);
  const bytes = new Uint8Array(await req.arrayBuffer());
  if (!bytes.length || bytes.length > 100 * 1024 * 1024) return reply(req, { ok: false, error: "cloud_file_size_out_of_range" }, 400);
  const name = decodeURIComponent(req.headers.get("x-file-name") || "archivo").replace(/[\\/\0]/g, "_").slice(0, 255);
  const mime = (req.headers.get("content-type") || "application/octet-stream").split(";")[0];
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))).map(v => v.toString(16).padStart(2, "0")).join("");
  const path = `${user.id}/${crypto.randomUUID()}/${encodeURIComponent(name)}`;
  const stored = await supabase(`/storage/v1/object/archeon-cloud/${path}`, { method: "POST", headers: { "Content-Type": mime, "x-upsert": "false" }, body: bytes }, token);
  if (!stored.ok) return reply(req, { ok: false, error: "cloud_upload_failed" }, 400);
  const rows = await rest(token, "archeon_cloud_files", "?select=id,display_name,mime_type,byte_size,sha256,state,created_at", { method: "POST", headers: { Prefer: "return=representation" }, body: JSON.stringify({ user_id: user.id, conversation_id: req.headers.get("x-conversation-id") || null, storage_path: path, display_name: name, mime_type: mime, byte_size: bytes.length, sha256: digest, state: "available" }) });
  return reply(req, { ok: true, file: rows[0] });
}

Deno.serve(async (req: Request) => {
  try {
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(req) });
    if (["GET", "HEAD"].includes(req.method) && new URL(req.url).pathname.endsWith("/health")) {
      const database = await supabase("/rest/v1/archeon_devices?select=id&limit=1", { method: "GET" }, "", true);
      if (req.method === "HEAD") return new Response(null, { status: database.ok ? 200 : 503, headers: { ...cors(req), "Cache-Control": "no-store" } });
      return reply(req, {
        ok: database.ok,
        service: "archeon-mobile-api",
        database: database.ok ? "reachable" : "unavailable",
        checked_at: new Date().toISOString(),
      }, database.ok ? 200 : 503);
    }
    if (req.method !== "POST") return reply(req, { ok: false, error: "method_not_allowed" }, 405);
    if (!PUBLISHABLE_KEY || !SECRET_KEY || !GUEST_SECRET || req.headers.get("apikey") !== PUBLISHABLE_KEY) return reply(req, { ok: false, error: "unauthorized" }, 401);
    const route = req.headers.get("x-archeon-route") || "";
    const token = req.headers.get("x-archeon-session") || "";
    if (route === "/api/session") {
      if (await validGuest(token)) return reply(req, { ok: true, session: { mode: "guest", provider: "local", identity: null, email_verified: false, mfa_required: false } });
      const user = await userFor(token);
      return user ? reply(req, { ok: true, session: publicSession(user) }) : reply(req, { ok: false, error: "session_required" }, 401);
    }
    if (route.startsWith("/api/auth/")) return auth(req, route.slice(10), await req.json().catch(() => ({})), token);
    if (route === "/api/action") return action(req, await req.json().catch(() => ({})), token);
    if (route === "/api/command") return command(req, await req.json().catch(() => ({})), token);
    if (route === "/api/attachment") return uploadAttachment(req, token);
    if (route === "/api/cloud-file") return cloudUpload(req, token);
    return reply(req, { ok: false, error: "route_not_found" }, 404);
  } catch (error) {
    console.error("archeon-mobile-api", error);
    return reply(req, { ok: false, error: error instanceof Error ? error.message : "internal_error" }, 500);
  }
});
