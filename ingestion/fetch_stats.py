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
        "oddsFormat": "american"
    }
    response = requests.get(url, params=params)
    data = response.json()

    games = []
    for game in data:
        games.append({
            "game_id": game["id"],
            "home_team": game["home_team"],
            "away_team": game["away_team"],
            "commence_time": game["commence_time"]
        })
    return games

def get_player_id(player_name):
    all_players = players.get_active_players()
    for player in all_players:
        if player["full_name"].lower() == player_name.lower():
            return player["id"]
    return None

def get_player_last5(player_name):
    player_id = get_player_id(player_name)
    if not player_id:
        print(f"Player {player_name} not found")
        return None

    gamelog = playergamelog.PlayerGameLog(
        player_id=player_id,
        season="2025-26"
    )
    df = gamelog.get_data_frames()[0]
    last5 = df.head(5)[["GAME_DATE", "MATCHUP", "PTS", "AST", "REB", "MIN", "FGA"]]
    return last5

if __name__ == "__main__":
    games = get_tonights_games()
    for game in games:
        print(game)

    stats = get_player_last5("LeBron James")
    print(stats)