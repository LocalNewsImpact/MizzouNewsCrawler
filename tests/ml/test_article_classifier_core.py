from __future__ import annotations

import types
from pathlib import Path

import pytest

import src.ml.article_classifier as article_classifier

# typing imports intentionally minimal for test




def _make_prediction_dict(label: str, score: float) -> dict:
    return {"label": label, "score": score}


def test_article_classifier_uses_checkpoint_pipeline(tmp_path, monkeypatch):
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_text("placeholder")

    captured: dict[str, object] = {}

    def fake_load_pt(checkpoint_path: Path, device: int):
        assert checkpoint_path == checkpoint
        captured["device"] = device

        def fake_runner(texts, truncation=True):
            captured["run"] = list(texts)
            return [
                [
                    _make_prediction_dict("second", 0.4),
                    _make_prediction_dict("first", 0.9),
                ]
            ]

        return fake_runner, "checkpoint-id", "1.2.3"

    monkeypatch.setattr(
        article_classifier,
        "_load_pt_classifier",
        fake_load_pt,
    )

    classifier = article_classifier.ArticleClassifier(checkpoint)

    predictions = classifier.predict_text("hello world", top_k=2)

    assert captured["device"] == -1
    assert captured["run"] == ["hello world"]
    assert classifier.model_identifier == "checkpoint-id"
    assert classifier.model_version == "1.2.3"
    assert [p.label for p in predictions] == ["first", "second"]
    assert all(isinstance(p.score, float) for p in predictions)


def test_article_classifier_falls_back_to_pretrained_dir(
    tmp_path,
    monkeypatch,
):
    model_dir = tmp_path / "classifier"
    model_dir.mkdir()

    captured: dict[str, object] = {
        "tokenizer_name": None,
        "model_name": None,
        "pipeline_device": None,
    }

    class DummyTokenizer:  # pragma: no cover - trivial container
        pass

    class DummyAutoTokenizer:
        @staticmethod
        def from_pretrained(name: str):
            captured["tokenizer_name"] = name
            return DummyTokenizer()

    class DummyModel:
        def __init__(self):
            self.config = types.SimpleNamespace(
                model_version=None,
                name_or_path="hf-model",
            )

    class DummyAutoModel:
        @staticmethod
        def from_pretrained(name: str):
            captured["model_name"] = name
            return DummyModel()

    def fake_pipeline(task, *, model, tokenizer, return_all_scores, device):
        captured["pipeline_device"] = device
        assert task == "text-classification"
        assert return_all_scores is True
        assert model is not None
        assert tokenizer is not None

        def runner(texts, truncation=True):
            return [[_make_prediction_dict("label", 0.7)]] * len(texts)

        return runner

    monkeypatch.setattr(
        article_classifier,
        "AutoTokenizer",
        DummyAutoTokenizer,
    )
    monkeypatch.setattr(
        article_classifier,
        "AutoModelForSequenceClassification",
        DummyAutoModel,
    )
    monkeypatch.setattr(article_classifier, "pipeline", fake_pipeline)

    classifier = article_classifier.ArticleClassifier(model_dir, device=0)

    assert captured["tokenizer_name"] == str(model_dir)
    assert captured["model_name"] == str(model_dir)
    assert captured["pipeline_device"] == 0
    assert classifier.model_identifier == str(model_dir)
    assert classifier.model_version == "hf-model"
    preds = classifier.predict_batch(["a", "b"], top_k=1)
    assert len(preds) == 2
    assert preds[0][0].label == "label"


def test_predict_batch_validates_input(tmp_path, monkeypatch):
    runner_calls: dict[str, object] = {}

    def fake_load_pt(_path, _device):
        def runner(texts, truncation=True):
            runner_calls["texts"] = list(texts)
            return [[_make_prediction_dict("ok", 1.0)]]

        return runner, "id", "ver"

    monkeypatch.setattr(
        article_classifier,
        "_load_pt_classifier",
        fake_load_pt,
    )

    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_text("data")

    classifier = article_classifier.ArticleClassifier(checkpoint)

    with pytest.raises(TypeError):
        classifier.predict_batch("not-a-sequence")

    inputs = ["", None]  # type: ignore[list-item]
    preds = classifier.predict_batch(inputs, top_k=1)
    assert runner_calls["texts"] == ["", ""]
    assert preds[0][0].label == "ok"


def test_load_pt_classifier_normalizes_state_dict(tmp_path, monkeypatch):
    checkpoint = tmp_path / "cin_model.pt"
    checkpoint.write_text("binary")

    state_dict = {
        "state_dict": {
            "classifier_primary.weight": article_classifier.torch.zeros(2, 2),
            "classifier_primary.bias": article_classifier.torch.zeros(2),
        }
    }

    monkeypatch.setattr(
        article_classifier.torch,
        "load",
        lambda path, map_location: state_dict,
    )

    loaded_state: dict[str, article_classifier.torch.Tensor] = {}

    class DummyConfig:  # pragma: no cover - simple struct
        pass

    class DummyBertConfig:
        @staticmethod
        def from_pretrained(*_args, **_kwargs):
            return DummyConfig()

    class DummyBertModel:
        def __init__(self, config):
            self.config = config
            self.state = None
            self.eval_called = False

        def load_state_dict(self, state, strict=False):
            self.state = state
            loaded_state.update(state)
            return ([], [])

        def eval(self):
            self.eval_called = True

    class DummyAutoTokenizer:
        @staticmethod
        def from_pretrained(name: str):
            assert name == article_classifier._BASE_MODEL_NAME
            return "tokenizer"

    pipeline_calls: dict[str, object] = {}

    def fake_pipeline(task, *, model, tokenizer, return_all_scores, device):
        pipeline_calls["task"] = task
        pipeline_calls["tokenizer"] = tokenizer
        pipeline_calls["device"] = device

        def runner(texts, truncation=True):
            return [[_make_prediction_dict("label", 0.8)]] * len(texts)

        return runner

    monkeypatch.setattr(article_classifier, "BertConfig", DummyBertConfig)
    monkeypatch.setattr(
        article_classifier,
        "BertForSequenceClassification",
        DummyBertModel,
    )
    monkeypatch.setattr(
        article_classifier,
        "AutoTokenizer",
        DummyAutoTokenizer,
    )
    monkeypatch.setattr(article_classifier, "pipeline", fake_pipeline)

    runner, model_identifier, model_version = article_classifier._load_pt_classifier(
        checkpoint,
        device=-1,
    )

    assert "classifier.weight" in loaded_state
    assert "classifier.bias" in loaded_state
    assert pipeline_calls["task"] == "text-classification"
    assert pipeline_calls["device"] == -1
    assert model_identifier == str(checkpoint)
    assert model_version == checkpoint.stem
    outputs = runner(["text"])  # type: ignore[assignment]
    first_prediction = outputs[0][0]  # type: ignore[index]
    assert first_prediction["label"] == "label"
