# analysis/agent.py
import json
import ollama
from analysis.prompts import (
    SCORING_ANALYST_PROMPT,
    TEAM_STATS_ANALYST_PROMPT,
    PLAYER_STATS_ANALYST_PROMPT,
    MVP_ANALYST_PROMPT,
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

REASONING_MODEL  = "qwen2.5:32b"  # deep analysis and writing
FORMATTING_MODEL = "qwen2.5:14b"  # structured JSON output
WRITER_MODEL     = "qwen2.5:32b"  # narratives need good reasoning
EDITOR_MODEL     = "qwen2.5:32b"  # final polish needs good reasoning
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

    def _call_with_reasoning(self, prompt: str, label: str, schema: str) -> dict:
        """Two step call — reasoning model thinks, formatting model structures"""
        
        # step 1 — reasoning model analyzes
        logger.info(f"Step 1 — reasoning for {label}")
        reasoning = self._call_llm(
            prompt=prompt,
            label=f"{label}_reasoning",
            model=REASONING_MODEL
        )
        logger.info(f"Reasoning complete for {label}")

        # step 2 — formatting model converts to JSON
        logger.info(f"Step 2 — formatting for {label}")
        format_prompt = f"""
    Convert the following analysis into valid JSON.
    Your response must exactly match this schema:
    {schema}

    Analysis to convert:
    {reasoning}

    CRITICAL: Output only valid JSON. No text before or after.
    """
        raw = self._call_llm(
            prompt=format_prompt,
            label=f"{label}_formatting",
            model=FORMATTING_MODEL
        )
        return self._parse_json(raw, label)

    def _call_llm(self, prompt: str, label: str, model: str, force_json: bool = False, retries: int = 3) -> str:
        """Single reusable method for all LLM calls"""
        system_content = (
            "You only output valid JSON. Never output text. Never explain. Never use markdown. Your entire response must be parseable by json.loads(). Always include all required fields from the schema provided."
            if force_json else
            "You are an expert NBA analyst with deep knowledge of basketball analytics, statistics, and the game."
        )
        
        for attempt in range(retries):
            logger.info(f"Calling LLM for: {label} (attempt {attempt + 1})")
            response = ollama.chat(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": system_content
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                options={
                    "temperature": 0.1 if force_json else 0.3,
                    "num_predict": 16000
                }
            )
            raw = response['message']['content']
            raw = raw.replace("```json", "").replace("```", "").strip()
            
            logger.info(f"Raw response preview: {raw[:200]}")

            if force_json:
                if raw.startswith('{') or raw.startswith('['):
                    return raw
                logger.warning(f"Attempt {attempt + 1} returned non-JSON, retrying...")
            else:
                return raw  # reasoning model can return anything

        raise ValueError(f"Failed to get valid JSON after {retries} attempts for {label}")

    def _parse_json(self, raw: str, label: str) -> dict | list:
        """Parse JSON with error handling and repair attempt"""
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed for {label}, attempting repair...")
            
            # attempt to fix truncated JSON by closing open brackets
            repaired = raw
            open_braces   = raw.count('{') - raw.count('}')
            open_brackets = raw.count('[') - raw.count(']')
            
            # close any open strings first
            if repaired.count('"') % 2 != 0:
                repaired += '"'
            
            # close open brackets and braces
            repaired += ']' * open_brackets
            repaired += '}' * open_braces
            
            try:
                result = json.loads(repaired)
                logger.info(f"JSON repair successful for {label}")
                return result
            except json.JSONDecodeError:
                logger.error(f"JSON repair failed for {label}: {e}")
                logger.error(f"Raw response: {raw[:500]}")
                raise

    def run_scoring_analyst(self) -> dict:
        """Analyst 1 — scoring runs and momentum shifts"""
        schema = """
        {
            "scoring_runs": [{"team": "", "run_size": "", "period": "", "start_clock": "", "end_clock": "", "description": "", "key_players": []}],
            "momentum_shifts": [{"period": "", "clock": "", "team_that_gained": "", "trigger_event": "", "score_margin_before": "", "score_margin_after": "", "description": "", "key_players": []}]
        }
        """
        prompt = SCORING_ANALYST_PROMPT.format(
            play_by_play=json.dumps(self.play_by_play, indent=2, default=str)
        )
        return self._call_with_reasoning(prompt, "scoring_analyst", schema)

    def run_team_stats_analyst(self) -> dict:
        """Analyst 2 — team level outliers"""
        schema = """
        {
            "team_outliers": [{"team": "", "stat": "", "game_value": "", "season_average": "", "season_rank": "", "deviation": "", "direction": "", "significance": ""}]
        }
        """
        prompt = TEAM_STATS_ANALYST_PROMPT.format(
            team_comparison=json.dumps(self.team_comparison, indent=2, default=str)
        )
        return self._call_with_reasoning(prompt, "team_stats_analyst", schema)

    def run_player_stats_analyst(self) -> dict:
        """Analyst 3 — player level outliers"""
        schema = """
        {
            "player_outliers": [{"player": "", "team": "", "stat": "", "game_value": "", "season_average": "", "season_rank": "", "deviation": "", "direction": "", "significance": ""}]
        }
        """
        prompt = PLAYER_STATS_ANALYST_PROMPT.format(
            player_comparison=json.dumps(self.player_comparison, indent=2, default=str)
        )
        return self._call_with_reasoning(prompt, "player_stats_analyst", schema)

    def run_mvp_analyst(self) -> dict:
        """Analyst 4 — MVP candidates"""
        schema = """
        {
            "mvp_candidates": [{"player": "", "team": "", "rank": "", "key_stats": {"points": 0, "rebounds": 0, "assists": 0, "plus_minus": 0, "true_shooting_pct": 0, "net_rating": 0, "pie": 0}, "key_moments": [], "reasoning": ""}]
        }
        """
        prompt = MVP_ANALYST_PROMPT.format(
            player_comparison=json.dumps(self.player_comparison, indent=2, default=str),
            mvp_data=json.dumps(self.mvp_data, indent=2, default=str)
        )
        return self._call_with_reasoning(prompt, "mvp_analyst", schema)

    def run_analyst(self) -> dict:
        """Run all four analysts and combine findings"""
        logger.info(f"Running analyst chain for game {self.game_id}")

        scoring   = self.run_scoring_analyst()
        team      = self.run_team_stats_analyst()
        player    = self.run_player_stats_analyst()
        mvp       = self.run_mvp_analyst()

        findings = {
            "scoring_runs":    scoring.get("scoring_runs", []),
            "momentum_shifts": scoring.get("momentum_shifts", []),
            "team_outliers":   team.get("team_outliers", []),
            "player_outliers": player.get("player_outliers", []),
            "mvp_candidates":  mvp.get("mvp_candidates", [])
        }

        logger.info(
            f"Analyst chain complete — "
            f"{len(findings['scoring_runs'])} runs, "
            f"{len(findings['momentum_shifts'])} momentum shifts, "
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