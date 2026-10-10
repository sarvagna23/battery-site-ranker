"""Weighted ranking of candidate sites. Pure Python so it can be tested without a database."""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    unit: str
    higher_is_better: bool
    default_weight: float


FEATURES = (
    Feature("max_kv", "Substation voltage", "kV", True, 0.20),
    Feature("dist_hv_line_km", "Distance to nearest 230 kV+ line", "km", False, 0.25),
    Feature("lines_within_10km", "115 kV+ lines within 10 km", "lines", True, 0.15),
    Feature("renewable_queue_mw", "Active solar and wind queue in county", "MW", True, 0.20),
    Feature("storage_queue_mw", "Active storage queue in county", "MW", False, 0.10),
    Feature("withdrawn_share", "Share of county queue withdrawn", "share", False, 0.10),
)
FEATURE_BY_KEY = {feature.key: feature for feature in FEATURES}

NEUTRAL_PERCENTILE = 0.5  # used when a feature has no data for a site


def default_weights() -> dict:
    return {feature.key: feature.default_weight for feature in FEATURES}


def percentile_ranks(values: list) -> list:
    """Midrank percentile in (0, 1) for each value; None stays None.

    Why midrank: ties share the average position, so a county with no queue data
    does not get an arbitrary rank among its equals.
    """
    present = sorted(value for value in values if value is not None)
    total = len(present)
    ranks = []
    for value in values:
        if value is None:
            ranks.append(None)
            continue
        below = bisect_left(present, value)
        equal = bisect_right(present, value) - below
        ranks.append((below + 0.5 * equal) / total)
    return ranks


def rank_sites(sites: list, weights: dict) -> list:
    """Score every site 0-100 and return them best first.

    Each feature becomes a percentile (flipped when lower is better), then the
    weighted average of percentiles is scaled to 100. Weights are relative, so
    they do not need to sum to 1. Each result carries per-feature points so the UI
    and the explainer can say exactly what drove the score.
    """
    cleaned = {feature.key: max(0.0, float(weights.get(feature.key, 0.0))) for feature in FEATURES}
    total_weight = sum(cleaned.values())
    if total_weight <= 0:
        raise ValueError("At least one weight must be greater than zero.")

    percentiles_by_key = {
        feature.key: percentile_ranks([site.get(feature.key) for site in sites])
        for feature in FEATURES
    }

    ranked = []
    for index, site in enumerate(sites):
        contributions = {}
        percentiles = {}
        imputed = []
        score = 0.0
        for feature in FEATURES:
            raw_percentile = percentiles_by_key[feature.key][index]
            if raw_percentile is None:
                goodness = NEUTRAL_PERCENTILE
                imputed.append(feature.key)
            else:
                goodness = raw_percentile if feature.higher_is_better else 1.0 - raw_percentile
            points = 100.0 * cleaned[feature.key] * goodness / total_weight
            contributions[feature.key] = points
            percentiles[feature.key] = None if raw_percentile is None else goodness
            score += points
        ranked.append({**site, "score": score, "contributions": contributions,
                       "percentiles": percentiles, "imputed": imputed})

    ranked.sort(key=lambda item: (-item["score"], str(item["id"])))
    for position, item in enumerate(ranked, start=1):
        item["rank"] = position
    return ranked


def feature_medians(sites: list) -> dict:
    """Median raw value of each feature across the candidate set (None if no data)."""
    medians = {}
    for feature in FEATURES:
        present = [site[feature.key] for site in sites if site.get(feature.key) is not None]
        medians[feature.key] = median(present) if present else None
    return medians
