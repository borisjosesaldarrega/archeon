(() => {
  "use strict";
  const runtime = window.ARCHEON_RUNTIME;
  if (!runtime?.token) return;
  if (runtime.resumeSession && !sessionStorage.getItem("archeon_session")) sessionStorage.setItem("archeon_session", runtime.resumeSession);
  const baseHeaders = {"Content-Type":"application/json","X-Archeon-Token":runtime.token};
  let messages = {};
  let session = null;
  let events = null;
  let settingsCache = null;

  const t = (key) => messages[key] || key;
  const authMessage = document.getElementById("auth-message");
  const sessionToken = () => sessionStorage.getItem("archeon_session") || "";
  const headers = () => ({...baseHeaders,"X-Archeon-Session":sessionToken()});

  async function loadLocale(locale) {
    const readCatalog = async (path) => { const response=await fetch(path); return response.ok ? response.json() : {}; };
    const [base, selected, voiceBase, voiceSelected] = await Promise.all([
      readCatalog("/locales/es.json"), readCatalog(`/locales/${locale}.json`),
      readCatalog("/locales/voice-es.json"), readCatalog(`/locales/voice-${locale}.json`),
    ]);
    messages = {...base, ...voiceBase, ...selected, ...voiceSelected};
    document.documentElement.lang = locale;
    document.documentElement.dir = locale === "ar" ? "rtl" : "ltr";
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
    document.getElementById("account-open").hidden = value.mode === "guest";
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
    try { const value = await auth("guest"); sessionStorage.setItem("archeon_session", value.session_token); enterApplication(value.session); await loadCurrentSettings(document.documentElement.lang||"es"); } catch (error) { authError(error); }
  });
  document.getElementById("auth-login").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const value = await auth("login", {email:document.getElementById("login-email").value,password:document.getElementById("login-password").value});
      sessionStorage.setItem("archeon_session", value.session_token); enterApplication(value.session); await loadCurrentSettings(document.documentElement.lang||"es");
    } catch (error) { authError(error); }
  });
  document.getElementById("auth-register").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const value = await auth("register", {display_name:document.getElementById("register-name").value,email:document.getElementById("register-email").value,password:document.getElementById("register-password").value});
      if (value.session.pending_confirmation) {
        showAuthView("login"); authMessage.textContent=t("auth.confirmation_sent"); return;
      }
      sessionStorage.setItem("archeon_session", value.session_token); enterApplication(value.session); await loadCurrentSettings(document.documentElement.lang||"es");
    } catch (error) { authError(error); }
  });
  document.getElementById("auth-forgot").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await auth("forgot-password", {email:document.getElementById("forgot-email").value});
      showAuthView("login"); authMessage.textContent=t("auth.recovery_sent");
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
  const album = document.getElementById("track-album");
  function setState(state, detailKey) {
    ["idle","listening","transcribing","thinking","executing","speaking","music","paused","error"].forEach((name) => document.body.classList.remove(`state-${name}`));
    document.body.classList.add(`state-${state}`);
    stateElement.textContent = state === "idle" ? (settingsCache?.assistant?.wake_name || t("state.idle")) : t(`state.${state}`);
    if (detailKey) detailElement.textContent = t(detailKey);
  }
  const postAction = async (action, payload = {}) => (await fetch("/api/action", {method:"POST",headers:headers(),body:JSON.stringify({action,...payload})})).json();
  async function syncNow() {
    const status=document.getElementById("settings-sync-status");
    status.textContent="Sincronizando…";
    const result=await postAction("sync.now");
    if(result.ok&&result.settings)applySettings(result.settings);
    status.textContent=result.ok?(result.queued?"Sin conexión: cambios guardados para el próximo intento":"Sincronización completada"):(result.error||"sync_error");
    return result;
  }
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
  document.getElementById("voice-settings-preview").addEventListener("click",async()=>{
    const result=await postAction("voice.preview",{text:t("voice.settings.preview_text")});
    if(!result.ok)document.getElementById("voice-model-detail").textContent=result.error||"voice_preview_error";
  });
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
  const settingsDialog = document.getElementById("settings-dialog");
  const accountDialog = document.getElementById("account-dialog");
  const accountMessage = document.getElementById("account-message");
  let pendingFactorId="";
  document.getElementById("account-open").addEventListener("click",async()=>{
    document.getElementById("sidebar").classList.remove("open");
    document.getElementById("account-current-email").textContent=session?.identity.email||"";
    accountMessage.textContent=""; accountDialog.showModal();
    try{const value=await auth("mfa-status");document.getElementById("mfa-status").textContent=value.factors.some(f=>f.status==="verified")?t("account.mfa_enabled"):t("account.mfa_disabled");}catch(_){}
  });
  document.getElementById("account-close").addEventListener("click",()=>accountDialog.close());
  async function updateAccount(operation,payload,successKey){
    accountMessage.textContent="";
    try{
      const value=await auth(operation,payload);
      if(value.session){sessionStorage.setItem("archeon_session",value.session_token);session=value.session;document.getElementById("profile-email").textContent=session.identity.email;}
      accountMessage.textContent=t(successKey);
    }catch(error){authError(error);accountMessage.textContent=authMessage.textContent;authMessage.textContent="";}
  }
  document.getElementById("account-change-email").addEventListener("click",()=>updateAccount("change-email",{email:document.getElementById("account-email").value},"account.email_sent"));
  document.getElementById("account-send-nonce").addEventListener("click",()=>updateAccount("reauthenticate",{},"account.code_sent"));
  document.getElementById("account-change-password").addEventListener("click",()=>updateAccount("change-password",{password:document.getElementById("account-password").value,nonce:document.getElementById("account-nonce").value},"account.password_changed"));
  document.getElementById("account-logout-others").addEventListener("click",()=>updateAccount("logout-others",{},"account.others_closed"));
  document.getElementById("mfa-enroll").addEventListener("click",async()=>{
    try{const value=await auth("mfa-enroll",{friendly_name:"ARCHEON Windows"});pendingFactorId=value.factor.id;const totp=value.factor.totp||{};const qr=document.getElementById("mfa-qr");qr.src=totp.qr_code||"";qr.hidden=!qr.src;document.getElementById("mfa-secret").textContent=totp.secret||"";document.querySelector(".mfa-verify").hidden=false;}catch(error){authError(error);accountMessage.textContent=authMessage.textContent;authMessage.textContent="";}
  });
  document.getElementById("mfa-verify").addEventListener("click",async()=>{
    try{const value=await auth("mfa-verify",{factor_id:pendingFactorId,code:document.getElementById("mfa-code").value});sessionStorage.setItem("archeon_session",value.session_token);session=value.session;document.getElementById("mfa-status").textContent=t("account.mfa_enabled");document.querySelector(".mfa-verify").hidden=true;document.getElementById("mfa-qr").hidden=true;document.getElementById("mfa-secret").textContent="";}catch(error){authError(error);accountMessage.textContent=authMessage.textContent;authMessage.textContent="";}
  });
  document.getElementById("account-delete").addEventListener("click",async()=>{
    try{await auth("delete-account",{confirmation:document.getElementById("account-delete-confirm").value});events?.close();sessionStorage.removeItem("archeon_session");location.reload();}catch(error){authError(error);accountMessage.textContent=authMessage.textContent;authMessage.textContent="";}
  });
  const languageChoices = ["es","en","pt","fr","de","it","zh","ja","ko","ru","ar","hi"];
  function applySettings(settings) {
    settingsCache = settings;
    const theme = settings.appearance?.theme || "dark";
    const resolved = theme === "system" && matchMedia("(prefers-color-scheme: light)").matches ? "light" : theme;
    document.body.classList.toggle("theme-light", resolved === "light");
    document.body.classList.toggle("reduce-motion", Boolean(settings.appearance?.reduced_motion));
    document.body.classList.toggle("high-contrast", Boolean(settings.appearance?.high_contrast));
    document.body.dataset.performance = settings.performance?.profile || "eco";
    document.body.dataset.idleAnimation = String(Boolean(settings.performance?.idle_animation));
    document.documentElement.style.fontSize=`${settings.appearance?.text_scale||100}%`;
    document.body.style.zoom=String((settings.appearance?.ui_scale||100)/100);
    const curtain=document.querySelector(".background-curtain");
    const video=document.getElementById("background-video");
    const appearance=settings.appearance||{};
    const resource=`/personalization/background?token=${encodeURIComponent(runtime.token)}&v=${settings.sync?.version||0}`;
    curtain.style.filter=`blur(${appearance.background_blur||0}px)`;
    curtain.style.opacity=String((appearance.background_opacity??100)/100);
    curtain.style.backgroundSize=appearance.background_fit||"cover";
    if(appearance.background_type==="image"&&appearance.background_path){video.pause();video.removeAttribute("src");video.hidden=true;curtain.style.backgroundImage=`linear-gradient(rgba(0,0,0,.22),rgba(0,0,0,.36)),url("${resource}")`;}
    else if(appearance.background_type==="video"&&appearance.background_path){curtain.style.backgroundImage="linear-gradient(rgba(0,0,0,.2),rgba(0,0,0,.34))";video.style.objectFit=appearance.background_fit||"cover";if(video.src!==new URL(resource,location.href).href)video.src=resource;video.hidden=false;if((settings.performance?.profile||"eco")==="eco"){const freeze=()=>{try{video.currentTime=.05;}catch(_){}video.pause();};video.readyState>=2?freeze():video.addEventListener("loadeddata",freeze,{once:true});}else video.play().catch(()=>{});}
    else{video.pause();video.removeAttribute("src");video.hidden=true;curtain.style.backgroundImage="";}
    const logo=appearance.logo_path?`/personalization/logo?token=${encodeURIComponent(runtime.token)}&v=${settings.sync?.version||0}`:"/logo_asitente.png";
    document.querySelectorAll("#core-art,.auth-brand img").forEach(node=>{if(!node.closest(".state-music"))node.src=logo;});
    const clock=document.querySelector(".clock-widget");clock.hidden=settings.clock?.visible===false;document.getElementById("clock-date").hidden=settings.clock?.show_date===false;
    if (document.body.classList.contains("state-idle")) stateElement.textContent = settings.assistant?.wake_name || "Archeon";
  }
  document.getElementById("settings-open").addEventListener("click", async () => {
    document.getElementById("sidebar").classList.remove("open");
    const result = await postAction("settings.get");
    if (!result.ok) return;
    applySettings(result.settings);
    const interfaceSelect = document.getElementById("settings-interface-language");
    const conversationSelect = document.getElementById("settings-conversation-language");
    fillSelect(interfaceSelect, languageChoices.map((id)=>({id,name:id.toUpperCase()})), result.settings.language.interface, false);
    fillSelect(conversationSelect, [{id:"auto",name:t("settings.auto")},...languageChoices.map((id)=>({id,name:id.toUpperCase()}))], result.settings.language.conversation, false);
    document.getElementById("settings-theme").value=result.settings.appearance.theme;
    document.getElementById("settings-wake-name").value=result.settings.assistant.wake_name;
    document.getElementById("settings-context-language").checked=result.settings.assistant.context_language_enabled;
    document.getElementById("settings-wake-enabled").checked=result.settings.assistant.wake_word_enabled;
    document.getElementById("settings-background-type").value=result.settings.appearance.background_type;
    document.getElementById("settings-background-fit").value=result.settings.appearance.background_fit;
    document.getElementById("settings-background-blur").value=result.settings.appearance.background_blur;
    document.getElementById("settings-background-opacity").value=result.settings.appearance.background_opacity;
    document.getElementById("settings-ui-scale").value=result.settings.appearance.ui_scale;
    document.getElementById("settings-text-scale").value=result.settings.appearance.text_scale;
    document.getElementById("settings-reduced-motion").checked=result.settings.appearance.reduced_motion;
    document.getElementById("settings-high-contrast").checked=result.settings.appearance.high_contrast;
    document.getElementById("settings-clock-visible").checked=result.settings.clock.visible;
    document.getElementById("settings-clock-24h").checked=result.settings.clock.use_24_hour;
    document.getElementById("settings-clock-seconds").checked=result.settings.clock.show_seconds;
    document.getElementById("settings-clock-date").checked=result.settings.clock.show_date;
    document.getElementById("settings-startup-sound").checked=result.settings.startup.startup_sound;
    document.getElementById("settings-cloud").checked=result.settings.privacy.cloud_processing_allowed;
    document.getElementById("settings-sync-enabled").checked=result.settings.sync.enabled;
    document.getElementById("settings-message").textContent="";
    settingsDialog.showModal();
  });
  document.getElementById("settings-close").addEventListener("click",()=>settingsDialog.close());
  document.getElementById("settings-save").addEventListener("click",async()=>{
    const interfaceLanguage=document.getElementById("settings-interface-language").value;
    const result=await postAction("settings.update",{changes:{
      language:{interface:interfaceLanguage,conversation:document.getElementById("settings-conversation-language").value},
      appearance:{theme:document.getElementById("settings-theme").value,background_type:document.getElementById("settings-background-type").value,background_fit:document.getElementById("settings-background-fit").value,background_blur:Number(document.getElementById("settings-background-blur").value),background_opacity:Number(document.getElementById("settings-background-opacity").value),reduced_motion:document.getElementById("settings-reduced-motion").checked,high_contrast:document.getElementById("settings-high-contrast").checked,ui_scale:Number(document.getElementById("settings-ui-scale").value),text_scale:Number(document.getElementById("settings-text-scale").value)},
      assistant:{wake_name:document.getElementById("settings-wake-name").value,wake_word_enabled:document.getElementById("settings-wake-enabled").checked,activation_mode:document.getElementById("settings-wake-enabled").checked?"wake_word":"push_to_talk",context_language_enabled:document.getElementById("settings-context-language").checked},
      startup:{startup_sound:document.getElementById("settings-startup-sound").checked},
      clock:{visible:document.getElementById("settings-clock-visible").checked,use_24_hour:document.getElementById("settings-clock-24h").checked,show_seconds:document.getElementById("settings-clock-seconds").checked,show_date:document.getElementById("settings-clock-date").checked},
      privacy:{cloud_processing_allowed:document.getElementById("settings-cloud").checked},
      sync:{enabled:document.getElementById("settings-sync-enabled").checked,settings:true,personalization:true},
    }});
    const message=document.getElementById("settings-message");
    if(!result.ok){message.textContent=result.error||"settings_error";return;}
    applySettings(result.settings); await loadLocale(interfaceLanguage); document.getElementById("language-select").value=interfaceLanguage;
    if(result.settings.sync.enabled&&session?.mode==="account")await syncNow();
    message.textContent=t("settings.saved"); setTimeout(()=>settingsDialog.close(),450);
  });
  document.getElementById("settings-sync-now").addEventListener("click",syncNow);
  [["settings-choose-image","image"],["settings-choose-video","video"],["settings-choose-logo","logo"]].forEach(([id,kind])=>document.getElementById(id).addEventListener("click",async()=>{const result=await postAction("appearance.choose",{kind});if(result.ok&&!result.cancelled)applySettings(result.settings);}));
  document.getElementById("settings-clear-visuals").addEventListener("click",async()=>{const result=await postAction("appearance.clear");if(result.ok)applySettings(result.settings);});
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
  const launcherDialog=document.getElementById("launcher-dialog"),launcherList=document.getElementById("launcher-list");let launcherItems=[],launcherCategory="all";
  function renderLauncher(){const query=(document.getElementById("launcher-search").value||"").toLocaleLowerCase();launcherList.replaceChildren();launcherItems.filter(item=>item.name.toLocaleLowerCase().includes(query)).forEach(item=>{const row=document.createElement("div");row.className="launcher-item";const copy=document.createElement("div"),name=document.createElement("strong"),meta=document.createElement("small"),favorite=document.createElement("button"),alias=document.createElement("button"),open=document.createElement("button");name.textContent=item.name;meta.textContent=`${item.kind} · ${item.source}`;copy.append(name,meta);favorite.textContent=item.favorite?"★":"☆";favorite.title="Favorito";favorite.addEventListener("click",async()=>{await postAction("launcher.favorite",{id:item.id,enabled:!item.favorite});item.favorite=!item.favorite;renderLauncher();});alias.textContent="Alias";alias.addEventListener("click",async()=>{const value=prompt(`Alias de voz para ${item.name}`,item.name);if(value)await postAction("launcher.alias",{id:item.id,alias:value});});open.textContent="Abrir";open.addEventListener("click",async()=>{const result=await postAction("launcher.open",{id:item.id});document.getElementById("launcher-message").textContent=result.ok?`Abriendo ${item.name}`:(result.error||"launch_failed");});row.append(copy,favorite,alias,open);launcherList.append(row);});}
  async function loadLauncher(category="all",force=false){launcherCategory=category;document.getElementById("launcher-message").textContent="Detectando fuentes conocidas…";const result=await postAction("launcher.list",{category,force});launcherItems=result.items||[];document.getElementById("launcher-message").textContent=`${launcherItems.length} elementos`;renderLauncher();}
  document.getElementById("launcher-open").addEventListener("click",()=>{document.getElementById("sidebar").classList.remove("open");launcherDialog.showModal();loadLauncher();});
  document.getElementById("launcher-close").addEventListener("click",()=>launcherDialog.close());document.getElementById("launcher-search").addEventListener("input",renderLauncher);document.querySelectorAll("[data-launcher-category]").forEach(button=>button.addEventListener("click",()=>loadLauncher(button.dataset.launcherCategory)));
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
    events.addEventListener("wake.detected",()=>setState("listening","state.listening_detail"));
    events.addEventListener("music.started",(message)=>{const payload=JSON.parse(message.data).payload||{};art.classList.add("cover-changing");setTimeout(()=>{art.src=payload.artwork_url?`${payload.artwork_url}?token=${encodeURIComponent(runtime.token)}`:"/logo_asitente.png";art.classList.remove("cover-changing");},120);title.textContent=payload.title||t("music.demo");artist.textContent=payload.artist||t("music.local");album.textContent=payload.album||"";document.getElementById("music-seek").max=payload.duration_ms||1;document.getElementById("music-seek").value=0;musicPanel.classList.add("active");musicPanel.setAttribute("aria-hidden","false");setState("music","state.music_detail");});
    events.addEventListener("music.paused",()=>setState("paused","state.paused_detail"));
    events.addEventListener("music.resumed",()=>setState("music","state.music_detail"));
    events.addEventListener("music.seeked",(message)=>{const payload=JSON.parse(message.data).payload||{};document.getElementById("music-seek").value=payload.position_ms||0;});
    events.addEventListener("music.stopped",()=>{art.src="/logo_asitente.png";musicPanel.classList.remove("active");musicPanel.setAttribute("aria-hidden","true");title.textContent=t("music.none");artist.textContent="";album.textContent="";setState("idle","state.ready");});
  }

  function updateClock(){const now=new Date(),clock=settingsCache?.clock||{};document.getElementById("clock-time").textContent=now.toLocaleTimeString(document.documentElement.lang,{hour:"2-digit",minute:"2-digit",second:clock.show_seconds?"2-digit":undefined,hour12:clock.use_24_hour?false:undefined});document.getElementById("clock-date").textContent=now.toLocaleDateString(document.documentElement.lang,{weekday:"long",day:"numeric",month:"long"});const unit=clock.show_seconds?1000:60000;setTimeout(updateClock,unit-(Date.now()%unit));}
  document.getElementById("language-select").addEventListener("change",(event)=>loadLocale(event.target.value));
  document.addEventListener("visibilitychange",()=>{
    const video=document.getElementById("background-video");
    document.body.classList.toggle("ui-hidden",document.hidden);
    if(document.hidden)video.pause();
    else if(!video.hidden&&settingsCache?.appearance?.background_type==="video"&&(settingsCache.performance?.profile||"eco")!=="eco")video.play().catch(()=>{});
  });

  async function loadCurrentSettings(locale) {
    let current=await postAction("settings.get");
    if(!current.ok)return;
    if(current.settings.sync?.enabled&&session?.mode==="account"){
      const synced=await postAction("sync.now");
      if(synced.ok&&synced.settings)current={ok:true,settings:synced.settings};
    }
    applySettings(current.settings);
    if(current.settings.language.interface!==locale){
      document.getElementById("language-select").value=current.settings.language.interface;
      await loadLocale(current.settings.language.interface);
    }
  }

  (async()=>{
    const locale=localStorage.getItem("archeon_locale")||"es";
    document.getElementById("language-select").value=locale;
    await loadLocale(locale); updateClock();
    if(!sessionToken()) {
      try {
        const restored=await auth("restore");
        sessionStorage.setItem("archeon_session",restored.session_token);
        enterApplication(restored.session);
        await loadCurrentSettings(locale);
      } catch(_) { /* Offline and first-run both keep the access screen usable. */ }
      return;
    }
    try {
      const response=await fetch("/api/session",{headers:headers()});
      const value=await response.json();
      if(!value.ok){sessionStorage.removeItem("archeon_session");return;}
      enterApplication(value.session);
      await loadCurrentSettings(locale);
    } catch(_){sessionStorage.removeItem("archeon_session");}
  })();
})();
