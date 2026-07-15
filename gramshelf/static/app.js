(() => {
  "use strict";

  document.querySelectorAll("[data-copy-secret]").forEach((button) => {
    button.addEventListener("click", async () => {
      const value = document.querySelector("[data-secret-value]")?.textContent?.trim();
      if (!value) return;
      try {
        await navigator.clipboard.writeText(value);
        const original = button.textContent;
        button.textContent = "Copied";
        window.setTimeout(() => { button.textContent = original; }, 1500);
      } catch (_) {
        window.prompt("Copy the API token", value);
      }
    });
  });

  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  const statusNode = document.querySelector("[data-sync-status]");
  if (!statusNode) return;
  let wasRunning = statusNode.textContent.trim().toLowerCase() === "syncing";

  const updateStatus = async () => {
    try {
      const response = await fetch(statusNode.dataset.statusUrl, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) return;
      const payload = await response.json();
      const running = Boolean(payload.running);
      const label = running
        ? "Syncing"
        : payload.status === "never_run"
          ? "Not synced"
          : String(payload.status || "Unknown").replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
      statusNode.textContent = label;
      [...statusNode.classList]
        .filter((name) => name.startsWith("status-") && name !== "status-pill")
        .forEach((name) => statusNode.classList.remove(name));
      statusNode.classList.add(`status-${running ? "running" : payload.status}`);
      if (wasRunning && !running && document.querySelector("[data-reload-when-sync-complete]")) {
        window.location.reload();
      }
      wasRunning = running;
    } catch (_) {
      // The static page remains useful when polling is unavailable.
    }
  };

  window.setInterval(updateStatus, 5000);
})();
