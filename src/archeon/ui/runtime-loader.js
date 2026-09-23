(() => {
  "use strict";
  const token = new URLSearchParams(window.location.search).get("token");
  if (!token) {
    document.body.dataset.runtimeError = "missing-token";
    return;
  }
  const runtime = document.createElement("script");
  runtime.src = `/runtime-config.js?token=${encodeURIComponent(token)}`;
  runtime.addEventListener("load", () => {
    const application = document.createElement("script");
    application.src = "/app.js";
    document.body.append(application);
  });
  runtime.addEventListener("error", () => {
    document.body.dataset.runtimeError = "unauthorized";
  });
  document.body.append(runtime);
})();
