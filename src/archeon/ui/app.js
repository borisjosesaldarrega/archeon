(() => {
  "use strict";
  const runtime = window.ARCHEON_RUNTIME;
  if (!runtime || !runtime.token) return;

  const headers = {"Content-Type": "application/json", "X-Archeon-Token": runtime.token};
  const stateElement = document.getElementById("assistant-state");
  const art = document.getElementById("core-art");
  const musicPanel = document.getElementById("music-panel");
  const title = document.getElementById("track-title");
  const artist = document.getElementById("track-artist");

  const setState = (state) => {
    for (const name of ["idle", "listening", "thinking", "speaking", "executing", "music", "paused"]) {
      document.body.classList.remove(`state-${name}`);
    }
    document.body.classList.add(`state-${state}`);
    if (stateElement) stateElement.textContent = state.toUpperCase();
  };

  const postAction = async (action) => {
    const response = await fetch("/api/action", {method: "POST", headers, body: JSON.stringify({action})});
    return response.json();
  };

  document.getElementById("ghost-button")?.addEventListener("click", () => postAction("window.ghost"));
  document.getElementById("main-button")?.addEventListener("click", (event) => {
    event.stopPropagation();
    postAction("window.main");
  });

  const audio = document.getElementById("music-audio");
  document.getElementById("music-play")?.addEventListener("click", async () => {
    if (!audio) return;
    await audio.play();
    await postAction("music.started");
  });
  document.getElementById("music-pause")?.addEventListener("click", async () => {
    audio?.pause();
    await postAction("music.paused");
  });
  document.getElementById("music-stop")?.addEventListener("click", async () => {
    if (audio) {
      audio.pause();
      audio.currentTime = 0;
    }
    await postAction("music.stopped");
  });
  audio?.addEventListener("ended", () => postAction("music.stopped"));

  document.getElementById("command-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.getElementById("command-input");
    const result = document.getElementById("result");
    const text = input?.value.trim();
    if (!text) return;
    input.disabled = true;
    try {
      const response = await fetch("/api/command", {method: "POST", headers, body: JSON.stringify({text})});
      const payload = await response.json();
      result.textContent = payload.ok ? `${payload.message}\n${JSON.stringify(payload.data, null, 2)}` : payload.message || payload.error;
    } catch (error) {
      result.textContent = `Error local: ${error.message}`;
    } finally {
      input.disabled = false;
      input.focus();
    }
  });

  const events = new EventSource(`/events?token=${encodeURIComponent(runtime.token)}`);
  for (const state of ["idle", "listening", "thinking", "speaking", "executing"]) {
    events.addEventListener(`assistant.${state}`, () => setState(state));
  }
  events.addEventListener("music.started", (message) => {
    const event = JSON.parse(message.data);
    const payload = event.payload || {};
    if (payload.artwork_url && art) art.src = payload.artwork_url;
    if (title) title.textContent = payload.title || "Pulso de ARCHEON";
    if (artist) artist.textContent = payload.artist || "Audio local bajo demanda";
    musicPanel?.classList.add("active");
    musicPanel?.setAttribute("aria-hidden", "false");
    setState("music");
  });
  events.addEventListener("music.paused", () => setState("paused"));
  events.addEventListener("music.resumed", () => setState("music"));
  events.addEventListener("music.stopped", () => {
    if (art) art.src = "/logo_asitente.png";
    musicPanel?.classList.remove("active");
    if (title) title.textContent = "Sin reproducción activa";
    if (artist) artist.textContent = "";
    setState("idle");
  });
})();
