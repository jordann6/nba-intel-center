import os
import json
from datetime import datetime, timezone
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AzureOpenAI
from nba_api.stats.endpoints import playergamelog, commonallplayers
from nba_api.stats.static import players as nba_players_static
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="NBA Intel Center API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version="2024-02-01",
)

DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
ODDS_BASE_URL = "https://api.the-odds-api.com/v4"

STAT_MAP = {
    "points": "PTS",
    "pts": "PTS",
    "assists": "AST",
    "ast": "AST",
    "rebounds": "REB",
    "reb": "REB",
    "steals": "STL",
    "stl": "STL",
    "blocks": "BLK",
    "blk": "BLK",
    "turnovers": "TOV",
    "tov": "TOV",
    "three pointers made": "FG3M",
    "threes": "FG3M",
    "3pm": "FG3M",
    "minutes": "MIN",
    "min": "MIN",
}


# ── Request/Response models ──────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    player_name: str
    stat_category: str
    prop_line: float

class ChatRequest(BaseModel):
    message: str
    context: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def resolve_stat_key(raw: str) -> str:
    return STAT_MAP.get(raw.lower().strip(), raw.upper())


def lookup_player_id(name: str) -> int:
    matches = nba_players_static.find_players_by_full_name(name)
    if not matches:
        # Fallback: partial first/last name search
        parts = name.strip().split()
        all_players = nba_players_static.get_active_players()
        for p in all_players:
            if all(part.lower() in p["full_name"].lower() for part in parts):
                return p["id"]
        raise HTTPException(status_code=404, detail=f"Player '{name}' not found.")
    return matches[0]["id"]


def fetch_game_log(player_id: int, season: str = "2025-26", last_n: int = 5):
    log = playergamelog.PlayerGameLog(
        player_id=player_id,
        season=season,
        season_type_all_star="Regular Season",
    )
    df = log.get_data_frames()[0]
    return df


def compute_averages(df, stat_key: str, last_n: int = 5):
    if stat_key not in df.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Stat '{stat_key}' not available. Try: points, assists, rebounds, etc.",
        )
    season_avg = round(float(df[stat_key].mean()), 1)
    last5_avg = round(float(df.head(last_n)[stat_key].mean()), 1)
    last5_values = df.head(last_n)[stat_key].tolist()
    return season_avg, last5_avg, last5_values


def build_analysis_prompt(
    player_name: str,
    stat_label: str,
    prop_line: float,
    season_avg: float,
    last5_avg: float,
    last5_values: list,
) -> str:
    return f"""
You are a sharp NBA prop analyst helping casual fans make informed bets. Be conversational, direct, and confident.

Player: {player_name}
Prop: {stat_label} — Line: {prop_line}
Season average: {season_avg}
Last 5 game average: {last5_avg}
Last 5 game values: {last5_values}

Analyze this prop and respond with ONLY a valid JSON object in this exact format:
{{
  "lean": "Over" or "Under",
  "confidence": "Low", "Medium", or "High",
  "summary": "One sentence bottom line for a casual fan.",
  "reasoning": "Two to three sentences explaining the trend, any relevant context, and why the lean makes sense."
}}

Rules:
- Lean toward the last 5 trend more than the season average unless there is a clear reason not to.
- Confidence should reflect how clear the signal is, not just whether the averages beat the line.
- Write like a knowledgeable friend, not a robot. No bullet points, no jargon.
- Return ONLY the JSON object with no markdown, no preamble.
""".strip()


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/games")
def get_games():
    if not ODDS_API_KEY:
        raise HTTPException(status_code=500, detail="ODDS_API_KEY not configured.")

    url = f"{ODDS_BASE_URL}/sports/basketball_nba/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "american",
        "dateFormat": "iso",
    }

    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Odds API error: {resp.status_code} {resp.text}",
        )

    games_raw = resp.json()
    today = datetime.now(timezone.utc).date()

    games = []
    for game in games_raw:
        commence = datetime.fromisoformat(
            game["commence_time"].replace("Z", "+00:00")
        )
        if commence.date() == today:
            games.append(
                {
                    "id": game["id"],
                    "home_team": game["home_team"],
                    "away_team": game["away_team"],
                    "commence_time": game["commence_time"],
                }
            )

    return {"games": games, "count": len(games)}


@app.post("/analyze")
def analyze_prop(req: AnalyzeRequest):
    stat_key = resolve_stat_key(req.stat_category)

    player_id = lookup_player_id(req.player_name)
    df = fetch_game_log(player_id)

    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No game log found for {req.player_name} in the 2025-26 season.",
        )

    season_avg, last5_avg, last5_values = compute_averages(df, stat_key)

    prompt = build_analysis_prompt(
        player_name=req.player_name,
        stat_label=req.stat_category,
        prop_line=req.prop_line,
        season_avg=season_avg,
        last5_avg=last5_avg,
        last5_values=last5_values,
    )

    completion = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=400,
    )

    raw = completion.choices[0].message.content.strip()

    try:
        ai_output = json.loads(raw)
    except json.JSONDecodeError:
        ai_output = {
            "lean": "N/A",
            "confidence": "N/A",
            "summary": raw,
            "reasoning": "",
        }

    return {
        "player": req.player_name,
        "stat": req.stat_category,
        "prop_line": req.prop_line,
        "season_avg": season_avg,
        "last5_avg": last5_avg,
        "last5_values": last5_values,
        "lean": ai_output.get("lean"),
        "confidence": ai_output.get("confidence"),
        "summary": ai_output.get("summary"),
        "reasoning": ai_output.get("reasoning"),
    }


@app.post("/chat")
def chat(req: ChatRequest):
    system_prompt = (
        "You are NBA Intel, a sharp and friendly NBA analyst. "
        "You help fans understand player props, stats, and matchups. "
        "Be concise, conversational, and direct. No bullet points unless the user asks. "
        "If you don't know something specific, say so plainly."
    )

    messages = [{"role": "system", "content": system_prompt}]

    if req.context:
        messages.append(
            {
                "role": "system",
                "content": f"Additional context for this conversation:\n{req.context}",
            }
        )

    messages.append({"role": "user", "content": req.message})

    completion = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=messages,
        temperature=0.7,
        max_tokens=600,
    )

    return {"response": completion.choices[0].message.content.strip()}


# ── Health check ─────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "deployment": DEPLOYMENT}