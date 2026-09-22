from pathlib import Path
from nba_api.stats.static import teams

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
COURTS_DIR = ASSETS_DIR / "courts"
LOGOS_DIR = ASSETS_DIR / "logos"
COURT_EXTENSIONS = (".svg", ".png", ".jpg", ".jpeg")
LOGO_EXTENSIONS = (".svg", ".png", ".jpg", ".jpeg")

TEAMS_BY_ID = {t["id"]: t for t in teams.get_teams()}
TEAMS_BY_ABBR = {t["abbreviation"]: t for t in teams.get_teams()}


def get_team(team_id):
    return TEAMS_BY_ID.get(int(team_id))


def get_abbr(team_id):
    team = get_team(team_id)
    return team["abbreviation"] if team else None


def get_court_asset_path(team_id):
    abbr = get_abbr(team_id)
    if not abbr:
        return None
    for ext in COURT_EXTENSIONS:
        candidate = COURTS_DIR / f"{abbr}{ext}"
        if candidate.exists():
            return candidate
    return None


def get_logo_asset_path(team_id):
    abbr = get_abbr(team_id)
    if not abbr:
        return None
    for ext in LOGO_EXTENSIONS:
        candidate = LOGOS_DIR / f"{abbr}{ext}"
        if candidate.exists():
            return candidate
    return None
