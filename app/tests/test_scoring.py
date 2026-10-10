import pytest

from ranker.scoring import FEATURES, default_weights, percentile_ranks, rank_sites


def make_site(site_id, **overrides):
    base = {"id": site_id, "max_kv": 138, "dist_hv_line_km": 5.0, "lines_within_10km": 3,
            "renewable_queue_mw": 100.0, "storage_queue_mw": 50.0, "withdrawn_share": 0.2}
    base.update(overrides)
    return base


def test_percentile_ranks_midrank_and_none():
    ranks = percentile_ranks([10, 20, 20, None, 30])
    assert ranks[3] is None
    assert ranks[0] == pytest.approx(0.125)   # 0 below, 1 equal, of 4 present
    assert ranks[1] == ranks[2] == pytest.approx(0.5)
    assert ranks[4] == pytest.approx(0.875)


def test_better_site_ranks_first():
    strong = make_site("strong", max_kv=345, dist_hv_line_km=1.0, lines_within_10km=9,
                       renewable_queue_mw=900.0, storage_queue_mw=0.0, withdrawn_share=0.0)
    weak = make_site("weak", max_kv=69, dist_hv_line_km=30.0, lines_within_10km=0,
                     renewable_queue_mw=5.0, storage_queue_mw=800.0, withdrawn_share=0.7)
    middle = make_site("middle")
    ranked = rank_sites([weak, middle, strong], default_weights())
    assert [site["id"] for site in ranked] == ["strong", "middle", "weak"]
    assert [site["rank"] for site in ranked] == [1, 2, 3]
    assert ranked[0]["score"] > ranked[1]["score"] > ranked[2]["score"]


def test_lower_is_better_flips_distance():
    near = make_site("near", dist_hv_line_km=1.0)
    far = make_site("far", dist_hv_line_km=40.0)
    weights = {f.key: 0.0 for f in FEATURES}
    weights["dist_hv_line_km"] = 1.0
    ranked = rank_sites([far, near], weights)
    assert ranked[0]["id"] == "near"


def test_weights_are_relative_and_contributions_sum_to_score():
    sites = [make_site("a", max_kv=345), make_site("b", max_kv=138), make_site("c", max_kv=69)]
    small = rank_sites(sites, {f.key: 1.0 for f in FEATURES})
    large = rank_sites(sites, {f.key: 10.0 for f in FEATURES})
    assert [s["score"] for s in small] == pytest.approx([s["score"] for s in large])
    for site in small:
        assert sum(site["contributions"].values()) == pytest.approx(site["score"])
        assert 0 <= site["score"] <= 100


def test_missing_feature_is_neutral_and_flagged():
    with_data = make_site("a")
    without_queue = make_site("b", renewable_queue_mw=None, storage_queue_mw=None, withdrawn_share=None)
    ranked = rank_sites([with_data, without_queue], default_weights())
    missing = next(site for site in ranked if site["id"] == "b")
    assert set(missing["imputed"]) == {"renewable_queue_mw", "storage_queue_mw", "withdrawn_share"}
    assert missing["percentiles"]["renewable_queue_mw"] is None


def test_all_zero_weights_rejected():
    with pytest.raises(ValueError):
        rank_sites([make_site("a")], {f.key: 0.0 for f in FEATURES})
