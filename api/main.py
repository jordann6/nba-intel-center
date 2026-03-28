import os
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AzureOpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from nba_api.stats.endpoints import playergamelog, commonteamroster
from nba_api.stats.static import players as nba_players_static
from nba_api.stats.static import teams as nba_teams_static
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

# ── Clients ───────────────────────────────────────────────────────────────────

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version="2024-02-01",
)

qdrant = QdrantClient(
    host=os.getenv("QDRANT_HOST", "localhost"),
    port=int(os.getenv("QDRANT_PORT", 6333)),
)

DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
ODDS_BASE_URL = "https://api.the-odds-api.com/v4"
ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
COLLECTION_NAME = "nba_analyses"
EMBED_MODEL = "text-embedding-3-small"
VECTOR_SIZE = 1536

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

# ── Roster cache ──────────────────────────────────────────────────────────────
# Populated on first chat request per team, reused across all subsequent ones.
# Resets on server restart which is fine since you restart daily.
_roster_cache: dict[str, list[str]] = {}


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
def init_qdrant():
    existing = [c.name for c in qdrant.get_collections().collections]
    if COLLECTION_NAME not in existing:
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )


# ── Request/Response models ───────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    player_name: str
    stat_category: str
    prop_line: float

class ChatRequest(BaseModel):
    message: str
    context: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def resolve_stat_key(raw: str) -> str:
    return STAT_MAP.get(raw.lower().strip(), raw.upper())


def lookup_player_id(name: str) -> int:
    matches = nba_players_static.find_players_by_full_name(name)
    if not matches:
        parts = name.strip().split()
        all_players = nba_players_static.get_active_players()
        for p in all_players:
            if all(part.lower() in p["full_name"].lower() for part in parts):
                return p["id"]
        raise HTTPException(status_code=404, detail=f"Player '{name}' not found.")
    return matches[0]["id"]


def fetch_game_log(player_id: int, season: str = "2025-26"):
    """
    Tries playoffs first, falls back to regular season.
    Ensures correct data is returned as the postseason begins.
    """
    for season_type in ("Playoffs", "Regular Season"):
        log = playergamelog.PlayerGameLog(
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )
        df = log.get_data_frames()[0]
        if not df.empty:
            return df
    return df


def compute_averages(df, stat_key: str):
    if stat_key not in df.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Stat '{stat_key}' not available. Try: points, assists, rebounds, steals, blocks, turnovers, etc.",
        )
    season_avg = round(float(df[stat_key].mean()), 1)
    last5_avg = round(float(df.head(5)[stat_key].mean()), 1)
    last5_values = df.head(5)[stat_key].tolist()
    last10_avg = round(float(df.head(10)[stat_key].mean()), 1)
    last10_values = df.head(10)[stat_key].tolist()
    return season_avg, last5_avg, last5_values, last10_avg, last10_values


def get_injury_status(player_name: str) -> dict:
    """
    Hits the ESPN injuries endpoint and fuzzy matches the player name.
    Returns a dict with 'status' and 'description'.
    Falls back to 'Available' if the player is not listed or the request fails.
    """
    try:
        resp = requests.get(ESPN_INJURIES_URL, timeout=5)
        if resp.status_code != 200:
            return {"status": "Unknown", "description": "Injury data unavailable."}

        data = resp.json()
        name_lower = player_name.lower().strip()

        for team in data.get("injuries", []):
            for injury in team.get("injuries", []):
                athlete = injury.get("athlete", {})
                full_name = athlete.get("displayName", "").lower()

                parts = name_lower.split()
                if all(part in full_name for part in parts):
                    status = injury.get("status", "Unknown")
                    description = injury.get("details", {}).get("detail", "No details available.")
                    return {"status": status, "description": description}

        return {"status": "Available", "description": "No injury report found. Assumed available."}

    except Exception as e:
        print(f"Injury fetch error: {e}")
        return {"status": "Unknown", "description": "Could not retrieve injury data."}


def fetch_injured_players() -> dict[str, str]:
    """
    Fetches all current injuries from ESPN and returns a flat lookup:
    player name (lowercase) -> status string.
    Used to annotate rosters in the chat context block.
    """
    try:
        resp = requests.get(ESPN_INJURIES_URL, timeout=5)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        injured = {}
        for team in data.get("injuries", []):
            for injury in team.get("injuries", []):
                name = injury.get("athlete", {}).get("displayName", "").lower()
                status = injury.get("status", "")
                if name:
                    injured[name] = status
        return injured
    except Exception as e:
        print(f"Injury bulk fetch error: {e}")
        return {}


