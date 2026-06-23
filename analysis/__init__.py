import json
import ollama
from analysis.prompts import (
    ANALYST_PROMPT,
    SCORING_WRITER_PROMPT,
    STATS_WRITER_PROMPT,
    MVP_WRITER_PROMPT,
    EDITOR_PROMPT
)
from analysis.queries import (
    get_play_by_play,
    get_team_comparison,
    get_player_comparison,
    get_mvp_data
)
from loguru import logger

ANALYST_MODEL = "qwen2.5:72b"
WRITER_MODEL  = "mistral:7b"
EDITOR_MODEL  = "qwen2.5:72b"

class NBAAnalysisAgent:

    def __init__(self, game_id: str):
        self.game_id           = game_id
        self.play_by_play      = None
        self.team_comparison   = None
        self.player_comparison = None
        self.mvp_data          = None