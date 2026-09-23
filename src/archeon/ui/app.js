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
  let settingsDraft = null;
  let settingsDirty = false;
  let activeLocale = "es";
  let desktopTourIndex = -1;
  let pendingVerificationEmail = "", pendingMfaFactor = "";
  const draftPreview={background:false,logo:false,chat:false};
  const recoveryCopy={
    es:{"auth.recover_note":"Recibirás un código de 8 dígitos si la cuenta existe.","auth.recovery_sent":"Si la cuenta existe, enviamos un código de recuperación.","auth.have_recovery_code":"Ya tengo un código","auth.reset_title":"Crea una contraseña nueva","auth.reset_note":"Introduce el código de 8 dígitos enviado a tu correo.","auth.reset_submit":"Actualizar contraseña","auth.reset_done":"Contraseña actualizada. Ya puedes iniciar sesión."},
    en:{"auth.recover_note":"You will receive an 8-digit code if the account exists.","auth.recovery_sent":"If the account exists, a recovery code was sent.","auth.have_recovery_code":"I already have a code","auth.reset_title":"Create a new password","auth.reset_note":"Enter the 8-digit code sent to your email.","auth.reset_submit":"Update password","auth.reset_done":"Password updated. You can now sign in."},
    pt:{"auth.recover_note":"Você receberá um código de 8 dígitos se a conta existir.","auth.recovery_sent":"Se a conta existir, enviamos um código de recuperação.","auth.reset_title":"Crie uma nova senha","auth.reset_note":"Digite o código de 8 dígitos enviado ao seu e-mail.","auth.reset_submit":"Atualizar senha","auth.reset_done":"Senha atualizada. Agora você pode entrar."},
    fr:{"auth.recover_note":"Vous recevrez un code à 8 chiffres si le compte existe.","auth.recovery_sent":"Si le compte existe, un code de récupération a été envoyé.","auth.reset_title":"Créez un nouveau mot de passe","auth.reset_note":"Saisissez le code à 8 chiffres envoyé par e-mail.","auth.reset_submit":"Mettre à jour le mot de passe","auth.reset_done":"Mot de passe mis à jour. Vous pouvez vous connecter."},
    de:{"auth.recover_note":"Wenn das Konto existiert, erhältst du einen 8-stelligen Code.","auth.recovery_sent":"Falls das Konto existiert, wurde ein Wiederherstellungscode gesendet.","auth.reset_title":"Neues Passwort erstellen","auth.reset_note":"Gib den 8-stelligen Code aus deiner E-Mail ein.","auth.reset_submit":"Passwort aktualisieren","auth.reset_done":"Passwort aktualisiert. Du kannst dich jetzt anmelden."},
    it:{"auth.recover_note":"Riceverai un codice di 8 cifre se l'account esiste.","auth.recovery_sent":"Se l'account esiste, è stato inviato un codice di recupero.","auth.reset_title":"Crea una nuova password","auth.reset_note":"Inserisci il codice di 8 cifre inviato via e-mail.","auth.reset_submit":"Aggiorna password","auth.reset_done":"Password aggiornata. Ora puoi accedere."},
    zh:{"auth.recover_note":"如果账户存在，你将收到 8 位验证码。","auth.recovery_sent":"如果账户存在，恢复验证码已发送。","auth.reset_title":"创建新密码","auth.reset_note":"请输入发送到邮箱的 8 位验证码。","auth.reset_submit":"更新密码","auth.reset_done":"密码已更新，现在可以登录。"},
    ja:{"auth.recover_note":"アカウントが存在する場合、8桁のコードが届きます。","auth.recovery_sent":"アカウントが存在する場合、復旧コードを送信しました。","auth.reset_title":"新しいパスワードを作成","auth.reset_note":"メールに届いた8桁のコードを入力してください。","auth.reset_submit":"パスワードを更新","auth.reset_done":"パスワードを更新しました。ログインできます。"},
    ko:{"auth.recover_note":"계정이 있으면 8자리 코드를 받게 됩니다.","auth.recovery_sent":"계정이 있으면 복구 코드를 보냈습니다.","auth.reset_title":"새 비밀번호 만들기","auth.reset_note":"이메일로 전송된 8자리 코드를 입력하세요.","auth.reset_submit":"비밀번호 업데이트","auth.reset_done":"비밀번호가 업데이트되었습니다. 이제 로그인할 수 있습니다."},
    ru:{"auth.recover_note":"Если учётная запись существует, вы получите 8-значный код.","auth.recovery_sent":"Если учётная запись существует, код восстановления отправлен.","auth.reset_title":"Создайте новый пароль","auth.reset_note":"Введите 8-значный код из письма.","auth.reset_submit":"Обновить пароль","auth.reset_done":"Пароль обновлён. Теперь можно войти."},
    ar:{"auth.recover_note":"ستتلقى رمزًا من 8 أرقام إذا كان الحساب موجودًا.","auth.recovery_sent":"إذا كان الحساب موجودًا، فقد أرسلنا رمز الاسترداد.","auth.reset_title":"إنشاء كلمة مرور جديدة","auth.reset_note":"أدخل الرمز المكون من 8 أرقام المرسل إلى بريدك الإلكتروني.","auth.reset_submit":"تحديث كلمة المرور","auth.reset_done":"تم تحديث كلمة المرور. يمكنك تسجيل الدخول الآن."},
    hi:{"auth.recover_note":"यदि खाता मौजूद है तो आपको 8 अंकों का कोड मिलेगा।","auth.recovery_sent":"यदि खाता मौजूद है तो रिकवरी कोड भेज दिया गया है।","auth.reset_title":"नया पासवर्ड बनाएँ","auth.reset_note":"ईमेल पर भेजा गया 8 अंकों का कोड दर्ज करें।","auth.reset_submit":"पासवर्ड अपडेट करें","auth.reset_done":"पासवर्ड अपडेट हो गया। अब आप साइन इन कर सकते हैं।"},
  };
  const haveRecoveryCode={es:"Ya tengo un código",en:"I already have a code",pt:"Já tenho um código",fr:"J'ai déjà un code",de:"Ich habe bereits einen Code",it:"Ho già un codice",zh:"我已有验证码",ja:"コードを持っています",ko:"이미 코드가 있습니다",ru:"У меня уже есть код",ar:"لدي رمز بالفعل",hi:"मेरे पास पहले से कोड है"};

  const brandNames={es:"ARCHEON",en:"ARCHEON",pt:"ARCHEON",fr:"ARCHEON",de:"ARCHEON",it:"ARCHEON",zh:"阿尔刻翁",ja:"アルケオン",ko:"아르케온",ru:"АРХЕОН",ar:"أركيون",hi:"आर्कियोन"};
  const brandPattern=/ARCHEON|Archeon|阿尔刻翁|アルケオン|아르케온|АРХЕОН|أركيون|आर्कियोन/g;
  const localizeBrand=(value)=>String(value).replace(brandPattern,brandNames[activeLocale]||"ARCHEON");
  const localizeStaticBrand=()=>{
    const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    let node;
    while((node=walker.nextNode())){
      const parent=node.parentElement;
      if(!parent||parent.closest("script,style,#conversation-stack,#command-stack")) continue;
      node.nodeValue=localizeBrand(node.nodeValue);
    }
    document.title=localizeBrand(document.title);
  };
  const t = (key) => localizeBrand(messages[key] || key);
  const localizeStatus=(value)=>{const key=`status.${String(value??"").toLowerCase()}`;return messages[key]?t(key):localizeBrand(String(value??"—").replaceAll("_"," "));};
  const authMessage = document.getElementById("auth-message");
  const sessionToken = () => sessionStorage.getItem("archeon_session") || "";
  const headers = () => ({...baseHeaders,"X-Archeon-Session":sessionToken()});

  function showNotice(message, level="info", persistent=false) {
    const host=document.getElementById("notifications"),notice=document.createElement("div");
    notice.className=`notice notice-${level}`; notice.textContent=message; host.replaceChildren(notice);
    if(!persistent)setTimeout(()=>notice.remove(),level==="error"?6000:4000);
  }

  const requestAttachments=[];
  const commandInput=document.getElementById("command-input");
  const attachmentPreviews=document.getElementById("attachment-previews");
  function renderAttachments(){
    attachmentPreviews.replaceChildren();
    const icons={image:"▧",code:"</>",data:"▦",presentation:"▣",archive:"▤",audio:"♪",document:"▤",text:"≡",file:"□"};
    requestAttachments.forEach(item=>{const chip=document.createElement("span"),icon=document.createElement(item.preview_url?"img":"span"),copy=document.createElement("span"),name=document.createElement("strong"),meta=document.createElement("small"),remove=document.createElement("button");chip.className="attachment-chip";chip.title=`${item.name} · ${item.content_type} · ${item.size_label||item.size}`;icon.className="attachment-icon";if(item.preview_url){icon.src=item.preview_url;icon.alt=`Vista previa de ${item.name}`;}else icon.textContent=icons[item.kind]||icons.file;copy.className="attachment-copy";name.textContent=item.name;meta.textContent=`${(item.extension||item.kind).toUpperCase()} · ${item.size_label||formatBytes(item.size)}`;copy.append(name,meta);remove.type="button";remove.textContent="×";remove.ariaLabel=`Quitar ${item.name}`;remove.addEventListener("click",async()=>{await postAction("attachment.remove",{id:item.id});if(item.preview_url)URL.revokeObjectURL(item.preview_url);requestAttachments.splice(requestAttachments.findIndex(value=>value.id===item.id),1);renderAttachments();});chip.append(icon,copy,remove);attachmentPreviews.append(chip);});
  }
  function formatBytes(bytes){const units=["B","KB","MB","GB"];let value=Number(bytes)||0,index=0;while(value>=1024&&index<units.length-1){value/=1024;index+=1;}return `${index?value.toFixed(1):Math.round(value)} ${units[index]}`;}
  function renderArtifactPreviews(items=[]){
    const host=document.getElementById("artifact-previews");host.replaceChildren();
    items.filter(item=>item.ok&&item.verified).forEach(item=>{const card=document.createElement("section"),copy=document.createElement("div"),name=document.createElement("strong"),meta=document.createElement("small"),actions=document.createElement("div");card.className="artifact-preview";name.textContent=item.path.split(/[\\/]/).pop();meta.textContent=`${String(item.format||"archivo").toUpperCase()} · verificado`;copy.append(name,meta);actions.className="artifact-preview-actions";
      const action=(label,handler)=>{const button=document.createElement("button");button.type="button";button.textContent=label;button.addEventListener("click",handler);actions.append(button);};
      action("Abrir",()=>postAction("artifact.open",{path:item.path}));action("Mostrar en carpeta",()=>postAction("artifact.show_in_folder",{path:item.path}));
      action("Otra versión",()=>{commandInput.value=`crea otra versión en ${item.format}`;commandInput.focus();});action("Editar",()=>{commandInput.value="edita ese documento: ";commandInput.focus();});action("Convertir",()=>{commandInput.value=`convierte ese documento a ${item.format==="pdf"?"Word":"PDF"}`;commandInput.focus();});card.append(copy,actions);host.append(card);
    });
  }
  async function uploadAttachment(file){
    if(requestAttachments.length>=10){showNotice("Máximo 10 archivos por solicitud.","error");return;}
    if(!file.size||file.size>512*1024*1024){showNotice(`${file.name}: tamaño no permitido.`,"error");return;}
    const response=await fetch(`/api/attachment?name=${encodeURIComponent(file.webkitRelativePath||file.name)}`,{method:"POST",headers:{"X-Archeon-Token":runtime.token,"X-Archeon-Session":sessionToken(),"Content-Type":file.type||"application/octet-stream"},body:file});
    const value=await response.json();
    if(!response.ok||!value.ok){showNotice(value.error||`No pude adjuntar ${file.name}.`,"error");return;}
    if(file.type.startsWith("image/"))value.attachment.preview_url=URL.createObjectURL(file);
    requestAttachments.push(value.attachment);renderAttachments();
  }
  async function uploadMany(files){const selected=Array.from(files).slice(0,10-requestAttachments.length);for(let offset=0;offset<selected.length;offset+=3)await Promise.all(selected.slice(offset,offset+3).map(uploadAttachment));}
  const attachmentMenu=document.getElementById("attachment-menu");
  document.getElementById("attachment-button").addEventListener("click",()=>{attachmentMenu.hidden=!attachmentMenu.hidden;});
  document.getElementById("attachment-file-open").addEventListener("click",()=>{attachmentMenu.hidden=true;document.getElementById("attachment-files").click();});
  document.getElementById("attachment-folder-open").addEventListener("click",()=>{attachmentMenu.hidden=true;document.getElementById("attachment-folder").click();});
  ["attachment-files","attachment-folder"].forEach(id=>document.getElementById(id).addEventListener("change",async event=>{await uploadMany(event.target.files);event.target.value="";}));
  document.getElementById("command-form").addEventListener("dragover",event=>{event.preventDefault();event.currentTarget.classList.add("drag-active");});
  document.getElementById("command-form").addEventListener("dragleave",event=>event.currentTarget.classList.remove("drag-active"));
  document.getElementById("command-form").addEventListener("drop",async event=>{event.preventDefault();event.currentTarget.classList.remove("drag-active");await uploadMany(event.dataTransfer.files);});
  commandInput.addEventListener("paste",async event=>{const files=Array.from(event.clipboardData?.files||[]);if(files.length){event.preventDefault();await uploadMany(files);}});
  commandInput.addEventListener("input",()=>{commandInput.style.height="auto";commandInput.style.height=`${Math.min(commandInput.scrollHeight,112)}px`;});
  commandInput.addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey&&!event.isComposing){event.preventDefault();document.getElementById("command-form").requestSubmit();}});
  const dictateButton=document.getElementById("command-dictate");
  dictateButton.addEventListener("click",async()=>{const active=dictateButton.classList.toggle("active");dictateButton.title=active?"Detener dictado":"Dictar sin enviar";const result=await postAction(active?"voice.dictation":"voice.stop");if(!result.ok){dictateButton.classList.remove("active");showNotice("No pude iniciar el dictado.","error");}});

  async function loadLocale(locale) {
    const readCatalog = async (path) => { const response=await fetch(path); return response.ok ? response.json() : {}; };
    const [base, selected, voiceBase, voiceSelected, settingsCatalog, settingsDetails] = await Promise.all([
      readCatalog("/locales/es.json"), readCatalog(`/locales/${locale}.json`),
      readCatalog("/locales/voice-es.json"), readCatalog(`/locales/voice-${locale}.json`),
      readCatalog("/locales/settings.json"),
      readCatalog("/locales/settings-details.json"),
    ]);
    activeLocale = locale;
    messages = {...base, ...voiceBase, ...selected, ...voiceSelected, ...(settingsCatalog.es||{}), ...(settingsCatalog[locale]||{}), ...(settingsDetails[locale]||{}), ...(recoveryCopy[locale]||recoveryCopy.es), "auth.have_recovery_code":haveRecoveryCode[locale]||haveRecoveryCode.es};
    document.documentElement.lang = locale;
    document.documentElement.dir = locale === "ar" ? "rtl" : "ltr";
    document.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = t(node.dataset.i18n); });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => { node.placeholder = t(node.dataset.i18nPlaceholder); });
    document.querySelectorAll("[data-i18n-aria]").forEach((node) => { node.setAttribute("aria-label", t(node.dataset.i18nAria)); });
    document.querySelectorAll("[data-i18n-value]").forEach((node) => { node.value = t(node.dataset.i18nValue); });
    localizeStaticBrand();
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

  async function requireMfa(sessionValue){if(!sessionValue?.mfa_required)return false;const status=await auth("mfa-status"),factor=(status.factors||[]).find(item=>item.status==="verified");if(!factor?.id)throw new Error("mfa_factor_unavailable");pendingMfaFactor=factor.id;showAuthGateway("mfa");setTimeout(()=>document.getElementById("login-mfa-code").focus(),0);return true;}

  function enterApplication(value) {
    session = value;
    document.getElementById("boot-shell").hidden = true;
    document.getElementById("auth-shell").hidden = true;
    document.getElementById("app-shell").hidden = false;
    document.body.classList.remove("auth-active");
    const identity = value.identity;
    document.getElementById("profile-name").textContent = identity.display_name;
    document.getElementById("profile-email").textContent = identity.email || t("guest.local");
    document.getElementById("session-badge").textContent = value.mode === "guest" ? t("session.guest") : t("session.account");
    document.getElementById("account-open").hidden = value.mode === "guest";
    document.querySelector('[data-settings-open="account"]').hidden = value.mode === "guest";
    document.getElementById("logout-button").hidden=value.mode==="guest";
    document.getElementById("guest-account-cta").hidden=value.mode!=="guest";
    document.querySelectorAll(".account-only").forEach(node=>node.hidden=value.mode==="guest");
    document.querySelectorAll(".guest-only").forEach(node=>node.hidden=value.mode!=="guest");
    connectEvents();
    configureVoice();
    setTimeout(() => openDesktopTour(), 320);
  }

  const desktopTourCopy={
    es:{welcome:"Bienvenido a ARCHEON",question:"¿Quieres iniciar un recorrido para conocer la aplicación?",start:"Sí, iniciar tour",skip:"No, quiero descubrirlo solo",next:"Siguiente",done:"Terminar",steps:[["#command-input","Escribe aquí una orden o conversa con ARCHI."],["#attachment-button","Adjunta imágenes, documentos, carpetas y otros archivos."],["#command-dictate","Dicta texto sin enviarlo automáticamente; puedes corregirlo antes."],["#orb-launcher","El orbe muestra el estado de ARCHI y abre el Launcher."],["#ghost-button","Cambia entre la interfaz completa y el modo radial."],["#menu-button","Aquí encuentras cuenta, Cloud, voz y toda la configuración."]]},
    en:{welcome:"Welcome to ARCHEON",question:"Would you like a quick tour of the application?",start:"Yes, start tour",skip:"No, I’ll explore",next:"Next",done:"Finish",steps:[["#command-input","Type a command or talk with ARCHI here."],["#attachment-button","Attach images, documents, folders, and other files."],["#command-dictate","Dictate without sending automatically, then edit the text."],["#orb-launcher","The orb shows ARCHI’s state and opens the Launcher."],["#ghost-button","Switch between the full interface and radial mode."],["#menu-button","Account, Cloud, voice, and all settings are here."]]}
  };
  function desktopTourLanguage(){return desktopTourCopy[activeLocale]||desktopTourCopy.es;}
  function clearDesktopTourTarget(){document.querySelector(".desktop-tour-target")?.classList.remove("desktop-tour-target");}
  function placeDesktopTour(target){const dialog=document.getElementById("desktop-tour"),rect=target?.getBoundingClientRect(),targetLow=Boolean(rect&&rect.top>innerHeight/2);dialog.classList.toggle("tour-top",targetLow);dialog.classList.toggle("tour-bottom",!targetLow);}
  function finishDesktopTour(){clearDesktopTourTarget();document.getElementById("desktop-tour").close();localStorage.setItem("archeon_desktop_onboarding_completed","1");desktopTourIndex=-1;}
  function renderDesktopTour(){const copy=desktopTourLanguage(),dialog=document.getElementById("desktop-tour"),progress=document.getElementById("desktop-tour-progress"),title=document.getElementById("desktop-tour-title"),body=document.getElementById("desktop-tour-copy"),next=document.getElementById("desktop-tour-next"),back=document.getElementById("desktop-tour-back"),skip=document.getElementById("desktop-tour-skip");clearDesktopTourTarget();if(desktopTourIndex<0){progress.textContent="ARCHEON";title.textContent=copy.welcome;body.textContent=copy.question;next.textContent=copy.start;back.hidden=true;skip.textContent=copy.skip;placeDesktopTour(null);return;}const [selector,text]=copy.steps[desktopTourIndex],target=document.querySelector(selector);progress.textContent=`${desktopTourIndex+1} / ${copy.steps.length}`;title.textContent="ARCHEON";body.textContent=text;next.textContent=desktopTourIndex===copy.steps.length-1?copy.done:copy.next;back.hidden=false;back.textContent=activeLocale==="en"?"Back":"Anterior";skip.textContent=copy.skip;if(target){target.classList.add("desktop-tour-target");target.scrollIntoView({block:"nearest",inline:"nearest"});placeDesktopTour(target);}}
  function openDesktopTour(force=false){if(!force&&localStorage.getItem("archeon_desktop_onboarding_completed")==="1")return;const dialog=document.getElementById("desktop-tour");desktopTourIndex=-1;renderDesktopTour();if(!dialog.open)dialog.show();}

  function showAuthGateway(view="welcome") {
    document.getElementById("boot-shell").hidden = true;
    document.getElementById("app-shell").hidden = true;
    document.getElementById("auth-shell").hidden = false;
    document.body.classList.add("auth-active");
    showAuthView(view);
  }

  async function configureVoice() {
    const button = document.getElementById("voice-button");
    try {
      const response = await fetch("/api/health", {headers:baseHeaders});
      const value = await response.json();
      button.disabled = !value.voice?.available;
      button.lastElementChild.textContent = value.voice?.available ? "VOZ · LISTA" : "VOZ · NO DISPONIBLE";
    } catch (_) { button.disabled = true; }
  }

  function authError(error) {
    authMessage.textContent = messages[`error.${error.message}`] || messages["error.auth_error"];
  }
  const mascotErrorDialog=document.getElementById("desktop-mascot-error"),mascotErrorMessage=document.getElementById("desktop-mascot-error-message");
  function showMascotError(message){mascotErrorMessage.textContent=message||"No se pudo completar la operación.";if(!mascotErrorDialog.open)mascotErrorDialog.showModal();}
  document.getElementById("desktop-mascot-error-close").addEventListener("click",()=>mascotErrorDialog.close());

  document.querySelectorAll("[data-auth-view]").forEach((button) => button.addEventListener("click", () => {const view=button.dataset.authView;if(view==="verify"&&pendingVerificationEmail)document.getElementById("verify-email").value=pendingVerificationEmail;if(view==="forgot"){const email=document.getElementById("login-email").value.trim();if(email)document.getElementById("forgot-email").value=email;}if(view==="reset"){const email=document.getElementById("forgot-email").value.trim()||document.getElementById("login-email").value.trim();if(email)document.getElementById("reset-email").value=email;}showAuthView(view);}));
  document.querySelectorAll("[data-password-target]").forEach((button)=>button.addEventListener("click",()=>{const input=document.getElementById(button.dataset.passwordTarget),revealed=input.type==="text";input.type=revealed?"password":"text";button.setAttribute("aria-label",revealed?"Mostrar contraseña":"Ocultar contraseña");button.title=button.getAttribute("aria-label");}));
  document.getElementById("verify-code").addEventListener("input",event=>{event.target.value=event.target.value.replace(/\D/g,"").slice(0,8);});
  document.getElementById("reset-code").addEventListener("input",event=>{event.target.value=event.target.value.replace(/\D/g,"").slice(0,8);});
  document.getElementById("login-mfa-code").addEventListener("input",event=>{event.target.value=event.target.value.replace(/\D/g,"").slice(0,6);});
  document.getElementById("guest-button").addEventListener("click", async () => {
    try { const value = await auth("guest"); sessionStorage.setItem("archeon_session", value.session_token); enterApplication(value.session); await loadCurrentSettings(document.documentElement.lang||"es"); } catch (error) { authError(error); }
  });
  document.getElementById("auth-login").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const value = await auth("login", {email:document.getElementById("login-email").value,password:document.getElementById("login-password").value});
      sessionStorage.setItem("archeon_session", value.session_token);
      if(await requireMfa(value.session))return;
      enterApplication(value.session); await loadCurrentSettings(document.documentElement.lang||"es");
    } catch (error) { authError(error); }
  });
  document.getElementById("auth-mfa").addEventListener("submit",async event=>{event.preventDefault();try{const value=await auth("mfa-verify",{factor_id:pendingMfaFactor,code:document.getElementById("login-mfa-code").value});sessionStorage.setItem("archeon_session",value.session_token);pendingMfaFactor="";enterApplication(value.session);await loadCurrentSettings(document.documentElement.lang||"es");}catch(error){authError(error);}});
  document.getElementById("auth-register").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const password=document.getElementById("register-password").value,confirmPassword=document.getElementById("register-password-confirm").value;
      if(password!==confirmPassword)throw new Error("passwords_do_not_match");
      pendingVerificationEmail=document.getElementById("register-email").value.trim();
      const value = await auth("register", {display_name:document.getElementById("register-name").value,email:pendingVerificationEmail,password,confirm_password:confirmPassword,locale:document.documentElement.lang||"es"});
      if (value.session.pending_confirmation) {
        document.getElementById("verify-email").value=pendingVerificationEmail;showAuthView("verify"); authMessage.textContent=t("auth.confirmation_sent"); document.getElementById("verify-code").focus(); return;
      }
      sessionStorage.setItem("archeon_session", value.session_token); enterApplication(value.session); await loadCurrentSettings(document.documentElement.lang||"es");
    } catch (error) { authError(error); }
  });
  document.getElementById("auth-verify").addEventListener("submit",async(event)=>{event.preventDefault();try{pendingVerificationEmail=document.getElementById("verify-email").value.trim();const value=await auth("verify-signup",{email:pendingVerificationEmail,code:document.getElementById("verify-code").value});sessionStorage.setItem("archeon_session",value.session_token);enterApplication(value.session);await loadCurrentSettings(document.documentElement.lang||"es");}catch(error){authError(error);}});
  document.getElementById("verify-resend").addEventListener("click",async()=>{try{pendingVerificationEmail=document.getElementById("verify-email").value.trim();await auth("resend-signup",{email:pendingVerificationEmail});authMessage.textContent=t("verify.resent");}catch(error){authError(error);}});
  document.getElementById("auth-forgot").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const email=document.getElementById("forgot-email").value.trim();
      await auth("forgot-password", {email});
      document.getElementById("reset-email").value=email; showAuthView("reset"); authMessage.textContent=t("auth.recovery_sent");
    } catch (error) { authError(error); }
  });
  document.getElementById("auth-reset").addEventListener("submit",async(event)=>{event.preventDefault();try{const password=document.getElementById("reset-password").value,confirmPassword=document.getElementById("reset-password-confirm").value;await auth("reset-password",{email:document.getElementById("reset-email").value.trim(),code:document.getElementById("reset-code").value,password,confirm_password:confirmPassword});showAuthView("login");authMessage.textContent=t("auth.reset_done");}catch(error){authError(error);}});
  document.getElementById("logout-button").addEventListener("click", async () => {
    try { await auth("logout"); } catch (_) { /* local session is cleared regardless */ }
    events?.close();
    sessionStorage.removeItem("archeon_session"); location.reload();
  });
  function leaveGuestForAuth(view){events?.close();events=null;sessionStorage.removeItem("archeon_session");session=null;document.getElementById("sidebar").classList.remove("open");showAuthGateway(view);}
  document.getElementById("guest-login").addEventListener("click",()=>leaveGuestForAuth("login"));
  document.getElementById("guest-register").addEventListener("click",()=>leaveGuestForAuth("register"));

  const stateElement = document.getElementById("assistant-state");
  const detailElement = document.getElementById("assistant-detail");
  const art = document.getElementById("core-art");
  let mediaProgressTimer=null;
  const musicPanel = document.getElementById("music-panel");
  const title = document.getElementById("track-title");
  const artist = document.getElementById("track-artist");
  const album = document.getElementById("track-album");
  function configuredLogoResource(){const appearance=settingsCache?.appearance||{};return appearance.logo_path?`/personalization/logo?token=${encodeURIComponent(runtime.token)}&v=${settingsCache?.sync?.version||0}`:"/logo_asitente.png";}
  function restoreUserOrbVisual(){const appearance=settingsCache?.appearance||{},logoVideo=document.getElementById("core-logo-video"),logoIsVideo=/\.(?:mp4|webm|m4v)$/i.test(appearance.logo_path||""),transform=`scale(${(appearance.logo_zoom||100)/100}) translate(${appearance.logo_position_x||0}%,${appearance.logo_position_y||0}%)`,resource=configuredLogoResource();document.body.classList.remove("vinyl-enabled");art.style.transform=transform;logoVideo.style.transform=transform;if(logoIsVideo){logoVideo.dataset.active=String(appearance.logo_visible!==false);if(logoVideo.src!==new URL(resource,location.href).href)logoVideo.src=resource;art.hidden=true;logoVideo.hidden=appearance.logo_visible===false;if(!logoVideo.hidden&&!document.hidden)logoVideo.play().catch(()=>{});}else{logoVideo.pause();logoVideo.hidden=true;art.src=resource;art.hidden=appearance.logo_visible===false;}}
  function artworkResource(value){if(!value)return null;try{const url=new URL(value,location.href);if(url.origin===location.origin){url.searchParams.set("token",runtime.token);return url.href;}return url.protocol==="https:"?url.href:null;}catch(_){return null;}}
  function scheduleMediaProgress(state){if(mediaProgressTimer!==null){clearTimeout(mediaProgressTimer);mediaProgressTimer=null;}if(!["playing","buffering"].includes(state)||document.hidden)return;mediaProgressTimer=setTimeout(async()=>{mediaProgressTimer=null;const value=await postAction("media.status");if(!value.ok)return;const media=value.media||{},seek=document.getElementById("music-seek"),position=Number(media.position_ms)||0,duration=Number(media.track?.duration_ms)||Number(seek.max)||1;seek.max=String(Math.max(1,duration));if(!seek.matches(":active"))seek.value=String(Math.max(0,Math.min(duration,position)));if(media.state==="stopped"||media.state==="paused")renderMediaSession(media);else scheduleMediaProgress(media.state);},750);}
  function renderMediaSession(media){const state=media?.state||"stopped",track=media?.track||null,active=Boolean(track&&state!=="stopped"),play=document.getElementById("music-play"),pause=document.getElementById("music-pause"),volume=document.getElementById("music-volume");musicPanel.classList.toggle("active",active);musicPanel.setAttribute("aria-hidden",String(!active));play.disabled=!active||state==="playing"||state==="buffering";pause.disabled=!active||state==="paused";play.setAttribute("aria-pressed",String(state==="playing"||state==="buffering"));pause.setAttribute("aria-pressed",String(state==="paused"));if(Number.isFinite(Number(media?.volume)))volume.value=String(Math.round(Number(media.volume)*100));if(!active){scheduleMediaProgress("stopped");title.textContent=t("music.none");artist.textContent="";album.textContent="";restoreUserOrbVisual();setState("idle","state.ready");return;}title.textContent=track.title||t("music.demo");artist.textContent=track.artist||"";album.textContent=track.album||"";document.getElementById("music-seek").max=track.duration_ms||1;document.getElementById("music-seek").value=media.position_ms||0;const showArtwork=settingsCache?.media?.show_album_art!==false,cover=showArtwork?artworkResource(track.artwork_url):null,logoVideo=document.getElementById("core-logo-video");if(cover){logoVideo.pause();logoVideo.hidden=true;art.hidden=false;art.src=cover;art.style.transform="";}else{restoreUserOrbVisual();if(/\.(?:mp4|webm|m4v)$/i.test(settingsCache?.appearance?.logo_path||""))art.src="/logo_asitente.png";}document.body.classList.toggle("vinyl-enabled",Boolean(showArtwork&&cover));setState(state==="paused"?"paused":"music",state==="paused"?"state.paused_detail":"state.music_detail");scheduleMediaProgress(state);}
  function setState(state, detailKey) {
    ["idle","listening","transcribing","thinking","executing","speaking","music","paused","error"].forEach((name) => document.body.classList.remove(`state-${name}`));
    document.body.classList.add(`state-${state}`);
    stateElement.textContent = state === "idle" ? (settingsCache?.assistant?.wake_name || t("state.idle")) : t(`state.${state}`);
    if (detailKey) detailElement.textContent = t(detailKey);
    const logoVideo=document.getElementById("core-logo-video"),art=document.getElementById("core-art");
    if(state==="music"||state==="paused"||logoVideo.dataset.active!=="true"){logoVideo.pause();logoVideo.hidden=true;art.hidden=false;}
    else{art.hidden=true;logoVideo.hidden=false;if(!document.hidden)logoVideo.play().catch(()=>{});}
  }
  const postAction = async (action, payload = {}) => {
    try {
      const response=await fetch("/api/action",{method:"POST",headers:headers(),body:JSON.stringify({action,...payload})});
      const value=await response.json();
      return value&&typeof value==="object"?value:{ok:false,error:"invalid_response"};
    } catch (_) {
      return {ok:false,error:"local_connection_error"};
    }
  };
  async function syncNow() {
    const status=document.getElementById("settings-sync-status");
    status.textContent=t("sync.syncing");
    const result=await postAction("sync.now");
    if(result.ok&&result.settings)applySettings(result.settings);
    status.textContent=result.ok?(result.queued?t("sync.offline_queued"):t("sync.completed")):(messages[`error.${result.error}`]?t(`error.${result.error}`):(result.error||t("sync.error")));
    return result;
  }
  const voiceDialog = document.getElementById("voice-settings");
  function renderWakeDiagnostics(wake){const device=wake.wake_input_device||{};document.getElementById("wake-diag-stream").textContent=wake.wake_stream_active?t("wake.receiving"):t("wake.inactive");document.getElementById("wake-diag-frames").textContent=String(wake.wake_frames_received||0);document.getElementById("wake-diag-detector").textContent=localizeStatus(wake.wake_worker_status||wake.wake_monitor_state||"disabled");document.getElementById("wake-diag-backend").textContent=wake.wake_monitor_active?t("wake.ready"):t("wake.idle");document.getElementById("wake-diag-device").textContent=device.name||"—";document.getElementById("wake-diag-rate").textContent=`${wake.wake_target_sample_rate||"—"} Hz ← ${wake.wake_native_sample_rate||device.samplerate||"—"} Hz`;document.getElementById("wake-diag-error").textContent=wake.wake_error_category?`${wake.wake_error_category} · ${wake.wake_error_type||"error"}: ${wake.wake_monitor_error||"—"}`:"—";document.getElementById("wake-diag-candidate").textContent=wake.wake_last_candidate||"—";document.getElementById("wake-diag-activation").textContent=wake.wake_last_activation_at||"—";document.getElementById("wake-diag-level").value=wake.wake_input_level||0;}
  function renderSpeakerProfiles(profiles){const host=document.getElementById("speaker-profiles");host.replaceChildren();if(!profiles?.length){const empty=document.createElement("p");empty.className="provider-note";empty.textContent=t("voice.no_authorized");host.append(empty);return;}profiles.forEach(profile=>{const row=document.createElement("div");row.className="speaker-profile";const info=document.createElement("span");const title=document.createElement("strong");title.textContent=profile.name;const detail=document.createElement("small");detail.textContent=`${t(profile.role==="owner"?"voice.owner":"voice.authorized_role")} · ${profile.sample_count||0} ${t("voice.samples")} · ${t(profile.enabled?"voice.enabled":"voice.disabled")}`;info.append(title,detail);const actions=document.createElement("div");const toggle=document.createElement("button");toggle.type="button";toggle.textContent=t(profile.enabled?"voice.disable":"voice.enable");toggle.addEventListener("click",async()=>{const result=await postAction("voice.speaker.update",{profile_id:profile.id,enabled:!profile.enabled});if(result.ok)renderSpeakerProfiles(result.profiles);else showNotice(result.error||t("voice.change_error"),"error");});const retrain=document.createElement("button");retrain.type="button";retrain.textContent=t("voice.retrain");retrain.addEventListener("click",()=>beginSpeakerEnrollment(profile.id,profile.name));const rename=document.createElement("button");rename.type="button";rename.textContent=t("voice.rename");rename.addEventListener("click",async()=>{const name=window.prompt(t("voice.new_name"),profile.name);if(!name)return;const result=await postAction("voice.speaker.update",{profile_id:profile.id,name});if(result.ok)renderSpeakerProfiles(result.profiles);else showNotice(result.error||t("voice.invalid_name"),"error");});const remove=document.createElement("button");remove.type="button";remove.textContent=t("voice.remove");remove.addEventListener("click",async()=>{if(!window.confirm(`${t("voice.remove_confirm")} ${profile.name}?`))return;const result=await postAction("voice.speaker.delete",{profile_id:profile.id});if(result.ok)renderSpeakerProfiles(result.profiles);else showNotice(result.error||t("voice.remove_error"),"error");});actions.append(toggle,retrain,rename,remove);row.append(info,actions);host.append(row);});}
  async function beginSpeakerEnrollment(profileId="",existingName=""){const name=(existingName||document.getElementById("speaker-profile-name").value).trim();const status=document.getElementById("speaker-enrollment-status");if(!name){status.textContent=t("voice.name_required");return;}status.textContent=t("voice.enroll_preparing");const result=await postAction("voice.speaker.enroll",{name,profile_id:profileId});if(!result.ok)status.textContent=result.error||t("voice.enroll_error");}
  function fillSelect(select, items, selected, includeDefault = true) {
    select.replaceChildren();
    if (includeDefault) select.add(new Option(t("voice.settings.default"), ""));
    items.forEach((item) => select.add(new Option(item.name, String(item.id))));
    select.value = selected || "";
  }
  document.getElementById("voice-settings-open").addEventListener("click", async () => {
    document.getElementById("sidebar").classList.remove("open");
    const result = await postAction("voice.catalog");
    if (!result.ok) { showNotice(t("voice.catalog_error"),"error"); return; }
    const voice = result.voice, config = voice.configuration;
    fillSelect(document.getElementById("voice-profile"), voice.profiles.map((id)=>({id,name:id.toUpperCase()})), config.profile, false);
    fillSelect(document.getElementById("voice-input"), voice.input_devices.map((device)=>({id:device.index,name:device.name})), config.input_device_id);
    fillSelect(document.getElementById("voice-tts"), voice.tts_voices, config.tts_voice_id);
    fillSelect(document.getElementById("voice-output"), voice.tts_outputs, config.tts_output_device_id);
    document.getElementById("voice-style").value=config.tts_style||"natural";
    document.getElementById("voice-rate").value=config.tts_rate;
    document.getElementById("voice-volume").value=config.tts_volume;
    document.getElementById("voice-barge").checked=config.barge_in;
    document.getElementById("speaker-verification-enabled").checked=Boolean(config.speaker_verification_enabled);
    document.getElementById("speaker-rejection-feedback").value=config.speaker_rejection_feedback||"silent";
    renderSpeakerProfiles(config.speaker_profiles||[]);
    document.getElementById("voice-model-detail").textContent=voice.available?t("voice.local_ready"):t("voice.local_unavailable");
    const wake=voice.status,device=wake.wake_input_device?.name||t("voice.settings.default");
    renderWakeDiagnostics(wake);
    document.getElementById("wake-status-detail").textContent=wake.wake_word_enabled
      ? (wake.wake_monitor_active&&wake.wake_monitor_state!=="error"?`● ${t("wake.waiting")} “${wake.wake_name}” · ${device}`:`${t("state.error")} · ${wake.wake_monitor_error||"detector_inactive"}`)
      : `${t("wake.disabled")} · ${device}`;
    voiceDialog.showModal();
  });
  document.getElementById("voice-settings-close").addEventListener("click",()=>voiceDialog.close());
  document.getElementById("speaker-enroll").addEventListener("click",()=>beginSpeakerEnrollment());
  document.getElementById("voice-settings-preview").addEventListener("click",async()=>{
    const status=document.getElementById("voice-preview-status");status.textContent=t("voice.preview_playing");
    const result=await postAction("voice.preview",{text:document.getElementById("voice-preview-text").value||t("voice.settings.preview_text"),tts_voice_id:document.getElementById("voice-tts").value,tts_output_device_id:document.getElementById("voice-output").value,tts_style:document.getElementById("voice-style").value,tts_rate:Number(document.getElementById("voice-rate").value),tts_volume:Number(document.getElementById("voice-volume").value)});
    status.textContent=result.ok?t("voice.preview_started"):(result.error||"voice_preview_error");
  });
  document.getElementById("voice-input-test").addEventListener("click",async()=>{
    const status=document.getElementById("voice-input-test-status");status.textContent=t("voice.microphone_preparing");document.getElementById("voice-input-level").value=0;
    const result=await postAction("audio.test_input",{duration_seconds:3});if(!result.ok)status.textContent=result.error||"microphone_test_error";
  });
  document.getElementById("voice-settings-save").addEventListener("click",async()=>{
    const result=await postAction("voice.configure",{
      profile:document.getElementById("voice-profile").value,
      input_device_id:document.getElementById("voice-input").value,
      tts_voice_id:document.getElementById("voice-tts").value,
      tts_output_device_id:document.getElementById("voice-output").value,
      tts_style:document.getElementById("voice-style").value,
      tts_rate:Number(document.getElementById("voice-rate").value),
      tts_volume:Number(document.getElementById("voice-volume").value),
      barge_in:document.getElementById("voice-barge").checked,
      speaker_verification_enabled:document.getElementById("speaker-verification-enabled").checked,
      speaker_rejection_feedback:document.getElementById("speaker-rejection-feedback").value,
    });
    if(result.ok)voiceDialog.close();else document.getElementById("voice-model-detail").textContent=result.error||"voice_configuration_error";
  });
  const settingsDialog = document.getElementById("settings-dialog");
  const settingsSearch=document.getElementById("settings-search");
  function showSettingsSection(name){
    document.querySelectorAll("[data-settings-section]").forEach(button=>button.classList.toggle("active",button.dataset.settingsSection===name));
    document.querySelectorAll("[data-settings-panel]").forEach(panel=>panel.classList.toggle("active",panel.dataset.settingsPanel===name));
  }
  document.querySelectorAll("[data-settings-section]").forEach(button=>button.addEventListener("click",()=>{settingsSearch.value="";document.querySelectorAll("[data-settings-panel]").forEach(panel=>panel.classList.remove("search-match"));showSettingsSection(button.dataset.settingsSection);}));
  document.querySelectorAll("[data-settings-open]").forEach(button=>button.addEventListener("click",()=>{settingsDialog.close();document.getElementById(button.dataset.settingsOpen==="voice"?"voice-settings-open":"account-open").click();}));
  settingsSearch.addEventListener("input",()=>{
    const query=settingsSearch.value.trim().toLocaleLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"");let matches=0;
    document.querySelectorAll("[data-settings-panel]").forEach(panel=>{panel.classList.remove("active");const content=`${panel.dataset.searchTerms||""} ${panel.textContent}`.toLocaleLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"");const match=Boolean(query)&&content.includes(query);panel.classList.toggle("search-match",match);if(match)matches++;});
    document.getElementById("settings-search-empty").hidden=!query||matches>0;
    if(!query){document.querySelectorAll("[data-settings-panel]").forEach(panel=>panel.classList.remove("search-match"));showSettingsSection(document.querySelector("[data-settings-section].active")?.dataset.settingsSection||"general");}
  });
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
  function appendInlineMarkup(parent,value){
    const source=String(value??"");
    const pattern=/(\*\*([^*\n]+)\*\*|__([^_\n]+)__|`([^`\n]+)`|\*([^*\n]+)\*|_([^_\n]+)_|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\))/g;
    let cursor=0,match;
    while((match=pattern.exec(source))){
      if(match.index>cursor)parent.append(document.createTextNode(source.slice(cursor,match.index)));
      if(match[2]||match[3]){const strong=document.createElement("strong");strong.textContent=match[2]||match[3];parent.append(strong);}
      else if(match[4]){const code=document.createElement("code");code.textContent=match[4];parent.append(code);}
      else if(match[5]||match[6]){const emphasis=document.createElement("em");emphasis.textContent=match[5]||match[6];parent.append(emphasis);}
      else{const link=document.createElement("a");link.textContent=match[7];link.href=match[8];link.target="_blank";link.rel="noopener noreferrer";parent.append(link);}
      cursor=pattern.lastIndex;
    }
    if(cursor<source.length)parent.append(document.createTextNode(source.slice(cursor).replace(/\*{2,}/g,"")));
  }
  function renderAssistantText(node,value){
    const fragment=document.createDocumentFragment();
    const lines=String(value??"").replace(/\r\n?/g,"\n").split("\n");
    let list=null,listType="",codeBlock=null;
    const closeList=()=>{list=null;listType="";};
    lines.forEach(line=>{
      if(/^\s*```/.test(line)){closeList();if(codeBlock){codeBlock=null;}else{const pre=document.createElement("pre");codeBlock=document.createElement("code");pre.append(codeBlock);fragment.append(pre);}return;}
      if(codeBlock){codeBlock.append(document.createTextNode(`${line}\n`));return;}
      const item=line.match(/^\s*([-*+]|\d+[.)])\s+(.+)$/);
      if(item){const type=/\d/.test(item[1])?"ol":"ul";if(!list||listType!==type){list=document.createElement(type);listType=type;fragment.append(list);}const li=document.createElement("li");appendInlineMarkup(li,item[2]);list.append(li);return;}
      closeList();
      if(!line.trim()){fragment.append(document.createElement("br"));return;}
      const paragraph=document.createElement("p");appendInlineMarkup(paragraph,line.replace(/^\s*#{1,6}\s+/,"").replace(/~~([^~\n]+)~~/g,"$1"));fragment.append(paragraph);
    });
    node.replaceChildren(fragment);
  }
  function previewAccent(value){
    const accent=/^#[0-9a-f]{6}$/i.test(value||"")?value:"#00F3FF";
    const channels=[parseInt(accent.slice(1,3),16),parseInt(accent.slice(3,5),16),parseInt(accent.slice(5,7),16)];
    const luminance=(.2126*channels[0]+.7152*channels[1]+.0722*channels[2])/255;
    document.documentElement.style.setProperty("--accent",accent);document.documentElement.style.setProperty("--accent-rgb",channels.join(" "));document.documentElement.style.setProperty("--accent-glow",`rgb(${channels.join(" ")} / .18)`);document.documentElement.style.setProperty("--accent-contrast",luminance>.57?"#001013":"#ffffff");
  }
  const layoutTargets=Object.fromEntries(Array.from(document.querySelectorAll("[data-layout-key]"),node=>[node.dataset.layoutKey,node]));
  const essentialLayoutItems=new Set(["menu_toggle"]),resizableLayoutItems=new Set(["conversation","command","music"]);
  function normalizeInterfaceLayout(value){
    const source=value&&typeof value==="object"?value:{};const output={};
    const legacyGroups={top_actions:["session_badge","command_toggle","ghost_toggle","menu_toggle"],status:["assistant_name","assistant_detail","voice_button"],command:["conversation","command"]};
    Object.entries(legacyGroups).forEach(([legacy,keys])=>{if(source[legacy]&&typeof source[legacy]==="object")keys.forEach(key=>{if(!source[key])source[key]=source[legacy];});});
    Object.keys(layoutTargets).forEach(key=>{const item=source[key]&&typeof source[key]==="object"?source[key]:{};const color=/^#[0-9a-f]{6}$/i.test(item.color||"")?item.color.toUpperCase():null,background=/^#[0-9a-f]{6}$/i.test(item.background||"")?item.background.toUpperCase():null,textColor=/^#[0-9a-f]{6}$/i.test(item.text_color||"")?item.text_color.toUpperCase():null,style=key==="conversation"&&["card","compact","bubbles"].includes(item.style)?item.style:"card",left=Number(item.left),top=Number(item.top);output[key]={x:Math.max(-4000,Math.min(4000,Number(item.x)||0)),y:Math.max(-2400,Math.min(2400,Number(item.y)||0)),anchor:item.anchor==="viewport"?"viewport":"flow",left:Math.max(0,Math.min(100,Number.isFinite(left)?left:50)),top:Math.max(0,Math.min(100,Number.isFinite(top)?top:50)),color,background,text_color:textColor,style,visible:essentialLayoutItems.has(key)?true:item.visible!==false,scale:Math.max(50,Math.min(180,Number(item.scale)||100)),width:Math.max(35,Math.min(100,Number(item.width)||70))};});
    return output;
  }
  function applyInterfaceLayout(value){
    const layout=normalizeInterfaceLayout(value);
    Object.entries(layoutTargets).forEach(([key,node])=>{if(!node)return;const item=layout[key],anchored=item.anchor==="viewport";node.classList.toggle("layout-viewport",anchored);node.style.setProperty("--layout-x",`${anchored?0:item.x}px`);node.style.setProperty("--layout-y",`${anchored?0:item.y}px`);if(anchored){node.style.setProperty("--layout-left",`${item.left}%`);node.style.setProperty("--layout-top",`${item.top}%`);}else{node.style.removeProperty("--layout-left");node.style.removeProperty("--layout-top");}node.style.setProperty("--layout-scale",String(item.scale/100));if(resizableLayoutItems.has(key))node.style.setProperty("--layout-width",`${item.width}vw`);else node.style.removeProperty("--layout-width");if(item.color)node.style.setProperty("--layout-color",item.color);else node.style.removeProperty("--layout-color");if(item.background)node.style.setProperty("--layout-background",item.background);else node.style.removeProperty("--layout-background");if(item.text_color)node.style.setProperty("--layout-text",item.text_color);else node.style.removeProperty("--layout-text");if(key==="conversation")node.dataset.messageStyle=item.style;node.classList.toggle("layout-user-hidden",!item.visible);node.classList.toggle("layout-user-visible",item.visible);});
  }
  function normalizeSettings(value) {
    const settings=value&&typeof value==="object"?value:{};
    return {...settings,
      appearance:{...(settings.appearance||{})}, performance:{...(settings.performance||{})},
      assistant:{...(settings.assistant||{})}, language:{...(settings.language||{})},
      clock:{...(settings.clock||{})}, startup:{...(settings.startup||{})}, approval:{...(settings.approval||{})}, sync:{...(settings.sync||{})},
      intelligence:{...(settings.intelligence||{})}, personality:{...(settings.personality||{})}, media:{...(settings.media||{})},
    };
  }
  function cloneSettings(value){return typeof structuredClone==="function"?structuredClone(value):JSON.parse(JSON.stringify(value));}
  function renderServiceStatus(services){
    const cloud=document.getElementById("settings-cloud-status"),plugins=document.getElementById("settings-extensions-status"),updates=document.getElementById("settings-updates-status");
    const escapeHtml=(value)=>String(value).replace(/[&<>"']/g,character=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[character]);
    const row=(labelKey,value)=>`<div class="status-row"><span>${escapeHtml(t(labelKey))}</span><strong>${escapeHtml(localizeStatus(value))}</strong></div>`;
    if(cloud){const value=services?.cloud||{};cloud.innerHTML=row("service.settings_sync",value.settings_sync)+row("service.pairing",value.device_pairing)+row("service.lan",value.lan_direct)+row("service.relay",value.remote_relay)+row("service.file_transfer",value.file_transfer)+row("service.remote_commands",value.remote_commands)+row("service.mobile",value.mobile);}
    if(plugins){const value=services?.plugins||{};plugins.innerHTML=row("service.engine",value.engine)+row("service.installed",value.installed)+row("service.enabled",value.enabled)+row("service.active",value.active)+row("service.signature_verifier",value.trusted_signature_provider?"configured":"not_configured");}
    if(updates){const value=services?.updates||{};updates.innerHTML=row("service.current_version",String(value.current_version||"").replace(".dev0",` (${t("status.development")})`))+row("service.provider",value.configured?value.provider:"not_configured")+row("service.available_version",value.available_version||"not_checked")+row("service.download",value.download_state)+row("service.verification",value.verification_state)+row("service.installation",value.install_state);}
  }
  function applySettings(value) {
    const settings=normalizeSettings(value);
    settingsCache = settings;
    const theme = settings.appearance?.theme || "dark";
    const accent=/^#[0-9a-f]{6}$/i.test(settings.appearance?.accent_color||"")?settings.appearance.accent_color:"#00F3FF";
    previewAccent(accent);
    const resolved = theme === "system" && matchMedia("(prefers-color-scheme: light)").matches ? "light" : theme;
    document.body.classList.toggle("theme-light", resolved === "light");
    document.body.classList.toggle("reduce-motion", Boolean(settings.appearance?.reduced_motion));
    document.body.classList.toggle("high-contrast", Boolean(settings.appearance?.high_contrast));
    document.body.classList.toggle("large-targets", Boolean(settings.appearance?.large_targets));
    document.body.classList.toggle("left-handed", Boolean(settings.appearance?.left_handed));
    document.body.classList.toggle("visual-voice-cues", settings.appearance?.visual_voice_cues!==false);
    document.body.classList.toggle("listening-paused", Boolean(settings.assistant?.listening_paused));
    document.body.dataset.performance = settings.performance?.profile || "eco";
    document.body.dataset.idleAnimation = String(Boolean(settings.performance?.idle_animation));
    document.documentElement.style.fontSize=`${settings.appearance?.text_scale||100}%`;
    document.body.style.zoom=String((settings.appearance?.ui_scale||100)/100);
    const curtain=document.querySelector(".background-curtain");
    const video=document.getElementById("background-video");
    const appearance=settings.appearance||{};
    const backgroundType=document.getElementById("settings-background-type");
    const backgroundFit=document.getElementById("settings-background-fit");
    if(backgroundType)backgroundType.value=appearance.background_type||"default";
    if(backgroundFit)backgroundFit.value=appearance.background_fit||"cover";
    const inputVisible=appearance.command_input_visible!==false;
    document.getElementById("app-shell").classList.toggle("input-hidden",!inputVisible);
    const inputToggle=document.getElementById("command-toggle");
    const inputToggleLabel=inputVisible?"Ocultar barra de comandos":"Mostrar barra de comandos";
    inputToggle.setAttribute("aria-label",inputToggleLabel);inputToggle.title=inputToggleLabel;
    document.getElementById("voice-button").hidden=appearance.status_indicator_visible===false;
    const resource=`/personalization/background?token=${encodeURIComponent(runtime.token)}&v=${settings.sync?.version||0}`;
    curtain.style.filter=`blur(${appearance.background_blur||0}px)`;
    curtain.style.opacity=String((appearance.background_opacity??100)/100);
    curtain.style.backgroundSize=appearance.background_fit||"cover";
    curtain.style.transform=`scale(${(appearance.background_zoom||100)/100}) translate(${appearance.background_position_x||0}%,${appearance.background_position_y||0}%)`;
    video.style.transform=curtain.style.transform;
    if(appearance.background_type==="image"&&appearance.background_path){video.pause();video.removeAttribute("src");video.hidden=true;curtain.style.backgroundImage=`linear-gradient(rgba(0,0,0,.22),rgba(0,0,0,.36)),url("${resource}")`;}
    else if(appearance.background_type==="video"&&appearance.background_path){curtain.style.backgroundImage="linear-gradient(rgba(0,0,0,.2),rgba(0,0,0,.34))";video.style.objectFit=appearance.background_fit||"cover";if(video.src!==new URL(resource,location.href).href)video.src=resource;video.hidden=false;if((settings.performance?.profile||"eco")==="eco"){const freeze=()=>{try{video.currentTime=.05;}catch(_){}video.pause();};video.readyState>=2?freeze():video.addEventListener("loadeddata",freeze,{once:true});}else video.play().catch(()=>{});}
    else{video.pause();video.removeAttribute("src");video.hidden=true;curtain.style.backgroundImage="";}
    const logo=appearance.logo_path?`/personalization/logo?token=${encodeURIComponent(runtime.token)}&v=${settings.sync?.version||0}`:"/logo_asitente.png";
    const logoIsVideo=/\.(?:mp4|webm|m4v)$/i.test(appearance.logo_path||"");const logoTransform=`scale(${(appearance.logo_zoom||100)/100}) translate(${appearance.logo_position_x||0}%,${appearance.logo_position_y||0}%)`;
    document.querySelectorAll("#core-art,.auth-brand img").forEach(node=>{if(!node.closest(".state-music,.state-paused")){node.src=logo;node.style.transform=logoTransform;}});
    const logoVideo=document.getElementById("core-logo-video");logoVideo.dataset.active=String(logoIsVideo&&appearance.logo_visible!==false);logoVideo.style.transform=logoTransform;
    if(logoIsVideo){if(logoVideo.src!==new URL(logo,location.href).href)logoVideo.src=logo;}else{logoVideo.pause();logoVideo.removeAttribute("src");}
    document.getElementById("core-art").hidden=appearance.logo_visible===false||logoIsVideo;logoVideo.hidden=appearance.logo_visible===false||!logoIsVideo;if(!logoVideo.hidden&&!document.hidden)logoVideo.play().catch(()=>{});
    const conversationStack=document.getElementById("conversation-stack");
    if(appearance.chat_background_path){const chatPreview=draftPreview.chat?"-preview":"";const chatResource=`/personalization/chat${chatPreview}?token=${encodeURIComponent(runtime.token)}&v=${settings.sync?.version||0}`;conversationStack.style.setProperty("--chat-background-image",`url("${chatResource}")`);conversationStack.classList.add("has-chat-background");}
    else{conversationStack.style.removeProperty("--chat-background-image");conversationStack.classList.remove("has-chat-background");}
    const clock=document.querySelector(".clock-widget");clock.hidden=settings.clock?.visible===false;document.getElementById("clock-date").hidden=settings.clock?.show_date===false;scheduleClock();
    if (document.body.classList.contains("state-idle")) stateElement.textContent = settings.assistant?.wake_name || "Archeon";
    applyInterfaceLayout(appearance.interface_layout);
  }
  document.getElementById("settings-open").addEventListener("click", async () => {
    document.getElementById("sidebar").classList.remove("open");
    const result = await postAction("settings.get");
    if (!result.ok) { showNotice("No pude abrir Configuración. Inténtalo de nuevo.","error"); return; }
    result.settings=normalizeSettings(result.settings);
    renderServiceStatus(result.services);
    settingsSearch.value="";document.getElementById("settings-search-empty").hidden=true;document.querySelectorAll("[data-settings-panel]").forEach(panel=>panel.classList.remove("search-match"));showSettingsSection("general");
    applySettings(result.settings);
    settingsDraft=cloneSettings(result.settings);settingsDirty=false;draftPreview.background=false;draftPreview.logo=false;draftPreview.chat=false;
    const interfaceSelect = document.getElementById("settings-interface-language");
    const conversationSelect = document.getElementById("settings-conversation-language");
    fillSelect(interfaceSelect, languageChoices.map((id)=>({id,name:id.toUpperCase()})), result.settings.language.interface, false);
    fillSelect(conversationSelect, [{id:"auto",name:t("settings.auto")},...languageChoices.map((id)=>({id,name:id.toUpperCase()}))], result.settings.language.conversation, false);
    document.getElementById("settings-theme").value=result.settings.appearance.theme;
    const accentPresets=["#00F3FF","#2F80FF","#A855F7","#FF3B5C","#22C55E","#FF8A1F"],accentValue=(result.settings.appearance.accent_color||"#00F3FF").toUpperCase();document.getElementById("settings-accent").value=accentPresets.includes(accentValue)?accentValue:"custom";document.getElementById("settings-accent-custom").value=accentValue;document.getElementById("settings-accent-custom-row").hidden=document.getElementById("settings-accent").value!=="custom";
    document.getElementById("settings-preferred-name").value=result.settings.assistant.preferred_name||"";
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
    document.getElementById("settings-large-targets").checked=Boolean(result.settings.appearance.large_targets);
    document.getElementById("settings-left-handed").checked=Boolean(result.settings.appearance.left_handed);
    document.getElementById("settings-visual-voice-cues").checked=result.settings.appearance.visual_voice_cues!==false;
    document.getElementById("settings-pause-listening-phrase").value=result.settings.assistant.pause_listening_phrase||"deja de escuchar";
    document.getElementById("settings-resume-listening-phrase").value=result.settings.assistant.resume_listening_phrase||"vuelve a escuchar";
    document.getElementById("settings-listening-toggle").textContent=result.settings.assistant.listening_paused?"Reanudar escucha ahora":"Pausar escucha ahora";
    document.getElementById("settings-input-visible").checked=result.settings.appearance.command_input_visible!==false;
    document.getElementById("settings-status-visible").checked=result.settings.appearance.status_indicator_visible!==false;
    document.getElementById("settings-logo-visible").checked=result.settings.appearance.logo_visible!==false;
    document.getElementById("settings-clock-visible").checked=result.settings.clock.visible;
    document.getElementById("settings-clock-24h").checked=result.settings.clock.use_24_hour;
    document.getElementById("settings-clock-seconds").checked=result.settings.clock.show_seconds;
    document.getElementById("settings-clock-date").checked=result.settings.clock.show_date;
    document.getElementById("settings-startup-sound").checked=result.settings.startup.startup_sound;
    document.getElementById("settings-launch-at-login").checked=Boolean(result.settings.startup.launch_at_login);
    document.getElementById("settings-window-mode").value=result.settings.startup.window_mode||(result.settings.startup.start_minimized?"minimized":"normal");
    document.getElementById("settings-start-ghost").checked=Boolean(result.settings.startup.start_in_ghost_mode);
    document.getElementById("settings-approval-mode").value=result.settings.approval?.mode||"ask";
    document.getElementById("settings-computer-use-display").value=result.settings.computer_use?.action_display||"normal";
    renderApprovalHelp();
    document.getElementById("settings-ghost-topmost").checked=result.settings.ghost?.always_on_top!==false;
    document.getElementById("settings-performance-profile").value=result.settings.performance?.profile||"balanced";
    document.getElementById("settings-idle-animation").checked=Boolean(result.settings.performance?.idle_animation);
    document.getElementById("settings-sync-enabled").checked=result.settings.sync.enabled;
    document.getElementById("settings-ai-profile").value=result.settings.intelligence.profile;
    document.getElementById("settings-ai-memory").checked=result.settings.intelligence.memory_enabled!==false;
    document.getElementById("settings-ai-context-turns").value=String(result.settings.intelligence.conversation_turns||4);
    document.getElementById("settings-personality").value=result.settings.personality.style;
    document.getElementById("settings-media-alternatives").value=result.settings.media?.alternative_versions||"ask";
    document.getElementById("settings-media-volume").value=String(result.settings.media?.preferred_volume??70);
    document.getElementById("settings-media-dj").checked=Boolean(result.settings.media?.dj_mode);
    document.getElementById("settings-media-dj-strategy").value=result.settings.media?.dj_strategy||"mixed";
    document.getElementById("settings-media-autoplay").checked=Boolean(result.settings.media?.autoplay);
    document.getElementById("settings-media-artwork").checked=result.settings.media?.show_album_art!==false;
    document.getElementById("settings-media-vinyl").checked=Boolean(result.settings.media?.vinyl_orb);
    document.getElementById("settings-media-local").checked=result.settings.media?.local_library!==false;
    document.getElementById("settings-media-online").checked=result.settings.media?.online_providers!==false;
    document.getElementById("settings-media-notification-volume").value=String(result.settings.media?.notification_volume??70);
    const aiStatus=await postAction("intelligence.status");if(aiStatus.ok&&aiStatus.status)document.getElementById("settings-ai-status").textContent=aiStatus.status.state==="ready"?"ARCHI listo":"ARCHI en reposo · se activa cuando hace falta";
    document.getElementById("settings-message").textContent="";
    if(!settingsDialog.open)settingsDialog.showModal();
  });
  const settingsConfirmDialog=document.getElementById("settings-confirm-dialog");
  let settingsConfirmMode="discard";
  function showSettingsConfirmation(mode){
    settingsConfirmMode=mode;const saving=mode==="save";
    document.getElementById("settings-confirm-title").textContent=saving?"Aplicar cambios":"Cambios sin guardar";
    document.getElementById("settings-confirm-message").textContent=saving?"¿Deseas aplicar los cambios realizados?":"Los cambios realizados no se aplicarán. ¿Deseas continuar?";
    document.getElementById("settings-confirm-stay").textContent=saving?"No, seguir personalizando":"Seguir personalizando";
    document.getElementById("settings-confirm-accept").textContent=saving?"Sí, aplicar cambios":"Salir de configuración";
    if(!settingsConfirmDialog.open)settingsConfirmDialog.showModal();
  }
  async function discardSettingsDraft(){await postAction("appearance.discard");if(settingsCache)applySettings(settingsCache);settingsDraft=null;settingsDirty=false;draftPreview.background=false;draftPreview.logo=false;draftPreview.chat=false;if(settingsDialog.open)settingsDialog.close();}
  function requestSettingsClose(){if(settingsDirty)showSettingsConfirmation("discard");else discardSettingsDraft();}
  document.getElementById("settings-close").addEventListener("click",requestSettingsClose);
  settingsDialog.addEventListener("cancel",event=>{event.preventDefault();requestSettingsClose();});
  settingsConfirmDialog.addEventListener("cancel",event=>{event.preventDefault();settingsConfirmDialog.close();});
  document.getElementById("settings-confirm-stay").addEventListener("click",()=>settingsConfirmDialog.close());
  document.getElementById("settings-confirm-accept").addEventListener("click",async()=>{const mode=settingsConfirmMode;settingsConfirmDialog.close();if(mode==="save")await saveSettingsChanges();else await discardSettingsDraft();});
  settingsDialog.addEventListener("input",event=>{if(event.target.id!=="settings-search")settingsDirty=true;});
  settingsDialog.addEventListener("change",event=>{if(event.target.id!=="settings-search")settingsDirty=true;});
  function previewSettingsControls(){
    if(!settingsCache)return;
    const preview=cloneSettings(settingsDraft||settingsCache);
    preview.clock={...preview.clock,visible:document.getElementById("settings-clock-visible").checked,use_24_hour:document.getElementById("settings-clock-24h").checked,show_seconds:document.getElementById("settings-clock-seconds").checked,show_date:document.getElementById("settings-clock-date").checked};
    preview.appearance={...preview.appearance,reduced_motion:document.getElementById("settings-reduced-motion").checked,high_contrast:document.getElementById("settings-high-contrast").checked,large_targets:document.getElementById("settings-large-targets").checked,left_handed:document.getElementById("settings-left-handed").checked,visual_voice_cues:document.getElementById("settings-visual-voice-cues").checked,ui_scale:Number(document.getElementById("settings-ui-scale").value),text_scale:Number(document.getElementById("settings-text-scale").value),command_input_visible:document.getElementById("settings-input-visible").checked,status_indicator_visible:document.getElementById("settings-status-visible").checked,logo_visible:document.getElementById("settings-logo-visible").checked};
    preview.performance={...preview.performance,profile:document.getElementById("settings-performance-profile").value,idle_animation:document.getElementById("settings-idle-animation").checked};
    settingsDraft=preview;
    applySettings(preview);
  }
  const immediatePreviewIds=["settings-clock-visible","settings-clock-24h","settings-clock-seconds","settings-clock-date","settings-reduced-motion","settings-high-contrast","settings-large-targets","settings-left-handed","settings-visual-voice-cues","settings-ui-scale","settings-text-scale","settings-input-visible","settings-status-visible","settings-logo-visible","settings-performance-profile","settings-idle-animation"];
  immediatePreviewIds.forEach(id=>{const control=document.getElementById(id);control.addEventListener(control.type==="range"?"input":"change",previewSettingsControls);});
  document.getElementById("settings-save").addEventListener("click",()=>{if(!settingsDirty){document.getElementById("settings-message").textContent="No hay cambios pendientes.";return;}showSettingsConfirmation("save");});
  async function saveSettingsChanges(){
    const interfaceLanguage=document.getElementById("settings-interface-language").value;
    const accent=document.getElementById("settings-accent").value==="custom"?document.getElementById("settings-accent-custom").value:document.getElementById("settings-accent").value;
    const message=document.getElementById("settings-message");
    if(!/^#[0-9a-f]{6}$/i.test(accent)){message.textContent="El color debe tener el formato #RRGGBB.";return;}
    const saveButton=document.getElementById("settings-save");saveButton.disabled=true;
    const result=await postAction("settings.update",{changes:{
      language:{interface:interfaceLanguage,conversation:document.getElementById("settings-conversation-language").value},
      appearance:{theme:document.getElementById("settings-theme").value,accent_color:accent,background_type:document.getElementById("settings-background-type").value,background_fit:document.getElementById("settings-background-fit").value,background_blur:Number(document.getElementById("settings-background-blur").value),background_opacity:Number(document.getElementById("settings-background-opacity").value),background_position_x:Number(settingsDraft?.appearance?.background_position_x||0),background_position_y:Number(settingsDraft?.appearance?.background_position_y||0),background_zoom:Number(settingsDraft?.appearance?.background_zoom||100),logo_position_x:Number(settingsDraft?.appearance?.logo_position_x||0),logo_position_y:Number(settingsDraft?.appearance?.logo_position_y||0),logo_zoom:Number(settingsDraft?.appearance?.logo_zoom||100),reduced_motion:document.getElementById("settings-reduced-motion").checked,high_contrast:document.getElementById("settings-high-contrast").checked,large_targets:document.getElementById("settings-large-targets").checked,left_handed:document.getElementById("settings-left-handed").checked,visual_voice_cues:document.getElementById("settings-visual-voice-cues").checked,ui_scale:Number(document.getElementById("settings-ui-scale").value),text_scale:Number(document.getElementById("settings-text-scale").value),command_input_visible:document.getElementById("settings-input-visible").checked,status_indicator_visible:document.getElementById("settings-status-visible").checked,logo_visible:document.getElementById("settings-logo-visible").checked,interface_layout:normalizeInterfaceLayout(settingsDraft?.appearance?.interface_layout||settingsCache?.appearance?.interface_layout)},
      assistant:{wake_name:document.getElementById("settings-wake-name").value,preferred_name:document.getElementById("settings-preferred-name").value,wake_word_enabled:document.getElementById("settings-wake-enabled").checked,activation_mode:document.getElementById("settings-wake-enabled").checked?"wake_word":"push_to_talk",context_language_enabled:document.getElementById("settings-context-language").checked,listening_paused:Boolean(settingsDraft?.assistant?.listening_paused),pause_listening_phrase:document.getElementById("settings-pause-listening-phrase").value,resume_listening_phrase:document.getElementById("settings-resume-listening-phrase").value},
      performance:{profile:document.getElementById("settings-performance-profile").value,idle_animation:document.getElementById("settings-idle-animation").checked},
      ghost:{always_on_top:document.getElementById("settings-ghost-topmost").checked},
      startup:{startup_sound:document.getElementById("settings-startup-sound").checked,launch_at_login:document.getElementById("settings-launch-at-login").checked,window_mode:document.getElementById("settings-window-mode").value,start_minimized:document.getElementById("settings-window-mode").value==="minimized",start_in_ghost_mode:document.getElementById("settings-start-ghost").checked},
      approval:{mode:document.getElementById("settings-approval-mode").value},
      computer_use:{action_display:document.getElementById("settings-computer-use-display").value},
      clock:{visible:document.getElementById("settings-clock-visible").checked,use_24_hour:document.getElementById("settings-clock-24h").checked,show_seconds:document.getElementById("settings-clock-seconds").checked,show_date:document.getElementById("settings-clock-date").checked},
      privacy:{cloud_processing_allowed:false},
      sync:{enabled:session?.mode==="account"&&document.getElementById("settings-sync-enabled").checked,settings:true,personalization:true},
      intelligence:{enabled:true,profile:document.getElementById("settings-ai-profile").value,cloud_fallback:false,memory_enabled:document.getElementById("settings-ai-memory").checked,conversation_turns:Number(document.getElementById("settings-ai-context-turns").value)},
      personality:{style:document.getElementById("settings-personality").value},
      media:{alternative_versions:document.getElementById("settings-media-alternatives").value,preferred_volume:Number(document.getElementById("settings-media-volume").value),dj_mode:document.getElementById("settings-media-dj").checked,dj_strategy:document.getElementById("settings-media-dj-strategy").value,autoplay:document.getElementById("settings-media-autoplay").checked,show_album_art:document.getElementById("settings-media-artwork").checked,vinyl_orb:document.getElementById("settings-media-vinyl").checked,local_library:document.getElementById("settings-media-local").checked,online_providers:document.getElementById("settings-media-online").checked,notification_volume:Number(document.getElementById("settings-media-notification-volume").value)},
    }});
    saveButton.disabled=false;
    if(!result.ok){message.textContent=result.error==="local_connection_error"?"Se perdió la conexión local. Los cambios no se aplicaron.":(result.error||"settings_error");return;}
    settingsDraft=null;settingsDirty=false;draftPreview.background=false;draftPreview.logo=false;draftPreview.chat=false;
    applySettings(result.settings); await loadLocale(interfaceLanguage); document.getElementById("language-select").value=interfaceLanguage;
    if(result.settings.sync.enabled&&session?.mode==="account")await syncNow();
    message.textContent=t("settings.saved"); setTimeout(()=>{if(settingsDialog.open)settingsDialog.close();},450);
  }
  document.getElementById("settings-sync-now").addEventListener("click",syncNow);
  function renderApprovalHelp(){const mode=document.getElementById("settings-approval-mode").value,help=document.getElementById("settings-approval-help");help.textContent=mode==="balanced"?"Las consultas y observaciones de solo lectura se permiten; editar, controlar o ejecutar sigue solicitando aprobación.":mode==="full_control"?"Permite lectura y acciones de riesgo bajo o medio. Las acciones de riesgo alto, crítico o denegadas expresamente siempre requieren confirmación.":"ARCHEON preguntará antes de usar herramientas que aún no tengan permiso.";}
  document.getElementById("settings-approval-mode").addEventListener("change",renderApprovalHelp);
  async function toggleListeningPause(){const paused=Boolean((settingsDraft||settingsCache)?.assistant?.listening_paused),result=await postAction(paused?"voice.resume_listening":"voice.pause_listening");if(!result.ok){showNotice(result.error||"No pude cambiar el estado de escucha.","error");return;}settingsCache=normalizeSettings(result.settings);if(settingsDraft)settingsDraft=cloneSettings(settingsCache);applySettings(settingsCache);const button=document.getElementById("settings-listening-toggle");button.textContent=result.paused?"Reanudar escucha ahora":"Pausar escucha ahora";showNotice(result.paused?"Escucha pausada.":"Escucha reanudada.");}
  document.getElementById("settings-listening-toggle").addEventListener("click",toggleListeningPause);
  document.getElementById("settings-ai-memory-clear").addEventListener("click",async()=>{const result=await postAction("intelligence.memory.clear");document.getElementById("settings-message").textContent=result.ok?"✓ Contexto de esta sesión eliminado":(result.error||"memory_clear_error");});
  document.getElementById("settings-accent").addEventListener("change",event=>{document.getElementById("settings-accent-custom-row").hidden=event.target.value!=="custom";previewAccent(event.target.value==="custom"?document.getElementById("settings-accent-custom").value:event.target.value);});
  document.getElementById("settings-accent-custom").addEventListener("input",event=>previewAccent(event.target.value));
  const layoutEditor=document.getElementById("layout-editor"),layoutElement=document.getElementById("layout-editor-element"),layoutColor=document.getElementById("layout-editor-color"),layoutBackground=document.getElementById("layout-editor-background"),layoutBackgroundRow=document.getElementById("layout-editor-background-row"),layoutText=document.getElementById("layout-editor-text"),layoutTextRow=document.getElementById("layout-editor-text-row"),layoutStyle=document.getElementById("layout-editor-style"),layoutStyleRow=document.getElementById("layout-editor-style-row"),layoutChatImageRow=document.getElementById("layout-editor-chat-image-row"),layoutVisible=document.getElementById("layout-editor-visible"),layoutScale=document.getElementById("layout-editor-scale"),layoutScaleValue=document.getElementById("layout-editor-scale-value"),layoutWidth=document.getElementById("layout-editor-width"),layoutWidthValue=document.getElementById("layout-editor-width-value"),layoutWidthRow=document.getElementById("layout-editor-width-row"),layoutHelp=document.getElementById("layout-editor-help"),layoutConfirmDialog=document.getElementById("layout-confirm-dialog");
  let layoutDraft=null,layoutBaseline=null,layoutDrag=null,layoutReturnToSettings=false,layoutConfirmMode="save",layoutChatDirty=false,layoutOuterSettingsDirty=false;
  function layoutIsDirty(){return layoutChatDirty||JSON.stringify(normalizeInterfaceLayout(layoutDraft))!==JSON.stringify(normalizeInterfaceLayout(layoutBaseline));}
  function selectLayoutItem(key){if(!layoutTargets[key])return;layoutElement.value=key;Object.entries(layoutTargets).forEach(([name,node])=>node?.classList.toggle("layout-selected",name===key));const item=normalizeInterfaceLayout(layoutDraft)[key],resizable=resizableLayoutItems.has(key),conversation=key==="conversation";layoutColor.value=item.color||(settingsDraft?.appearance?.accent_color||settingsCache?.appearance?.accent_color||"#00F3FF");layoutBackground.value=item.background||"#0C1217";layoutText.value=item.text_color||"#E5F7FA";layoutStyle.value=item.style;layoutBackgroundRow.hidden=!resizable;layoutTextRow.hidden=!resizable;layoutStyleRow.hidden=!conversation;layoutChatImageRow.hidden=!conversation;layoutVisible.checked=item.visible;layoutVisible.disabled=essentialLayoutItems.has(key);layoutVisible.closest("label").title=layoutVisible.disabled?"Este control es esencial para volver a abrir el menú.":"";layoutScale.value=String(item.scale);layoutScaleValue.textContent=`${Math.round(item.scale)}%`;layoutWidth.value=String(item.width);layoutWidthValue.textContent=`${Math.round(item.width)}%`;layoutWidthRow.hidden=!resizable;}
  function finishLayoutEditor(layout){applyInterfaceLayout(layout);document.body.classList.remove("layout-editing");layoutEditor.hidden=true;Object.values(layoutTargets).forEach(node=>node?.classList.remove("layout-selected"));layoutDraft=null;layoutBaseline=null;layoutDrag=null;layoutChatDirty=false;if(layoutReturnToSettings&&!settingsDialog.open)settingsDialog.showModal();if(settingsDirty){const selector=document.getElementById("settings-accent"),custom=document.getElementById("settings-accent-custom");previewAccent(selector.value==="custom"?custom.value:selector.value);}}
  function beginLayoutEditor(){layoutReturnToSettings=settingsDialog.open;layoutOuterSettingsDirty=settingsDirty;layoutBaseline=normalizeInterfaceLayout(settingsCache?.appearance?.interface_layout);layoutDraft=normalizeInterfaceLayout(settingsDraft?.appearance?.interface_layout||layoutBaseline);layoutChatDirty=false;if(settingsDialog.open)settingsDialog.close();document.body.classList.add("layout-editing");layoutEditor.hidden=false;applyInterfaceLayout(layoutDraft);selectLayoutItem(layoutElement.value||"clock");layoutHelp.textContent=t("layout.help");}
  function showLayoutConfirmation(mode){layoutConfirmMode=mode;const title=document.getElementById("layout-confirm-title"),message=document.getElementById("layout-confirm-message"),stay=document.getElementById("layout-confirm-stay"),accept=document.getElementById("layout-confirm-accept");if(mode==="save"){title.textContent=t("layout.confirm_save_title");message.textContent=t("layout.confirm_save_message");stay.textContent=t("layout.continue");accept.textContent=t("layout.apply");}else if(mode==="discard"){title.textContent=t("layout.confirm_discard_title");message.textContent=t("layout.confirm_discard_message");stay.textContent=t("layout.continue");accept.textContent=t("layout.discard");}else{title.textContent=t("layout.confirm_reset_title");message.textContent=t("layout.confirm_reset_message");stay.textContent=t("layout.cancel");accept.textContent=t("layout.reset_accept");}if(!layoutConfirmDialog.open)layoutConfirmDialog.showModal();}
  document.getElementById("settings-edit-layout").addEventListener("click",beginLayoutEditor);
  layoutElement.addEventListener("change",()=>selectLayoutItem(layoutElement.value));
  layoutColor.addEventListener("input",()=>{if(!layoutDraft)return;layoutDraft[layoutElement.value].color=layoutColor.value.toUpperCase();applyInterfaceLayout(layoutDraft);});
  layoutBackground.addEventListener("input",()=>{if(!layoutDraft||!resizableLayoutItems.has(layoutElement.value))return;layoutDraft[layoutElement.value].background=layoutBackground.value.toUpperCase();applyInterfaceLayout(layoutDraft);});
  layoutText.addEventListener("input",()=>{if(!layoutDraft||!resizableLayoutItems.has(layoutElement.value))return;layoutDraft[layoutElement.value].text_color=layoutText.value.toUpperCase();applyInterfaceLayout(layoutDraft);});
  layoutStyle.addEventListener("change",()=>{if(!layoutDraft||layoutElement.value!=="conversation")return;layoutDraft.conversation.style=layoutStyle.value;applyInterfaceLayout(layoutDraft);});
  document.getElementById("layout-editor-chat-image").addEventListener("click",async()=>{const result=await postAction("appearance.choose",{kind:"chat"});if(!result.ok||result.cancelled)return;settingsDraft=normalizeSettings(result.settings);draftPreview.chat=true;layoutChatDirty=true;const appearance=settingsDraft.appearance||{},stack=document.getElementById("conversation-stack"),resource=`/personalization/chat-preview?token=${encodeURIComponent(runtime.token)}&v=${Date.now()}`;stack.style.setProperty("--chat-background-image",`url("${resource}")`);stack.classList.add("has-chat-background");layoutHelp.textContent="Imagen del chat preparada. Se aplicará únicamente al guardar.";});
  document.getElementById("layout-editor-chat-clear").addEventListener("click",async()=>{const result=await postAction("appearance.clear",{kind:"chat"});if(!result.ok)return;settingsDraft=normalizeSettings(result.settings);draftPreview.chat=false;layoutChatDirty=true;const stack=document.getElementById("conversation-stack");stack.style.removeProperty("--chat-background-image");stack.classList.remove("has-chat-background");layoutHelp.textContent="La imagen del chat se quitará únicamente al guardar.";});
  layoutVisible.addEventListener("change",()=>{if(!layoutDraft||essentialLayoutItems.has(layoutElement.value))return;layoutDraft[layoutElement.value].visible=layoutVisible.checked;applyInterfaceLayout(layoutDraft);selectLayoutItem(layoutElement.value);});
  layoutScale.addEventListener("input",()=>{if(!layoutDraft)return;layoutDraft[layoutElement.value].scale=Number(layoutScale.value);layoutScaleValue.textContent=`${layoutScale.value}%`;applyInterfaceLayout(layoutDraft);});
  layoutWidth.addEventListener("input",()=>{if(!layoutDraft||!resizableLayoutItems.has(layoutElement.value))return;layoutDraft[layoutElement.value].width=Number(layoutWidth.value);layoutWidthValue.textContent=`${layoutWidth.value}%`;applyInterfaceLayout(layoutDraft);});
  Object.entries(layoutTargets).forEach(([key,node])=>{
    if(!node)return;
    node.addEventListener("pointerdown",event=>{if(!document.body.classList.contains("layout-editing")||event.button!==0)return;event.preventDefault();event.stopPropagation();selectLayoutItem(key);const item=layoutDraft[key],rect=node.getBoundingClientRect(),centerX=rect.left+rect.width/2,centerY=rect.top+rect.height/2;item.anchor="viewport";item.left=Math.max(0,Math.min(100,centerX/innerWidth*100));item.top=Math.max(0,Math.min(100,centerY/innerHeight*100));item.x=0;item.y=0;layoutDrag={id:event.pointerId,key,startClientX:event.clientX,startClientY:event.clientY,startCenterX:centerX,startCenterY:centerY,halfWidth:rect.width/2,halfHeight:rect.height/2};applyInterfaceLayout(layoutDraft);node.setPointerCapture(event.pointerId);});
    node.addEventListener("pointermove",event=>{if(!layoutDrag||layoutDrag.id!==event.pointerId||layoutDrag.key!==key)return;const margin=10,centerX=Math.max(layoutDrag.halfWidth+margin,Math.min(innerWidth-layoutDrag.halfWidth-margin,layoutDrag.startCenterX+(event.clientX-layoutDrag.startClientX))),centerY=Math.max(layoutDrag.halfHeight+margin,Math.min(innerHeight-layoutDrag.halfHeight-margin,layoutDrag.startCenterY+(event.clientY-layoutDrag.startClientY)));layoutDraft[key].left=centerX/innerWidth*100;layoutDraft[key].top=centerY/innerHeight*100;applyInterfaceLayout(layoutDraft);});
    const stop=()=>{layoutDrag=null;};node.addEventListener("pointerup",stop);node.addEventListener("pointercancel",stop);
  });
  document.addEventListener("click",event=>{if(document.body.classList.contains("layout-editing")&&event.target.closest("[data-layout-key]")){event.preventDefault();event.stopPropagation();}},true);
  document.getElementById("layout-editor-close").addEventListener("click",()=>{if(layoutIsDirty())showLayoutConfirmation("discard");else finishLayoutEditor(layoutBaseline);});
  document.getElementById("layout-editor-reset").addEventListener("click",()=>showLayoutConfirmation("reset"));
  document.getElementById("layout-editor-save").addEventListener("click",()=>{if(!layoutIsDirty()){layoutHelp.textContent=t("layout.no_changes");return;}showLayoutConfirmation("save");});
  document.getElementById("layout-confirm-stay").addEventListener("click",()=>layoutConfirmDialog.close());
  layoutConfirmDialog.addEventListener("cancel",event=>{event.preventDefault();layoutConfirmDialog.close();});
  document.getElementById("layout-confirm-accept").addEventListener("click",async()=>{const mode=layoutConfirmMode;layoutConfirmDialog.close();if(mode==="reset"){layoutDraft=normalizeInterfaceLayout({});applyInterfaceLayout(layoutDraft);selectLayoutItem(layoutElement.value);layoutHelp.textContent=t("layout.reset_preview");return;}if(mode==="discard"){if(layoutChatDirty)await postAction("appearance.discard",{kind:"chat"});draftPreview.chat=false;if(settingsCache)applySettings(settingsCache);finishLayoutEditor(layoutBaseline);return;}const result=await postAction("settings.update",{changes:{appearance:{interface_layout:normalizeInterfaceLayout(layoutDraft)}}});if(!result.ok){layoutHelp.textContent=result.error==="local_connection_error"?t("layout.connection_error"):(result.error||t("layout.save_error"));return;}draftPreview.chat=false;const persisted=normalizeSettings(result.settings),outerDraft=settingsDraft?cloneSettings(settingsDraft):null;settingsCache=persisted;if(layoutReturnToSettings&&outerDraft){outerDraft.appearance.interface_layout=cloneSettings(persisted.appearance.interface_layout);outerDraft.appearance.chat_background_path=persisted.appearance.chat_background_path;settingsDraft=outerDraft;settingsDirty=layoutOuterSettingsDirty;}else{settingsDraft=cloneSettings(persisted);settingsDirty=false;}applySettings(persisted);finishLayoutEditor(persisted.appearance.interface_layout);showNotice(t("layout.saved"));});
  const cropDialog=document.getElementById("crop-dialog"),cropFrame=document.getElementById("crop-frame"),cropImage=document.getElementById("crop-image"),cropVideo=document.getElementById("crop-video"),cropZoom=document.getElementById("crop-zoom"),cropZoomValue=document.getElementById("crop-zoom-value");
  let cropDraft={kind:"logo",x:0,y:0,zoom:100},cropDrag=null;
  function clampCrop(){const limit=Math.min(40,Math.max(0,((cropDraft.zoom-100)/(2*cropDraft.zoom))*100));cropDraft.x=Math.max(-limit,Math.min(limit,cropDraft.x));cropDraft.y=Math.max(-limit,Math.min(limit,cropDraft.y));}
  function renderCropPreview(){clampCrop();const transform=`scale(${cropDraft.zoom/100}) translate(${cropDraft.x}%,${cropDraft.y}%)`;cropImage.style.transform=transform;cropVideo.style.transform=transform;cropZoom.value=String(cropDraft.zoom);cropZoomValue.value=`${cropDraft.zoom}%`;}
  function openCropEditor(kind){
    const appearance=settingsDraft?.appearance||settingsCache?.appearance||{};
    const available=kind==="logo"?appearance.logo_path:appearance.background_path;
    if(!available){showNotice(kind==="logo"?"Primero elige un logo.":"Primero elige una imagen o GIF de fondo.","error");return;}
    cropDraft={kind,x:Number(appearance[`${kind}_position_x`]||0),y:Number(appearance[`${kind}_position_y`]||0),zoom:Number(appearance[`${kind}_zoom`]||100)};
    const resourceKind=kind==="logo"?"logo":"background";
    const preview=draftPreview[resourceKind]?"-preview":"";
    const resource=`/personalization/${resourceKind}${preview}?token=${encodeURIComponent(runtime.token)}&v=${settingsCache?.sync?.version||0}`;
    const videoBackground=(kind!=="logo"&&appearance.background_type==="video")||(kind==="logo"&&/\.(?:mp4|webm|m4v)$/i.test(available));
    cropImage.hidden=videoBackground;cropVideo.hidden=!videoBackground;
    if(videoBackground){cropImage.removeAttribute("src");cropVideo.src=resource;cropVideo.play().catch(()=>{});}else{cropVideo.pause();cropVideo.removeAttribute("src");cropImage.src=resource;}
    cropFrame.classList.toggle("logo-crop",kind==="logo");cropFrame.classList.toggle("background-crop",kind!=="logo");
    document.getElementById("crop-title").textContent=kind==="logo"?"Ajustar logo del orbe":"Ajustar fondo";renderCropPreview();cropDialog.showModal();
  }
  cropFrame.addEventListener("pointerdown",event=>{event.preventDefault();cropDrag={id:event.pointerId,x:event.clientX,y:event.clientY,startX:cropDraft.x,startY:cropDraft.y};cropFrame.setPointerCapture(event.pointerId);cropFrame.classList.add("dragging");});
  cropFrame.addEventListener("pointermove",event=>{if(!cropDrag||cropDrag.id!==event.pointerId)return;const rect=cropFrame.getBoundingClientRect();cropDraft.x=cropDrag.startX+(event.clientX-cropDrag.x)/rect.width*100/cropDraft.zoom*100;cropDraft.y=cropDrag.startY+(event.clientY-cropDrag.y)/rect.height*100/cropDraft.zoom*100;renderCropPreview();});
  const stopCropDrag=()=>{cropDrag=null;cropFrame.classList.remove("dragging");};cropFrame.addEventListener("pointerup",stopCropDrag);cropFrame.addEventListener("pointercancel",stopCropDrag);
  cropZoom.addEventListener("input",()=>{cropDraft.zoom=Number(cropZoom.value);renderCropPreview();});
  document.getElementById("crop-reset").addEventListener("click",()=>{cropDraft.x=0;cropDraft.y=0;cropDraft.zoom=100;renderCropPreview();});
  document.getElementById("crop-close").addEventListener("click",()=>{cropVideo.pause();cropDialog.close();});
  document.getElementById("crop-save").addEventListener("click",()=>{const prefix=cropDraft.kind;if(!settingsDraft)settingsDraft=structuredClone(settingsCache);settingsDraft.appearance[`${prefix}_position_x`]=cropDraft.x;settingsDraft.appearance[`${prefix}_position_y`]=cropDraft.y;settingsDraft.appearance[`${prefix}_zoom`]=cropDraft.zoom;settingsDirty=true;cropVideo.pause();cropDialog.close();});
  [["settings-choose-image","image"],["settings-choose-video","video"],["settings-choose-logo","logo"]].forEach(([id,kind])=>document.getElementById(id).addEventListener("click",async()=>{const result=await postAction("appearance.choose",{kind});if(result.ok&&!result.cancelled){settingsDraft=result.settings;settingsDirty=true;const slot=kind==="logo"?"logo":"background";draftPreview[slot]=true;document.getElementById("settings-background-type").value=settingsDraft.appearance.background_type;openCropEditor(slot);}}));
  document.getElementById("settings-adjust-background").addEventListener("click",()=>openCropEditor("background"));
  document.getElementById("settings-adjust-logo").addEventListener("click",()=>openCropEditor("logo"));
  document.getElementById("settings-clear-visuals").addEventListener("click",async()=>{const result=await postAction("appearance.clear");if(result.ok){settingsDraft=result.settings;settingsDirty=true;draftPreview.background=false;draftPreview.logo=false;document.getElementById("settings-background-type").value="default";showNotice("El restablecimiento se aplicará al guardar.");}});
  async function toggleCommandInput(){
    const visible=settingsCache?.appearance?.command_input_visible!==false;
    const result=await postAction("settings.update",{changes:{appearance:{command_input_visible:!visible}}});
    if(!result.ok){showNotice(result.error||"No pude cambiar la barra de comandos.","error");return;}
    applySettings(result.settings);if(!visible)document.getElementById("command-input").focus();
  }
  document.getElementById("command-toggle").addEventListener("click",toggleCommandInput);
  document.addEventListener("keydown",event=>{if(event.ctrlKey&&event.altKey&&event.key.toLocaleLowerCase()==="i"){event.preventDefault();toggleCommandInput();}if(event.ctrlKey&&event.altKey&&event.key.toLocaleLowerCase()==="m"){event.preventDefault();toggleListeningPause();}});
  document.getElementById("ghost-button").addEventListener("click", () => postAction("window.ghost"));
  document.getElementById("voice-button").addEventListener("click", async () => {
    const stopping = ["listening","transcribing","thinking","speaking"].some((state)=>document.body.classList.contains(`state-${state}`));
    const result=await postAction(stopping ? "voice.stop" : "voice.listen");
    if(!result.ok){showNotice(messages[`error.${result.error}`]||"No pude iniciar el micrófono.","error");setState("error","state.error_detail");}
  });
  document.getElementById("menu-button").addEventListener("click", () => document.getElementById("sidebar").classList.add("open"));
  document.getElementById("close-menu").addEventListener("click", () => document.getElementById("sidebar").classList.remove("open"));

  document.getElementById("music-open").addEventListener("click", async () => {
    document.getElementById("sidebar").classList.remove("open");
    musicPanel.classList.add("active");musicPanel.setAttribute("aria-hidden","false");
  });
  document.getElementById("music-choose").addEventListener("click", async () => {
    const loaded = await postAction("media.choose");
    if (loaded.cancelled) return;
    if (!loaded.ok) { document.getElementById("result").textContent=loaded.error||"media_load_error"; return; }
    await postAction("media.play");
  });
  const launcherDialog=document.getElementById("launcher-dialog"),launcherList=document.getElementById("launcher-list");let launcherItems=[],launcherCategory="all";
  function renderLauncher(){const query=(document.getElementById("launcher-search").value||"").toLocaleLowerCase(),matches=launcherItems.filter(item=>item.name.toLocaleLowerCase().includes(query)),visible=matches.slice(0,60);launcherList.replaceChildren();visible.forEach(item=>{const row=document.createElement("div");row.className="launcher-item";const copy=document.createElement("div"),name=document.createElement("strong"),meta=document.createElement("small"),favorite=document.createElement("button"),alias=document.createElement("button"),open=document.createElement("button");name.textContent=item.name;meta.textContent=`${item.kind} · ${item.source}`;copy.append(name,meta);favorite.textContent=item.favorite?"★":"☆";favorite.title="Favorito";favorite.addEventListener("click",async()=>{await postAction("launcher.favorite",{id:item.id,enabled:!item.favorite});item.favorite=!item.favorite;renderLauncher();});alias.textContent="Alias";alias.addEventListener("click",async()=>{const value=prompt(`Alias de voz para ${item.name}`,item.name);if(value)await postAction("launcher.alias",{id:item.id,alias:value});});open.textContent="Abrir";open.addEventListener("click",async()=>{const result=await postAction("launcher.open",{id:item.id});document.getElementById("launcher-message").textContent=result.ok?`Abriendo ${item.name}`:(result.error||"launch_failed");});row.append(copy,favorite,alias,open);launcherList.append(row);});if(matches.length>visible.length)document.getElementById("launcher-message").textContent=`Mostrando ${visible.length} de ${matches.length}; escribe para filtrar`;}
  async function loadLauncher(category="all",force=false){launcherCategory=category;document.getElementById("launcher-message").textContent="Detectando fuentes conocidas…";const result=await postAction("launcher.list",{category,force});launcherItems=result.items||[];document.getElementById("launcher-message").textContent=`${launcherItems.length} elementos`;renderLauncher();}
  document.getElementById("launcher-open").addEventListener("click",()=>{document.getElementById("sidebar").classList.remove("open");launcherDialog.showModal();loadLauncher("all",true);});
  document.getElementById("orb-launcher").addEventListener("click",()=>{launcherDialog.showModal();loadLauncher("all",true);});
  document.getElementById("launcher-add").addEventListener("click",async()=>{const result=await postAction("launcher.add_custom",{});if(result.cancelled)return;if(!result.ok){document.getElementById("launcher-message").textContent=result.error||"No se pudo añadir el atajo";return;}await loadLauncher(launcherCategory);});
  document.getElementById("launcher-close").addEventListener("click",()=>launcherDialog.close());document.getElementById("launcher-search").addEventListener("input",renderLauncher);document.querySelectorAll("[data-launcher-category]").forEach(button=>button.addEventListener("click",()=>loadLauncher(button.dataset.launcherCategory)));

  const cloudDialog=document.getElementById("cloud-dialog"),cloudFiles=document.getElementById("cloud-files"),cloudDevices=document.getElementById("cloud-devices"),cloudMessage=document.getElementById("cloud-message");
  function cloudEmpty(text,{mascot=true}={}){const node=document.createElement("section"),copy=document.createElement("p");node.className="cloud-empty";copy.textContent=text;if(mascot){const image=document.createElement("img");image.src="/archeon-cloud-mascot.png";image.alt="";node.append(image);}node.append(copy);return node;}
  function cloudItem(copyText,metaText,actions=[]){const row=document.createElement("article"),copy=document.createElement("div"),title=document.createElement("strong"),meta=document.createElement("small"),buttons=document.createElement("div");row.className="cloud-item";copy.className="cloud-item-copy";buttons.className="cloud-item-actions";title.textContent=copyText;meta.textContent=metaText;copy.append(title,meta);actions.forEach(([label,handler])=>{const button=document.createElement("button");button.type="button";button.textContent=label;button.addEventListener("click",handler);buttons.append(button);});row.append(copy,buttons);return row;}
  async function openCloudFile(file,preview){cloudMessage.textContent=preview?"Preparando vista previa…":"Preparando descarga…";const result=await postAction(preview?"cloud.files.preview":"cloud.files.download",{file_id:file.id});if(!result.ok){cloudMessage.textContent=result.error||"No se pudo abrir el archivo.";return;}const binary=atob(result.file.content_base64),bytes=new Uint8Array(binary.length);for(let index=0;index<binary.length;index+=1)bytes[index]=binary.charCodeAt(index);const url=URL.createObjectURL(new Blob([bytes],{type:result.file.mime_type})),link=document.createElement("a");link.href=url;link.target="_blank";if(!preview)link.download=result.file.display_name;link.click();cloudMessage.textContent=preview?"Vista previa abierta.":"Descarga preparada.";setTimeout(()=>URL.revokeObjectURL(url),60000);}
  async function loadCloud(){cloudMessage.textContent="Sincronizando…";cloudFiles.replaceChildren(cloudEmpty("Cargando archivos…"));cloudDevices.replaceChildren(cloudEmpty("Cargando dispositivos…"));const [fileResult,deviceResult]=await Promise.all([postAction("cloud.files.list"),postAction("cloud.devices.list")]);if(!fileResult.ok||!deviceResult.ok){const error=fileResult.error||deviceResult.error||"cloud_unavailable",message=error==="account_session_required"?"ARCHEON Cloud no disponible sin una cuenta activa.":error;cloudMessage.textContent=message;cloudFiles.replaceChildren(cloudEmpty("No se pudieron cargar los archivos."));cloudDevices.replaceChildren(cloudEmpty("No se pudieron cargar los dispositivos."));showMascotError(message);return;}const devices=deviceResult.devices||[],deviceNames=new Map(devices.map(item=>[item.id,item.display_name]));document.getElementById("cloud-file-count").textContent=String((fileResult.files||[]).length);document.getElementById("cloud-device-count").textContent=String(devices.length);cloudFiles.replaceChildren(...((fileResult.files||[]).length?(fileResult.files||[]).map(file=>{const created=file.created_at?new Date(file.created_at).toLocaleString():"Fecha no disponible",source=deviceNames.get(file.uploader_device_id)||"Este dispositivo",actions=[];if(file.preview_allowed)actions.push(["Previsualizar",()=>openCloudFile(file,true)]);actions.push(["Descargar",()=>openCloudFile(file,false)],["Eliminar",async()=>{if(!confirm(`¿Eliminar ${file.display_name} de ARCHEON Cloud?`))return;const result=await postAction("cloud.files.delete",{file_id:file.id});cloudMessage.textContent=result.ok?"Archivo eliminado.":(result.error||"No se pudo eliminar.");if(result.ok)await loadCloud();}]);return cloudItem(file.display_name,`${file.mime_type} · ${formatBytes(file.byte_size)} · ${created} · ${source}`,actions);}):[cloudEmpty("Todavía no hay archivos en ARCHEON Cloud.")]));cloudDevices.replaceChildren(...(devices.length?devices.map(device=>cloudItem(device.display_name,`${device.platform} · ${device.remote_control_enabled?"Control remoto habilitado":"Control remoto desactivado"}`)): [cloudEmpty("No hay dispositivos registrados.")]));cloudMessage.textContent="Sincronización completada.";}
  document.getElementById("cloud-open").addEventListener("click",()=>{document.getElementById("sidebar").classList.remove("open");if(session?.mode!=="account"){showNotice("ARCHEON Cloud no disponible sin una cuenta activa.","error");return;}cloudDialog.showModal();loadCloud();});
  document.getElementById("cloud-close").addEventListener("click",()=>cloudDialog.close());document.getElementById("cloud-refresh").addEventListener("click",loadCloud);
  document.getElementById("cloud-file-input").addEventListener("change",async event=>{const file=event.target.files[0];if(!file)return;cloudMessage.textContent="Subiendo…";try{const response=await fetch(`/api/cloud-file?name=${encodeURIComponent(file.name)}`,{method:"POST",headers:{"X-Archeon-Token":runtime.token,"X-Archeon-Session":sessionToken(),"Content-Type":file.type||"application/octet-stream"},body:file}),value=await response.json();cloudMessage.textContent=response.ok&&value.ok?"Archivo subido y verificado.":(value.error||"No se pudo subir el archivo.");if(response.ok&&value.ok)await loadCloud();}catch(_){cloudMessage.textContent="No se pudo conectar con ARCHEON Cloud.";}event.target.value="";});

  const requestedView=new URLSearchParams(location.search).get("view");
  if(requestedView==="launcher"||requestedView==="launcher-add"){launcherDialog.showModal();loadLauncher("all",true);if(requestedView==="launcher-add")setTimeout(()=>document.getElementById("launcher-add").click(),250);}
  if(requestedView==="settings")setTimeout(()=>document.getElementById("settings-open").click(),0);
  if(requestedView==="cloud")setTimeout(()=>document.getElementById("cloud-open").click(),0);
  async function invokeMediaAction(action,payload={}){const value=await postAction(action,payload);if(value.ok&&value.media)renderMediaSession(value.media);else if(!value.ok)showNotice(value.error||"No pude controlar la reproducción.","error");return value;}
  document.getElementById("music-play").addEventListener("click", () => invokeMediaAction(document.body.classList.contains("state-paused")?"media.resume":"media.play"));
  document.getElementById("music-pause").addEventListener("click", () => invokeMediaAction("media.pause"));
  document.getElementById("music-stop").addEventListener("click", () => invokeMediaAction("media.stop"));
  document.getElementById("music-next").addEventListener("click", () => invokeMediaAction("media.next"));
  document.getElementById("music-previous").addEventListener("click", () => invokeMediaAction("media.previous"));
  document.getElementById("music-seek").addEventListener("change", (event) => invokeMediaAction("media.seek", {position_ms:Number(event.target.value)}));
  let mediaVolumeTimer=0;
  const applyMediaVolume=(event)=>{clearTimeout(mediaVolumeTimer);const volume=Number(event.target.value)/100;mediaVolumeTimer=setTimeout(()=>invokeMediaAction("media.volume",{volume}),70);};
  document.getElementById("music-volume").addEventListener("input",applyMediaVolume);
  document.getElementById("music-volume").addEventListener("change",applyMediaVolume);
  const youtubeDialog=document.getElementById("youtube-player-dialog");let youtubePlayer=null,youtubeApiPromise=null,youtubePendingTrack=null,youtubeClockTimer=null;
  function loadYouTubeApi(){if(window.YT?.Player)return Promise.resolve(window.YT);if(youtubeApiPromise)return youtubeApiPromise;youtubeApiPromise=new Promise((resolve,reject)=>{const previous=window.onYouTubeIframeAPIReady;window.onYouTubeIframeAPIReady=()=>{if(typeof previous==="function")previous();resolve(window.YT);};const script=document.createElement("script");script.src="https://www.youtube.com/iframe_api";script.async=true;script.onerror=()=>reject(new Error("youtube_iframe_api_unavailable"));document.head.append(script);});return youtubeApiPromise;}
  function stopYouTubeClock(){if(youtubeClockTimer!==null){clearTimeout(youtubeClockTimer);youtubeClockTimer=null;}}
  function reportYouTubeState(state){if(!youtubePlayer)return;let position=0,duration=0;try{position=Math.round((youtubePlayer.getCurrentTime()||0)*1000);duration=Math.round((youtubePlayer.getDuration()||0)*1000);}catch(_){}postAction("media.web_state",{state,position_ms:position,duration_ms:duration}).catch(()=>{});}
  function scheduleYouTubeClock(){stopYouTubeClock();const tick=()=>{reportYouTubeState("playing");youtubeClockTimer=setTimeout(tick,500);};youtubeClockTimer=setTimeout(tick,500);}
  function handleYouTubeState(event){const states=window.YT?.PlayerState||{};stopYouTubeClock();if(event.data===states.PLAYING){reportYouTubeState("playing");scheduleYouTubeClock();}else if(event.data===states.PAUSED)reportYouTubeState("paused");else if(event.data===states.BUFFERING)reportYouTubeState("buffering");else if(event.data===states.ENDED)reportYouTubeState("ended");}
  async function openOfficialYouTube(track){const videoId=String(track?.external_id||"");if(!/^[A-Za-z0-9_-]{6,20}$/.test(videoId)){showNotice("El resultado de YouTube no contiene un identificador válido.","error");return;}youtubePendingTrack=track;document.getElementById("youtube-player-title").textContent=[track.title,track.artist].filter(Boolean).join(" — ");if(!youtubeDialog.open)youtubeDialog.showModal();try{await loadYouTubeApi();if(youtubePlayer){youtubePlayer.loadVideoById(videoId);return;}youtubePlayer=new window.YT.Player("youtube-player",{width:"100%",height:"100%",videoId,playerVars:{controls:1,enablejsapi:1,playsinline:1,origin:location.origin},events:{onReady:event=>{event.target.playVideo();reportYouTubeState("buffering");},onStateChange:handleYouTubeState,onAutoplayBlocked:()=>showNotice("Pulsa reproducir en el reproductor oficial de YouTube.")}});}catch(error){showNotice(error.message||"No pude cargar el reproductor oficial de YouTube.","error");}}
  function commandOfficialYouTube(payload){if(!youtubePlayer)return;const command=payload?.command;try{if(command==="play")youtubePlayer.playVideo();else if(command==="pause")youtubePlayer.pauseVideo();else if(command==="stop")youtubePlayer.stopVideo();else if(command==="seek")youtubePlayer.seekTo(Number(payload.position_ms||0)/1000,true);else if(command==="volume")youtubePlayer.setVolume(Math.round(Number(payload.volume||0)*100));}catch(_){}if(command==="stop"){stopYouTubeClock();if(youtubeDialog.open)youtubeDialog.close();}}
  document.getElementById("youtube-player-close").addEventListener("click",async()=>{await invokeMediaAction("media.pause");stopYouTubeClock();youtubeDialog.close();});
  youtubeDialog.addEventListener("cancel",event=>{event.preventDefault();document.getElementById("youtube-player-close").click();});
  const agentControl=document.getElementById("agent-control"),agentPause=document.getElementById("agent-pause");
  document.getElementById("agent-collapse").addEventListener("click",()=>agentControl.classList.toggle("collapsed"));
  agentPause.addEventListener("click",async()=>{const paused=agentPause.dataset.paused!=="true",value=await postAction(paused?"agent.pause":"agent.resume");if(value.ok){agentPause.dataset.paused=String(paused);agentPause.textContent=paused?"Continuar":"Pausa";}});
  document.getElementById("agent-stop").addEventListener("click",async()=>{document.getElementById("agent-step").textContent="Deteniendo y liberando teclado y ratón…";const result=await postAction("agent.stop");document.getElementById("agent-step").textContent=result.ok?"Detenido · entradas liberadas":(result.error||"No pude detener la tarea");});

  let commandStartedAt=0,firstVisibleReported=false;
  function reportFirstVisible(correlationId,stage){
    if(firstVisibleReported||!commandStartedAt)return;
    firstVisibleReported=true;
    requestAnimationFrame(()=>postAction("telemetry.stage",{stage,correlation_id:correlationId||"",elapsed_ms:performance.now()-commandStartedAt}));
  }

  document.getElementById("command-form").addEventListener("submit", async (event) => {
    event.preventDefault(); const input=document.getElementById("command-input"); const result=document.getElementById("result"); const text=input.value.trim(); if(!text)return;
    document.getElementById("context-reply").hidden=false;document.getElementById("context-user").textContent=text;result.textContent="";
    input.value="";input.style.height="";
    commandStartedAt=performance.now();firstVisibleReported=false;input.disabled=true; setState("thinking","state.thinking_detail");
    try { const response=await fetch("/api/command",{method:"POST",headers:headers(),body:JSON.stringify({text,attachments:requestAttachments.map(item=>item.id)})}); const value=await response.json(); if(!response.ok||!value.ok){const message=value.message||messages[`error.${value.error}`]||"No pude procesar esa solicitud.";showNotice(message,"error");showMascotError(message);setState("error","state.error_detail");return;} renderAssistantText(result,value.message);renderArtifactPreviews(value.data?.artifacts||[]);reportFirstVisible(value.correlation_id,"first_visible_response");if(value.attachments_consumed){requestAttachments.forEach(item=>{if(item.preview_url)URL.revokeObjectURL(item.preview_url);});requestAttachments.splice(0);renderAttachments();} }
    catch(_error){const message="ARCHEON perdió la conexión local. Puedes editar y reenviar desde el mensaje anterior.";showNotice(message,"error",true);showMascotError(message);setState("error","state.error_detail");}
    finally{input.disabled=false;input.focus();setState("idle","state.ready");}
  });

  const eventStates = {"speech.listening.started":"listening","speech.transcription.started":"transcribing","assistant.processing.started":"thinking","tool.execution.started":"executing","assistant.speaking.started":"speaking"};
  function connectEvents() {
    if (events || !sessionToken()) return;
    events = new EventSource(`/events?token=${encodeURIComponent(runtime.token)}&session=${encodeURIComponent(sessionToken())}`);
    Object.entries(eventStates).forEach(([eventName,state]) => events.addEventListener(eventName,()=>{if(eventName==="assistant.processing.started"&&!commandStartedAt){commandStartedAt=performance.now();firstVisibleReported=false;}setState(state,`state.${state}_detail`);}));
    events.addEventListener("speech.audio.level",(message)=>{const level=JSON.parse(message.data).payload?.level||0;document.querySelectorAll(".amplitude i").forEach((bar,index)=>{bar.style.height=`${5+level*(10+(index%3)*8)}px`;});});
    events.addEventListener("audio.input.test.started",()=>{document.getElementById("voice-input-test-status").textContent="Habla durante tres segundos…";});
    events.addEventListener("audio.input.test.completed",message=>{const payload=JSON.parse(message.data).payload||{};document.getElementById("voice-input-level").value=payload.peak||0;document.getElementById("voice-input-test-status").textContent=`Prueba terminada · pico ${Math.round((payload.peak||0)*100)}%`;});
    events.addEventListener("audio.input.test.error",()=>{document.getElementById("voice-input-test-status").textContent="No pude acceder al micrófono.";});
    events.addEventListener("speech.audio.level",message=>{if(voiceDialog.open)document.getElementById("voice-input-level").value=JSON.parse(message.data).payload?.level||0;});
    events.addEventListener("speech.transcription.completed",(message)=>{const text=JSON.parse(message.data).payload?.text||"";document.getElementById("context-reply").hidden=false;document.getElementById("context-user").textContent=text;document.getElementById("result").textContent="";});
    events.addEventListener("speech.dictation.completed",message=>{const text=JSON.parse(message.data).payload?.text||"";commandInput.value=[commandInput.value.trim(),text].filter(Boolean).join(" ");commandInput.dispatchEvent(new Event("input"));commandInput.focus();dictateButton.classList.remove("active");dictateButton.title="Dictar sin enviar";});
    events.addEventListener("speech.dictation.error",()=>{dictateButton.classList.remove("active");dictateButton.title="Dictar sin enviar";showNotice("No pude transcribir el dictado.","error");});
    events.addEventListener("assistant.processing.completed",(message)=>{const payload=JSON.parse(message.data).payload||{};document.getElementById("context-reply").hidden=false;renderAssistantText(document.getElementById("result"),payload.message||"");});
    events.addEventListener("assistant.response.delta",message=>{const envelope=JSON.parse(message.data),delta=envelope.payload?.delta||"";if(!delta)return;document.getElementById("context-reply").hidden=false;document.getElementById("result").append(document.createTextNode(delta));reportFirstVisible(envelope.correlation_id,"first_visible_token");});
    events.addEventListener("assistant.speaking.ended",()=>{if(!document.body.classList.contains("state-listening"))setState("idle","state.ready");});
    events.addEventListener("voice.preview.error",message=>{const error=JSON.parse(message.data).payload?.error||"tts_error";document.getElementById("voice-model-detail").textContent=`Error de salida: ${error}`;showNotice("No se pudo reproducir la prueba de voz.","error");});
    events.addEventListener("voice.cycle.completed",()=>setState("idle","state.ready"));
    events.addEventListener("voice.cycle.cancelled",()=>setState("idle","state.ready"));
    events.addEventListener("voice.cycle.error",(message)=>{const error=JSON.parse(message.data).payload?.error||"voice_error";showNotice(messages[`error.${error}`]||"No pude completar la escucha.","error");setState("error","state.error_detail");});
    events.addEventListener("wake.monitor.error",(message)=>{const payload=JSON.parse(message.data).payload||{},button=document.getElementById("voice-button");button.disabled=false;button.title=payload.error||"Wake Word no disponible";button.lastElementChild.textContent="PULSA PARA HABLAR · WAKE EN REVISIÓN";});
    events.addEventListener("wake.audio.level",message=>{const payload=JSON.parse(message.data).payload||{};document.getElementById("wake-diag-level").value=payload.level||0;document.getElementById("wake-diag-frames").textContent=String(payload.frames||0);document.getElementById("wake-diag-stream").textContent="ACTIVE · RECEIVING";document.getElementById("wake-diag-detector").textContent="RUNNING";});
    events.addEventListener("wake.candidate.rejected",message=>{const payload=JSON.parse(message.data).payload||{};document.getElementById("wake-diag-candidate").textContent=payload.candidate||"(sin transcripción)";});
    events.addEventListener("wake.speaker.rejected",message=>{const payload=JSON.parse(message.data).payload||{};if(voiceDialog.open)document.getElementById("speaker-enrollment-status").textContent=`Voz no autorizada · coincidencia ${Math.round((payload.confidence||0)*100)}%`;if(settingsCache?.voice?.speaker_rejection_feedback==="visual")showNotice("ARCHEON ignoró una voz no autorizada.");});
    events.addEventListener("speaker.enrollment.sample.requested",message=>{const payload=JSON.parse(message.data).payload||{};document.getElementById("speaker-enrollment-status").textContent=`Muestra ${payload.index} de ${payload.total}: habla con naturalidad.`;});
    events.addEventListener("speaker.enrollment.sample.completed",message=>{const payload=JSON.parse(message.data).payload||{};document.getElementById("speaker-enrollment-status").textContent=`Muestra ${payload.index} de ${payload.total} guardada temporalmente.`;});
    events.addEventListener("speaker.enrollment.completed",async()=>{document.getElementById("speaker-enrollment-status").textContent="Voz registrada. El audio temporal fue descartado.";const result=await postAction("voice.catalog");if(result.ok)renderSpeakerProfiles(result.voice.configuration.speaker_profiles||[]);});
    events.addEventListener("speaker.enrollment.failed",message=>{document.getElementById("speaker-enrollment-status").textContent=JSON.parse(message.data).payload?.error||"No pude completar el registro de voz.";});
    events.addEventListener("wake.detected",()=>{document.getElementById("wake-diag-activation").textContent=new Date().toLocaleString();setState("listening","state.listening_detail");});
    events.addEventListener("music.started",(message)=>{const track=JSON.parse(message.data).payload||{};art.classList.add("cover-changing");renderMediaSession({state:"playing",track,position_ms:0});setTimeout(()=>art.classList.remove("cover-changing"),120);});
    events.addEventListener("music.buffering",(message)=>{const track=JSON.parse(message.data).payload||{};renderMediaSession({state:"buffering",track,position_ms:0});});
    events.addEventListener("music.resolving",message=>{const phase=(JSON.parse(message.data).payload||{}).phase;showNotice(phase==="prepare"?"Preparando reproducción…":"Buscando la mejor versión…");});
    events.addEventListener("music.web.requested",message=>openOfficialYouTube(JSON.parse(message.data).payload||{}));
    events.addEventListener("music.web.command",message=>commandOfficialYouTube(JSON.parse(message.data).payload||{}));
    events.addEventListener("music.paused",message=>renderMediaSession(JSON.parse(message.data).payload||{}));
    events.addEventListener("music.resumed",message=>renderMediaSession(JSON.parse(message.data).payload||{}));
    events.addEventListener("music.seeked",(message)=>{const payload=JSON.parse(message.data).payload||{};document.getElementById("music-seek").value=payload.position_ms||0;});
    events.addEventListener("music.volume.changed",message=>{const payload=JSON.parse(message.data).payload||{};if(Number.isFinite(Number(payload.volume)))document.getElementById("music-volume").value=String(Math.round(Number(payload.volume)*100));});
    events.addEventListener("music.stopped",()=>renderMediaSession({state:"stopped",track:null}));
    const agentUpdate=message=>{const payload=JSON.parse(message.data).payload||{};agentControl.hidden=false;document.getElementById("agent-goal").textContent=payload.goal||"Tarea activa";document.getElementById("agent-step").textContent=payload.step_description||`${payload.current_step||0} / ${payload.step_count||0}`;};
    events.addEventListener("agent.visual.updated",message=>{const payload=JSON.parse(message.data).payload||{},visual=document.getElementById("agent-visual"),application=payload.application||{},windowInfo=payload.window||{},target=payload.target||{};visual.hidden=false;agentControl.hidden=false;document.getElementById("agent-app").textContent=application.name||windowInfo.process_name||"Aplicación local";document.getElementById("agent-target").textContent=target.name||target.label||payload.action||"Ventana activa";document.getElementById("agent-method").textContent=`${payload.method||"UI Automation"}${payload.confidence?` · ${Math.round(payload.confidence*100)}%`:""}`;document.getElementById("agent-result").textContent=payload.verified?"Verificado":payload.ok?"Ejecutado":"Falló";if(payload.preview_revision){document.getElementById("agent-preview").src=`/personalization/control-preview?token=${encodeURIComponent(runtime.token)}&v=${payload.preview_revision}`;}});
    ["agent.task.started","agent.step.started","agent.step.retry","agent.step.verified"].forEach(name=>events.addEventListener(name,agentUpdate));
    events.addEventListener("agent.task.paused",()=>{agentControl.hidden=false;document.getElementById("agent-step").textContent="En pausa";agentPause.dataset.paused="true";agentPause.textContent="Continuar";});
    events.addEventListener("agent.task.resumed",()=>{agentPause.dataset.paused="false";agentPause.textContent="Pausa";});
    ["agent.task.completed","agent.task.failed","agent.task.cancelled"].forEach(name=>events.addEventListener(name,message=>{agentUpdate(message);setTimeout(()=>{agentControl.hidden=true;agentPause.dataset.paused="false";agentPause.textContent="Pausa";},1800);}));
  }

  let clockTimer=null;
  function renderClock(){const now=new Date(),clock=settingsCache?.clock||{},time=now.toLocaleTimeString(document.documentElement.lang,{hour:"2-digit",minute:"2-digit",second:clock.show_seconds?"2-digit":undefined,hour12:!clock.use_24_hour}),date=now.toLocaleDateString(document.documentElement.lang,{weekday:"long",day:"numeric",month:"long"});document.getElementById("clock-time").textContent=time;document.getElementById("clock-date").textContent=date;const preview=document.getElementById("settings-clock-preview");if(preview){const timeNode=document.createElement("span"),dateNode=document.createElement("small");timeNode.textContent=clock.visible===false?"Reloj oculto":time;dateNode.textContent=clock.show_date===false?"Fecha oculta":date;dateNode.hidden=clock.visible===false;preview.replaceChildren(timeNode,dateNode);}}
  function scheduleClock(){if(clockTimer!==null)clearTimeout(clockTimer);renderClock();const unit=settingsCache?.clock?.show_seconds?1000:60000;clockTimer=setTimeout(scheduleClock,unit-(Date.now()%unit));}
  document.getElementById("language-select").addEventListener("change",(event)=>loadLocale(event.target.value));
  document.getElementById("settings-repeat-tour").addEventListener("click",()=>{document.getElementById("settings-dialog").close();openDesktopTour(true);});
  document.getElementById("desktop-tour-skip").addEventListener("click",finishDesktopTour);
  document.getElementById("desktop-tour-next").addEventListener("click",()=>{const copy=desktopTourLanguage();if(desktopTourIndex<0){desktopTourIndex=0;renderDesktopTour();return;}if(desktopTourIndex>=copy.steps.length-1){finishDesktopTour();return;}desktopTourIndex+=1;renderDesktopTour();});
  document.getElementById("desktop-tour-back").addEventListener("click",()=>{desktopTourIndex=Math.max(-1,desktopTourIndex-1);renderDesktopTour();});
  document.getElementById("desktop-tour").addEventListener("cancel",event=>{event.preventDefault();finishDesktopTour();});
  addEventListener("resize",()=>{if(document.getElementById("desktop-tour").open&&desktopTourIndex>=0){const selector=desktopTourLanguage().steps[desktopTourIndex]?.[0];placeDesktopTour(document.querySelector(selector));}});
  document.addEventListener("visibilitychange",()=>{
    const video=document.getElementById("background-video");
    const logoVideo=document.getElementById("core-logo-video");
    document.body.classList.toggle("ui-hidden",document.hidden);
    if(document.hidden){video.pause();logoVideo.pause();if(mediaProgressTimer!==null){clearTimeout(mediaProgressTimer);mediaProgressTimer=null;}}
    else{if(!video.hidden&&settingsCache?.appearance?.background_type==="video"&&(settingsCache.performance?.profile||"eco")!=="eco")video.play().catch(()=>{});if(!logoVideo.hidden&&logoVideo.dataset.active==="true")logoVideo.play().catch(()=>{});postAction("media.status").then(value=>{if(value.ok)renderMediaSession(value.media);});}
  });

  async function loadCurrentSettings(locale) {
    let current=await postAction("settings.get");
    if(!current.ok)return;
    if(current.settings.sync?.enabled&&session?.mode==="account"){
      const synced=await postAction("sync.now");
      if(synced.ok&&synced.settings)current={ok:true,settings:synced.settings};
    }
    applySettings(current.settings);
    const mediaStatus=await postAction("media.status");if(mediaStatus.ok)renderMediaSession(mediaStatus.media);
    if(current.settings.language.interface!==locale){
      document.getElementById("language-select").value=current.settings.language.interface;
      await loadLocale(current.settings.language.interface);
    }
  }

  (async()=>{
    const locale=localStorage.getItem("archeon_locale")||"es";
    document.getElementById("language-select").value=locale;
    try{await loadLocale(locale);}catch(_){} scheduleClock();
    if(!sessionToken()) {
      try {
        const restored=await auth("restore");
        sessionStorage.setItem("archeon_session",restored.session_token);
        if(await requireMfa(restored.session))return;
        enterApplication(restored.session);
        await loadCurrentSettings(locale);
      } catch(_) { showAuthGateway(); }
      return;
    }
    try {
      const response=await fetch("/api/session",{headers:headers()});
      const value=await response.json();
      if(!value.ok){
        sessionStorage.removeItem("archeon_session");
        try{
          const restored=await auth("restore");
          sessionStorage.setItem("archeon_session",restored.session_token);
          if(await requireMfa(restored.session))return;
          enterApplication(restored.session);await loadCurrentSettings(locale);
        }catch(_){showAuthGateway();}
        return;
      }
      if(await requireMfa(value.session))return;
      enterApplication(value.session);
      await loadCurrentSettings(locale);
    } catch(_){sessionStorage.removeItem("archeon_session");showAuthGateway();}
  })();
})();
