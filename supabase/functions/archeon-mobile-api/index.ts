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
      if (token && !await validGuest(token)) {
        const user = await userFor(token), sessionId = jwtSessionId(token);
        if (user && sessionId) await adminRest("archeon_devices", `?user_id=eq.${encodeURIComponent(user.id)}&auth_session_id=eq.${encodeURIComponent(sessionId)}`, {
          method: "PATCH", body: JSON.stringify({ session_revoked_at: new Date().toISOString(), remote_control_enabled: false, updated_at: new Date().toISOString() }),
        });
        await supabase("/auth/v1/logout?scope=local", { method: "POST", body: "{}" }, token);
      }
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

async function adminRest(table: string, query: string, init: RequestInit = {}): Promise<any> {
  const response = await supabase(`/rest/v1/${table}${query}`, init, "", true);
  return jsonOrError(response);
}

function previewAllowed(mime: string): boolean {
  return mime.startsWith("image/") || mime.startsWith("text/") || mime === "application/pdf" || mime === "application/json";
}

function cleanTransportText(body: string): string {
  return String(body || "")
    .replace(/%20/giu, " ")
    .replace(/(?<=\p{L})%(?=\p{L})/gu, " ")
    .replace(/%[0-9a-f]{2}/giu, " ")
    .replace(/\s+/g, " ").trim();
}

function informationSubject(value: string): string {
  const clean = cleanTransportText(value).replace(/[.!?¡¿]+$/g, "").trim();
  const words = clean.split(/\s+/u), folded = words.map(contextFold);
  if (["sabes", "conoces"].includes(folded[0])) {
    let start = 1;
    if (folded[start] === "de" || editDistance(folded[start] || "", "sobre") <= 1) start++;
    return words.slice(start).join(" ").trim();
  }
  const direct = clean.match(/^(?:qui[eé]n\s+es|qu[eé]\s+es|h[aá]blame\s+de|expl[ií]came(?:\s+sobre)?)\s+(.+)$/iu);
  return direct?.[1]?.trim() || "";
}

const TITLE_PREFIX_BY_INTENT: Record<string, string> = {
  diagnose: "Problema con", play_media: "Música ·", find: "Búsqueda ·",
  create: "Creación ·", ask_information: "Sobre",
};

