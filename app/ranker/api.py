"""FastAPI app: ranked sites, feature metadata, explanations, and the map page."""
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Settings, load_settings
from .db import connect
from .explain.agent import build_explainer
from .explain.facts import build_fact_sheet
from .explain.llm import make_llm_call
from .scoring import FEATURES, default_weights, rank_sites

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
CACHE_SECONDS = 60


class SiteRepository:
    """Reads the site_features view, caching the result briefly so slider drags stay fast."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self._cache = None
        self._loaded_at = 0.0

    def load(self) -> list:
        if self._cache is not None and time.monotonic() - self._loaded_at < CACHE_SECONDS:
            return self._cache
        with connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM site_features")
            rows = cursor.fetchall()
        self._cache = rows
        self._loaded_at = time.monotonic()
        return rows


class ExplainRequest(BaseModel):
    weights: Optional[dict] = None
    min_kv: float = 69.0


def parse_weights(query_params) -> dict:
    """Weights come from w_<feature> query parameters; missing ones use the defaults."""
    weights = default_weights()
    for feature in FEATURES:
        raw = query_params.get(f"w_{feature.key}")
        if raw is None:
            continue
        try:
            weights[feature.key] = float(raw)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"w_{feature.key} must be a number")
    return weights


def ranked_for(repository, weights: dict, min_kv: float) -> list:
    candidates = [site for site in repository.load() if site["max_kv"] >= min_kv]
    if not candidates:
        return []
    try:
        return rank_sites(candidates, weights)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


def public_site(site: dict) -> dict:
    """The fields the UI needs, rounded for a compact payload."""
    return {
        "id": site["id"], "rank": site["rank"], "score": round(site["score"], 1),
        "name": site.get("name"), "operator": site.get("operator"), "county": site.get("county"),
        "lat": site["lat"], "lon": site["lon"],
        "features": {feature.key: site.get(feature.key) for feature in FEATURES},
        "contributions": {k: round(v, 1) for k, v in site["contributions"].items()},
        "imputed": site["imputed"],
    }


def create_app(repository=None, settings: Settings | None = None, llm_call="auto") -> FastAPI:
    settings = settings or load_settings()
    repository = repository or SiteRepository(settings.database_url)
    llm = make_llm_call(settings) if llm_call == "auto" else llm_call
    explainer = build_explainer(llm)

    app = FastAPI(title="Battery Storage Site Ranker")

    @app.get("/health")
    def health():
        return {"status": "ok", "state": settings.state}

    @app.get("/features")
    def features():
        return [
            {"key": f.key, "label": f.label, "unit": f.unit,
             "higher_is_better": f.higher_is_better, "default_weight": f.default_weight}
            for f in FEATURES
        ]

    @app.get("/sites")
    def sites(request: Request, top: int = 25, min_kv: float = 69.0):
        if not 1 <= top <= 200:
            raise HTTPException(status_code=422, detail="top must be between 1 and 200")
        weights = parse_weights(request.query_params)
        started = time.perf_counter()
        ranked = ranked_for(repository, weights, min_kv)
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {
            "state": settings.state, "candidates": len(ranked), "weights": weights,
            "rank_ms": round(elapsed_ms, 1), "sites": [public_site(s) for s in ranked[:top]],
        }

    @app.post("/sites/{site_id:path}/explain")
    def explain(site_id: str, body: ExplainRequest | None = None):
        body = body or ExplainRequest()
        weights = {**default_weights(), **(body.weights or {})}
        ranked = ranked_for(repository, weights, body.min_kv)
        site = next((item for item in ranked if item["id"] == site_id), None)
        if site is None:
            raise HTTPException(status_code=404, detail="Site not found for these filters")
        facts = build_fact_sheet(site, ranked)
        result = explainer.invoke({"facts": facts, "attempts": 0, "problems": []})
        return {
            "id": site_id, "explanation": result["explanation"], "mode": result["mode"],
            "attempts": result.get("attempts", 0), "reason": result.get("reason"),
            "facts": facts["lines"],
        }

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def app_factory() -> FastAPI:
    """Entry point for uvicorn: uvicorn ranker.api:app_factory --factory"""
    return create_app()
