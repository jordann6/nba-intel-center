const API_BASE = "https://ppc-epinions-life-gentleman.trycloudflare.com";
let PASSWORD = null;
let selectedGame = null;
let lastAnalysis = null;

// ── Init ──────────────────────────────────────────────────────────────────────
async function loadConfig() {
  const input = document.getElementById("password-input");
  const btn = document.querySelector("#password-gate button");

  if (input) {
    input.disabled = true;
    input.placeholder = "Loading...";
  }
  if (btn) {
    btn.disabled = true;
  }

  try {
    const res = await fetch(`${API_BASE}/config`);
    const data = await res.json();
    PASSWORD = data.password;
  } catch (e) {
    console.error("Could not load config.", e);
    if (input) input.placeholder = "Config error — refresh page";
    return;
  }

  if (input) {
    input.disabled = false;
    input.placeholder = "Access code";
  }
  if (btn) {
    btn.disabled = false;
  }
  input?.focus();
}

function checkPassword() {
  if (!PASSWORD) {
    document.getElementById("gate-error").textContent =
      "Config still loading, try again in a moment.";
    return;
  }
  const input = document.getElementById("password-input").value;
  if (input === PASSWORD) {
    document.getElementById("password-gate").classList.add("hidden");
    document.getElementById("app").classList.remove("hidden");
    loadGames();
  } else {
    document.getElementById("gate-error").textContent =
      "Incorrect access code.";
  }
}

document.getElementById("password-input")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") checkPassword();
});
document.getElementById("chat-input")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});

// ── Games ─────────────────────────────────────────────────────────────────────
async function loadGames() {
  try {
    const res = await fetch(`${API_BASE}/games`);
    const data = await res.json();
    const grid = document.getElementById("games-grid");
    grid.innerHTML = "";
    if (!data.games || data.games.length === 0) {
      grid.innerHTML = '<div class="loading-text">No games tonight.</div>';
      return;
    }
    data.games.forEach((game) => {
      const card = document.createElement("div");
      card.className = "game-card";
      card.innerHTML = `
        <div class="game-teams">${game.away_team} vs ${game.home_team}</div>
        <div class="game-time">${formatTime(game.commence_time)}</div>
      `;
      card.onclick = () => selectGame(game, card);
      grid.appendChild(card);
    });
  } catch (e) {
    document.getElementById("games-grid").innerHTML =
      '<div class="loading-text">Could not load games.</div>';
  }
}

function selectGame(game, card) {
  document
    .querySelectorAll(".game-card")
    .forEach((c) => c.classList.remove("active"));
  card.classList.add("active");
  selectedGame = game;
}

function formatTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

// ── Analyze ───────────────────────────────────────────────────────────────────
async function analyzeProp() {
  const player = document.getElementById("player-input").value.trim();
  const stat = document.getElementById("stat-select").value;
  const line = document.getElementById("prop-input").value;

  if (!player || !line) {
    appendMessage("ai", "Please enter a player name and prop line first.");
    return;
  }

  appendMessage("user", `Analyze ${player} ${stat} over/under ${line}`);
  appendMessage("ai", "Pulling stats and analyzing...");

  try {
    const res = await fetch(`${API_BASE}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        player_name: player,
        stat_category: stat,
        prop_line: parseFloat(line),
      }),
    });
    if (!res.ok) {
      const err = await res.json();
      removeLastMessage();
      appendMessage("ai", `Error: ${err.detail ?? "Something went wrong."}`);
      return;
    }
    const data = await res.json();
    lastAnalysis = data;
    removeLastMessage();
    appendAnalysis(data);
    document.getElementById("season-avg").textContent = data.season_avg ?? "--";
    document.getElementById("last5-avg").textContent = data.last5_avg ?? "--";
    document.getElementById("prop-line-display").textContent = line;
    document.getElementById("stat-cards").classList.remove("hidden");
  } catch (e) {
    removeLastMessage();
    appendMessage(
      "ai",
      "Something went wrong. Make sure the backend is running.",
    );
  }
}

// ── Chat ──────────────────────────────────────────────────────────────────────
async function sendMessage() {
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  appendMessage("user", text);
  appendMessage("ai", "Thinking...");

  const context = lastAnalysis
    ? `The user just analyzed ${lastAnalysis.player} ${lastAnalysis.stat} with a prop line of ${lastAnalysis.prop_line}. Season avg: ${lastAnalysis.season_avg}, last 5 avg: ${lastAnalysis.last5_avg}. Lean: ${lastAnalysis.lean}. Reasoning: ${lastAnalysis.reasoning}`
    : null;

  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, context }),
    });
    if (!res.ok) {
      const err = await res.json();
      removeLastMessage();
      appendMessage("ai", `Error: ${err.detail ?? "Something went wrong."}`);
      return;
    }
    const data = await res.json();
    removeLastMessage();
    appendMessage("ai", data.response);
  } catch (e) {
    removeLastMessage();
    appendMessage(
      "ai",
      "Something went wrong. Make sure the backend is running.",
    );
  }
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function appendMessage(role, text) {
  const container = document.getElementById("chat-messages");
  const div = document.createElement("div");
  div.className = `msg msg-${role}`;
  div.textContent = text;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function appendAnalysis(data) {
  const container = document.getElementById("chat-messages");
  const div = document.createElement("div");
  div.className = "msg msg-ai";
  div.innerHTML = `
    ${data.summary}
    <div class="verdict">
      <div class="verdict-label">Lean: ${data.lean} &mdash; ${data.confidence} confidence</div>
      <div class="verdict-text">${data.reasoning}</div>
    </div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function removeLastMessage() {
  const container = document.getElementById("chat-messages");
  if (container.lastChild) container.removeChild(container.lastChild);
}

// ── Load config on startup ────────────────────────────────────────────────────
loadConfig();
