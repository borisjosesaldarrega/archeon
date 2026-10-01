(() => {
  "use strict";
  const fail = message => {
    document.body.dataset.runtimeError = message;
    const status = document.getElementById("mobile-boot-status");
    if (status) status.textContent = "No se pudo iniciar la conexión segura de ARCHEON.";
  };
  const loadApp = source => { const app=document.createElement("script"); app.src=source; document.body.append(app); };
  if (window.ArcheonNative?.apiBase) {
    const apiBase=String(window.ArcheonNative.apiBase()||"");
    const publishableKey=String(window.ArcheonNative.publishableKey?.()||"");
    const installationId=String(window.ArcheonNative.installationId?.()||"");
    if (!apiBase || !publishableKey || !installationId) { fail("missing-standalone-config"); return; }
    window.ARCHEON_RUNTIME={token:"android-standalone",apiBase,publishableKey,installationId,standalone:true};
    loadApp("mobile.js");
    return;
  }
  const token = new URLSearchParams(location.search).get("token");
  if (!token) { fail("missing-token"); return; }
  const runtime = document.createElement("script");
  runtime.src = `/runtime-config.js?token=${encodeURIComponent(token)}`;
  runtime.onload = () => loadApp("/mobile.js");
  runtime.onerror = () => fail("unauthorized");
  document.body.append(runtime);
})();
