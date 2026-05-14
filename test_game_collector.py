from data.collectors.game_collector import GameCollector

collector = GameCollector()
games = collector.get_games_by_date("2024-11-13")

for game in games:
    print(game)