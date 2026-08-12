const API = "/api";

const grid = document.getElementById("channelGrid");
const template = document.getElementById("channelTemplate");
const emptyState = document.getElementById("emptyState");
const channelCount = document.getElementById("channelCount");
const liveClock = document.getElementById("liveClock");

const modal = document.getElementById("channelModal");
const modalTitle = document.getElementById("modalTitle");
const channelForm = document.getElementById("channelForm");
const formAccountId = document.getElementById("formAccountId");
const formDisplayName = document.getElementById("formDisplayName");
const formTopic = document.getElementById("formTopic");
const formFrequency = document.getElementById("formFrequency");
const formTimesList = document.getElementById("formTimesList");
const formAddTime = document.getElementById("formAddTime");
const formWindow = document.getElementById("formWindow");
const formActive = document.getElementById("formActive");

const drawer = document.getElementById("logDrawer");
const logList = document.getElementById("logList");
const logTitle = document.getElementById("logTitle");

const linkedinModal = document.getElementById("linkedinModal");
const linkedinForm = document.getElementById("linkedinForm");
const linkedinAccountId = document.getElementById("linkedinAccountId");
const linkedinClientId = document.getElementById("linkedinClientId");
const linkedinClientSecret = document.getElementById("linkedinClientSecret");
const linkedinSubmitBtn = document.getElementById("linkedinSubmitBtn");

const toast = document.getElementById("toast");

function showToast(message) {
  toast.textContent = message;
  toast.hidden = false;
  setTimeout(() => (toast.hidden = true), 3200);
}

function tickClock() {
  liveClock.textContent = new Date().toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}
setInterval(tickClock, 1000);
tickClock();

async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = { "Content-Type": "application/json", ...options.headers };
  if (method !== "GET") {
    headers["X-CSRFToken"] = getCsrfToken();
  }
  const response = await fetch(`${API}${path}`, {
    credentials: "same-origin", // always send the session/csrf cookies
    headers,
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed (${response.status})`);
  }
  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json") ? response.json() : null;
}

function getCsrfToken() {
  // Read straight from the csrftoken cookie — this is always current for
  // the active session, unlike a hidden form field which can go stale if
  // the page itself was cached from before a login/token rotation.
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  if (match) return decodeURIComponent(match[1]);
  const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
  return input ? input.value : "";
}

function formatFrequency(days) {
  if (days === 1) return "daily";
  if (days === 7) return "weekly";
  return `every ${days} days`;
}

function formatSchedule(account) {
  const times = (account.posting_times || []).join(", ") || "no times set";
  return `${times} · ${formatFrequency(account.frequency_days)} ±${account.posting_window_minutes}m`;
}

async function loadAccounts() {
  const accounts = await api("/accounts");
  grid.innerHTML = "";
  channelCount.textContent = `${accounts.length} channel${accounts.length === 1 ? "" : "s"}`;
  emptyState.hidden = accounts.length > 0;

  for (const [i, account] of accounts.entries()) {
    const node = template.content.cloneNode(true);
    const strip = node.querySelector(".strip");
    strip.dataset.id = account.id;
    strip.dataset.connected = account.is_connected;
    strip.dataset.active = account.is_active;

    node.querySelector(".strip__index").textContent = `CH.${String(i + 1).padStart(2, "0")}`;
    node.querySelector(".status-label").textContent = account.is_connected
      ? (account.is_active ? "Live" : "Paused")
      : "Not connected";
    node.querySelector(".strip__name").textContent = account.display_name;
    node.querySelector(".strip__topic").textContent = account.topic;
    node.querySelector(".strip__time").textContent = formatSchedule(account);

    node.querySelector(".btn--connect").addEventListener("click", () => {
      openLinkedinModal(account);
    });
    node.querySelector(".btn--connect").textContent = account.is_connected
      ? "Reconnect"
      : "Connect LinkedIn";

    node.querySelector(".btn--postnow").addEventListener("click", async (e) => {
      e.target.disabled = true;
      try {
        await api(`/accounts/${account.id}/post-now`, { method: "POST" });
        showToast("Post queued — check the log shortly.");
      } catch (err) {
        showToast(err.message);
      } finally {
        e.target.disabled = false;
      }
    });

    node.querySelector(".btn--edit").addEventListener("click", () => openEditModal(account));
    node.querySelector(".btn--log").addEventListener("click", () => openLog(account));

    grid.appendChild(node);

    // meter — fetch recent posts for this account and render 7 slots
    renderMeter(strip, account.id);
  }
}

async function renderMeter(stripEl, accountId) {
  const meterEl = stripEl.querySelector(".meter");
  let posts = [];
  try {
    posts = await api(`/accounts/${accountId}/posts`);
  } catch (_) { /* ignore, leave meter empty */ }

  const last7 = posts.slice(0, 7).reverse();
  const slots = Array.from({ length: 7 }, (_, i) => last7[i] || null);

  meterEl.innerHTML = "";
  for (const post of slots) {
    const bar = document.createElement("div");
    bar.className = "meter__bar";
    bar.dataset.status = post ? post.status : "none";
    bar.title = post ? `${post.status} — ${new Date(post.scheduled_for).toLocaleDateString()}` : "No post";
    meterEl.appendChild(bar);
  }
}

// ---------- modal ----------

function addTimeRow(value = "") {
  const row = document.createElement("div");
  row.className = "time-row";
  row.innerHTML = `
    <input type="time" class="form-time-input" value="${value}" required>
    <button type="button" class="time-row__remove" title="Remove this time">×</button>
  `;
  row.querySelector(".time-row__remove").addEventListener("click", () => {
    // Always keep at least one row so the form can't be submitted empty.
    if (formTimesList.children.length > 1) {
      row.remove();
    } else {
      row.querySelector("input").value = "";
    }
  });
  formTimesList.appendChild(row);
}

if (formAddTime) formAddTime.addEventListener("click", () => addTimeRow());

function getTimesFromForm() {
  return Array.from(formTimesList.querySelectorAll(".form-time-input"))
    .map((input) => input.value)
    .filter(Boolean);
}

function openNewModal() {
  modalTitle.textContent = "New channel";
  channelForm.reset();
  formAccountId.value = "";
  formFrequency.value = "1";
  formTimesList.innerHTML = "";
  addTimeRow();
  formWindow.value = 30;
  formActive.checked = true;
  modal.classList.add("is-open");
}

function openEditModal(account) {
  modalTitle.textContent = "Edit channel";
  formAccountId.value = account.id;
  formDisplayName.value = account.display_name;
  formTopic.value = account.topic;
  formFrequency.value = String(account.frequency_days);
  formTimesList.innerHTML = "";
  const times = account.posting_times && account.posting_times.length ? account.posting_times : [""];
  times.forEach((t) => addTimeRow(t));
  formWindow.value = account.posting_window_minutes;
  formActive.checked = account.is_active;
  modal.classList.add("is-open");
}

const newChannelBtn = document.getElementById("newChannelBtn");
if (newChannelBtn) newChannelBtn.addEventListener("click", openNewModal);
const modalCancelBtn = document.getElementById("modalCancel");
if (modalCancelBtn) modalCancelBtn.addEventListener("click", () => modal.classList.remove("is-open"));
modal.addEventListener("click", (e) => { if (e.target === modal) modal.classList.remove("is-open"); });

channelForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const posting_times = getTimesFromForm();
  if (posting_times.length === 0) {
    showToast("Add at least one posting time.");
    return;
  }

  const payload = {
    display_name: formDisplayName.value.trim(),
    topic: formTopic.value.trim(),
    posting_times,
    frequency_days: Number(formFrequency.value),
    posting_window_minutes: Number(formWindow.value) || 0,
  };

  try {
    if (formAccountId.value) {
      payload.is_active = formActive.checked;
      await api(`/accounts/${formAccountId.value}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
    } else {
      await api("/accounts", { method: "POST", body: JSON.stringify(payload) });
    }
    modal.classList.remove("is-open");
    await loadAccounts();
  } catch (err) {
    showToast(err.message);
  }
});

