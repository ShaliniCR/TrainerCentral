// TrainerCentral Frontend Application Logic

let conversationHistory = [];
let countdownSeconds = 0;
let countdownTimer = null;

// DOM Elements
const messagesContainer = document.getElementById("messagesContainer");
const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const sendBtn = document.getElementById("sendBtn");
const clearChatBtn = document.getElementById("clearChatBtn");

const headerTriggerBtn = document.getElementById("headerTriggerBtn");
const headerToggleBtn = document.getElementById("headerToggleBtn");
const sideTriggerBtn = document.getElementById("sideTriggerBtn");

const schedulerDot = document.getElementById("schedulerDot");
const schedulerStatusText = document.getElementById("schedulerStatusText");
const countdownTag = document.getElementById("countdownTag");

const schedStatusVal = document.getElementById("schedStatusVal");
const nextRunVal = document.getElementById("nextRunVal");
const lastRunVal = document.getElementById("lastRunVal");
const runCountVal = document.getElementById("runCountVal");

const fileList = document.getElementById("fileList");
const entryList = document.getElementById("entryList");
const logStream = document.getElementById("logStream");
const refreshFilesBtn = document.getElementById("refreshFilesBtn");
const refreshEntriesBtn = document.getElementById("refreshEntriesBtn");

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  setupEventListeners();
  loadStatus();
  loadFiles();
  loadEntries();
  loadHistory();

  // Poll status every 5 seconds
  setInterval(loadStatus, 5000);
  setInterval(loadHistory, 8000);
});

function setupEventListeners() {
  chatForm.addEventListener("submit", handleChatSubmit);

  // Auto-resize chat input
  chatInput.addEventListener("input", () => {
    chatInput.style.height = "auto";
    chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + "px";
  });

  // Shift+Enter to newline, Enter to submit
  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      chatForm.dispatchEvent(new Event("submit"));
    }
  });

  clearChatBtn.addEventListener("click", () => {
    messagesContainer.innerHTML = `
      <div class="message assistant-msg">
        <div class="avatar">🤖</div>
        <div class="bubble">
          <p>Conversation cleared. Ready for your questions!</p>
        </div>
      </div>
    `;
    conversationHistory = [];
  });

  // Quick Chips
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const prompt = chip.getAttribute("data-prompt");
      chatInput.value = prompt;
      chatForm.dispatchEvent(new Event("submit"));
    });
  });

  // Manual Trigger buttons
  headerTriggerBtn.addEventListener("click", triggerSyncNow);
  sideTriggerBtn.addEventListener("click", triggerSyncNow);

  // Toggle Scheduler
  headerToggleBtn.addEventListener("click", toggleScheduler);

  refreshFilesBtn.addEventListener("click", loadFiles);
  refreshEntriesBtn.addEventListener("click", loadEntries);
}

// ---------------------------------------------------------------------------
// Chat Handling
// ---------------------------------------------------------------------------
async function handleChatSubmit(e) {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;

  // Append user message
  appendMessage("user", text);
  chatInput.value = "";
  chatInput.style.height = "auto";

  // Append typing indicator
  const typingId = appendTypingIndicator();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        history: conversationHistory,
      }),
    });

    const data = await res.json();
    removeElement(typingId);

    const reply = data.reply || "No response received.";
    appendMessage("assistant", reply);

    // Save history
    conversationHistory.push({ role: "user", content: text });
    conversationHistory.push({ role: "assistant", content: reply });

    // Refresh dashboard if an action was executed
    if (data.action_executed) {
      loadStatus();
      loadEntries();
      loadHistory();
    }
  } catch (err) {
    removeElement(typingId);
    appendMessage("assistant", `❌ **Network error:** ${err.message}`);
  }
}

function appendMessage(role, text) {
  const msgDiv = document.createElement("div");
  msgDiv.className = `message ${role}-msg`;

  const avatar = role === "user" ? "👤" : "🤖";
  // Basic markdown conversion for bold and linebreaks
  const formatted = formatMarkdown(text);

  msgDiv.innerHTML = `
    <div class="avatar">${avatar}</div>
    <div class="bubble">${formatted}</div>
  `;

  messagesContainer.appendChild(msgDiv);
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function appendTypingIndicator() {
  const id = "typing-" + Date.now();
  const div = document.createElement("div");
  div.id = id;
  div.className = "message assistant-msg";
  div.innerHTML = `
    <div class="avatar">🤖</div>
    <div class="bubble" style="color: var(--text-muted); font-style: italic;">
      Claude Sonnet 5.5 is thinking...
    </div>
  `;
  messagesContainer.appendChild(div);
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
  return id;
}

function removeElement(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function formatMarkdown(text) {
  // Convert code fences
  let html = text.replace(/```([\s\S]*?)```/g, "<pre><code>$1</code></pre>");
  // Inline code
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  // Bold
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  // Linebreaks to paragraphs/breaks
  html = html.replace(/\n\n/g, "</p><p>").replace(/\n/g, "<br>");
  return `<p>${html}</p>`;
}

// ---------------------------------------------------------------------------
// Scheduler & Status
// ---------------------------------------------------------------------------
async function loadStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    const sched = data.scheduler;

    // Update Header Pill
    if (sched.active) {
      schedulerDot.className = "status-dot active";
      schedulerStatusText.textContent = `Hourly Sync: Active (${sched.interval_human})`;
      headerToggleBtn.textContent = "⏸";
      headerToggleBtn.title = "Pause hourly scheduler";
      schedStatusVal.textContent = "Active";
      schedStatusVal.style.color = "var(--success-color)";
    } else {
      schedulerDot.className = "status-dot paused";
      schedulerStatusText.textContent = "Hourly Sync: Paused";
      headerToggleBtn.textContent = "▶";
      headerToggleBtn.title = "Resume hourly scheduler";
      schedStatusVal.textContent = "Paused";
      schedStatusVal.style.color = "var(--warning-color)";
    }

    // Countdown
    countdownSeconds = sched.seconds_until_next || 0;
    updateCountdownDisplay();
    startCountdownTimer();

    // Metric Values
    nextRunVal.textContent = sched.next_run ? new Date(sched.next_run).toLocaleTimeString() : "--:--";
    lastRunVal.textContent = sched.last_run ? new Date(sched.last_run).toLocaleTimeString() : "Never";
    runCountVal.textContent = sched.run_count;
  } catch (err) {
    console.error("Failed to load status:", err);
  }
}

