const PASSWORD = "nbaintel2026";
const API_BASE = "http://localhost:8000";

let selectedGame = null;
let playerStats = null;

function checkPassword() {
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

async function loadGames() {
  try {
    const res = await fetch(`${API_BASE}/games`);
    const games = await res.json();
    const grid = document.getElementById("games-grid");
    grid.innerHTML = "";
    games.forEach((game, i) => {
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
      body: JSON.stringify({ player, stat, line: parseFloat(line) }),
    });
    const data = await res.json();
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

async function sendMessage() {
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  appendMessage("user", text);
  appendMessage("ai", "Thinking...");

  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
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
      <div class="verdict-label">Lean: ${data.lean}</div>
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
