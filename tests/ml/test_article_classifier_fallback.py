from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def tmp_invalid_models_dir(tmp_path: Path) -> Path:
    # Create an empty dir to simulate invalid MODEL_PATH
    d = tmp_path / "models"
    d.mkdir()
    return d


def test_classifier_falls_back_when_model_path_invalid(
    tmp_invalid_models_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    # Point MODEL_PATH to an empty directory
    monkeypatch.setenv("MODEL_PATH", str(tmp_invalid_models_dir))

    # Mock HF loading pieces so no network is used
    with (
        patch("src.ml.article_classifier.AutoTokenizer.from_pretrained") as mock_tok,
        patch(
            "src.ml.article_classifier.AutoModelForSequenceClassification."
            "from_pretrained"
        ) as mock_model,
        patch("src.ml.article_classifier.pipeline") as mock_pipe,
    ):
        mock_tok.return_value = MagicMock()
        model_instance = MagicMock()
        # Surface a minimal config with name_or_path for version fallback
        model_instance.config = MagicMock()
        model_instance.config.name_or_path = (
            "distilbert-base-uncased-finetuned-sst-2-english"
        )
        mock_model.return_value = model_instance

        # Make pipeline return a callable that yields expected list shape
        def fake_pipeline(*args, **kwargs):
            def _call(texts, **_):
                # Return one prediction per input text
                return [[{"label": "POS", "score": 0.9}] for _t in texts]

            return _call

        mock_pipe.side_effect = fake_pipeline

        from src.ml.article_classifier import ArticleClassifier

        clf = ArticleClassifier(model_path=str(tmp_invalid_models_dir))

        # Basic predict smoke
        preds = clf.predict_text("news story")
        assert preds and preds[0].label

        # Ensure fallback path used mocked HF pieces
        assert mock_tok.called
        assert mock_model.called
        assert mock_pipe.called