def get_roster_for_team(team_name: str, season: str = "2025-26") -> list[str]:
    """
    Fetches the current live roster for a team via nba_api.
    Fuzzy matches the Odds API team name against nba_api's team list.
    Returns a list of player name strings.
    """
    if team_name in _roster_cache:
        return _roster_cache[team_name]

    try:
        all_teams = nba_teams_static.get_teams()
        match = None
        for t in all_teams:
            if (
                t["full_name"].lower() == team_name.lower()
                or t["nickname"].lower() in team_name.lower()
                or t["city"].lower() in team_name.lower()
            ):
                match = t
                break

        if not match:
            print(f"Roster lookup: no team match for '{team_name}'")
            _roster_cache[team_name] = []
            return []

        roster = commonteamroster.CommonTeamRoster(
            team_id=match["id"],
            season=season,
        )
        df = roster.get_data_frames()[0]
        players = df["PLAYER"].tolist()
        _roster_cache[team_name] = players
        return players

    except Exception as e:
        print(f"Roster fetch error for {team_name}: {e}")
        _roster_cache[team_name] = []
        return []


def get_tonights_games_context() -> str:
    """
    Fetches tonight's games and builds a roster-grounded, injury-annotated
    context block. Players marked Out are flagged so GPT-4o excludes them
    from recommendations. Questionable/Doubtful players are noted.
    """
    try:
        games_resp = get_games()
        if not games_resp["games"]:
            return "Tonight's games: none scheduled."

        injured_players = fetch_injured_players()

        def format_roster(roster: list[str]) -> str:
            if not roster:
                return "roster unavailable"
            out = []
            for p in roster:
                status = injured_players.get(p.lower(), "")
                if status in ("Out", "Injured Reserve", "Suspended"):
                    out.append(f"{p} (OUT)")
                elif status in ("Questionable", "Doubtful", "Day-To-Day"):
                    out.append(f"{p} ({status})")
                else:
                    out.append(p)
            return ", ".join(out)

        lines = []
        for g in games_resp["games"]:
            away = g["away_team"]
            home = g["home_team"]
            away_roster = get_roster_for_team(away)
            home_roster = get_roster_for_team(home)
            lines.append(
                f"- {away} vs {home}\n"
                f"  {away} roster: {format_roster(away_roster)}\n"
                f"  {home} roster: {format_roster(home_roster)}"
            )

        return "Tonight's games and current rosters (injury status noted):\n" + "\n".join(lines)

    except Exception as e:
        print(f"Games context error: {e}")
        return "Tonight's games: unavailable."


def embed_text(text: str) -> list[float]:
    response = client.embeddings.create(
        model=EMBED_MODEL,
        input=text,
    )
    return response.data[0].embedding


def store_analysis(analysis: dict):
    trend = (
        "trending up" if analysis["last5_avg"] > analysis["last10_avg"]
        else "trending down" if analysis["last5_avg"] < analysis["last10_avg"]
        else "steady"
    )
    text = (
        f"{analysis['player']} {analysis['stat']} prop line {analysis['prop_line']}. "
        f"Season avg {analysis['season_avg']}, last 10 avg {analysis['last10_avg']}, "
        f"last 5 avg {analysis['last5_avg']} ({trend}). "
        f"Injury status: {analysis['injury_status']} — {analysis['injury_description']}. "
        f"Lean: {analysis['lean']}. Confidence: {analysis['confidence']}. "
        f"{analysis['summary']} {analysis['reasoning']}"
    )
    vector = embed_text(text)
    qdrant.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload={**analysis, "timestamp": datetime.now(timezone.utc).isoformat()},
            )
        ],
    )


def retrieve_relevant_analyses(query: str, limit: int = 3) -> list[dict]:
    vector = embed_text(query)
    results = qdrant.search(
        collection_name=COLLECTION_NAME,
        query_vector=vector,
        limit=limit,
        with_payload=True,
    )
    return [r.payload for r in results]


