from groq import Groq
from config.settings import GROQ_API_KEY

class NBAAnalysisAgent:

    def __init__(self, game_id: str):
        self.game_id           = game_id
        self.client            = Groq(api_key=GROQ_API_KEY)
        self.play_by_play      = None
        self.team_comparison   = None
        self.player_comparison = None
        self.mvp_data          = None