(() => {
  "use strict";
  const runtime = window.ARCHEON_RUNTIME;
  if (!runtime?.token) return;
  const baseHeaders = {"Content-Type":"application/json","X-Archeon-Token":runtime.token};
  let messages = {};
  let session = null;

  const t = (key) => messages[key] || key;
  const authMessage = document.getElementById("auth-message");
  const sessionToken = () => sessionStorage.getItem("archeon_session") || "";
  const headers = () => ({...baseHeaders,"X-Archeon-Session":sessionToken()});

  async function loadLocale(locale) {
    const response = await fetch(`/locales/${locale}.json`);
    messages = await response.json();
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
  const postAction = async (action) => (await fetch("/api/action", {method:"POST",headers:headers(),body:JSON.stringify({action})})).json();
  document.getElementById("ghost-button").addEventListener("click", () => postAction("window.ghost"));
  document.getElementById("menu-button").addEventListener("click", () => document.getElementById("sidebar").classList.add("open"));
  document.getElementById("close-menu").addEventListener("click", () => document.getElementById("sidebar").classList.remove("open"));

  const audio = document.getElementById("music-audio");
  document.getElementById("music-play").addEventListener("click", async () => { await audio.play(); await postAction("music.started"); });
  document.getElementById("music-pause").addEventListener("click", async () => { audio.pause(); await postAction("music.paused"); });
  document.getElementById("music-stop").addEventListener("click", async () => { audio.pause(); audio.currentTime=0; await postAction("music.stopped"); });
  audio.addEventListener("ended", () => postAction("music.stopped"));

  document.getElementById("command-form").addEventListener("submit", async (event) => {
    event.preventDefault(); const input=document.getElementById("command-input"); const result=document.getElementById("result"); const text=input.value.trim(); if(!text)return;
    input.disabled=true; setState("executing","state.executing_detail");
    try { const response=await fetch("/api/command",{method:"POST",headers:headers(),body:JSON.stringify({text})}); const value=await response.json(); result.textContent=value.ok?`${value.message}\n${JSON.stringify(value.data,null,2)}`:(value.message||value.error); }
    catch(error){result.textContent=error.message;setState("error","state.error_detail");}
    finally{input.disabled=false;input.focus();setState("idle","state.ready");}
  });

  const events = new EventSource(`/events?token=${encodeURIComponent(runtime.token)}`);
  const eventStates = {"speech.listening.started":"listening","speech.transcription.started":"transcribing","assistant.processing.started":"thinking","tool.execution.started":"executing","assistant.speaking.started":"speaking"};
  Object.entries(eventStates).forEach(([eventName,state]) => events.addEventListener(eventName,()=>setState(state,`state.${state}_detail`)));
  events.addEventListener("music.started",(message)=>{const payload=JSON.parse(message.data).payload||{};if(payload.artwork_url)art.src=payload.artwork_url;title.textContent=payload.title||t("music.demo");artist.textContent=payload.artist||t("music.local");musicPanel.classList.add("active");setState("music","state.music_detail");});
  events.addEventListener("music.paused",()=>setState("paused","state.paused_detail"));
  events.addEventListener("music.resumed",()=>setState("music","state.music_detail"));
  events.addEventListener("music.stopped",()=>{art.src="/logo_asitente.png";musicPanel.classList.remove("active");title.textContent=t("music.none");artist.textContent="";setState("idle","state.ready");});

  function updateClock(){const now=new Date();document.getElementById("clock-time").textContent=now.toLocaleTimeString(document.documentElement.lang,{hour:"2-digit",minute:"2-digit"});document.getElementById("clock-date").textContent=now.toLocaleDateString(document.documentElement.lang,{weekday:"long",day:"numeric",month:"long"});setTimeout(updateClock,60000-(Date.now()%60000));}
  document.getElementById("language-select").addEventListener("change",(event)=>loadLocale(event.target.value));

  (async()=>{const locale=localStorage.getItem("archeon_locale")||"es";document.getElementById("language-select").value=locale;await loadLocale(locale);updateClock();const token=sessionToken();if(token){try{const response=await fetch("/api/session",{headers:headers()});const value=await response.json();if(value.ok)enterApplication(value.session);else sessionStorage.removeItem("archeon_session");}catch(_){sessionStorage.removeItem("archeon_session");}}})();
})();