def build_analysis_prompt(
    player_name: str,
    stat_label: str,
    prop_line: float,
    season_avg: float,
    last5_avg: float,
    last5_values: list,
    last10_avg: float,
    last10_values: list,
    injury_status: str,
    injury_description: str,
) -> str:
    trend = (
        "trending up" if last5_avg > last10_avg
        else "trending down" if last5_avg < last10_avg
        else "steady"
    )
    return f"""
You are a sharp NBA prop analyst helping casual fans make informed bets. Be conversational, direct, and confident.

Player: {player_name}
Prop: {stat_label} — Line: {prop_line}
Season average: {season_avg}
Last 10 game average: {last10_avg}
Last 5 game average: {last5_avg} ({trend} vs last 10)
Last 5 game values: {last5_values}
Injury status: {injury_status} — {injury_description}

Analyze this prop and respond with ONLY a valid JSON object in this exact format:
{{
  "lean": "Over", "Under", or "N/A — Player Out",
  "confidence": "Low", "Medium", or "High",
  "summary": "One sentence bottom line for a casual fan.",
  "reasoning": "Two to three sentences explaining the trend, momentum direction, injury context if relevant, and why the lean makes sense."
}}

Rules:
- If the injury status is "Out", set lean to "N/A — Player Out" and confidence to "N/A", and explain in the summary that the player is ruled out.
- If the status is "Questionable" or "Doubtful", factor uncertainty into the confidence level and mention it in the reasoning.
- Use the trend direction (last 5 vs last 10) as a momentum signal alongside the raw averages.
- Confidence should reflect how clear the signal is across both windows, not just whether the averages beat the line.
- Write like a knowledgeable friend, not a robot. No bullet points, no jargon.
- Return ONLY the JSON object with no markdown, no preamble.
""".strip()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/config")
def config():
    password = os.getenv("APP_PASSWORD")
    if not password:
        raise HTTPException(status_code=500, detail="APP_PASSWORD not configured.")
    return {"password": password}


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
    tomorrow = today + timedelta(days=1)

    games = []
    for game in games_raw:
        commence = datetime.fromisoformat(
            game["commence_time"].replace("Z", "+00:00")
        )
        if commence.date() in (today, tomorrow):
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

    season_avg, last5_avg, last5_values, last10_avg, last10_values = compute_averages(df, stat_key)

    injury = get_injury_status(req.player_name)

    prompt = build_analysis_prompt(
        player_name=req.player_name,
        stat_label=req.stat_category,
        prop_line=req.prop_line,
        season_avg=season_avg,
        last5_avg=last5_avg,
        last5_values=last5_values,
        last10_avg=last10_avg,
        last10_values=last10_values,
        injury_status=injury["status"],
        injury_description=injury["description"],
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

    result = {
        "player": req.player_name,
        "stat": req.stat_category,
        "prop_line": req.prop_line,
        "season_avg": season_avg,
        "last5_avg": last5_avg,
        "last5_values": last5_values,
        "last10_avg": last10_avg,
        "last10_values": last10_values,
        "injury_status": injury["status"],
        "injury_description": injury["description"],
        "lean": ai_output.get("lean"),
        "confidence": ai_output.get("confidence"),
        "summary": ai_output.get("summary"),
        "reasoning": ai_output.get("reasoning"),
    }

    try:
        store_analysis(result)
    except Exception as e:
        print(f"Qdrant store error: {e}")

    return result


@app.post("/chat")
def chat(req: ChatRequest):
    games_context = get_tonights_games_context()

    system_prompt = (
        "You are NBA Intel, a sharp and friendly NBA analyst. "
        "You help fans understand player props, stats, and matchups. "
        "Be concise, conversational, and direct. No bullet points unless the user asks. "
        "If you don't know something specific, say so plainly. "
        "Always remind users to verify current injury status before placing any bet. "
        "Only recommend players who appear in the roster lists below. "
        "Do not recommend any player marked as OUT — they are not playing tonight. "
        "For players marked Questionable or Doubtful, note the uncertainty in your response. "
        "Do not suggest any player not listed in tonight's rosters. "
        f"{games_context}"
    )

    messages = [{"role": "system", "content": system_prompt}]

    try:
        past = retrieve_relevant_analyses(req.message)
        if past:
            rag_context = "Relevant past analyses:\n" + "\n".join(
                f"- {p['player']} {p['stat']} (line {p['prop_line']}): "
                f"Lean {p['lean']}, {p['confidence']} confidence. {p['summary']}"
                for p in past
            )
            messages.append({"role": "system", "content": rag_context})
    except Exception as e:
        print(f"Qdrant retrieve error: {e}")

    if req.context:
        messages.append(
            {
                "role": "system",
                "content": f"Current session context:\n{req.context}",
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


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    try:
        collections = [c.name for c in qdrant.get_collections().collections]
        qdrant_status = "ok"
    except Exception:
        collections = []
        qdrant_status = "unreachable"

    return {
        "status": "ok",
        "deployment": DEPLOYMENT,
        "qdrant": qdrant_status,
        "collections": collections,
    }