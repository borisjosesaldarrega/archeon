(() => {
  "use strict";
  const runtime = window.ARCHEON_RUNTIME;
  if (!runtime?.token) return;
  if (runtime.resumeSession && !sessionStorage.getItem("archeon_session")) sessionStorage.setItem("archeon_session", runtime.resumeSession);
  const baseHeaders = {"Content-Type":"application/json","X-Archeon-Token":runtime.token};
  let messages = {};
  let session = null;
  let events = null;

  const t = (key) => messages[key] || key;
  const authMessage = document.getElementById("auth-message");
  const sessionToken = () => sessionStorage.getItem("archeon_session") || "";
  const headers = () => ({...baseHeaders,"X-Archeon-Session":sessionToken()});

  async function loadLocale(locale) {
    const [response, voiceResponse] = await Promise.all([
      fetch(`/locales/${locale}.json`),
      fetch(`/locales/voice-${locale}.json`),
    ]);
    messages = {...await response.json(), ...await voiceResponse.json()};
    document.documentElement.lang = locale;
    document.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = t(node.dataset.i18n); });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => { node.placeholder = t(node.dataset.i18nPlaceholder); });
    document.querySelectorAll("[data-i18n-aria]").forEach((node) => { node.setAttribute("aria-label", t(node.dataset.i18nAria)); });
    localStorage.setItem("archeon_locale", locale);
  }

  function showAuthView(name) {
    document.querySelectorAll(".auth-view").forEach((node) => node.classList.remove("active"));
    document.getElementById(`auth-${name}`)?.classList.add("active");
    authMessage.textContent = "";
  }

  async function auth(operation, payload = {}) {
    const response = await fetch(`/api/auth/${operation}`, {method:"POST",headers:headers(),body:JSON.stringify(payload)});
    const value = await response.json();
    if (!value.ok) throw new Error(value.error || "auth_error");
    return value;
  }

  function enterApplication(value) {
    session = value;
    document.getElementById("auth-shell").hidden = true;
    document.getElementById("app-shell").hidden = false;
    document.body.classList.remove("auth-active");
    const identity = value.identity;
    document.getElementById("profile-name").textContent = identity.display_name;
    document.getElementById("profile-email").textContent = identity.email || t("guest.local");
    document.getElementById("session-badge").textContent = value.mode === "guest" ? t("session.guest") : t("session.account");
    connectEvents();
    configureVoice();
  }

  async function configureVoice() {
    const button = document.getElementById("voice-button");
    try {
      const response = await fetch("/api/health", {headers:baseHeaders});
      const value = await response.json();
      button.disabled = !value.voice?.available;
      button.lastElementChild.textContent = value.voice?.available ? t("voice.ready") : t("voice.experimental");
    } catch (_) { button.disabled = true; }
  }

  function authError(error) {
    authMessage.textContent = messages[`error.${error.message}`] || messages["error.auth_error"];
  }

  document.querySelectorAll("[data-auth-view]").forEach((button) => button.addEventListener("click", () => showAuthView(button.dataset.authView)));
  document.getElementById("guest-button").addEventListener("click", async () => {
    try { const value = await auth("guest"); sessionStorage.setItem("archeon_session", value.session_token); enterApplication(value.session); } catch (error) { authError(error); }
  });
  document.getElementById("auth-login").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const value = await auth("login", {email:document.getElementById("login-email").value,password:document.getElementById("login-password").value});
      sessionStorage.setItem("archeon_session", value.session_token); enterApplication(value.session);
    } catch (error) { authError(error); }
  });
  document.getElementById("auth-register").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const value = await auth("register", {display_name:document.getElementById("register-name").value,email:document.getElementById("register-email").value,password:document.getElementById("register-password").value});
      sessionStorage.setItem("archeon_session", value.session_token); enterApplication(value.session);
    } catch (error) { authError(error); }
  });
  document.getElementById("logout-button").addEventListener("click", async () => {
    try { await auth("logout"); } catch (_) { /* local session is cleared regardless */ }
    events?.close();
    sessionStorage.removeItem("archeon_session"); location.reload();
  });

  const stateElement = document.getElementById("assistant-state");
  const detailElement = document.getElementById("assistant-detail");
  const art = document.getElementById("core-art");
  const musicPanel = document.getElementById("music-panel");
  const title = document.getElementById("track-title");
  const artist = document.getElementById("track-artist");
  function setState(state, detailKey) {
    ["idle","listening","transcribing","thinking","executing","speaking","music","paused","error"].forEach((name) => document.body.classList.remove(`state-${name}`));
    document.body.classList.add(`state-${state}`);
    stateElement.textContent = t(`state.${state}`);
    if (detailKey) detailElement.textContent = t(detailKey);
  }
  const postAction = async (action, payload = {}) => (await fetch("/api/action", {method:"POST",headers:headers(),body:JSON.stringify({action,...payload})})).json();
  const voiceDialog = document.getElementById("voice-settings");
  function fillSelect(select, items, selected, includeDefault = true) {
    select.replaceChildren();
    if (includeDefault) select.add(new Option(t("voice.settings.default"), ""));
    items.forEach((item) => select.add(new Option(item.name, String(item.id))));
    select.value = selected || "";
  }
  document.getElementById("voice-settings-open").addEventListener("click", async () => {
    document.getElementById("sidebar").classList.remove("open");
    const result = await postAction("voice.catalog");
    if (!result.ok) { document.getElementById("result").textContent=result.error||"voice_catalog_error"; return; }
    const voice = result.voice, config = voice.configuration;
    fillSelect(document.getElementById("voice-profile"), voice.profiles.map((id)=>({id,name:id.toUpperCase()})), config.profile, false);
    fillSelect(document.getElementById("voice-input"), voice.input_devices.map((device)=>({id:device.index,name:device.name})), config.input_device_id);
    fillSelect(document.getElementById("voice-tts"), voice.tts_voices, config.tts_voice_id);
    fillSelect(document.getElementById("voice-output"), voice.tts_outputs, config.tts_output_device_id);
    document.getElementById("voice-rate").value=config.tts_rate;
    document.getElementById("voice-volume").value=config.tts_volume;
    document.getElementById("voice-barge").checked=config.barge_in;
    document.getElementById("voice-model-detail").textContent=`${t("voice.settings.model")}: ${voice.status.model_id} · ${voice.status.capture}`;
    voiceDialog.showModal();
  });
  document.getElementById("voice-settings-close").addEventListener("click",()=>voiceDialog.close());
  document.getElementById("voice-settings-save").addEventListener("click",async()=>{
    const result=await postAction("voice.configure",{
      profile:document.getElementById("voice-profile").value,
      input_device_id:document.getElementById("voice-input").value,
      tts_voice_id:document.getElementById("voice-tts").value,
      tts_output_device_id:document.getElementById("voice-output").value,
      tts_rate:Number(document.getElementById("voice-rate").value),
      tts_volume:Number(document.getElementById("voice-volume").value),
      barge_in:document.getElementById("voice-barge").checked,
    });
    if(result.ok)voiceDialog.close();else document.getElementById("voice-model-detail").textContent=result.error||"voice_configuration_error";
  });
  document.getElementById("ghost-button").addEventListener("click", () => postAction("window.ghost"));
  document.getElementById("voice-button").addEventListener("click", async () => {
    const stopping = ["listening","transcribing","thinking","speaking"].some((state)=>document.body.classList.contains(`state-${state}`));
    await postAction(stopping ? "voice.stop" : "voice.listen");
  });
  document.getElementById("menu-button").addEventListener("click", () => document.getElementById("sidebar").classList.add("open"));
  document.getElementById("close-menu").addEventListener("click", () => document.getElementById("sidebar").classList.remove("open"));

  document.getElementById("music-open").addEventListener("click", async () => {
    document.getElementById("sidebar").classList.remove("open");
    const loaded = await postAction("media.choose");
    if (loaded.cancelled) return;
    if (!loaded.ok) { document.getElementById("result").textContent=loaded.error||"media_load_error"; return; }
    await postAction("media.play");
  });
  document.getElementById("music-play").addEventListener("click", () => postAction("media.play"));
  document.getElementById("music-pause").addEventListener("click", () => postAction("media.pause"));
  document.getElementById("music-stop").addEventListener("click", () => postAction("media.stop"));
  document.getElementById("music-next").addEventListener("click", () => postAction("media.next"));
  document.getElementById("music-previous").addEventListener("click", () => postAction("media.previous"));
  document.getElementById("music-seek").addEventListener("change", (event) => postAction("media.seek", {position_ms:Number(event.target.value)}));
  document.getElementById("music-volume").addEventListener("change", (event) => postAction("media.volume", {volume:Number(event.target.value)/100}));

  document.getElementById("command-form").addEventListener("submit", async (event) => {
    event.preventDefault(); const input=document.getElementById("command-input"); const result=document.getElementById("result"); const text=input.value.trim(); if(!text)return;
    input.disabled=true; setState("executing","state.executing_detail");
    try { const response=await fetch("/api/command",{method:"POST",headers:headers(),body:JSON.stringify({text})}); const value=await response.json(); result.textContent=value.ok?`${value.message}\n${JSON.stringify(value.data,null,2)}`:(value.message||value.error); }
    catch(error){result.textContent=error.message;setState("error","state.error_detail");}
    finally{input.disabled=false;input.focus();setState("idle","state.ready");}
  });

  const eventStates = {"speech.listening.started":"listening","speech.transcription.started":"transcribing","assistant.processing.started":"thinking","tool.execution.started":"executing","assistant.speaking.started":"speaking"};
  function connectEvents() {
    if (events || !sessionToken()) return;
    events = new EventSource(`/events?token=${encodeURIComponent(runtime.token)}&session=${encodeURIComponent(sessionToken())}`);
    Object.entries(eventStates).forEach(([eventName,state]) => events.addEventListener(eventName,()=>setState(state,`state.${state}_detail`)));
    events.addEventListener("speech.audio.level",(message)=>{const level=JSON.parse(message.data).payload?.level||0;document.querySelectorAll(".amplitude i").forEach((bar,index)=>{bar.style.height=`${5+level*(10+(index%3)*8)}px`;});});
    events.addEventListener("speech.transcription.completed",(message)=>{const text=JSON.parse(message.data).payload?.text||"";document.getElementById("result").textContent=`${t("voice.heard")}: “${text}”`;});
    events.addEventListener("assistant.processing.completed",(message)=>{const payload=JSON.parse(message.data).payload||{};document.getElementById("result").textContent=payload.message||"";});
    events.addEventListener("assistant.speaking.ended",()=>{if(!document.body.classList.contains("state-listening"))setState("idle","state.ready");});
    events.addEventListener("voice.cycle.completed",()=>setState("idle","state.ready"));
    events.addEventListener("voice.cycle.cancelled",()=>setState("idle","state.ready"));
    events.addEventListener("voice.cycle.error",(message)=>{const error=JSON.parse(message.data).payload?.error||"voice_error";document.getElementById("result").textContent=`${t("state.error")}: ${messages[`error.${error}`]||error}`;setState("error","state.error_detail");});
    events.addEventListener("music.started",(message)=>{const payload=JSON.parse(message.data).payload||{};art.classList.add("cover-changing");setTimeout(()=>{art.src=payload.artwork_url?`${payload.artwork_url}?token=${encodeURIComponent(runtime.token)}`:"/logo_asitente.png";art.classList.remove("cover-changing");},120);title.textContent=payload.title||t("music.demo");artist.textContent=payload.artist||t("music.local");document.getElementById("music-seek").max=payload.duration_ms||1;document.getElementById("music-seek").value=0;musicPanel.classList.add("active");setState("music","state.music_detail");});
    events.addEventListener("music.paused",()=>setState("paused","state.paused_detail"));
    events.addEventListener("music.resumed",()=>setState("music","state.music_detail"));
    events.addEventListener("music.seeked",(message)=>{const payload=JSON.parse(message.data).payload||{};document.getElementById("music-seek").value=payload.position_ms||0;});
    events.addEventListener("music.stopped",()=>{art.src="/logo_asitente.png";musicPanel.classList.remove("active");title.textContent=t("music.none");artist.textContent="";setState("idle","state.ready");});
  }

  function updateClock(){const now=new Date();document.getElementById("clock-time").textContent=now.toLocaleTimeString(document.documentElement.lang,{hour:"2-digit",minute:"2-digit"});document.getElementById("clock-date").textContent=now.toLocaleDateString(document.documentElement.lang,{weekday:"long",day:"numeric",month:"long"});setTimeout(updateClock,60000-(Date.now()%60000));}
  document.getElementById("language-select").addEventListener("change",(event)=>loadLocale(event.target.value));

  (async()=>{const locale=localStorage.getItem("archeon_locale")||"es";document.getElementById("language-select").value=locale;await loadLocale(locale);updateClock();const token=sessionToken();if(token){try{const response=await fetch("/api/session",{headers:headers()});const value=await response.json();if(value.ok)enterApplication(value.session);else sessionStorage.removeItem("archeon_session");}catch(_){sessionStorage.removeItem("archeon_session");}}})();
})();
