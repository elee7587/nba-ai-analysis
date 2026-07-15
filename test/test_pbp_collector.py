from data.collectors.playbyplay_collector import PlayByPlayCollector

collector = PlayByPlayCollector()
plays = collector.get_play_by_play_by_game_id("0052500131") 

for play in plays:
    print(play)