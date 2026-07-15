# analysis/agent.py
import json
import ollama
import os
from pathlib import Path
from analysis.vector_store import NBAVectorStore

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

# Define models for different stages of analysis and writing
REASONING_MODEL  = "qwen2.5:32b"  # deep analysis and writing
FORMATTING_MODEL = "qwen2.5:14b"  # structured JSON output
WRITER_MODEL     = "qwen2.5:32b"  # narratives need good reasoning
EDITOR_MODEL     = "qwen2.5:32b"  # final polish needs good reasoning

# Output directory for narratives
OUTPUT_RAW_DIR = Path("output/raw-findings")

class NBAAnalysisAgent:

    def __init__(self, game_id: str):
        self.game_id                = game_id
        self.play_by_play           = None
        self.play_by_play_by_period = None
        self.team_comparison        = None
        self.player_comparison      = None
        self.mvp_data               = None
        self.vector_store           = NBAVectorStore()  # to be initialized later if needed

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

    def _save_output(self, filename: str, data: dict | list):
        """Save output to file for review"""
        OUTPUT_RAW_DIR.mkdir(parents=True, exist_ok=True)
        filepath = OUTPUT_RAW_DIR / filename
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"Saved output to {filepath}")

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
                    "num_predict": 16000,
                    "num_ctx": 32768  # increase context window
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
        except json.JSONDecodeError:
            logger.warning(f"JSON parse failed for {label}, attempting repair...")
            try:
                from json_repair import repair_json
                repaired = repair_json(raw)
                result = json.loads(repaired)
                logger.info(f"JSON repair successful for {label}")
                return result
            except Exception as e:
                logger.error(f"JSON repair failed for {label}: {e}")
                logger.error(f"Raw response: {raw[:500]}")
                raise

    def run_scoring_analyst(self, corrections: dict = None) -> dict:
        schema = """..."""
        
        correction_context = ""
        if corrections and corrections.get("scoring_runs"):
            correction_context = f"""
    IMPORTANT — Previous corrections from human reviewer:
    {json.dumps(corrections.get('scoring_runs'), indent=2)}
    Use these corrections to improve your analysis.
    """
        
        prompt = SCORING_ANALYST_PROMPT.format(
            play_by_play=json.dumps(self.play_by_play, indent=2, default=str)
        ) + correction_context

        findings = self._call_with_reasoning(prompt, "scoring_analyst", schema)
        self._save_output(f"scoring_analyst_{self.game_id}.json", findings)
        return findings
    
    def run_team_stats_analyst(self, corrections: dict = None) -> dict:
        schema = """..."""
        
        correction_context = ""
        if corrections and corrections.get("scoring_runs"):
            correction_context = f"""
    IMPORTANT — Previous corrections from human reviewer:
    {json.dumps(corrections.get('scoring_runs'), indent=2)}
    Use these corrections to improve your analysis.
    """
            
        prompt = TEAM_STATS_ANALYST_PROMPT.format(
            team_comparison=json.dumps(self.team_comparison, indent=2, default=str)
        ) + correction_context
        findings = self._call_with_reasoning(prompt, "team_stats_analyst", schema)
        self._save_output(f"team_stats_analyst_{self.game_id}.json", findings)
        return findings

    def run_player_stats_analyst(self, corrections: dict = None) -> dict:
        """Analyst 3 — player level outliers"""
        schema = """..."""
        correction_context = ""
        if corrections and corrections.get("scoring_runs"):
            correction_context = f"""
    IMPORTANT — Previous corrections from human reviewer:
    {json.dumps(corrections.get('scoring_runs'), indent=2)}
    Use these corrections to improve your analysis.
    """
        prompt = PLAYER_STATS_ANALYST_PROMPT.format(
            player_comparison=json.dumps(self.player_comparison, indent=2, default=str)
        ) + correction_context
        findings = self._call_with_reasoning(prompt, "player_stats_analyst", schema)
        self._save_output(f"player_stats_analyst_{self.game_id}.json", findings)
        return findings

    def run_mvp_analyst(self, corrections: dict = None) -> dict:
        """Analyst 4 — MVP candidates"""
        schema = """..."""
        correction_context = ""
        if corrections and corrections.get("scoring_runs"):
            correction_context = f"""
    IMPORTANT — Previous corrections from human reviewer:
    {json.dumps(corrections.get('scoring_runs'), indent=2)}
    Use these corrections to improve your analysis.
    """
        prompt = MVP_ANALYST_PROMPT.format(
            player_comparison=json.dumps(self.player_comparison, indent=2, default=str),
            mvp_data=json.dumps(self.mvp_data, indent=2, default=str)
        ) + correction_context
        findings = self._call_with_reasoning(prompt, "mvp_analyst", schema)
        self._save_output(f"mvp_analyst_{self.game_id}.json", findings)
        return findings

    def run_analyst(self) -> dict:
        """Run all four analysts and combine findings"""
        logger.info(f"Running analyst chain for game {self.game_id}")

        # pull any existing corrections to use as context
        corrections = self.vector_store.get_corrections(self.game_id)
        if corrections:
            logger.info(f"Found existing corrections for game {self.game_id} — using as context")

        scoring = self.run_scoring_analyst(corrections=corrections)
        team    = self.run_team_stats_analyst(corrections=corrections)
        player  = self.run_player_stats_analyst(corrections=corrections)
        mvp     = self.run_mvp_analyst(corrections=corrections)

        findings = {
            "scoring_runs":    scoring.get("scoring_runs", []),
            "momentum_shifts": scoring.get("momentum_shifts", []),
            "team_outliers":   team.get("team_outliers", []),
            "player_outliers": player.get("player_outliers", []),
            "mvp_candidates":  mvp.get("mvp_candidates", [])
        }

        # store findings in vector store
        self.vector_store.store_analysis(self.game_id, findings)
        self._save_output(f"full_analyst_{self.game_id}.json", findings)

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