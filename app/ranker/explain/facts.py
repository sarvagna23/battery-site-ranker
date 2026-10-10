"""Turns a ranked site into a fact sheet, and checks that text only uses numbers from it."""
import re

from ..scoring import FEATURE_BY_KEY, FEATURES, feature_medians

NUMBER_PATTERN = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")


def format_value(key: str, value) -> str:
    """Human-readable value with its unit, e.g. '345 kV', '2.2 km', '1,250 MW', '33 %'."""
    if value is None:
        return "no data"
    if key == "max_kv":
        return f"{value:g} kV"
    if key == "dist_hv_line_km":
        return f"{value:.1f} km"
    if key == "lines_within_10km":
        return f"{int(value)} lines"
    if key == "withdrawn_share":
        return f"{value * 100:.0f} %"
    return f"{value:,.0f} MW"


def numbers_in(text: str) -> set:
    """Every number written in the text, with thousands separators removed."""
    return {token.replace(",", "") for token in NUMBER_PATTERN.findall(text)}


def build_fact_sheet(site: dict, all_ranked: list) -> dict:
    """Collect everything the explanation may mention.

    Returns the facts as readable lines, the strongest and weakest features, and the set of
    numbers the explanation is allowed to contain.
    """
    medians = feature_medians(all_ranked)
    total = len(all_ranked)
    name = site.get("name") or "Unnamed substation"
    operator = f" ({site['operator']})" if site.get("operator") else ""

    lines = [
        f"Site: {name}{operator}, {site.get('county', 'unknown')} County",
        f"Rank: {site['rank']} of {total}; score {site['score']:.1f} out of 100",
    ]
    feature_facts = []
    for feature in FEATURES:
        value = site.get(feature.key)
        if value is None:
            lines.append(f"{feature.label}: no data for this county, so a neutral score was used")
            continue
        percentile = round(site["percentiles"][feature.key] * 100)
        points = site["contributions"][feature.key]
        direction = "higher is better" if feature.higher_is_better else "lower is better"
        lines.append(
            f"{feature.label}: {format_value(feature.key, value)} "
            f"(goodness percentile {percentile} of 100, {direction}; "
            f"median across sites {format_value(feature.key, medians[feature.key])}; "
            f"adds {points:.1f} points)"
        )
        feature_facts.append((feature.key, value, percentile, points))

    by_goodness = sorted(feature_facts, key=lambda item: item[2], reverse=True)
    strongest = by_goodness[:2]
    weakest = by_goodness[-1:] if len(by_goodness) > 2 else []
    return {
        "lines": lines,
        "strongest": strongest,
        "weakest": weakest,
        "allowed_numbers": numbers_in("\n".join(lines)),
        "site_name": name,
        "rank": site["rank"],
        "total": total,
        "score": site["score"],
    }


def unsupported_numbers(text: str, facts: dict) -> list:
    """Numbers in the text that do not appear in the fact sheet (empty means grounded)."""
    return sorted(numbers_in(text) - facts["allowed_numbers"])


def template_explanation(facts: dict) -> str:
    """Deterministic explanation built only from the fact sheet. Used as the fallback."""
    def describe(item):
        key, value, _, _ = item
        return f"{FEATURE_BY_KEY[key].label.lower()} ({format_value(key, value)})"

    sentences = [
        f"{facts['site_name']} ranks {facts['rank']} of {facts['total']} with a score of {facts['score']:.1f} out of 100."
    ]
    if facts["strongest"]:
        sentences.append("Its strongest factors are " + " and ".join(describe(i) for i in facts["strongest"]) + ".")
    if facts["weakest"]:
        sentences.append(f"The weakest factor is {describe(facts['weakest'][0])}.")
    return " ".join(sentences)
