"""Contracts for the API stack: fastapi + starlette TestClient, pydantic v2.

Call sites: src/api (FastAPI app, pydantic response models)."""

from __future__ import annotations

import pytest


class TestFastapi:
    def test_app_route_roundtrip(self):
        fastapi = pytest.importorskip("fastapi")
        testclient = pytest.importorskip("fastapi.testclient")

        app = fastapi.FastAPI()

        @app.get("/health")
        def health():  # pragma: no cover - exercised via TestClient
            return {"status": "ok"}

        client = testclient.TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestPydanticV2:
    def test_model_validate_and_dump(self):
        pydantic = pytest.importorskip("pydantic")

        class Article(pydantic.BaseModel):
            url: str
            title: str | None = None
            word_count: int = 0

        model = Article.model_validate(
            {"url": "https://a.com/x", "title": "T", "word_count": "7"}
        )
        assert model.word_count == 7  # coercion contract
        dumped = model.model_dump()
        assert dumped["url"] == "https://a.com/x"