function startCountdownTimer() {
  if (countdownTimer) clearInterval(countdownTimer);
  countdownTimer = setInterval(() => {
    if (countdownSeconds > 0) {
      countdownSeconds--;
      updateCountdownDisplay();
    }
  }, 1000);
}

function updateCountdownDisplay() {
  if (countdownSeconds <= 0) {
    countdownTag.textContent = "Next in: Syncing...";
    return;
  }
  const mins = Math.floor(countdownSeconds / 60);
  const secs = countdownSeconds % 60;
  countdownTag.textContent = `Next in: ${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

async function triggerSyncNow() {
  headerTriggerBtn.disabled = true;
  sideTriggerBtn.disabled = true;
  headerTriggerBtn.textContent = "⏳ Running...";
  sideTriggerBtn.textContent = "⏳ Executing assignment sync...";

  try {
    const res = await fetch("/api/scheduler/trigger", { method: "POST" });
    const data = await res.json();

    loadStatus();
    loadFiles();
    loadEntries();
    loadHistory();

    appendMessage(
      "assistant",
      `✅ **Manual Sync Finished!**<br>Status: \`${data.result.status}\`<br>Matches: ${data.result.matched_files.join(", ") || "None"}`
    );
  } catch (err) {
    alert("Trigger failed: " + err.message);
  } finally {
    headerTriggerBtn.disabled = false;
    sideTriggerBtn.disabled = false;
    headerTriggerBtn.textContent = "⚡ Run Now";
    sideTriggerBtn.textContent = "⚡ Trigger Assignment Sync Now";
  }
}

async function toggleScheduler() {
  try {
    const res = await fetch("/api/scheduler/toggle", { method: "POST" });
    const data = await res.json();
    loadStatus();
  } catch (err) {
    console.error("Toggle error:", err);
  }
}

// ---------------------------------------------------------------------------
// Monitored Files & API Entries
// ---------------------------------------------------------------------------
async function loadFiles() {
  try {
    const res = await fetch("/api/files");
    const data = await res.json();

    fileList.innerHTML = "";
    if (!data.files || data.files.length === 0) {
      fileList.innerHTML = '<li class="loading-item">No text files in directory.</li>';
      return;
    }

    data.files.forEach((f) => {
      const li = document.createElement("li");
      li.className = "file-item";
      const matchBadge = f.contains_target
        ? '<span class="badge badge-match">MATCH</span>'
        : '<span class="badge badge-neutral">No Match</span>';

      li.innerHTML = `
        <div class="file-header">
          <span class="file-name" title="${f.name}">${f.name}</span>
          ${matchBadge}
        </div>
        <div class="file-preview">${f.preview}</div>
      `;
      fileList.appendChild(li);
    });
  } catch (err) {
    fileList.innerHTML = `<li class="loading-item">Failed to load files: ${err.message}</li>`;
  }
}

async function loadEntries() {
  try {
    const res = await fetch("/api/remote-entries");
    const data = await res.json();

    entryList.innerHTML = "";
    const items = data.items || [];
    if (items.length === 0) {
      entryList.innerHTML = '<li class="loading-item">No API entries found.</li>';
      return;
    }

    items.slice(0, 5).forEach((item) => {
      const li = document.createElement("li");
      li.className = "entry-item";
      const createdStr = item.created_at ? new Date(item.created_at).toLocaleString() : "";
      const textPreview = (item.text || "").replace(/\n/g, " ").slice(0, 90);

      li.innerHTML = `
        <div class="entry-header">
          <span class="entry-sender">${item.sender}</span>
          <span class="entry-date">${createdStr}</span>
        </div>
        <div class="entry-text">${textPreview}...</div>
      `;
      entryList.appendChild(li);
    });
  } catch (err) {
    entryList.innerHTML = `<li class="loading-item">Could not reach API: ${err.message}</li>`;
  }
}

async function loadHistory() {
  try {
    const res = await fetch("/api/scheduler/history");
    const data = await res.json();

    if (!data.history || data.history.length === 0) return;

    logStream.innerHTML = "";
    data.history.slice(0, 8).forEach((item) => {
      const timeStr = new Date(item.timestamp).toLocaleTimeString();
      const div = document.createElement("div");
      div.className = "log-entry";
      div.innerHTML = `[${timeStr}] <strong>Run #${item.run_id} (${item.trigger})</strong>: ${item.status.toUpperCase()} - ${item.matched_files.length} match(es)`;
      logStream.appendChild(div);
    });
  } catch (err) {
    console.error("Log error:", err);
  }
}