function conversationTitle(body: string, context: any = null): string {
  const interpreted = cleanTransportText(context?.interpreted_request || context?.normalized_input || body);
  const topicId = String(context?.topic?.id || ""), intent = String(context?.intent?.name || "");
  const topicName = CONTEXT_TOPICS.find(topic => topic.topic_id === topicId)?.name || "";
  const prefix = TITLE_PREFIX_BY_INTENT[intent] || "";
  const information = informationSubject(interpreted);
  if (information) return `Sobre ${information}`.slice(0, 64);
  if (topicName && prefix) return `${prefix} ${topicName}`.replace(/\s+·\s+/g, " · ").slice(0, 64);
  if (topicName && topicId !== "general") return topicName.slice(0, 64);
  let value = interpreted.replace(/^(?:archi|archeon)[,:\s-]+/iu, "").replace(/^(?:por favor|oye|hola)[,:\s-]+/iu, "");
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

function unsafeConversationTitle(value: unknown): boolean {
  const title = String(value || "");
  return ["Nuevo chat", "Información"].includes(title) || /%(?:[0-9a-f]{2}|(?=\p{L}))/iu.test(title) || /[\\]{1,2}(?:n|r|t|u[0-9a-f]{4})/iu.test(title);
}

async function ensureMobileDevice(req: Request, token: string, userId: string): Promise<any | null> {
  const installation = String(req.headers.get("x-archeon-installation") || "").slice(0, 128);
  if (installation.length < 16) return null;
  const requestedName = String(req.headers.get("x-archeon-device-name") || "Este teléfono").trim().slice(0, 120) || "Este teléfono";
  const sessionId = jwtSessionId(token);
  if (!sessionId) throw new Error("session_id_required");
  const existing = await adminRest("archeon_devices", `?select=id,display_name,auth_session_id,session_revoked_at&user_id=eq.${encodeURIComponent(userId)}&installation_id=eq.${encodeURIComponent(installation)}&limit=1`, { method: "GET" });
  // The cloud name is authoritative after first registration. This lets any
  // device in the same account rename another one without the target's next
  // heartbeat immediately overwriting that choice with a stale local value.
  const displayName = String(existing?.[0]?.display_name || requestedName).slice(0, 120);
  if (existing?.[0]?.session_revoked_at && String(existing[0].auth_session_id || "") === sessionId) throw new Error("device_session_revoked");
  const rows = await rest(token, "archeon_devices", "?on_conflict=user_id,installation_id&select=id,installation_id,display_name,platform,capabilities,remote_control_enabled,power_commands_enabled,file_access_enabled,last_seen_at,auth_session_id,session_revoked_at", {
    method: "POST", headers: { Prefer: "resolution=merge-duplicates,return=representation" },
    body: JSON.stringify({ user_id: userId, installation_id: installation, display_name: displayName, platform: "android", public_key: await hmac(`device:${userId}:${installation}`), capabilities: ["media.play", "launcher.open", "cloud.files"], remote_control_enabled: true, file_access_enabled: true, auth_session_id: sessionId, session_revoked_at: null, last_seen_at: new Date().toISOString(), updated_at: new Date().toISOString() }),
  });
  return rows[0] || null;
}

function jwtSessionId(token: string): string {
  try {
    const claims = JSON.parse(decoder.decode(fromBase64Url(token.split(".")[1] || "")));
    const value = String(claims?.session_id || "");
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(value) ? value : "";
  } catch (_) { return ""; }
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

function mergeSettings(base: any, changes: any): Record<string, any> {
  const result = base && typeof base === "object" && !Array.isArray(base) ? { ...base } : {};
  if (!changes || typeof changes !== "object" || Array.isArray(changes)) return result;
  for (const [key, value] of Object.entries(changes)) {
    result[key] = value && typeof value === "object" && !Array.isArray(value)
      ? mergeSettings(result[key], value) : value;
  }
  return result;
}

function publicMobileSettings(account: any = {}, device: any = {}): Record<string, any> {
  const assistant = account.assistant && typeof account.assistant === "object" ? account.assistant : {};
  const intelligence = account.intelligence && typeof account.intelligence === "object" ? account.intelligence : {};
  const activation = device.activation && typeof device.activation === "object" ? device.activation : {};
  return {
    assistant: {
      wake_name: String(assistant.wake_name || "ARCHI").slice(0, 24),
      context_language_enabled: assistant.context_language_enabled !== false,
      preferred_location: String(assistant.preferred_location || "").trim().slice(0, 80),
      configured: Object.prototype.hasOwnProperty.call(assistant, "wake_name"),
    },
    intelligence: {
      profile: String(intelligence.profile || "balanced"),
      context_size: Math.max(2048, Math.min(8192, Number(intelligence.context_size) || 4096)),
      max_tokens: Math.max(512, Math.min(2048, Number(intelligence.max_tokens) || 1024)),
      conversation_turns: Math.max(2, Math.min(8, Number(intelligence.conversation_turns) || 4)),
    },
    activation: {
      wake_word_enabled: Boolean(activation.wake_word_enabled),
      background_enabled: Boolean(activation.background_enabled),
      configured: Object.prototype.hasOwnProperty.call(activation, "wake_word_enabled") || Object.prototype.hasOwnProperty.call(activation, "background_enabled"),
    },
  };
}

async function mobileSettings(req: Request, token: string, user: any, changes: any = null): Promise<Record<string, any>> {
  if (!user) return publicMobileSettings(changes || {}, changes || {});
  const userId = String(user.id), current = await ensureMobileDevice(req, token, userId);
  if (!current) throw new Error("current_device_not_registered");
  const installation = String(req.headers.get("x-archeon-installation") || "").slice(0, 128);
  const accountRows = await rest(token, "account_settings", `?user_id=eq.${encodeURIComponent(userId)}&select=settings,version&limit=1`);
  const deviceRows = await rest(token, "device_settings", `?user_id=eq.${encodeURIComponent(userId)}&device_id=eq.${encodeURIComponent(installation)}&select=settings,version&limit=1`);
  let account = accountRows?.[0]?.settings || {}, device = deviceRows?.[0]?.settings || {};
  if (changes && typeof changes === "object" && !Array.isArray(changes)) {
    const assistantChanges = changes.assistant && typeof changes.assistant === "object" ? {
      ...(typeof changes.assistant.wake_name === "string" ? { wake_name: changes.assistant.wake_name.trim().slice(0, 24) || "ARCHI" } : {}),
      ...(typeof changes.assistant.context_language_enabled === "boolean" ? { context_language_enabled: changes.assistant.context_language_enabled } : {}),
      ...(typeof changes.assistant.preferred_location === "string" ? { preferred_location: changes.assistant.preferred_location.trim().slice(0, 80) } : {}),
    } : {};
    const intelligenceChanges = changes.intelligence && typeof changes.intelligence === "object" ? changes.intelligence : {};
    const activationChanges = changes.activation && typeof changes.activation === "object" ? {
      ...(typeof changes.activation.wake_word_enabled === "boolean" ? { wake_word_enabled: changes.activation.wake_word_enabled } : {}),
      ...(typeof changes.activation.background_enabled === "boolean" ? { background_enabled: changes.activation.background_enabled } : {}),
    } : {};
    account = mergeSettings(account, { assistant: assistantChanges, intelligence: intelligenceChanges });
    device = mergeSettings(device, { activation: activationChanges });
    const updatedAt = new Date().toISOString();
    await rest(token, "account_settings", "?on_conflict=user_id", { method: "POST", headers: { Prefer: "resolution=merge-duplicates,return=minimal" }, body: JSON.stringify({ user_id: userId, settings: account, version: Math.max(0, Number(accountRows?.[0]?.version) || 0) + 1, updated_at: updatedAt }) });
    await rest(token, "device_settings", "?on_conflict=user_id,device_id", { method: "POST", headers: { Prefer: "resolution=merge-duplicates,return=minimal" }, body: JSON.stringify({ user_id: userId, device_id: installation, device_name: String(current.display_name || "Android device").slice(0, 120), settings: device, version: Math.max(0, Number(deviceRows?.[0]?.version) || 0) + 1, updated_at: updatedAt }) });
  }
  return publicMobileSettings(account, device);
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
    if (name === "settings.get") return reply(req, { ok: true, settings: await mobileSettings(req, token, user) });
    if (name === "settings.update") return reply(req, { ok: true, settings: await mobileSettings(req, token, user, payload.changes ?? {}) });
    if (name === "permissions.list") return reply(req, { ok: true, permissions: [] });
    if (name === "permissions.update") return reply(req, { ok: true, permissions: [] });
    if (name.startsWith("media.") || name === "attachment.remove") return reply(req, { ok: true, media: { state: "stopped" } });
    if (!user) return reply(req, { ok: false, error: "account_session_required" }, 401);
    const userId = String(user.id);
    const currentDevice = await ensureMobileDevice(req, token, userId);
    if (name === "cloud.conversations.list") {
      let rows = await rest(token, "archeon_conversations", "?select=id,title,created_at,updated_at&archived_at=is.null&order=updated_at.desc");
      const repairable = rows.filter((item: any) => unsafeConversationTitle(item.title)).slice(0, 30);
      await Promise.all(repairable.map(async (item: any) => {
        const history = await rest(token, "archeon_messages", `?conversation_id=eq.${encodeURIComponent(item.id)}&select=role,body,context_data&order=created_at.asc&limit=12`);
        if (!history.length) {
          await rest(token, "archeon_conversations", `?id=eq.${encodeURIComponent(item.id)}`, { method: "PATCH", body: JSON.stringify({ archived_at: new Date().toISOString(), updated_at: new Date().toISOString() }) });
          return;
        }
        const context = history.find((message: any) => message.role === "assistant" && message.context_data?.interpreted_request)?.context_data;
        const firstUser = history.find((message: any) => message.role === "user");
        if (context || firstUser?.body) await rest(token, "archeon_conversations", `?id=eq.${encodeURIComponent(item.id)}`, { method: "PATCH", body: JSON.stringify({ title: conversationTitle(firstUser?.body || "", context), updated_at: new Date().toISOString() }) });
      }));
      if (repairable.length) rows = await rest(token, "archeon_conversations", "?select=id,title,created_at,updated_at&archived_at=is.null&order=updated_at.desc");
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
      const rows = await rest(token, "archeon_messages", `?select=id,role,body,context_data,created_at&conversation_id=eq.${encodeURIComponent(payload.conversation_id)}&order=created_at.asc`);
      const files = await rest(token, "archeon_cloud_files", `?select=id,message_id,storage_path,display_name,mime_type&conversation_id=eq.${encodeURIComponent(payload.conversation_id)}&message_id=not.is.null&state=eq.available&order=created_at.asc`);
      const attachments = new Map<string, any[]>();
      const visibleFiles = await Promise.all(files.map(async (file: any) => {
        let previewUrl = "";
        if (String(file.mime_type || "").startsWith("image/")) {
          const signed = await supabase(`/storage/v1/object/sign/archeon-cloud/${file.storage_path}`, { method: "POST", body: JSON.stringify({ expiresIn: 600 }) }, "", true);
          if (signed.ok) {
            const value = await signed.json();
            const relative = String(value.signedURL || value.signedUrl || "");
            previewUrl = relative.startsWith("http") ? relative : relative ? `${SUPABASE_URL}/storage/v1${relative}` : "";
          }
        }
        return { ...file, previewUrl };
      }));
      for (const file of visibleFiles) {
        const messageId = String(file.message_id || "");
        if (!messageId) continue;
        const values = attachments.get(messageId) || [];
        values.push({ id: file.id, fileId: file.id, name: file.display_name, kind: String(file.mime_type || "").startsWith("image/") ? "image" : "file", previewUrl: file.previewUrl });
        attachments.set(messageId, values);
      }
      return reply(req, { ok: true, messages: rows.map((message: any) => ({ ...message, attachments: attachments.get(String(message.id)) || [] })) });
    }
    if (name === "cloud.messages.add") {
      const suppliedContext = payload.context_data && typeof payload.context_data === "object" && !Array.isArray(payload.context_data) ? payload.context_data : {};
      const contextData = JSON.stringify(suppliedContext).length <= 32000 ? suppliedContext : {};
      const rows = await rest(token, "archeon_messages", "?select=id,role,body,context_data,created_at", { method: "POST", headers: { Prefer: "return=representation" }, body: JSON.stringify({ user_id: userId, conversation_id: payload.conversation_id, role: payload.role, body: String(payload.body || "").slice(0, 100000), context_data: contextData, client_message_id: crypto.randomUUID() }) });
      const conversations = await rest(token, "archeon_conversations", `?id=eq.${encodeURIComponent(payload.conversation_id)}&select=id,title&limit=1`);
      const currentTitle = String(conversations?.[0]?.title || "");
      const nextTitle = payload.role === "assistant" && unsafeConversationTitle(currentTitle) && Object.keys(contextData).length
        ? conversationTitle(String(payload.body || ""), contextData) : currentTitle;
      await rest(token, "archeon_conversations", `?id=eq.${encodeURIComponent(payload.conversation_id)}`, { method: "PATCH", body: JSON.stringify({ title: nextTitle || "Nuevo chat", updated_at: new Date().toISOString() }) });
      return reply(req, { ok: true, message: rows[0], conversation_title: nextTitle || "Nuevo chat" });
    }
    if (name === "cloud.files.attach_message") {
      const messageRows = await rest(token, "archeon_messages", `?id=eq.${encodeURIComponent(payload.message_id)}&select=id,conversation_id&limit=1`);
      const fileRows = await rest(token, "archeon_cloud_files", `?id=eq.${encodeURIComponent(payload.file_id)}&state=eq.available&select=id,conversation_id&limit=1`);
      if (!messageRows[0] || !fileRows[0] || messageRows[0].conversation_id !== fileRows[0].conversation_id) throw new Error("cloud_attachment_context_mismatch");
      await rest(token, "archeon_cloud_files", `?id=eq.${encodeURIComponent(payload.file_id)}`, { method: "PATCH", body: JSON.stringify({ message_id: payload.message_id }) });
      return reply(req, { ok: true });
    }
    if (name === "cloud.devices.list") {
      const installation = String(req.headers.get("x-archeon-installation") || "").slice(0, 128);
      const rows = await rest(token, "archeon_devices", "?select=id,installation_id,display_name,platform,capabilities,remote_control_enabled,power_commands_enabled,file_access_enabled,last_seen_at,session_revoked_at&order=last_seen_at.desc");
      return reply(req, { ok: true, devices: rows.map((device: any) => ({ ...device, current: device.installation_id === installation })) });
    }
    if (name === "cloud.devices.rename") {
      const deviceId = String(payload.device_id || "");
      const displayName = String(payload.display_name || "").trim().replace(/[\r\n\t]+/g, " ").slice(0, 60);
      if (!displayName) throw new Error("device_name_required");
      const rows = await rest(token, "archeon_devices", `?id=eq.${encodeURIComponent(deviceId)}&select=id,display_name`, { method: "PATCH", headers: { Prefer: "return=representation" }, body: JSON.stringify({ display_name: displayName, updated_at: new Date().toISOString() }) });
      if (!rows.length) throw new Error("device_not_found");
      return reply(req, { ok: true, device: rows[0] });
    }
    if (name === "cloud.devices.revoke") {
      const deviceId = String(payload.device_id || "");
      if (!deviceId || deviceId === String(currentDevice?.id || "")) throw new Error("use_local_logout_for_current_device");
      const rows = await rest(token, "archeon_devices", `?id=eq.${encodeURIComponent(deviceId)}&select=id,display_name,session_revoked_at`, {
        method: "PATCH", headers: { Prefer: "return=representation" },
        body: JSON.stringify({ session_revoked_at: new Date().toISOString(), remote_control_enabled: false, updated_at: new Date().toISOString() }),
      });
      if (!rows.length) throw new Error("device_not_found");
      return reply(req, { ok: true, device: rows[0] });
    }
    if (name === "remote.commands.pending") {
      if (!currentDevice) throw new Error("current_device_not_registered");
      const rows = await rest(token, "archeon_remote_commands", `?select=id,action,arguments,state,expires_at&target_device_id=eq.${encodeURIComponent(currentDevice.id)}&state=eq.queued&expires_at=gt.${encodeURIComponent(new Date().toISOString())}&order=created_at.asc&limit=10`);
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
    const code = error instanceof Error ? error.message : "cloud_unavailable";
    return reply(req, { ok: false, error: code }, code === "device_session_revoked" ? 401 : 400);
  }
}

async function uploadAttachment(req: Request, token: string): Promise<Response> {
  const guest = await validGuest(token), user = guest ? null : await userFor(token);
  if (!guest && !user) return reply(req, { ok: false, error: "session_required" }, 401);
  if (user) await ensureMobileDevice(req, token, String(user.id));
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

function imageCreationPrompt(text: string): string {
  const match = text.match(/^\s*(?:crea(?:me)?|genera(?:me)?|haz(?:me)?|dibuja(?:me)?)\s+(?:una?\s+)?(?:imagen|foto|ilustraci[oó]n)\s+(?:de|sobre|con)?\s*(.{3,1000})$/iu);
  if (!match) return "";
  return compactText(match[1]
    .replace(/\bvotando\s+fuego\b/giu, "escupiendo fuego")
    .replace(/\bcsbezas\b/giu, "cabezas"), 1000);
}

function standardBase64(bytes: Uint8Array): string {
  const encoded = base64Url(bytes);
  return encoded.replaceAll("-", "+").replaceAll("_", "/") + "=".repeat((4 - encoded.length % 4) % 4);
}

async function generateEphemeralImage(req: Request, prompt: string, context_interpretation?: unknown): Promise<Response> {
  const seed = crypto.getRandomValues(new Uint32Array(1))[0] % 2147483647;
  const enhancedPrompt = `${prompt}. composición cinematográfica coherente, alta calidad visual, sin texto, sin marcas de agua`;
  let generated: Response;
  try {
    const space = "https://black-forest-labs-flux-1-schnell.hf.space";
    const queued = await fetch(`${space}/gradio_api/call/infer`, {
      method: "POST", headers: { "Content-Type": "application/json", "User-Agent": "ARCHEON/1.0 image service" },
      body: JSON.stringify({ data: [enhancedPrompt, seed, false, 1024, 1024, 4] }), signal: AbortSignal.timeout(20_000),
    });
    if (!queued.ok) throw new Error("image_queue_failed");
    const eventId = String((await queued.json())?.event_id || "");
    if (!/^[a-f0-9-]{16,80}$/i.test(eventId)) throw new Error("image_event_invalid");
    const eventResponse = await fetch(`${space}/gradio_api/call/infer/${eventId}`, { headers: { "Accept": "text/event-stream" }, signal: AbortSignal.timeout(100_000) });
    if (!eventResponse.ok) throw new Error("image_event_failed");
    const eventText = await eventResponse.text();
    const completed = eventText.match(/event:\s*complete\s*\r?\ndata:\s*([^\r\n]+)/i)?.[1];
    const output = completed ? JSON.parse(completed) : [];
    const imageUrl = String(output?.[0]?.url || "");
    if (!imageUrl.startsWith(`${space}/gradio_api/file=`)) throw new Error("image_result_url_invalid");
    generated = await fetch(imageUrl, { headers: { "Accept": "image/webp,image/png,image/jpeg" }, signal: AbortSignal.timeout(30_000) });
  } catch (_) {
    return reply(req, { ok: false, error: "image_generation_unavailable", message: "El generador de imágenes no respondió a tiempo. Inténtalo nuevamente." }, 503);
  }
  if (!generated.ok) return reply(req, { ok: false, error: "image_generation_failed", message: "El generador no pudo completar esta imagen." }, 502);
  const bytes = new Uint8Array(await generated.arrayBuffer());
  const contentType = String(generated.headers.get("content-type") || "").split(";")[0].toLowerCase();
  const jpeg = bytes.length >= 4 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes.at(-2) === 0xff && bytes.at(-1) === 0xd9;
  const png = bytes.length >= 8 && bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47;
  const webp = bytes.length >= 12 && decoder.decode(bytes.slice(0, 4)) === "RIFF" && decoder.decode(bytes.slice(8, 12)) === "WEBP";
  if (bytes.length < 4096 || bytes.length > 12 * 1024 * 1024 || !(jpeg || png || webp)) {
    return reply(req, { ok: false, error: "image_output_invalid", message: "El resultado no fue una imagen válida y no se guardó." }, 502);
  }
  const mime = png ? "image/png" : webp ? "image/webp" : "image/jpeg";
  if (contentType && !contentType.startsWith("image/")) return reply(req, { ok: false, error: "image_output_invalid" }, 502);
  const extension = png ? "png" : webp ? "webp" : "jpg";
  const timestamp = new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 14);
  const name = `ARCHI_Image_${timestamp}.${extension}`;
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))).map(value => value.toString(16).padStart(2, "0")).join("");
  return reply(req, {
    ok: true,
    message: "",
    generated_image: { id: `ephemeral-${crypto.randomUUID()}`, name, mime_type: mime, content_base64: standardBase64(bytes), width: 1024, height: 1024, sha256: digest, ephemeral: true },
    context_interpretation,
    engine: "archeon-image",
    attachments_consumed: true,
  });
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
  const information = informationSubject(text);
  if (information) return information;
  const explicit = normalized.match(/^(?:investiga|investigar|busca|buscar|explicame|hablame|sabes)\s+(?:informacion\s+)?(?:sobre|de)?\s*(.{3,240})$/u);
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

