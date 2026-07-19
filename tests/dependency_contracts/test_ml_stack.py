"""Contracts for the model-coupled stack: torch+transformers (production
checkpoint), storysniffer→scikit-learn (skops model), spacy, nltk.

These are the highest-risk bumps: the artifact (checkpoint / skops pickle /
spacy model) was produced under one library version and loaded under another.
The transformers 5.x `return_all_scores` removal broke production for a day
while mocked unit tests stayed green — these contracts are the replacement.
"""

from __future__ import annotations

import pytest

from .conftest import find_production_checkpoint


class TestTransformersTorchClassifier:
    """Call site: src/ml/article_classifier.py — pipeline('text-classification',
    top_k=None) + predict_batch expecting List[List[{label, score}]]."""

    @pytest.mark.allow_network  # tokenizer fetch from HuggingFace hub
    def test_checkpoint_loads_and_predicts_batch(self):
        checkpoint = find_production_checkpoint()
        if checkpoint is None:
            pytest.skip("production checkpoint not present in this venue")
        pytest.importorskip("torch")
        pytest.importorskip("transformers")

        try:
            from src.ml.article_classifier import ArticleClassifier
        except ImportError:
            pytest.skip("src/ not shipped in this image (e.g. ml-base)")

        clf = ArticleClassifier(checkpoint)
        preds = clf.predict_batch(
            [
                "The city council approved the municipal budget on Tuesday.",
                "The Tigers beat the Jayhawks 78-70 in overtime.",
            ],
            top_k=2,
        )
        assert len(preds) == 2
        for per_text in preds:
            assert len(per_text) >= 1
            for p in per_text:
                assert isinstance(p.label, str) and p.label
                assert isinstance(p.score, float) and 0.0 <= p.score <= 1.0

    @pytest.mark.allow_network  # tokenizer fetch from HuggingFace hub
    def test_pipeline_top_k_none_returns_all_scores_per_text(self):
        """Pin the raw pipeline return shape predict_batch depends on:
        top_k=None → a LIST of {label, score} dicts per input text."""
        checkpoint = find_production_checkpoint()
        if checkpoint is None:
            pytest.skip("production checkpoint not present in this venue")
        pytest.importorskip("torch")
        pytest.importorskip("transformers")

        try:
            from src.ml.article_classifier import ArticleClassifier
        except ImportError:
            pytest.skip("src/ not shipped in this image (e.g. ml-base)")

        clf = ArticleClassifier(checkpoint)
        raw = clf._pipeline(["A short local news sentence."], truncation=True)
        assert isinstance(raw, list) and len(raw) == 1
        per_text = raw[0]
        assert isinstance(per_text, list), (
            "pipeline no longer returns all scores per text — the "
            "return_all_scores/top_k contract changed again"
        )
        assert all("label" in d and "score" in d for d in per_text)


class TestStorySnifferSklearn:
    """Call sites: src/pipeline/url_filters.py:128, src/crawler/discovery.py —
    StorySniffer().guess(url). Exercises the skops model load under the
    installed scikit-learn (the model was trained with sklearn 1.7.2; this
    test is the evidence gate for moving that pin)."""

    def test_skops_model_loads_and_guesses(self):
        storysniffer = pytest.importorskip("storysniffer")

        sniffer = storysniffer.StorySniffer()
        article_guess = sniffer.guess(
            "https://www.example-gazette.com/2026/03/05/city-council-budget/"
        )
        section_guess = sniffer.guess("https://www.example-gazette.com/about")
        # Contract: boolean-like results (numpy bools in practice) without
        # raising — a sklearn-incompatible skops pickle raises at load or
        # predict time. An obviously article-shaped URL must classify True.
        assert bool(article_guess) is True
        assert bool(section_guess) in (True, False)


class TestSpacyNltk:
    """Call sites: entity extraction pipeline (spacy NER), nltk tokenizers."""

    def test_spacy_model_load_and_ner(self):
        spacy = pytest.importorskip("spacy")

        try:
            nlp = spacy.load("en_core_web_sm")
        except OSError:
            pytest.skip("en_core_web_sm not installed in this venue")
        doc = nlp("Mayor Pat Alderman spoke in Jefferson City on Tuesday.")
        assert [t.text for t in doc]  # tokenization
        assert any(ent.label_ for ent in doc.ents)  # NER produced entities

    def test_nltk_tokenize(self):
        nltk = pytest.importorskip("nltk")

        try:
            tokens = nltk.word_tokenize("The council approved the budget.")
        except LookupError:
            pytest.skip("nltk punkt data not installed in this venue")
        assert "council" in tokens
