import sys
from pathlib import Path

# add project root to Python path so we can import analysis modules
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import json
from analysis.agent import NBAAnalysisAgent
from analysis.vector_store import NBAVectorStore

# ── Page Configuration ────────────────────────────────────
# sets the browser tab title, icon, and layout
st.set_page_config(
    page_title="NBA Analysis Review",
    page_icon="🏀",
    layout="wide"  # use full screen width
)

# ── Agent Options ─────────────────────────────────────────
# maps display names to the internal agent keys used by NBAAnalysisAgent
AGENT_OPTIONS = {
    "Scoring Analyst":      "scoring",
    "Team Stats Analyst":   "team_stats",
    "Player Stats Analyst": "player_stats",
    "MVP Analyst":          "mvp",
    "Full Pipeline":        "full"
}

# ── Helper Functions ──────────────────────────────────────

def load_existing_findings(game_id: str, agent: str) -> dict | None:
    """
    Check if we already have findings saved for this game and agent.
    This avoids re-running the agent if we already have results.
    Files are saved to output/raw-findings/ by the agent automatically.
    """
    path = Path(f"output/raw-findings/{agent}_analyst_{game_id}.json")
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None

def run_agent(game_id: str, agent: str) -> dict:
    """
    Initialize and run the selected agent for a given game.
    load_data() pulls all game data from PostgreSQL.
    Then runs the specific analyst method selected by the user.
    """
    nba_agent = NBAAnalysisAgent(game_id)
    nba_agent.load_data()

    if agent == "scoring":
        return nba_agent.run_scoring_analyst()
    elif agent == "team_stats":
        return nba_agent.run_team_stats_analyst()
    elif agent == "player_stats":
        return nba_agent.run_player_stats_analyst()
    elif agent == "mvp":
        return nba_agent.run_mvp_analyst()
    elif agent == "full":
        return nba_agent.run_analyst()

# ── Sidebar ───────────────────────────────────────────────
# the sidebar is the control panel — game ID input, agent selection, run button
st.sidebar.title("🏀 NBA Analysis")

# text input for the NBA game ID (e.g. 0042500311)
game_id = st.sidebar.text_input(
    "Game ID",
    placeholder="e.g. 0042500311"
)

# dropdown to select which agent to run
selected_agent_label = st.sidebar.selectbox(
    "Select Agent",
    options=list(AGENT_OPTIONS.keys())
)
selected_agent = AGENT_OPTIONS[selected_agent_label]

# only show run button if a game ID has been entered
if game_id:
    # check if findings already exist for this game + agent combination
    existing = load_existing_findings(game_id, selected_agent)

    if existing:
        # if findings exist, give user option to load them or re-run
        st.sidebar.success("Found existing findings")
        col1, col2 = st.sidebar.columns(2)

        with col1:
            if st.button("Load Existing"):
                # load from file without calling the LLM again
                st.session_state['findings']     = existing
                st.session_state['game_id']      = game_id
                st.session_state['active_agent'] = selected_agent
                st.rerun()

        with col2:
            if st.button("Re-run"):
                # re-run the agent even though findings exist
                with st.spinner(f"Running {selected_agent_label}..."):
                    findings = run_agent(game_id, selected_agent)
                st.session_state['findings']     = findings
                st.session_state['game_id']      = game_id
                st.session_state['active_agent'] = selected_agent
                st.rerun()
    else:
        # no existing findings — show run button
        if st.sidebar.button(f"▶ Run {selected_agent_label}"):
            with st.spinner(f"Running {selected_agent_label}..."):
                findings = run_agent(game_id, selected_agent)
            st.session_state['findings']     = findings
            st.session_state['game_id']      = game_id
            st.session_state['active_agent'] = selected_agent
            st.rerun()

# ── Main Content ──────────────────────────────────────────
# session_state persists data between Streamlit reruns
# if no findings yet, show the welcome screen
if 'findings' not in st.session_state:
    st.title("🏀 NBA Game Analysis Review")
    st.info("Enter a game ID, select an agent, and click Run.")

