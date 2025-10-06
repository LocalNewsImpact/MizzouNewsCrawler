"""Article classification utilities leveraging HuggingFace pipelines."""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
import os
from typing import cast

import torch
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    BertConfig,
    BertForSequenceClassification,
    pipeline,
)

logger = logging.getLogger(__name__)


CRITICAL_INFORMATION_NEEDS_LABELS: list[str] = [
    "Civic Life",
    "Civic information",
    "Emergencies and Public Safety",
    "Health",
    "Transportation Systems",
    "Sports",
    "Environment and Planning",
    "Education",
    "Political life",
    "Economic Development",
]

_BASE_MODEL_NAME = "bert-base-uncased"


@dataclass
class Prediction:
    """Simple container for classifier predictions."""

    label: str
    score: float

    def as_dict(self) -> dict:
        return {"label": self.label, "score": float(self.score)}


class ArticleClassifier:
    """Wrapper around a text classification pipeline."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        device: int | None = None,
        default_model: str = "distilbert-base-uncased-finetuned-sst-2-english",
    ) -> None:
        self.model_path = str(model_path)
        self.device = -1 if device is None else device

        # Allow env override if caller passed a placeholder like "models"
        env_model_path = os.getenv("MODEL_PATH")
        resolved = Path(env_model_path or self.model_path)
        candidate_paths: list[str] = []
        pt_candidates: list[Path] = []

        if resolved.is_file() and resolved.suffix == ".pt":
            pt_candidates.append(resolved)
        elif resolved.is_dir():
            pt_candidates.extend(sorted(resolved.glob("*.pt")))

        last_error: Exception | None = None
        self.model_identifier: str | None = None
        self.model_version: str | None = None

        for checkpoint in pt_candidates:
            try:
                (
                    self._pipeline,
                    self.model_identifier,
                    self.model_version,
                ) = _load_pt_classifier(checkpoint, self.device)
                break
            except Exception as exc:  # pylint: disable=broad-except
                last_error = exc
                logger.warning(
                    "Failed to load classifier checkpoint %s: %s",
                    checkpoint,
                    exc,
                )
        else:
            # Consider common model directories only if they exist
            if resolved.is_dir():
                candidate_paths.append(str(resolved))
            elif resolved.exists() and resolved.parent.is_dir():
                candidate_paths.append(str(resolved.parent))

            # Also consider /app/models and ./models if present
            for extra in ("/app/models", "./models"):
                if os.path.isdir(extra) and extra not in candidate_paths:
                    candidate_paths.append(extra)

            candidate_paths.append(default_model)

            for candidate in candidate_paths:
                try:
                    tokenizer = AutoTokenizer.from_pretrained(candidate)
                    model = AutoModelForSequenceClassification.from_pretrained(
                        candidate
                    )
                    self._pipeline = pipeline(
                        "text-classification",
                        model=model,
                        tokenizer=tokenizer,
                        return_all_scores=True,
                        device=self.device,
                    )
                    self.model_identifier = candidate
                    self.model_version = getattr(
                        model.config,
                        "model_version",
                        None,
                    )
                    if not self.model_version:
                        self.model_version = getattr(
                            model.config,
                            "name_or_path",
                            None,
                        )
                    break
                except Exception as exc:  # pylint: disable=broad-except
                    last_error = exc
                    logger.warning(
                        "Failed to load classifier from %s: %s",
                        candidate,
                        exc,
                    )
            else:
                raise RuntimeError(
                    "Unable to load classification model;"
                    " attempted paths: " + ", ".join(candidate_paths)
                ) from last_error

        if not self.model_version:
            # Use directory or file stem as fallback version identifier
            if resolved.exists():
                self.model_version = resolved.stem
            else:
                self.model_version = default_model

        if not self.model_identifier and pt_candidates:
            # If we successfully loaded a checkpoint but identifier is missing,
            # default to the checkpoint path string for traceability.
            self.model_identifier = str(pt_candidates[0])

        logger.info(
            "Loaded article classifier from %s (device=%s)",
            self.model_identifier,
            self.device,
        )

    def predict_batch(
        self,
        texts: Sequence[str],
        *,
        top_k: int = 2,
    ) -> list[list[Prediction]]:
        """Run classification on a batch of texts."""

        if not isinstance(texts, Iterable) or isinstance(texts, (str, bytes)):
            raise TypeError("predict_batch expects a sequence of text strings")

        normalized: list[str] = [text or "" for text in texts]
        raw_outputs = cast(
            Sequence[Sequence[dict]],
            self._pipeline(normalized, truncation=True),
        )

        predictions: list[list[Prediction]] = []
        for output in raw_outputs:
            sorted_scores = sorted(
                output,
                key=lambda item: item.get("score", 0),
                reverse=True,
            )
            top_predictions = [
                Prediction(
                    label=item.get("label", ""),
                    score=float(item.get("score", 0.0)),
                )
                for item in sorted_scores[: max(1, top_k)]
            ]
            predictions.append(top_predictions)

        return predictions

    def predict_text(self, text: str, *, top_k: int = 2) -> list[Prediction]:
        """Convenience wrapper for single-text classification."""

        return self.predict_batch([text], top_k=top_k)[0]


def _load_pt_classifier(
    checkpoint_path: Path,
    device: int,
):
    """Load a custom fine-tuned BERT checkpoint with CIN label mapping.

    Parameters
    ----------
    checkpoint_path:
    Path to the Torch ``.pt`` state dictionary produced by the
    legacy pipeline.
    device:
        Device index expected by HuggingFace pipelines (-1 for CPU).

    Returns
    -------
    tuple[pipeline, str, str]
        The configured pipeline, a model identifier string, and a semantic
        version string derived from the checkpoint filename.
    """

    if not checkpoint_path.exists():
        raise FileNotFoundError(f"Classifier checkpoint not found: {checkpoint_path}")

    logger.info(
        "Loading custom classifier from checkpoint %s",
        checkpoint_path,
    )
    state_dict = torch.load(checkpoint_path, map_location="cpu")

    # Handle common wrappers from torch.save({'state_dict': ...}) formats.
    if isinstance(state_dict, dict):
        for candidate_key in ("state_dict", "model_state_dict", "model"):
            if candidate_key in state_dict and isinstance(
                state_dict[candidate_key],
                (dict, OrderedDict),
            ):
                state_dict = state_dict[candidate_key]
                break

    if not isinstance(state_dict, (dict, OrderedDict)):
        raise ValueError(
            "Unexpected checkpoint format; expected a state_dict mapping but"
            f" got {type(state_dict)!r}"
        )

    # Rename legacy classifier head keys to match HuggingFace's expectation.
    normalized_state: dict[str, torch.Tensor] = {}
    for key, value in state_dict.items():
        new_key = key
        if key.startswith("classifier_primary."):
            new_key = key.replace("classifier_primary", "classifier", 1)
        normalized_state[new_key] = value

    num_labels = len(CRITICAL_INFORMATION_NEEDS_LABELS)
    label2id = {
        label: idx for idx, label in enumerate(CRITICAL_INFORMATION_NEEDS_LABELS)
    }
    id2label = {idx: label for label, idx in label2id.items()}

    config = BertConfig.from_pretrained(
        _BASE_MODEL_NAME,
        num_labels=num_labels,
        id2label=id2label,
        label2id=label2id,
        problem_type="single_label_classification",
    )

    # Instantiate the classification head directly from the config so the
    # checkpoint provides every parameter (including the classifier weights).
    model = BertForSequenceClassification(config)

    missing_keys, unexpected_keys = model.load_state_dict(
        normalized_state,
        strict=False,
    )
    if missing_keys:
        logger.warning(
            "Classifier checkpoint %s missing keys: %s",
            checkpoint_path,
            ", ".join(missing_keys),
        )
    if unexpected_keys:
        logger.warning(
            "Classifier checkpoint %s had unexpected keys: %s",
            checkpoint_path,
            ", ".join(unexpected_keys),
        )

    model.eval()

    tokenizer = AutoTokenizer.from_pretrained(_BASE_MODEL_NAME)
    text_pipeline = pipeline(
        "text-classification",
        model=model,
        tokenizer=tokenizer,
        return_all_scores=True,
        device=device,
    )

    model_identifier = str(checkpoint_path)
    model_version = checkpoint_path.stem

    return text_pipeline, model_identifier, model_version
