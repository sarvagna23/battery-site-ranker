import pytest
from fastapi.testclient import TestClient

from ranker.api import create_app
from ranker.config import load_settings


class FakeRepository:
    def __init__(self, rows):
        self.rows = rows

    def load(self):
        return self.rows


def rows():
    return [
        {"id": f"way/{i}", "name": f"Sub {i}", "operator": None, "county": "Harris", "lat": 30 + i, "lon": -97,
         "max_kv": 69.0 + 69 * (i % 4), "dist_hv_line_km": 2.0 + i, "lines_within_10km": i,
         "renewable_queue_mw": 100.0 * i, "storage_queue_mw": 10.0, "withdrawn_share": 0.05 * i}
        for i in range(8)
    ]


@pytest.fixture
def client():
    app = create_app(repository=FakeRepository(rows()), settings=load_settings(), llm_call=None)
    return TestClient(app)


def test_health_and_features(client):
    assert client.get("/health").json()["status"] == "ok"
    keys = [f["key"] for f in client.get("/features").json()]
    assert "dist_hv_line_km" in keys and len(keys) == 6


def test_sites_default_ranking(client):
    data = client.get("/sites?top=3").json()
    assert data["candidates"] == 8 and len(data["sites"]) == 3
    assert [s["rank"] for s in data["sites"]] == [1, 2, 3]


def test_weights_change_the_order(client):
    only_distance = "&".join(f"w_{k}=0" for k in
                             ["max_kv", "lines_within_10km", "renewable_queue_mw", "storage_queue_mw", "withdrawn_share"])
    data = client.get(f"/sites?top=1&w_dist_hv_line_km=1&{only_distance}").json()
    assert data["sites"][0]["id"] == "way/0"      # smallest distance wins


def test_min_kv_filters_candidates(client):
    assert client.get("/sites?min_kv=200").json()["candidates"] == 4


def test_bad_inputs_rejected(client):
    assert client.get("/sites?top=0").status_code == 422
    assert client.get("/sites?w_max_kv=abc").status_code == 422
    zero = "&".join(f"w_{k}=0" for k in ["max_kv", "dist_hv_line_km", "lines_within_10km",
                                         "renewable_queue_mw", "storage_queue_mw", "withdrawn_share"])
    assert client.get(f"/sites?{zero}").status_code == 422


def test_explain_with_slash_in_id(client):
    response = client.post("/sites/way/3/explain", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "template" and "Sub 3" in body["explanation"]


def test_explain_unknown_site(client):
    assert client.post("/sites/way/999/explain", json={}).status_code == 404


def test_index_page_served(client):
    assert "Battery Storage Site Ranker" in client.get("/").text
