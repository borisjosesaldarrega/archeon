(() => {
  "use strict";
  const fail = message => {
    document.body.dataset.runtimeError = message;
    const status = document.getElementById("mobile-boot-status");
    if (status) status.textContent = "No se pudo iniciar la conexión segura. Vuelve a abrir ARCHEON en el PC.";
  };
  const token = new URLSearchParams(location.search).get("token");
  if (!token) { fail("missing-token"); return; }
  const runtime = document.createElement("script");
  runtime.src = `/runtime-config.js?token=${encodeURIComponent(token)}`;
  runtime.onload = () => { const app=document.createElement("script"); app.src="/mobile.js"; document.body.append(app); };
  runtime.onerror = () => fail("unauthorized");
  document.body.append(runtime);
})();
