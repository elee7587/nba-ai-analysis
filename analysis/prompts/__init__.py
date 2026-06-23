# analysis/prompts/__init__.py
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent

def load_prompt(name: str) -> str:
    """Load a prompt from a markdown file"""
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")

ANALYST_PROMPT         = load_prompt("analyst")
SCORING_WRITER_PROMPT  = load_prompt("scoring_writer")
STATS_WRITER_PROMPT    = load_prompt("stats_writer")
MVP_WRITER_PROMPT      = load_prompt("mvp_writer")
EDITOR_PROMPT          = load_prompt("editor")