type Evidence = "KNOWN" | "INFERRED" | "UNKNOWN";
type ContextEntity = { entity_id: string; entity_type: string; name: string; aliases: string[]; attributes: Record<string, unknown>; status: Evidence; confidence: number; source: string; position: number };
type EntityDefinition = { entity_id: string; entity_type: string; name: string; aliases: string[]; topic_hints: string[]; compatible_intents: string[]; attributes?: Record<string, unknown> };
type IntentDefinition = { name: string; patterns: RegExp[]; compatible_types: string[]; sensitive?: boolean; implicit_active_target?: boolean; governing?: boolean };
type TopicDefinition = { topic_id: string; name: string; concepts: string[]; compatible_intents: string[] };
type ContextThread = { topic_id: string; messages: string[]; entities: ContextEntity[]; intents: string[]; last_turn: number };
type ContextResult = {
  raw_input: string; normalized_input: string; interpreted_request: string;
  intent: { name: string; confidence: number }; topic: { id: string; confidence: number; scores: Record<string, number> };
  entities: ContextEntity[]; references: Record<string, unknown>[]; related_topics: string[]; context_sources: string[];
  confidence: number; requires_confirmation: boolean; requires_clarification: boolean; clarification_required: boolean;
  resolution: "CONTINUE_ACTIVE_THREAD" | "SWITCH_TO_RECENT_THREAD" | "CREATE_NEW_THREAD" | "RELATE_MULTIPLE_THREADS";
  facts: Array<{ key: string; value: unknown; status: Evidence; confidence: number; source: string }>;
};

