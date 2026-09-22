"""
Per-team primary colors for the dashboard's charts.

Fill in a hex string (e.g. "#C8102E") for any team below. Leave a team as
None to fall back to the neutral palette (DEFAULT_HOME_PRIMARY /
DEFAULT_AWAY_PRIMARY below) for that team, whether it plays home or away.

One color per team is enough — the same team can be the "home" side
in one game and the "away" side in another, so callers should assign
whichever color is here to the home/away side depending on that game's
matchup, not on anything fixed here.
"""

TEAM_COLORS = {
    "ATL": "#C8102E",
    "BKN": "#222222",
    "BOS": "#007A33",
    "CHA": "#1D1160",
    "CHI": "#CE1141",
    "CLE": "#860038",
    "DAL": "#00538C",
    "DEN": "#FEC524",
    "DET": "#1D428A",
    "GSW": "#1D428A",
    "HOU": "#CE1141",
    "IND": "#FDBB30",
    "LAC": "#1D428A",
    "LAL": "#552583",
    "MEM": "#5D76A9",
    "MIA": "#98002E",
    "MIL": "#00471B",
    "MIN": "#0C2340",
    "NOP": "#0C2340",
    "NYK": "#eb6834",
    "OKC": "#007ac1",
    "ORL": "#0077c0",
    "PHI": "#ed174c",
    "PHX": "#e56020",
    "POR": "#e03a3e",
    "SAC": "#5a2d81",
    "SAS": "#6b7680",
    "TOR": "#ce1141",
    "UTA": "#002B5C",
    "WAS": "#002B5C",
}

# Neutral fallback for either side of a matchup when a team's primary color
# is left unset above.
DEFAULT_HOME_PRIMARY = "#6b7680"  # gray
DEFAULT_AWAY_PRIMARY = "#eb6834"  # orange


