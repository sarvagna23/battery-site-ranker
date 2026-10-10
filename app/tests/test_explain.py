from ranker.explain.agent import build_explainer
from ranker.explain.facts import build_fact_sheet, numbers_in, template_explanation, unsupported_numbers
from ranker.scoring import default_weights, rank_sites


def sample_ranked():
    sites = []
    for index in range(5):
        sites.append({"id": f"way/{index}", "name": f"Sub {index}", "operator": "Oncor", "county": "Harris",
                      "max_kv": 69 + index * 69, "dist_hv_line_km": 10.0 - index, "lines_within_10km": index,
                      "renewable_queue_mw": 100.0 * index, "storage_queue_mw": 50.0, "withdrawn_share": 0.1 * index})
    sites[0]["renewable_queue_mw"] = None
    return rank_sites(sites, default_weights())


def facts_for_top():
    ranked = sample_ranked()
    return build_fact_sheet(ranked[0], ranked), ranked


def test_fact_sheet_contains_rank_score_and_allowed_numbers():
    facts, ranked = facts_for_top()
    text = "\n".join(facts["lines"])
    assert f"Rank: 1 of {len(ranked)}" in text
    assert str(ranked[0]["rank"]) in facts["allowed_numbers"]
    assert f"{ranked[0]['score']:.1f}" in facts["allowed_numbers"]


def test_unsupported_numbers_detects_invented_figures():
    facts, _ = facts_for_top()
    assert unsupported_numbers("Rank 1 of 5.", facts) == []
    assert unsupported_numbers("It has 7777 MW queued.", facts) == ["7777"]
    assert numbers_in("1,250 MW and 3.5 km") == {"1250", "3.5"}


def test_template_uses_only_fact_numbers():
    facts, _ = facts_for_top()
    assert unsupported_numbers(template_explanation(facts), facts) == []


def test_template_mode_without_llm():
    facts, _ = facts_for_top()
    result = build_explainer(None).invoke({"facts": facts, "attempts": 0, "problems": []})
    assert result["mode"] == "template" and result["verified"] is True


def test_good_llm_draft_accepted_first_try():
    facts, _ = facts_for_top()
    calls = []

    def llm(system, prompt):
        calls.append(prompt)
        return f"This site ranks {facts['rank']} of {facts['total']}."

    result = build_explainer(llm).invoke({"facts": facts, "attempts": 0, "problems": []})
    assert result["mode"] == "llm" and result["attempts"] == 1 and len(calls) == 1


def test_bad_draft_retried_with_feedback_then_accepted():
    facts, _ = facts_for_top()
    prompts = []

    def llm(system, prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            return "It has 9876 MW of capacity."
        return f"Rank {facts['rank']} of {facts['total']}."

    result = build_explainer(llm).invoke({"facts": facts, "attempts": 0, "problems": []})
    assert result["mode"] == "llm" and result["attempts"] == 2
    assert "9876" in prompts[1]          # the retry prompt names the bad number


def test_persistent_bad_draft_falls_back_to_template():
    facts, _ = facts_for_top()
    result = build_explainer(lambda s, p: "Capacity is 9876 MW.").invoke(
        {"facts": facts, "attempts": 0, "problems": []})
    assert result["mode"] == "template_fallback" and "9876" in result["reason"]
    assert unsupported_numbers(result["explanation"], facts) == []


def test_llm_exception_falls_back():
    facts, _ = facts_for_top()

    def broken(system, prompt):
        raise RuntimeError("rate limited")

    result = build_explainer(broken).invoke({"facts": facts, "attempts": 0, "problems": []})
    assert result["mode"] == "template_fallback" and "rate limited" in result["reason"]
