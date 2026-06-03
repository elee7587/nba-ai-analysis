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
from config.settings import GROQ_API_KEY
from loguru import logger

MODEL = "llama-3.1-8b-instant"

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

    def _call_llm(self, prompt: str, label: str) -> str:
        """Single reusable method for all LLM calls"""
        logger.info(f"Calling LLM for: {label}")
        response = ollama.chat(
            model="llama3.1:70b",
            messages=[
                {
                    "role": "system",
                    "content": "You are a JSON-only response bot. You must respond with valid JSON only. No explanations, no markdown, no preamble. Only raw JSON."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            options={"temperature": 0.1}  # lower temperature = more consistent output
        )
        raw = response['message']['content']
        raw = raw.replace("```json", "").replace("```", "").strip()
        return raw
    def _parse_json(self, raw: str, label: str) -> dict | list:
        """Parse JSON with error handling"""
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from {label}: {e}")
            logger.error(f"Raw response: {raw[:500]}")
            raise

    def run_quarter_analyst(self) -> dict:
        """
        Analyze play by play quarter by quarter
        Returns combined findings across all periods
        """
        all_scoring_runs     = []
        all_momentum_shifts  = []

        for period, plays in self.play_by_play_by_period.items():
            logger.info(f"Analyzing period {period} — {len(plays)} plays")

            prompt = QUARTER_ANALYST_PROMPT.format(
                period=period,
                play_by_play=json.dumps(plays, indent=2, default=str)
            )

            raw      = self._call_llm(prompt, f"quarter_analyst_period_{period}")
            findings = self._parse_json(raw, f"quarter_analyst_period_{period}")

            # accumulate findings across all periods
            all_scoring_runs.extend(findings.get("scoring_runs", []))
            all_momentum_shifts.extend(findings.get("momentum_shifts", []))

            logger.info(
                f"Period {period}: {len(findings.get('scoring_runs', []))} runs, "
                f"{len(findings.get('momentum_shifts', []))} momentum shifts"
            )

        return {
            "scoring_runs":     all_scoring_runs,
            "momentum_shifts":  all_momentum_shifts
        }

    def run_analyst(self) -> dict:
        """
        Agent 1 — full analysis
        Quarter by quarter for play by play
        Single call for stats and MVP
        """
        logger.info(f"Running analyst for game {self.game_id}")

        # step 1 — quarter by quarter play by play analysis
        pbp_findings = self.run_quarter_analyst()

        # step 2 — stats and MVP analysis in one call
        prompt = ANALYST_PROMPT.format(
            team_comparison=json.dumps(self.team_comparison, indent=2, default=str),
            player_comparison=json.dumps(self.player_comparison, indent=2, default=str),
            mvp_data=json.dumps(self.mvp_data, indent=2, default=str)
        )

        raw          = self._call_llm(prompt, "stats_and_mvp_analyst")
        stats_findings = self._parse_json(raw, "stats_and_mvp_analyst")

        # combine everything into one findings dict
        findings = {
            "scoring_runs":     pbp_findings["scoring_runs"],
            "momentum_shifts":  pbp_findings["momentum_shifts"],
            "team_outliers":    stats_findings.get("team_outliers", []),
            "player_outliers":  stats_findings.get("player_outliers", []),
            "mvp_candidates":   stats_findings.get("mvp_candidates", [])
        }

        logger.info(
            f"Analyst complete — {len(findings['scoring_runs'])} runs, "
            f"{len(findings['team_outliers'])} team outliers, "
            f"{len(findings['player_outliers'])} player outliers, "
            f"{len(findings['mvp_candidates'])} MVP candidates"
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