const CONTEXT_TOPICS: TopicDefinition[] = [
  { topic_id: "minecraft_server", name: "Servidor Minecraft", concepts: ["minecraft", "server", "servidor", "java", "puerto", "25565"], compatible_intents: ["diagnose", "inspect_version", "check_network_port", "restart"] },
  { topic_id: "media_playback", name: "Música y reproducción", concepts: ["musica", "cancion", "artista", "reproduccion", "volumen"], compatible_intents: ["open", "close", "play_media", "pause_media", "adjust_volume"] },
  { topic_id: "system_hardware", name: "Sistema y hardware", concepts: ["ram", "cpu", "gpu", "disco", "espacio", "temperatura", "memoria"], compatible_intents: ["inspect_system", "close"] },
  { topic_id: "web_browsing", name: "Navegación web", concepts: ["navegador", "web", "pagina", "youtube"], compatible_intents: ["open", "close", "navigate"] },
  { topic_id: "applications", name: "Aplicaciones", concepts: ["aplicacion", "programa", "proceso"], compatible_intents: ["open", "close", "restart"] },
  { topic_id: "network_security", name: "Red y seguridad", concepts: ["red", "ip", "puerto", "router", "firewall", "cortafuegos"], compatible_intents: ["check_network_port", "diagnose"] },
  { topic_id: "documents", name: "Archivos y documentos", concepts: ["archivo", "documento", "pdf", "word", "docx", "carpeta", "proyecto"], compatible_intents: ["open", "close", "find", "delete", "create_artifact"] },
  { topic_id: "programming", name: "Programación", concepts: ["codigo", "programar", "proyecto", "python", "java", "c++"], compatible_intents: ["open", "inspect_version", "create"] },
  { topic_id: "general_information", name: "Información", concepts: ["sabes", "quien", "que es", "sobre", "informacion"], compatible_intents: ["ask_information"] },
  { topic_id: "casual_conversation", name: "Conversación", concepts: ["hola", "saludo", "charla", "conversacion", "cuentas", "andas", "jaja", "jeje"], compatible_intents: ["casual_conversation"] },
  { topic_id: "current_news", name: "Noticias", concepts: ["noticia", "noticias", "actualidad", "hoy", "reciente", "localidad", "crimen"], compatible_intents: ["news_search"] },
  { topic_id: "date_time", name: "Fecha y hora", concepts: ["fecha", "dia", "año", "hora", "hoy", "calendario"], compatible_intents: ["date_time_query"] },
  { topic_id: "visual_input", name: "Contenido visual", concepts: ["imagen", "captura", "camara", "pantalla", "ves", "mira"], compatible_intents: ["inspect_visual"] },
];
const CONTEXT_ENTITIES: EntityDefinition[] = [
  { entity_id: "app.spotify", entity_type: "application", name: "Spotify", aliases: ["spotify", "spoti", "espotifai"], topic_hints: ["media_playback"], compatible_intents: ["open", "close", "play_media"] },
  { entity_id: "app.discord", entity_type: "application", name: "Discord", aliases: ["discord"], topic_hints: ["applications"], compatible_intents: ["open", "close"] },
  { entity_id: "app.chrome", entity_type: "application", name: "Chrome", aliases: ["chrome", "google chrome"], topic_hints: ["web_browsing", "applications"], compatible_intents: ["open", "close", "navigate"] },
  { entity_id: "app.vscode", entity_type: "application", name: "Visual Studio Code", aliases: ["visual studio code", "vscode", "el editor donde programamos"], topic_hints: ["programming", "applications"], compatible_intents: ["open", "close"] },
  { entity_id: "service.minecraft.local", entity_type: "server", name: "Minecraft Server", aliases: ["server de minecraft", "servidor de minecraft", "minecraft", "server", "servidor"], topic_hints: ["minecraft_server"], compatible_intents: ["diagnose", "restart", "check_network_port"], attributes: { port: 25565 } },
  { entity_id: "runtime.java", entity_type: "runtime", name: "Java", aliases: ["java"], topic_hints: ["minecraft_server", "programming"], compatible_intents: ["inspect_version", "diagnose"] },
  { entity_id: "network.firewall", entity_type: "security_control", name: "Firewall", aliases: ["firewall", "cortafuegos"], topic_hints: ["network_security"], compatible_intents: ["diagnose"] },
  { entity_id: "media.song.numb", entity_type: "song", name: "Numb", aliases: ["numb"], topic_hints: ["media_playback"], compatible_intents: ["play_media"] },
  { entity_id: "media.artist.linkin_park", entity_type: "artist", name: "Linkin Park", aliases: ["linkin park", "linkin", "likin par", "likin"], topic_hints: ["media_playback"], compatible_intents: ["play_media"] },
  { entity_id: "website.youtube", entity_type: "website", name: "YouTube", aliases: ["youtube", "you tube"], topic_hints: ["web_browsing"], compatible_intents: ["open", "navigate"] },
  { entity_id: "hardware.ram", entity_type: "hardware", name: "RAM", aliases: ["memoria ram", "ram"], topic_hints: ["system_hardware"], compatible_intents: ["inspect_system"] },
  { entity_id: "hardware.cpu", entity_type: "hardware", name: "CPU", aliases: ["cpu", "procesador"], topic_hints: ["system_hardware"], compatible_intents: ["inspect_system"] },
  { entity_id: "hardware.gpu", entity_type: "hardware", name: "GPU", aliases: ["gpu", "tarjeta grafica"], topic_hints: ["system_hardware"], compatible_intents: ["inspect_system"] },
  { entity_id: "hardware.disk", entity_type: "hardware", name: "Disco", aliases: ["disco", "almacenamiento"], topic_hints: ["system_hardware"], compatible_intents: ["inspect_system"] },
  { entity_id: "artifact.pdf", entity_type: "artifact_format", name: "PDF", aliases: ["pdf"], topic_hints: ["documents"], compatible_intents: ["create_artifact", "open"] },
  { entity_id: "artifact.document", entity_type: "artifact_format", name: "Documento", aliases: ["documento", "word", "docx"], topic_hints: ["documents"], compatible_intents: ["create_artifact", "open"] },
  { entity_id: "artifact.presentation", entity_type: "artifact_format", name: "Presentación", aliases: ["presentacion", "diapositivas", "powerpoint", "pptx"], topic_hints: ["documents"], compatible_intents: ["create_artifact", "open"] },
  { entity_id: "artifact.spreadsheet", entity_type: "artifact_format", name: "Hoja de cálculo", aliases: ["hoja de calculo", "excel", "xlsx"], topic_hints: ["documents"], compatible_intents: ["create_artifact", "open"] },
];
const CONTEXT_INTENTS: IntentDefinition[] = [
  { name: "open", patterns: [/\b(?:abre|inicia|ejecuta|lanza)\b/u], compatible_types: ["application", "website", "file", "project"] },
  { name: "close", patterns: [/\b(?:cierra|cerralo|cierralo|terminalo)\b/u], compatible_types: ["application", "process", "file"], sensitive: true },
  { name: "play_media", patterns: [/\b(?:pon|reproduce|toca|musica|cancion)\b/u], compatible_types: ["application", "song", "artist"] },
  { name: "pause_media", patterns: [/\b(?:pausa|pausala|deten la musica)\b/u], compatible_types: ["application", "song"], implicit_active_target: true },
  { name: "adjust_volume", patterns: [/\b(?:sube|subele|baja|bajale|bajito|volumen|mas bajo|mas alto)\b/u], compatible_types: ["application", "song", "artist"], implicit_active_target: true },
  { name: "inspect_version", patterns: [/\b(?:que version|version tengo|version)\b/u], compatible_types: ["runtime", "application"] },
  { name: "check_network_port", patterns: [/\b(?:puerto|port)\b/u, /\b\d{2,5}\b/u], compatible_types: ["server", "network_port"] },
  { name: "inspect_system", patterns: [/\b(?:cuanto|cuanta|temperatura|uso|espacio)\b/u], compatible_types: ["hardware"] },
  { name: "diagnose", patterns: [/\b(?:no inicia|no abre|no funciona|falla|problema|esta mal|ta mal|bloqueando)\b/u], compatible_types: ["server", "runtime", "security_control", "application"] },
  { name: "restart", patterns: [/\b(?:reinicia|reinicialo|reiniciar)\b/u], compatible_types: ["server", "application"], sensitive: true },
  { name: "delete", patterns: [/\b(?:borra|elimina|formatea|desinstala)\b/u], compatible_types: ["file", "application"], sensitive: true },
  { name: "find", patterns: [/\b(?:busca|encuentra|localiza)\b/u], compatible_types: ["file", "project"] },
  { name: "create_artifact", patterns: [/\b(?:crea(?:me)?|genera(?:me)?|haz(?:me)?|elabora|redacta|disena|escribe)\b/u], compatible_types: ["artifact_format"], governing: true },
  { name: "create", patterns: [/\b(?:crea(?:me)?|genera(?:me)?|programa)\b/u], compatible_types: ["file", "project"], governing: true },
  { name: "ask_information", patterns: [/\b(?:sabes|conoces|quien es|que es|hablame de|explicame)\b/u], compatible_types: ["person", "artist", "topic"] },
  { name: "casual_conversation", patterns: [/\b(?:hola|buenas|como (?:estas|andas|va todo)|que (?:tal|te cuentas)|charlemos|conversemos|jaja+|jeje+)\b/u], compatible_types: [] },
  { name: "news_search", patterns: [/\b(?:noticias?|actualidad|que paso hoy|algo nuevo|sucesos recientes)\b/u], compatible_types: ["location"], governing: true },
  { name: "date_time_query", patterns: [], compatible_types: [], governing: true },
  { name: "inspect_visual", patterns: [/\b(?:puedes ver|que ves|mira|revisa|analiza|inspecciona)\b[^.]{0,100}\b(?:imagen|captura|camara|pantalla|dispositivo)\b/u], compatible_types: ["image", "screen", "camera", "device"] },
];
const CONTEXT_NORMALIZATIONS: Array<[RegExp, string]> = [[/\bespotifai\b/giu, "Spotify"], [/\bspoti\b/giu, "Spotify"], [/\blikin par\b/giu, "Linkin Park"], [/\blikin\b/giu, "Linkin Park"], [/\bcansion\b/giu, "canción"]];

