from pathlib import Path

PROMPTS_DIR = Path(__file__).parent

def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")

# Analyst prompts
GAME_ANALYST_PROMPT    = load_prompt("game_analyst")
QUARTER_ANALYST_PROMPT = load_prompt("quarter_analyst")

# Stats prompts
SCORING_ANALYST_PROMPT      = load_prompt("scoring_analyst")
TEAM_STATS_ANALYST_PROMPT   = load_prompt("team_stats_analyst")
PLAYER_STATS_ANALYST_PROMPT = load_prompt("player_stats_analyst")
MVP_ANALYST_PROMPT          = load_prompt("mvp_analyst")

# Writer prompts
SCORING_WRITER_PROMPT = load_prompt("scoring_writer")
STATS_WRITER_PROMPT   = load_prompt("stats_writer")
MVP_WRITER_PROMPT     = load_prompt("mvp_writer")
EDITOR_PROMPT         = load_prompt("editor")