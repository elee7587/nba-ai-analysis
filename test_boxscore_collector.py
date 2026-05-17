from data.collectors.boxscore_collector import BoxScoreCollector
from data.collectors.winprobability_collector import WinProbabilityCollector

box = BoxScoreCollector()
result = box.get_boxscore_by_game_id('0052500101')
print('Keys:', result.keys())