function contextFold(value: string): string {
  return value.normalize("NFKD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("es").replace(/\s+/g, " ").trim();
}

type TemporalResolution = { fields: Array<"day" | "month" | "year" | "time">; confidence: number; evidence: string[] };
const TEMPORAL_FIELDS = [
  { id: "day", aliases: ["dia", "dia de hoy", "jornada"] },
  { id: "month", aliases: ["mes"] },
  { id: "year", aliases: ["ano"] },
  { id: "time", aliases: ["hora", "horas"] },
  { id: "date", aliases: ["fecha", "fecha actual"] },
] as const;
const TEMPORAL_QUERY_CUES = new Set(["que", "cual", "dime", "decir", "dices", "indica", "indicame", "estamos", "es", "son"]);
const TEMPORAL_CURRENT_CUES = new Set(["hoy", "actual", "ahora", "estamos"]);
const TEMPORAL_CONFLICTS = new Set(["resumen", "noticias", "agenda", "historia", "explica", "temperatura", "clima", "pronostico"]);
const TEMPORAL_COMPOSITION_CUES = new Set(["junto", "juntos", "juntas", "ambos", "combina", "combinar", "completo", "together", "both", "combine"]);
const TEMPORAL_ORDER = ["day", "month", "year", "time"] as const;
const REQUEST_CAPABILITIES = [
  { id: "weather", concepts: new Set(["clima", "temperatura", "pronostico", "tiempo", "weather", "forecast"]) },
  { id: "daily_brief", concepts: new Set(["resumen", "noticias", "actualidad", "agenda"]) },
] as const;

function requestedCapabilities(value: string): string[] {
  const tokens = new Set(contextFold(value).match(/[\p{L}\p{N}]+/gu) || []);
  return REQUEST_CAPABILITIES
    .map(definition => ({ id: definition.id, score: [...definition.concepts].filter(concept => tokens.has(concept)).length }))
    .filter(candidate => candidate.score > 0)
    .sort((left, right) => right.score - left.score)
    .map(candidate => candidate.id);
}

const SEMANTIC_STOP_WORDS = new Set(["a", "al", "de", "del", "el", "en", "es", "la", "las", "lo", "los", "me", "mi", "por", "que", "se", "te", "un", "una", "y"]);

function semanticSufficiency(value: string, context?: Pick<ContextResult, "entities">): { score: number; concepts: string[] } {
  const concepts = (contextFold(value).match(/[\p{L}\p{N}]+/gu) || []).filter(token => token.length > 1 && !SEMANTIC_STOP_WORDS.has(token));
  const unique = [...new Set(concepts)], entityWeight = Math.min(2, context?.entities.length || 0);
  const relationWeight = /\b(?:con|contra|desde|hasta|para|porque|pero|cuando|donde|como)\b/u.test(contextFold(value)) ? 1 : 0;
  return { score: Math.min(1, (unique.length + entityWeight + relationWeight) / 5), concepts: unique };
}

function temporalResolution(value: string, history: string[] = []): TemporalResolution | null {
  const normalized = contextFold(value), tokens = normalized.match(/[\p{L}\p{N}]+/gu) || [], tokenSet = new Set(tokens);
  const matched = new Set<string>(), evidence: string[] = [];
  for (const definition of TEMPORAL_FIELDS) {
    const alias = [...definition.aliases].sort((a, b) => b.length - a.length).find(item => new RegExp(`(?:^| )${item}(?: |$)`, "u").test(normalized));
    if (alias) { matched.add(definition.id); evidence.push(`field:${definition.id}:${alias}`); }
  }
  if (matched.has("date")) { matched.delete("date"); ["day", "month", "year"].forEach(field => matched.add(field)); evidence.push("date_expansion"); }
  const query = [...tokenSet].filter(token => TEMPORAL_QUERY_CUES.has(token));
  const current = [...tokenSet].filter(token => TEMPORAL_CURRENT_CUES.has(token));
  const conflicts = [...tokenSet].filter(token => TEMPORAL_CONFLICTS.has(token));
  const composition = [...tokenSet].filter(token => TEMPORAL_COMPOSITION_CUES.has(token));
  if (!matched.size && composition.length && query.length) {
    for (const previous of history.slice(-6)) {
      const prior = temporalResolution(previous);
      prior?.fields.forEach(field => matched.add(field));
    }
    if (matched.size) evidence.push(...TEMPORAL_ORDER.filter(field => matched.has(field)).map(field => `context:${field}`), ...composition.map(item => `composition:${item}`));
  }
  if (!matched.size) return null;
  const score = Math.max(0, Math.min(1, .48 + Math.min(.22, .08 * matched.size) + (query.length ? .18 : 0) + (current.length ? .12 : 0) + (tokens.length <= 4 ? .12 : 0) + (composition.length && evidence.some(item => item.startsWith("context:")) ? .12 : 0) - (conflicts.length ? .55 : 0)));
  if (score < .66) return null;
  evidence.push(...query.map(item => `query:${item}`), ...current.map(item => `current:${item}`));
  return { fields: TEMPORAL_ORDER.filter(field => matched.has(field)), confidence: score, evidence };
}

type LocationMemoryResolution = { location: string; confidence: number; evidence: string[] };
const LOCATION_MEMORY_CONCEPTS = new Set(["guarda", "guardar", "recuerda", "recordar", "memoriza", "conserva", "save", "remember"]);
const LOCATION_SLOT_CONCEPTS = new Set(["ubicacion", "ciudad", "lugar", "location", "city"]);
const LOCATION_TRAILING_CONCEPTS = new Set([...LOCATION_MEMORY_CONCEPTS, ...LOCATION_SLOT_CONCEPTS, "asi", "entonces", "para", "proxima", "futuro", "siempre", "mi", "la", "lo", "que", "y"]);

function locationMemoryResolution(value: string): LocationMemoryResolution | null {
  const normalized = contextFold(value), tokens = normalized.match(/[\p{L}\p{N}]+/gu) || [];
  const memory = tokens.filter(token => LOCATION_MEMORY_CONCEPTS.has(token)), slots = tokens.filter(token => LOCATION_SLOT_CONCEPTS.has(token));
  if (!memory.length || !slots.length) return null;
  const boundary = Math.min(...memory.map(token => tokens.indexOf(token)));
  const leading = tokens.slice(0, boundary).filter(token => !LOCATION_TRAILING_CONCEPTS.has(token));
  const explicit = normalized.match(/(?:ubicacion|ciudad|lugar)\s+(?:es|sera)\s+([\p{L}\p{N}\s-]{2,80})/u)?.[1] || "";
  const candidate = compactText(leading.join(" ") || explicit, 80).replace(/\b(?:asi que|entonces|para la proxima|para el futuro)\b.*$/u, "").trim();
  if (!candidate) return null;
  const location = candidate.replace(/\b\p{L}/gu, letter => letter.toLocaleUpperCase("es"));
  return { location, confidence: Math.min(.99, .8 + (tokens.some(token => ["proxima", "futuro", "siempre"].includes(token)) ? .12 : 0)), evidence: [...memory.map(item => `memory:${item}`), ...slots.map(item => `location:${item}`)] };
}

function contextEntities(value: string): ContextEntity[] {
  const text = contextFold(value), found: ContextEntity[] = [], occupied: Array<[number, number]> = [];
  const aliases = CONTEXT_ENTITIES.flatMap(definition => definition.aliases.map(alias => ({ alias, definition }))).sort((a, b) => b.alias.length - a.alias.length);
  for (const { alias, definition } of aliases) {
    const match = new RegExp(`(?<!\\w)${contextFold(alias).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?!\\w)`, "u").exec(text);
    if (!match || occupied.some(([start, end]) => match.index < end && match.index + match[0].length > start) || found.some(item => item.entity_id === definition.entity_id)) continue;
    const exact = contextFold(alias) === contextFold(definition.name) || alias === definition.aliases[0];
    found.push({ entity_id: definition.entity_id, entity_type: definition.entity_type, name: definition.name, aliases: definition.aliases, attributes: definition.attributes || {}, status: exact ? "KNOWN" : "INFERRED", confidence: exact ? 1 : .9, source: "current_message", position: match.index });
    occupied.push([match.index, match.index + match[0].length]);
  }
  const port = text.match(/\b(?:puerto\s*)?(\d{2,5})\b/u)?.[1];
  if (port) found.push({ entity_id: `network.port.${port}`, entity_type: "network_port", name: `Port ${port}`, aliases: [], attributes: { port: Number(port) }, status: "KNOWN", confidence: 1, source: "current_message", position: text.indexOf(port) });
  const location = text.match(/\b(?:soy|vivo|estoy)\s+(?:de|en)\s+([\p{L}][\p{L}\s-]{2,80})$/u);
  if (location) found.push({ entity_id: `location.${location[1].replace(/\s+/g, "_")}`, entity_type: "location", name: location[1].trim(), aliases: [], attributes: { label: location[1].trim() }, status: "KNOWN", confidence: 1, source: "current_message", position: location.index || 0 });
  const rememberedLocation = locationMemoryResolution(value);
  if (rememberedLocation && !found.some(item => item.entity_type === "location")) found.push({ entity_id: `location.${contextFold(rememberedLocation.location).replace(/\s+/g, "_")}`, entity_type: "location", name: rememberedLocation.location, aliases: [], attributes: { label: rememberedLocation.location, authorized_for_future: true }, status: "KNOWN", confidence: rememberedLocation.confidence, source: "explicit_location_memory", position: 0 });
  return found.sort((a, b) => a.position - b.position);
}

function contextIntent(value: string, entities: ContextEntity[], previous = "", history: string[] = []): { name: string; confidence: number } {
  const text = contextFold(value), types = new Set(entities.map(item => item.entity_type));
  const scored = CONTEXT_INTENTS.flatMap(definition => {
    const matches = definition.patterns.map(pattern => pattern.exec(text)).filter(Boolean) as RegExpExecArray[];
    if (!matches.length) return [];
    const compatibility = definition.compatible_types.some(type => types.has(type));
    const first = Math.min(...matches.map(match => match.index)) / Math.max(1, text.length);
    let confidence = .68 + matches.length * .06 + (compatibility ? .14 : 0) + (definition.governing ? (1 - first) * .10 : first * .08);
    if (definition.governing && compatibility) confidence += .12;
    return [{ name: definition.name, confidence: Math.min(1, confidence) }];
  });
  const temporal = temporalResolution(value, history);
  if (temporal) scored.push({ name: "date_time_query", confidence: temporal.confidence });
  if (scored.length) return scored.sort((a, b) => b.confidence - a.confidence)[0];
  const prior = CONTEXT_INTENTS.find(item => item.name === previous);
  if (prior && prior.compatible_types.some(type => types.has(type))) return { name: previous, confidence: .76 };
  return { name: "respond", confidence: .55 };
}

function topicScores(value: string, entities: ContextEntity[], intent: string, threads: Map<string, ContextThread>, turn: number): Record<string, number> {
  const tokens = new Set(contextFold(value).match(/[a-z0-9+#]{2,}/gu) || []), scores: Record<string, number> = {};
  for (const topic of CONTEXT_TOPICS) {
    const overlap = topic.concepts.filter(concept => tokens.has(contextFold(concept))).length / Math.max(1, Math.min(4, tokens.size));
    const hints = entities.filter(entity => CONTEXT_ENTITIES.find(item => item.entity_id === entity.entity_id)?.topic_hints.includes(topic.topic_id)).length;
    scores[topic.topic_id] = overlap * .48 + Math.min(1, hints / 2) * .38 + (topic.compatible_intents.includes(intent) ? .14 : 0);
    const thread = threads.get(topic.topic_id);
    if (thread) {
      const threadTokens = new Set(contextFold(thread.entities.map(item => item.name).join(" ") + " " + thread.messages.slice(-3).join(" ")).match(/[a-z0-9+#]{2,}/gu) || []);
      const lexical = [...tokens].filter(token => threadTokens.has(token)).length / Math.max(1, Math.min(4, tokens.size));
      const entityOverlap = entities.filter(entity => thread.entities.some(item => item.entity_id === entity.entity_id)).length / Math.max(1, entities.length);
      const decay = Math.exp(-Math.max(0, turn - thread.last_turn) / 8);
      scores[topic.topic_id] = Math.max(scores[topic.topic_id], scores[topic.topic_id] * .32 + lexical * .25 + entityOverlap * .24 + decay * .08 + (thread.intents.slice(-4).includes(intent) ? .07 : 0));
    }
  }
  return scores;
}

function interpretContext(text: string, history: any[]): ContextResult {
  const threads = new Map<string, ContextThread>(); let active = "general", turn = 0;
  const userHistory = history.filter(item => item?.role === "user").map(item => String(item.body ?? item.content ?? "")).filter(Boolean);
  for (const item of history.slice(-24)) {
    const structured = item?.context_data?.entities;
    if (item?.role === "assistant" && Array.isArray(structured) && threads.has(active)) {
      const thread = threads.get(active)!;
      for (const entity of structured) if (entity?.entity_id && !thread.entities.some(existing => existing.entity_id === entity.entity_id)) thread.entities.push(entity as ContextEntity);
      continue;
    }
    if (item?.role !== "user") continue;
    const body = String(item.body ?? item.content ?? "").trim(); if (!body) continue; turn++;
    const entities = contextEntities(body), prior = threads.get(active)?.intents.at(-1) || "", intent = contextIntent(body, entities, prior), scores = topicScores(body, entities, intent.name, threads, turn);
    const ranked = Object.entries(scores).sort((a, b) => b[1] - a[1]); let topic = ranked[0]?.[1] >= .16 ? ranked[0][0] : active;
    if (!threads.size && !entities.length && ranked[1] && Math.abs(ranked[0][1] - ranked[1][1]) < .025) topic = "general";
    const thread = threads.get(topic) || { topic_id: topic, messages: [], entities: [], intents: [], last_turn: turn };
    thread.messages = [...thread.messages.slice(-10), body]; thread.intents = [...thread.intents.slice(-7), intent.name]; thread.last_turn = turn;
    for (const entity of entities) if (!thread.entities.some(existing => existing.entity_id === entity.entity_id)) thread.entities.push(entity);
    thread.entities = thread.entities.slice(-24); threads.set(topic, thread); active = topic;
  }
  let normalized = text.normalize("NFKC").replace(/%20/giu, " ").replace(/(?<=\p{L})%(?=\p{L})/gu, " ").replace(/\s+/g, " ").trim(); for (const [pattern, replacement] of CONTEXT_NORMALIZATIONS) normalized = normalized.replace(pattern, replacement);
  const folded = contextFold(normalized), explicit = contextEntities(normalized), initialIntent = contextIntent(normalized, explicit, threads.get(active)?.intents.at(-1) || "", userHistory), scores = topicScores(normalized, explicit, initialIntent.name, threads, turn + 1);
  const ranked = Object.entries(scores).sort((a, b) => b[1] - a[1]); let topic = ranked[0]?.[0] || "general", best = ranked[0]?.[1] || 0;
  if (best < .16 && threads.has(active)) { topic = active; best = .42; }
  else if (!threads.size && !explicit.length && ranked[1] && Math.abs(best - ranked[1][1]) < .025) { topic = "general"; best = .35; }
  const existed = threads.has(topic), previousActive = active, thread = threads.get(topic), contextList = thread?.entities || [], intent = contextIntent(normalized, explicit, thread?.intents.at(-1) || initialIntent.name, userHistory);
  let resolution: ContextResult["resolution"] = topic === previousActive ? "CONTINUE_ACTIVE_THREAD" : existed ? "SWITCH_TO_RECENT_THREAD" : "CREATE_NEW_THREAD";
  const related = ranked.slice(1, 4).filter(([, score]) => score >= .35 && score >= best * .72).map(([id]) => id); if (related.length) resolution = "RELATE_MULTIPLE_THREADS";
  const references: Record<string, unknown>[] = [], entities = [...explicit], sources = ["current_message"];
  const reference = /\b(?:eso|esto|ese|esa|aquel|ahi|alli|lo de antes|lo anterior|coso|vaina|cierralo|cerralo|pausala|reinicialo)\b/u.test(folded) || /\b(?:el|la)\s+(?:primero|primera|segundo|segunda|tercero|tercera)(?=$|[?.!,])/u.test(folded) || /^(?:lo|la)$/u.test(folded);
  const intentDef = CONTEXT_INTENTS.find(item => item.name === intent.name), candidates = contextList.filter(entity => !intentDef?.compatible_types.length || intentDef.compatible_types.includes(entity.entity_type));
  const ordinal = folded.match(/\b(?:el|la)\s+(primero|primera|segundo|segunda|tercero|tercera)(?=$|[?.!,])/u)?.[1]; let selected: ContextEntity | undefined;
  if (ordinal) selected = candidates[/primer/u.test(ordinal) ? 0 : /segund/u.test(ordinal) ? 1 : 2]; else if (reference && candidates.length === 1) selected = candidates[0];
  if (selected) { const inferred = { ...selected, status: "INFERRED" as Evidence, confidence: .92, source: ordinal ? "ordinal_reference" : "compatible_entity" }; entities.push(inferred); references.push({ text, entity_id: inferred.entity_id, status: "INFERRED", confidence: .92, source: inferred.source }); sources.push("resolved_reference"); }
  const unresolved = reference && !selected && !explicit.length; if (unresolved) references.push({ text, status: "UNKNOWN", confidence: .35, candidates: candidates.slice(0, 4).map(item => item.name) });
  if (["inspect_version", "check_network_port", "diagnose"].includes(intent.name) && intentDef) for (const entity of [...contextList].reverse()) if (intentDef.compatible_types.includes(entity.entity_type) && !entities.some(item => item.entity_id === entity.entity_id)) entities.push({ ...entity, status: "INFERRED", confidence: .9, source: "topic_thread" });
  let interpreted = normalized; const byType = (kind: string) => entities.find(item => item.entity_type === kind), target = byType("application") || byType("server") || byType("website") || byType("file");
  if (intent.name === "open" && target && entities.filter(item => ["application", "website", "file", "project"].includes(item.entity_type)).length === 1) interpreted = `abre ${target.name}`;
  else if (intent.name === "close" && target) interpreted = `cierra ${target.name}`;
  else if (intent.name === "restart" && target) interpreted = `reinicia ${target.name}`;
  else if (intent.name === "play_media") { const song = byType("song"), artist = byType("artist"), app = byType("application"); if (song || artist) { const detail = song?.name || `música de ${artist!.name}`; interpreted = `reproduce ${detail}${app ? ` en ${app.name}` : ""}`; } }
  else if (intent.name === "pause_media") interpreted = "pausa la reproducción actual";
  else if (intent.name === "adjust_volume") interpreted = `${/\b(?:baja|bajale|bajito|mas bajo)\b/u.test(folded) ? "baja" : "sube"} un poco el volumen de la reproducción actual`;
  else if (intent.name === "inspect_version" && (byType("runtime") || byType("application"))) interpreted = `consulta la versión de ${(byType("runtime") || byType("application"))!.name}`;
  else if (intent.name === "check_network_port" && byType("server")) interpreted = `revisa el puerto ${String(byType("server")!.attributes.port || "")} de ${byType("server")!.name}`.replace("puerto  de", "puerto de");
  if (interpreted !== normalized) sources.push("structured_reconstruction");
  if (/^(?:desde ayer|desde anoche|hace rato|otra vez|nuevamente)$/u.test(folded) && thread?.messages.length) { interpreted = `${thread.messages.at(-1)} ${normalized}`; sources.push("incomplete_continuation"); }
  if (resolution === "SWITCH_TO_RECENT_THREAD") sources.push("reactivated_thread"); if (related.length) sources.push("related_threads");
  const second = ranked[1]?.[1] || 0, topicConfidence = Math.min(.99, .58 + best * .42 + Math.max(0, best - second) * .22), confidence = unresolved ? .42 : Math.min(intent.confidence, topicConfidence, selected?.confidence || 1);
  const sufficientlySpecified = semanticSufficiency(normalized, { entities }).score >= .6;
  const sensitive = Boolean(intentDef?.sensitive), clarification = unresolved && !sufficientlySpecified && !intentDef?.implicit_active_target && (sensitive || confidence < .6), confirmation = sensitive && (unresolved || confidence < .6);
  const facts = [{ key: "resolved_topic", value: topic, status: (resolution === "CONTINUE_ACTIVE_THREAD" ? "KNOWN" : "INFERRED") as Evidence, confidence: topicConfidence, source: "topic_scores" }, ...entities.map(entity => ({ key: `entity:${entity.entity_id}`, value: entity.name, status: entity.status, confidence: entity.confidence, source: entity.source }))];
  return { raw_input: text, normalized_input: normalized, interpreted_request: interpreted, intent, topic: { id: topic, confidence: topicConfidence, scores }, entities, references, related_topics: related, context_sources: [...new Set(sources)], confidence, requires_confirmation: confirmation, requires_clarification: clarification, clarification_required: clarification, resolution, facts };
}

async function conversationHistory(payload: any, token: string, user: any, text: string): Promise<any[]> {
  let history = Array.isArray(payload.history) ? payload.history.slice(-12).filter((item: any) => ["user", "assistant"].includes(item?.role) && typeof item?.body === "string").map((item: any) => ({ role: item.role, body: item.body.slice(0, 16000), context_data: item.context_data && typeof item.context_data === "object" && !Array.isArray(item.context_data) ? item.context_data : {} })) : [];
  if (user && payload.conversation_id) {
    const stored = await rest(token, "archeon_messages", `?conversation_id=eq.${encodeURIComponent(String(payload.conversation_id))}&select=role,body,context_data,created_at&order=created_at.desc&limit=25`);
    history = stored.reverse().filter((item: any) => ["user", "assistant"].includes(item?.role) && typeof item?.body === "string");
    const current = history.at(-1);
    if (current?.role === "user" && current.body.trim() === text) history.pop();
    history = history.slice(-24);
  }
  return history;
}

type ResearchAnswer = { message: string; details?: string; source_label?: string; source_url?: string };

function briefResearchExtract(value: string): string {
  const clean = value.replace(/[\u200B-\u200D\u2060\uFEFF]/gu, "").replace(/\s+/g, " ").trim();
  const sentences = clean.match(/[^.!?]+[.!?]+(?:["»”')\]]+)?|[^.!?]+$/gu)?.map(sentence => sentence.trim()).filter(Boolean) || [];
  let brief = "";
  for (const sentence of sentences.slice(0, 3)) {
    const candidate = [brief, sentence].filter(Boolean).join(" ");
    if (brief && candidate.length > 190) break;
    brief = candidate;
  }
  return brief || clean;
}

function researchContinuation(fullExtract: string, brief: string): string {
  const full = fullExtract.replace(/[\u200B-\u200D\u2060\uFEFF]/gu, "").replace(/\s+/g, " ").trim();
  if (!brief || !full.startsWith(brief)) return full;
  return full.slice(brief.length).trim();
}

async function researchedAnswer(text: string, followup = false): Promise<ResearchAnswer | null> {
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
    if (followup) return { message: `${extract}\n\nFuente: [Wikipedia](${url})` };
    const brief = briefResearchExtract(fullExtract);
    const continuation = researchContinuation(fullExtract, brief);
    return {
      message: brief,
      ...(continuation.length > 40 ? { details: continuation, source_label: "Wikipedia", source_url: url } : {}),
    };
  } catch (_) {
    return null;
  }
}

function decodeXml(value: string): string {
  return value.replace(/^<!\[CDATA\[|\]\]>$/g, "").replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/\s+/g, " ").trim();
}

function rssValue(item: string, tag: string): string {
  return decodeXml(item.match(new RegExp(`<${tag}(?:\\s[^>]*)?>([\\s\\S]*?)<\\/${tag}>`, "iu"))?.[1] || "");
}

type CurrentNewsAnswer = {
  message: string;
  sources: Array<{ title: string; source: string; url: string }>;
};

function newsSearchTerms(text: string): string {
  const ignored = new Set(["dime", "cuentame", "busca", "muestra", "dame", "quiero", "saber", "noticia", "noticias", "actualidad", "reciente", "recientes", "algo", "nuevo", "nueva", "hoy", "de", "del", "en", "la", "las", "los", "el", "sobre", "por", "favor"]);
  const terms = contextFold(text).match(/[\p{L}\p{N}-]{2,}/gu)?.filter(token => !ignored.has(token)) || [];
  return compactText(terms.join(" ") || "Ecuador", 140);
}

async function currentNewsAnswer(text: string): Promise<CurrentNewsAnswer | null> {
  const clean = newsSearchTerms(text);
  const query = `${clean} ${/\bhoy\b/iu.test(clean) ? "when:1d" : "when:7d"}`.trim();
  if (!query) return null;
  try {
    const parameters = new URLSearchParams({ q: query, hl: "es-419", gl: "EC", ceid: "EC:es-419" });
    const response = await fetch(`https://news.google.com/rss/search?${parameters}`, {
      headers: { Accept: "application/rss+xml, application/xml", "User-Agent": "ARCHEON/1.0 current-news" },
      signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) return null;
    const xml = await response.text(), items = [...xml.matchAll(/<item>([\s\S]*?)<\/item>/giu)].slice(0, 4)
      .map(match => ({ title: rssValue(match[1], "title"), link: rssValue(match[1], "link"), source: rssValue(match[1], "source") }))
      .filter(item => item.title && /^https:\/\//i.test(item.link));
    if (!items.length) return null;
    const sources = items.slice(0, 3).map(item => {
      const escapedSource = item.source.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const repeatedSource = escapedSource ? new RegExp(`\\s+-\\s+${escapedSource}\\s*$`, "iu") : null;
      return {
        title: compactText(repeatedSource ? item.title.replace(repeatedSource, "") : item.title, 220),
        source: item.source,
        url: item.link,
      };
    });
    const narrative = sources.map((item, index) => {
      const lead = index === 0 ? "Entre lo más reciente" : index === 1 ? "También se informó" : "Por otro lado";
      return `${lead}: ${item.title}${/[.!?…]$/u.test(item.title) ? "" : "."}${item.source ? ` La información fue publicada por ${item.source}.` : ""}`;
    }).join("\n\n");
    return { message: `${narrative}\n\nSi quieres, puedo ampliar cualquiera de estos temas.`, sources };
  } catch (_) {
    return null;
  }
}

async function currentWeatherAnswer(location: string): Promise<string | null> {
  try {
    const response = await fetch(`https://wttr.in/${encodeURIComponent(location)}?format=j1`, {
      headers: { Accept: "application/json", "User-Agent": "ARCHEON/1.0 current-weather" },
      signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) return null;
    const value = await response.json(), current = value?.current_condition?.[0], area = value?.nearest_area?.[0];
    if (!current || !Number.isFinite(Number(current.temp_C))) return null;
    const label = String(area?.areaName?.[0]?.value || location), description = String(current?.lang_es?.[0]?.value || current?.weatherDesc?.[0]?.value || "").trim();
    return `Ahora mismo en ${label} hay ${current.temp_C} °C${description ? ` y ${description.toLocaleLowerCase("es")}` : ""}. La sensación térmica es de ${current.FeelsLikeC} °C y la humedad es del ${current.humidity} %.`;
  } catch (_) {
    return null;
  }
}

function currentDateTimeAnswer(text: string, payload: any, contextual?: TemporalResolution | null): string {
  const locale = /^[a-z]{2}(?:-[A-Z]{2})?$/.test(String(payload.locale || "")) ? String(payload.locale) : "es-EC";
  const requestedZone = String(payload.timezone || "America/Guayaquil");
  let timezone = "America/Guayaquil";
  try { new Intl.DateTimeFormat(locale, { timeZone: requestedZone }).format(new Date()); timezone = requestedZone; } catch (_) {}
  const now = new Date(), resolution = contextual || temporalResolution(text);
  const fields = resolution?.fields.length ? resolution.fields : ["day", "month", "year"] as TemporalResolution["fields"];
  const values: Record<string, string> = {
    day: new Intl.DateTimeFormat(locale, { timeZone: timezone, weekday: "long", day: "numeric" }).format(now),
    month: new Intl.DateTimeFormat(locale, { timeZone: timezone, month: "long" }).format(now),
    year: new Intl.DateTimeFormat(locale, { timeZone: timezone, year: "numeric" }).format(now),
    time: new Intl.DateTimeFormat(locale, { timeZone: timezone, hour: "numeric", minute: "2-digit" }).format(now),
  };
  const single: Record<string, string> = { day: `Hoy es ${values.day}.`, month: `Estamos en ${values.month}.`, year: `Estamos en ${values.year}.`, time: `Son las ${values.time}.` };
  if (fields.length === 1) return single[fields[0]];
  const combined: Record<string, string> = {
    "day,month": `Hoy es ${values.day} de ${values.month}.`,
    "month,year": `Estamos en ${values.month} de ${values.year}.`,
    "day,month,year": `Hoy es ${values.day} de ${values.month} de ${values.year}.`,
  };
  if (combined[fields.join(",")]) return combined[fields.join(",")];
  const labels: Record<string, string> = { day: "día", month: "mes", year: "año", time: "hora" };
  const answer = fields.map(field => `${labels[field]}: ${values[field]}`).join(", ");
  return answer.charAt(0).toUpperCase() + answer.slice(1) + ".";
}

type MobileCapabilityDefinition = { id: string; available: boolean; summary: string };
const MOBILE_CAPABILITIES: MobileCapabilityDefinition[] = [
  { id: "conversation", available: true, summary: "conversar y mantener el contexto de cada chat" },
  { id: "files", available: true, summary: "trabajar con archivos y ARCHEON Cloud" },
  { id: "music", available: true, summary: "reproducir música y usar el modo DJ" },
  { id: "voice", available: true, summary: "recibir dictado y responder por voz" },
  { id: "devices", available: true, summary: "enviar órdenes a dispositivos autorizados" },
  { id: "images", available: true, summary: "generar imágenes temporales descargables" },
  { id: "live_news", available: true, summary: "consultar noticias recientes con sus fuentes" },
  { id: "vision", available: false, summary: "analizar directamente cámara o pantalla" },
];

function mobileCapabilitySummary(): string {
  const available = MOBILE_CAPABILITIES.filter(item => item.available).map(item => item.summary);
  return `Puedo ${available.slice(0, -1).join(", ")} y ${available.at(-1)}. Las capacidades dependen de los permisos y del dispositivo activo.`;
}

function contextualAnswer(context: ContextResult): string | null {
  const intent = context.intent.name, entities = context.entities;
  const byType = (type: string) => entities.find(item => item.entity_type === type);
  const server = byType("server"), runtime = byType("runtime"), port = byType("network_port")?.attributes.port || server?.attributes.port;
  if (intent === "diagnose" && server && runtime) return `Sí, puede ser ${runtime.name}. Revisaría primero qué versión tienes instalada, cuál requiere ${server.name} y el log exacto del arranque.`;
  if (intent === "diagnose" && server) return `Vamos a revisar por qué no inicia ${server.name}. Primero comprobaría el entorno, la configuración${port ? `, el puerto ${port}` : ""} y el log de arranque.`;
  if (intent === "check_network_port" && server) return `Sí, también conviene revisar el puerto ${port || "configurado"} y confirmar que ${server.name} realmente esté escuchando en él.`;
  if (intent === "inspect_version" && (runtime || byType("application"))) return `Puedo comprobar la versión de ${(runtime || byType("application"))!.name} y compararla con la que necesita el hilo actual.`;
  if (intent === "inspect_system" && byType("hardware")) return `Puedo comprobar ${byType("hardware")!.name} en este dispositivo y relacionarlo con lo que estábamos revisando.`;
  if (context.confidence < .85 && entities.length === 1) return `Si te refieres a ${entities[0].name}, puedo revisar primero su estado y los errores más recientes.`;
  return null;
}

function clarificationAnswer(context: ContextResult): string {
  const candidates = context.references.flatMap(reference => Array.isArray(reference.candidates) ? reference.candidates : []).filter(Boolean).slice(0, 4);
  if (candidates.length > 1) return `¿Te refieres a ${candidates.slice(0, -1).join(", ")} o ${candidates.at(-1)}?`;
  if (candidates.length === 1) return `¿Te refieres a ${candidates[0]}?`;
  return "Necesito saber una cosa antes: ¿qué elemento exacto quieres que revise o use?";
}

function nativeArchi(text: string, attachmentParts: any[], history: any[], context: ContextResult): string {
  const normalized = text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("es");
  const calculation = arithmetic(text);
  if (calculation !== null) return `El resultado es ${Number.isInteger(calculation) ? calculation : Number(calculation.toFixed(8))}.`;
  const attachmentText = attachmentParts.filter(part => part.type === "text").map(part => String(part.text || "")).join("\n");
  const hasImage = attachmentParts.some(part => part.type === "image_url");
  if (/\b(resume|resumen|resumir|sintetiza)\b/.test(normalized) && attachmentText) return `Resumen:\n\n${extractiveSummary(attachmentText)}`;
  if (hasImage) return "Recibí la imagen, pero el análisis visual todavía no está disponible en este teléfono. Puedo guardarla, enviarla o trabajar con su nombre y metadatos, pero no voy a inventar lo que contiene.";
  if (attachmentText) return `Leí el contenido adjunto. Sus puntos principales son:\n\n${extractiveSummary(attachmentText)}`;
  if (context.intent.name === "casual_conversation") return /\b(?:hola|buenas|buenos dias|buenas tardes|buenas noches)\b/.test(normalized)
    ? "Hola. Aquí estoy, ¿qué hacemos hoy?"
    : "Todo bien por aquí, listo para conversar o ayudarte con lo que tengas en mente. ¿Y tú qué tal?";
  if (/\b(que puedes hacer|ayuda|capacidades)\b/.test(normalized)) return mobileCapabilitySummary();
  if (context.intent.name === "inspect_visual") return "Puedo trabajar con una captura o imagen que adjuntes. No puedo mirar tu pantalla o cámara por mi cuenta; para eso necesito una fuente compartida y el permiso correspondiente.";
  const informationSubject = researchSubject(text);
  if (context.intent.name === "ask_information" && informationSubject) return `Sí, puedo ayudarte con ${informationSubject}. ¿Qué quieres saber exactamente?`;
  if (/\b(plan|pasos|organiza|organizar|lista)\b/.test(normalized)) return `Plan propuesto para “${compactText(text, 180)}”:\n\n1. Define el resultado exacto y el límite de tiempo.\n2. Reúne los datos o archivos necesarios.\n3. Divide el trabajo en una primera versión verificable.\n4. Ejecuta y comprueba cada resultado antes de continuar.\n5. Cierra con una revisión y una lista de pendientes reales.`;
  const contextual = contextualAnswer(context);
  if (contextual) return contextual;
  const sufficiency = semanticSufficiency(text, context);
  if (sufficiency.score >= .6) return "Tu solicitud ya tiene suficiente detalle. No tengo una herramienta activa en este teléfono para completarla con fiabilidad, pero no necesitas repetirla ni explicarla otra vez.";
  return "¿Qué necesitas saber o hacer?";
}

async function command(req: Request, payload: any, token: string): Promise<Response> {
  const user = await userFor(token);
  if (!await validGuest(token) && !user) return reply(req, { ok: false, error: "session_required" }, 401);
  if (user) await ensureMobileDevice(req, token, String(user.id));
  const text = String(payload.text ?? "").trim();
  if (!text || text.length > 16000) return reply(req, { ok: false, error: "invalid_text" }, 400);
  const history = await conversationHistory(payload, token, user, text);
  const context = interpretContext(text, history);
  const locationMemory = locationMemoryResolution(text);
  if (locationMemory) {
    if (user) await mobileSettings(req, token, user, { assistant: { preferred_location: locationMemory.location } });
    return reply(req, {
      ok: true,
      message: user
        ? `Listo. Usaré ${locationMemory.location} como tu ubicación para el clima y otros resultados locales.`
        : `Usaré ${locationMemory.location} durante este chat. Inicia sesión para conservarla en tus dispositivos.`,
      context_interpretation: { ...context, context_sources: [...new Set([...context.context_sources, "explicit_location_memory"])], location_memory: locationMemory },
      engine: "archeon-location-memory", intelligence: payload.intelligence || "medium", attachments_consumed: true,
    });
  }
  if (context.clarification_required || context.requires_confirmation) return reply(req, { ok: true, message: clarificationAnswer(context), context_interpretation: context, attachments_consumed: true });
  const effectiveText = context.interpreted_request;
  const requested = requestedCapabilities(effectiveText);
  const requestedImage = imageCreationPrompt(effectiveText);
  if (requestedImage) return generateEphemeralImage(req, requestedImage, context);
  if (requestsFileTransferToPc(effectiveText)) {
    if (!user) return reply(req, { ok: false, error: "account_session_required" }, 401);
    const ids = Array.isArray(payload.attachments) ? payload.attachments.slice(0, 10) : [];
    if (!ids.length) return reply(req, { ok: false, error: "attachment_required", message: "Adjunta el archivo exacto que quieres enviar a la PC." }, 400);
    const source = await ensureMobileDevice(req, token, String(user.id));
    const files = (await Promise.all(ids.map((id: any) => persistAttachmentToCloud(String(id), token, String(user.id), source?.id || null)))).filter(Boolean);
    if (!files.length) return reply(req, { ok: false, error: "cloud_upload_failed" }, 400);
    return reply(req, { ok: true, message: `Envié ${files.length === 1 ? files[0].display_name : `${files.length} archivos`} a ARCHEON Cloud; ya ${files.length === 1 ? "está" : "están"} disponible${files.length === 1 ? "" : "s"} en tu PC.`, files, context_interpretation: context, attachments_consumed: true });
  }
  const remoteFile = remoteFileIntent(effectiveText);
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
      return reply(req, { ok: true, message: `${target.display_name} encontró y envió ${file.display_name} a tu ARCHEON Cloud.`, file, remote_command: { id, action: "file.send", state: "succeeded" }, context_interpretation: context, attachments_consumed: true });
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
    return reply(req, { ok: true, message: `${target.display_name} sigue buscando ${query}. Te aparecerá en Cloud cuando termine.`, remote_command: { id, action: "file.send", state: "queued" }, context_interpretation: context, attachments_consumed: true });
  }
  const remote = desktopRemoteIntent(effectiveText);
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
    return reply(req, { ok: true, message: `Envié la orden a ${target.display_name}.`, remote_command: rows[0], context_interpretation: context, attachments_consumed: true });
  }
  const music = context.intent.name === "create_artifact" ? null : mediaQuery(effectiveText);
  if (music) {
    const owned = await findOwnedMusic(token, music);
    const queue = owned.length ? owned : await findMusic(music);
    if (queue.length) {
      return reply(req, { ok: true, message: `Reproduciendo ${queue[0].title} de ${queue[0].artist}.`, media: { track: queue[0], queue }, context_interpretation: context, attachments_consumed: true });
    }
  }
  const parts: any[] = [{ type: "text", text }];
  const cleanup: string[] = [];
  for (const id of Array.isArray(payload.attachments) ? payload.attachments.slice(0, 10) : []) {
    const attachment = await readAttachment(String(id));
    if (attachment) { parts.push(attachment.content); cleanup.push(attachment.path); }
  }
  if (requested.includes("weather")) {
    const preferences = user ? await mobileSettings(req, token, user) : null;
    const storedLocation = String(preferences?.assistant?.preferred_location || "").trim();
    const knownLocation = [...context.entities, ...history.flatMap(item => contextEntities(String(item.body || item.content || "")))].reverse().find(item => item.entity_type === "location")
      || (storedLocation ? { name: storedLocation, entity_type: "location" } : null);
    if (!knownLocation) {
      return reply(req, {
        ok: true,
        message: requested.includes("daily_brief")
          ? "Puedo preparar el resumen del día y añadir el clima. Solo necesito tu ciudad para darte datos reales, no una ubicación inventada."
          : "¿De qué ciudad quieres el clima? Necesito la ubicación para darte datos reales.",
        context_interpretation: { ...context, context_sources: [...new Set([...context.context_sources, "capability_composition"])], planned_capabilities: requested },
        engine: "archeon-capability-planner", intelligence: payload.intelligence || "medium", attachments_consumed: true,
      });
    }
    const weather = await currentWeatherAnswer(knownLocation.name);
    if (!weather) return reply(req, { ok: true, message: `No pude verificar el clima de ${knownLocation.name} en este momento. Inténtalo de nuevo en unos minutos.`, context_interpretation: context, engine: "archeon-current-weather", attachments_consumed: true });
    const daily = requested.includes("daily_brief") ? await currentNewsAnswer("noticias de hoy") : null;
    return reply(req, {
      ok: true, message: daily ? `${weather}\n\n${daily.message}` : weather,
      news_sources: daily?.sources || [],
      context_interpretation: { ...context, context_sources: [...new Set([...context.context_sources, "capability_composition"])], planned_capabilities: requested },
      engine: "archeon-capability-planner", intelligence: payload.intelligence || "medium", attachments_consumed: true,
    });
  }
  const currentNews = context.intent.name === "news_search" ? await currentNewsAnswer(effectiveText) : null;
  if (currentNews) {
    await Promise.allSettled(cleanup.map(path => supabase(`/storage/v1/object/archeon-cloud/${path}`, { method: "DELETE" }, "", true)));
    return reply(req, { ok: true, message: currentNews.message, news_sources: currentNews.sources, context_interpretation: context, engine: "archeon-current-news", intelligence: payload.intelligence || "medium", attachments_consumed: true });
  }
  const temporal = temporalResolution(effectiveText, history.filter(item => item?.role === "user").map(item => String(item.body || item.content || "")));
  if (context.intent.name === "date_time_query" && temporal) {
    await Promise.allSettled(cleanup.map(path => supabase(`/storage/v1/object/archeon-cloud/${path}`, { method: "DELETE" }, "", true)));
    return reply(req, { ok: true, message: currentDateTimeAnswer(effectiveText, payload, temporal), context_interpretation: context, engine: "archeon-local-time", intelligence: payload.intelligence || "medium", attachments_consumed: true });
  }
  const followupSubject = contextualResearchSubject(effectiveText, history);
  const researched = await researchedAnswer(followupSubject ? `investiga ${followupSubject}` : effectiveText, Boolean(followupSubject));
  const answer = researched?.message || nativeArchi(effectiveText, parts.slice(1), history, context);
  await Promise.allSettled(cleanup.map(path => supabase(`/storage/v1/object/archeon-cloud/${path}`, { method: "DELETE" }, "", true)));
  return reply(req, {
    ok: true, message: answer, context_interpretation: context,
    expandable_details: researched?.details ? { body: researched.details, source_label: researched.source_label, source_url: researched.source_url } : null,
    engine: researched ? "archeon-native-research" : "archeon-native",
    intelligence: payload.intelligence || "medium", attachments_consumed: true,
  });
}

async function cloudUpload(req: Request, token: string): Promise<Response> {
  const user = await userFor(token);
  if (!user) return reply(req, { ok: false, error: "account_session_required" }, 401);
  await ensureMobileDevice(req, token, String(user.id));
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
      if (!user) return reply(req, { ok: false, error: "session_required" }, 401);
      await ensureMobileDevice(req, token, String(user.id));
      return reply(req, { ok: true, session: publicSession(user) });
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
