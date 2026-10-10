"""Measures the explainer on real data: how often the first draft passes the number check.

Needs ANTHROPIC_API_KEY. Usage: python scripts/eval_explanations.py [how_many_sites]
"""
import sys
import time

from ranker.api import SiteRepository
from ranker.config import load_settings
from ranker.explain.agent import build_explainer
from ranker.explain.facts import build_fact_sheet
from ranker.explain.llm import make_llm_call
from ranker.scoring import default_weights, rank_sites


def main() -> None:
    how_many = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    settings = load_settings()
    llm = make_llm_call(settings)
    if llm is None:
        sys.exit("Set ANTHROPIC_API_KEY (and leave EXPLAIN_MODE unset) to run this evaluation.")
    explainer = build_explainer(llm)
    ranked = rank_sites([s for s in SiteRepository(settings.database_url).load()], default_weights())

    first_try = retried = fell_back = 0
    latencies = []
    for site in ranked[:how_many]:
        facts = build_fact_sheet(site, ranked)
        started = time.perf_counter()
        result = explainer.invoke({"facts": facts, "attempts": 0, "problems": []})
        latencies.append(time.perf_counter() - started)
        if result["mode"] == "template_fallback":
            fell_back += 1
        elif result["attempts"] == 1:
            first_try += 1
        else:
            retried += 1
    total = len(latencies)
    print(f"sites evaluated: {total}")
    print(f"passed number check on first draft: {first_try} ({100 * first_try / total:.0f}%)")
    print(f"passed after one retry:             {retried} ({100 * retried / total:.0f}%)")
    print(f"fell back to template:              {fell_back} ({100 * fell_back / total:.0f}%)")
    print(f"mean latency per explanation:       {1000 * sum(latencies) / total:.0f} ms")


if __name__ == "__main__":
    main()
