import os
import requests
from dotenv import load_dotenv
from nba_api.stats.endpoints import playergamelog
from nba_api.stats.static import players

load_dotenv()

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4"


def get_tonights_games():
    url = f"{BASE_URL}/sports/basketball_nba/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "american",
    }
    response = requests.get(url, params=params)
    data = response.json()
    games = []
    for game in data:
        games.append({
            "game_id": game["id"],
            "home_team": game["home_team"],
            "away_team": game["away_team"],
            "commence_time": game["commence_time"],
        })
    return games


def get_player_id(player_name):
    all_players = players.get_active_players()
    for player in all_players:
        if player["full_name"].lower() == player_name.lower():
            return player["id"]
    return None


def get_player_stats(player_name, season="2025-26"):
    player_id = get_player_id(player_name)
    if not player_id:
        print(f"Player {player_name} not found")
        return None

    df = None
    for season_type in ("Playoffs", "Regular Season"):
        gamelog = playergamelog.PlayerGameLog(
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )
        df = gamelog.get_data_frames()[0]
        if not df.empty:
            break

    if df is None or df.empty:
        print(f"No game log found for {player_name}")
        return None

    cols = ["GAME_DATE", "MATCHUP", "PTS", "AST", "REB", "STL", "BLK", "TOV", "MIN", "FGA"]
    last5 = df.head(5)[cols]
    last10 = df.head(10)[cols]

    return {
        "last5": last5,
        "last10": last10,
    }


if __name__ == "__main__":
    games = get_tonights_games()
    for game in games:
        print(game)

    stats = get_player_stats("LeBron James")
    if stats:
        print("\n--- Last 5 ---")
        print(stats["last5"])
        print("\n--- Last 10 ---")
        print(stats["last10"])