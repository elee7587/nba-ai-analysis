from data.collectors.season_stats_collector import SeasonStatsCollector

collector = SeasonStatsCollector()
season_stats = collector.get_season_stats("2023-24")
print(season_stats["team_stats"].head())
print(season_stats["player_stats"].head())