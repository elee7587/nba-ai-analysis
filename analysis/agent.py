# analysis/agent.py
import json
import ollama
from analysis.prompts import (
    ANALYST_PROMPT,
    QUARTER_ANALYST_PROMPT,
    SCORING_WRITER_PROMPT,
    STATS_WRITER_PROMPT,
    MVP_WRITER_PROMPT,
    EDITOR_PROMPT
)
from analysis.queries import (
    get_play_by_play,
    get_play_by_play_by_period,
    get_team_comparison,
    get_player_comparison,
    get_mvp_data
)
from loguru import logger

ANALYST_MODEL = "qwen2.5:72b"
WRITER_MODEL = "mistral:7b"
class NBAAnalysisAgent:

    def __init__(self, game_id: str):
        self.game_id           = game_id
        self.play_by_play      = None
        self.play_by_play_by_period = None
        self.team_comparison   = None
        self.player_comparison = None
        self.mvp_data          = None

    def load_data(self):
        """Load all game data from the database"""
        logger.info(f"Loading data for game {self.game_id}")
        self.play_by_play           = get_play_by_play(self.game_id)
        self.play_by_play_by_period = get_play_by_play_by_period(self.game_id)
        self.team_comparison        = get_team_comparison(self.game_id)
        self.player_comparison      = get_player_comparison(self.game_id)
        self.mvp_data               = get_mvp_data(self.game_id)
        logger.info(f"Loaded {len(self.play_by_play)} plays across {len(self.play_by_play_by_period)} periods")

    def _call_llm(self, prompt: str, label: str, model: str, retries: int = 3) -> str:
        """Single reusable method for all LLM calls with retry"""
        for attempt in range(retries):
            logger.info(f"Calling LLM for: {label} (attempt {attempt + 1})")
            response = ollama.chat(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a JSON-only response bot. You must respond with valid JSON only. No explanations, no markdown, no preamble, no backticks. Only raw JSON starting with { or [."
                    },
                    {
                        "role": "user",
                        "content": prompt if attempt == 0 else f"IMPORTANT: Respond with ONLY valid JSON. No text before or after. Start your response with {{ or [\n\n{prompt}"
                    }
                ],
                options={"temperature": 0.1}
            )
            raw = response['message']['content']
            raw = raw.replace("```json", "").replace("```", "").strip()

            if raw.startswith('{') or raw.startswith('['):
                return raw

            logger.warning(f"Attempt {attempt + 1} returned non-JSON, retrying...")

        raise ValueError(f"Failed to get valid JSON after {retries} attempts for {label}")

    def _parse_json(self, raw: str, label: str) -> dict | list:
        """Parse JSON with error handling"""
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from {label}: {e}")
            logger.error(f"Raw response: {raw[:500]}")
            raise

    def run_analyst(self) -> dict:
        """Agent 1 — full game analysis in one shot"""
        logger.info(f"Running analyst for game {self.game_id}")

        prompt = ANALYST_PROMPT.format(
            play_by_play=json.dumps(self.play_by_play, indent=2, default=str),
            team_comparison=json.dumps(self.team_comparison, indent=2, default=str),
            player_comparison=json.dumps(self.player_comparison, indent=2, default=str),
            mvp_data=json.dumps(self.mvp_data, indent=2, default=str)
        )

        raw      = self._call_llm(prompt, "analyst", ANALYST_MODEL)
        findings = self._parse_json(raw, "analyst")

        logger.info(
            f"Analyst complete — "
            f"{len(findings.get('scoring_runs', []))} runs, "
            f"{len(findings.get('momentum_shifts', []))} momentum shifts, "
            f"{len(findings.get('team_outliers', []))} team outliers, "
            f"{len(findings.get('player_outliers', []))} player outliers, "
            f"{len(findings.get('mvp_candidates', []))} MVP candidates"
        )

        return findings


    def run_scoring_writer(self, analyst_findings: dict) -> list:
        """Agent 2a — write scoring breakdown narrative"""
        pass

    def run_stats_writer(self, analyst_findings: dict) -> list:
        """Agent 2b — write key stats narrative"""
        pass

    def run_mvp_writer(self, analyst_findings: dict) -> list:
        """Agent 2c — write MVP narrative"""
        pass

    def run_editor(self, scoring_narratives, stats_narratives, mvp_narratives, analyst_findings) -> dict:
        """Agent 3 — edit and produce final output"""
        pass

    def run(self) -> dict:
        """Run the full agent chain"""
        self.load_data()
        findings = self.run_analyst()
        return findings