else:
    # pull findings and metadata from session state
    findings     = st.session_state['findings']
    game_id      = st.session_state['game_id']
    active_agent = st.session_state['active_agent']

    st.title(f"🏀 {game_id} — {selected_agent_label}")

    # three tabs — one per section of the analysis
    tab1, tab2, tab3 = st.tabs([
        "📈 Scoring & Momentum",
        "📊 Statistical Outliers",
        "⭐ MVP Candidates"
    ])

    # ── Tab 1: Scoring & Momentum ─────────────────────────
    with tab1:
        st.header("Scoring Runs & Momentum Shifts")

        scoring_runs    = findings.get('scoring_runs', [])
        momentum_shifts = findings.get('momentum_shifts', [])

        if not scoring_runs and not momentum_shifts:
            st.warning("No scoring data found — try running the Scoring Analyst.")

        # lists to collect corrected versions of each finding
        corrected_runs   = []
        corrected_shifts = []

        # ── Scoring Runs ──────────────────────────────────
        if scoring_runs:
            st.subheader(f"Scoring Runs ({len(scoring_runs)})")

            # display each run in a collapsible expander
            for i, run in enumerate(scoring_runs):
                with st.expander(
                    f"Run {i+1} — {run.get('team')} | "
                    f"Q{run.get('period')} | "
                    f"{run.get('run_size')} pts"
                ):
                    # two columns — left for JSON, right for narrative
                    col1, col2 = st.columns(2)

                    with col1:
                        st.markdown("**Raw JSON**")
                        # editable JSON so user can correct the structured data
                        edited_json = st.text_area(
                            "Edit JSON",
                            value=json.dumps(run, indent=2),
                            height=250,
                            key=f"run_json_{i}"
                        )

                    with col2:
                        st.markdown("**Your Narrative**")
                        # editable text so user can write or correct the story
                        narrative = st.text_area(
                            "Write or correct the narrative",
                            value=run.get('description', ''),
                            height=250,
                            key=f"run_narrative_{i}"
                        )

                    # collect the corrected version for saving
                    corrected_runs.append({
                        "json":      edited_json,
                        "narrative": narrative
                    })

        # ── Momentum Shifts ───────────────────────────────
        if momentum_shifts:
            st.subheader(f"Momentum Shifts ({len(momentum_shifts)})")

            for i, shift in enumerate(momentum_shifts):
                with st.expander(
                    f"Shift {i+1} — {shift.get('team_that_gained')} | "
                    f"Q{shift.get('period')}"
                ):
                    col1, col2 = st.columns(2)

                    with col1:
                        st.markdown("**Raw JSON**")
                        edited_json = st.text_area(
                            "Edit JSON",
                            value=json.dumps(shift, indent=2),
                            height=250,
                            key=f"shift_json_{i}"
                        )

                    with col2:
                        st.markdown("**Your Narrative**")
                        narrative = st.text_area(
                            "Write or correct the narrative",
                            value=shift.get('description', ''),
                            height=250,
                            key=f"shift_narrative_{i}"
                        )

                    corrected_shifts.append({
                        "json":      edited_json,
                        "narrative": narrative
                    })

        # ── Save & Re-run Button ──────────────────────────
        # only show if there's something to save
        if scoring_runs or momentum_shifts:
            if st.button("💾 Save & Re-run", type="primary"):
                # initialize vector store and save corrections
                vector_store = NBAVectorStore()
                corrections  = {
                    "scoring_runs":    corrected_runs,
                    "momentum_shifts": corrected_shifts
                }

                # store corrections in ChromaDB for future reference
                vector_store.store_correction(game_id, corrections)
                st.success("Corrections saved to vector store!")

                # re-run the agent — it will now pull these corrections as context
                with st.spinner("Re-running agent with your corrections..."):
                    findings = run_agent(game_id, active_agent)
                    st.session_state['findings'] = findings

                st.success("Agent re-run complete!")
                st.rerun()

    # ── Tab 2: Statistical Outliers ───────────────────────
    with tab2:
        st.header("Statistical Outliers")

        team_outliers   = findings.get('team_outliers', [])
        player_outliers = findings.get('player_outliers', [])

        if not team_outliers and not player_outliers:
            st.warning("No outlier data found — try running Team or Player Stats Analyst.")

        # ── Team Outliers ─────────────────────────────────
        if team_outliers:
            st.subheader(f"Team Outliers ({len(team_outliers)})")
            for i, outlier in enumerate(team_outliers):
                with st.expander(
                    f"{outlier.get('team')} — {outlier.get('stat')} | "
                    f"{outlier.get('direction')} average"
                ):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**Raw JSON**")
                        st.text_area(
                            "Edit JSON",
                            value=json.dumps(outlier, indent=2),
                            height=250,
                            key=f"team_outlier_json_{i}"
                        )
                    with col2:
                        st.markdown("**Your Narrative**")
                        st.text_area(
                            "Write or correct the narrative",
                            value=outlier.get('significance', ''),
                            height=250,
                            key=f"team_outlier_narrative_{i}"
                        )

        # ── Player Outliers ───────────────────────────────
        if player_outliers:
            st.subheader(f"Player Outliers ({len(player_outliers)})")
            for i, outlier in enumerate(player_outliers):
                with st.expander(
                    f"{outlier.get('player')} ({outlier.get('team')}) — "
                    f"{outlier.get('stat')} | {outlier.get('direction')} average"
                ):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**Raw JSON**")
                        st.text_area(
                            "Edit JSON",
                            value=json.dumps(outlier, indent=2),
                            height=250,
                            key=f"player_outlier_json_{i}"
                        )
                    with col2:
                        st.markdown("**Your Narrative**")
                        st.text_area(
                            "Write or correct the narrative",
                            value=outlier.get('significance', ''),
                            height=250,
                            key=f"player_outlier_narrative_{i}"
                        )

    # ── Tab 3: MVP Candidates ─────────────────────────────
    with tab3:
        st.header("MVP Candidates")

        mvp_candidates = findings.get('mvp_candidates', [])

        if not mvp_candidates:
            st.warning("No MVP data found — try running the MVP Analyst.")

        for i, mvp in enumerate(mvp_candidates):
            with st.expander(
                f"{mvp.get('player')} ({mvp.get('team')}) — "
                f"Rank #{mvp.get('rank')}"
            ):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Raw JSON**")
                    st.text_area(
                        "Edit JSON",
                        value=json.dumps(mvp, indent=2),
                        height=300,
                        key=f"mvp_json_{i}"
                    )
                with col2:
                    st.markdown("**Your Narrative**")
                    st.text_area(
                        "Write or correct the narrative",
                        value=mvp.get('reasoning', ''),
                        height=300,
                        key=f"mvp_narrative_{i}"
                    )