// ---------- log drawer ----------

async function openLog(account) {
  logTitle.textContent = `${account.display_name} — post log`;
  logList.innerHTML = "<p>Loading…</p>";
  drawer.classList.add("is-open");

  try {
    const posts = await api(`/accounts/${account.id}/posts`);
    logList.innerHTML = "";
    if (posts.length === 0) {
      logList.innerHTML = "<p>No posts yet for this channel.</p>";
      return;
    }
    for (const post of posts) {
      const entry = document.createElement("div");
      entry.className = "log-entry";
      entry.innerHTML = `
        <div class="log-entry__top">
          <span>${new Date(post.scheduled_for).toLocaleString()}</span>
          <span class="log-entry__status" data-status="${post.status}">${post.status}</span>
        </div>
        ${post.caption ? `<div class="log-entry__caption">${escapeHtml(post.caption)}</div>` : ""}
        ${post.trend_context ? `<div class="log-entry__trend">${escapeHtml(post.trend_context)}</div>` : ""}
        ${post.error_message ? `<div class="log-entry__error">${escapeHtml(post.error_message)}</div>` : ""}
        ${post.image_url ? `<img src="${post.image_url}" alt="">` : ""}
      `;
      logList.appendChild(entry);
    }
  } catch (err) {
    logList.innerHTML = `<p>${escapeHtml(err.message)}</p>`;
  }
}

document.getElementById("logClose").addEventListener("click", () => drawer.classList.remove("is-open"));
drawer.addEventListener("click", (e) => { if (e.target === drawer) drawer.classList.remove("is-open"); });

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ---------- LinkedIn connect modal ----------

function openLinkedinModal(account) {
  linkedinForm.reset();
  linkedinAccountId.value = account.id;
  linkedinModal.classList.add("is-open");
}

document.getElementById("linkedinCancel").addEventListener("click", () => linkedinModal.classList.remove("is-open"));
linkedinModal.addEventListener("click", (e) => { if (e.target === linkedinModal) linkedinModal.classList.remove("is-open"); });

linkedinForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const accountId = linkedinAccountId.value;
  linkedinSubmitBtn.disabled = true;
  linkedinSubmitBtn.textContent = "Checking…";

  try {
    await api(`/accounts/${accountId}/linkedin-credentials`, {
      method: "POST",
      body: JSON.stringify({
        client_id: linkedinClientId.value.trim(),
        client_secret: linkedinClientSecret.value.trim(),
      }),
    });
    // Credentials saved — hand off to LinkedIn's own authorization page.
    // LinkedIn redirects back to /api/linkedin/callback, which redirects
    // back here to "/" with either ?connected=1 or ?linkedin_error=1.
    window.location.href = `${API}/linkedin/connect/${accountId}`;
  } catch (err) {
    showToast(err.message);
    linkedinSubmitBtn.disabled = false;
    linkedinSubmitBtn.textContent = "Connect";
  }
});

// ---------- boot ----------

loadAccounts().catch((err) => showToast(err.message));

(function handleOAuthRedirectResult() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("connected")) {
    showToast("LinkedIn connected — this channel is now live.");
  } else if (params.get("linkedin_error")) {
    showToast(params.get("msg") || "LinkedIn connection failed — check the credentials and try again.");
  }
  if (params.has("connected") || params.has("linkedin_error")) {
    window.history.replaceState({}, "", window.location.pathname);
  }
})();