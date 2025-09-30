"""Optional vector store integrations for LLM orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .settings import LLMSettings, VectorStoreSettings

logger = logging.getLogger(__name__)


class VectorStore:
    """Abstract vector store interface."""

    def store(
        self,
        *,
        prompt: str,
        response: str,
        metadata: Dict[str, object],
    ) -> None:  # pragma: no cover - interface stub
        raise NotImplementedError


@dataclass(slots=True)
class NoOpVectorStore(VectorStore):
    """Vector store that intentionally skips persistence."""

    provider: str
    reason: str = "disabled"
    events: List[Dict[str, object]] = field(default_factory=list)

    def store(
        self,
        *,
        prompt: str,
        response: str,
        metadata: Dict[str, object],
    ) -> None:
        logger.debug(
            "Vector store '%s' skipped: %s",
            self.provider,
            self.reason,
        )
        self.events.append(
            {
                "prompt": prompt,
                "response": response,
                "metadata": metadata,
                "reason": self.reason,
            }
        )


def _create_vector_store(settings: VectorStoreSettings) -> VectorStore:
    provider = settings.provider
    reason = "optional integration placeholder"

    if provider == "pinecone":
        required = {"pinecone_api_key", "pinecone_index"}
        missing = required - set(settings.options)
        if missing:
            reason = f"missing options: {sorted(missing)}"
        else:
            reason = "pinecone client not installed"
    elif provider == "weaviate":
        required = {"weaviate_url"}
        missing = required - set(settings.options)
        if missing:
            reason = f"missing options: {sorted(missing)}"
        else:
            reason = "weaviate client not installed"
    else:
        reason = "unknown provider"

    return NoOpVectorStore(provider=provider, reason=reason)


class VectorStoreFactory:
    """Factory for instantiating optional vector store integrations."""

    @staticmethod
    def create(settings: LLMSettings) -> Optional[VectorStore]:
        vec_settings = settings.vector_store
        if not vec_settings or not vec_settings.is_enabled():
            return None

        store = _create_vector_store(vec_settings)
        logger.info(
            "Vector store '%s' active in no-op mode (%s)",
            vec_settings.provider,
            getattr(store, "reason", ""),
        )
        return store
