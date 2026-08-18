# analysis/models/train.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from loguru import logger
from analysis.models.win_probability import WinProbabilityModel

# nba_api SEASON_ID convention: "2"+year = regular season, "4"+year = playoffs
DEFAULT_SEASONS = ["22024", "42024", "22025", "42025"]


def train_win_probability_model(seasons: list[str] = None, save_model: bool = True) -> dict:
    """
    Build training data, cross-validate, fit on the full dataset, and
    (optionally) persist the model.

    seasons:    season codes to train on (defaults to DEFAULT_SEASONS)
    save_model: whether to call model.save() after fitting
    """
    seasons = seasons or DEFAULT_SEASONS
    model = WinProbabilityModel()

    logger.info(f"Building training data for seasons: {seasons}")
    df = model.build_training_data(seasons)
    if df.empty:
        raise ValueError(f"No training data found for seasons {seasons}")
    logger.info(f"Training data shape: {df.shape}")

    logger.info("Running cross-validation before committing to a full fit")
    cv_results = model.cross_validate(df)

    logger.info("Fitting on full training data")
    fit_metadata = model.train(df=df)

    if save_model:
        model.save()

    return {
        "cv_results":    cv_results,
        "fit_metadata":  fit_metadata,
    }


if __name__ == "__main__":
    seasons_arg = sys.argv[1] if len(sys.argv) > 1 else None
    seasons     = seasons_arg.split(",") if seasons_arg else DEFAULT_SEASONS
    save_model  = sys.argv[2].lower() != "false" if len(sys.argv) > 2 else True

    results = train_win_probability_model(seasons, save_model)
    logger.info(f"CV results: {results['cv_results']}")
    logger.info(f"Fit metadata: {results['fit_metadata']}")
