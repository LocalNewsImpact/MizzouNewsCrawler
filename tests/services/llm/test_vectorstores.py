"""Tests for vector store integrations."""

import pytest

from src.services.llm.settings import LLMSettings, VectorStoreSettings
from src.services.llm.vectorstores import (
    NoOpVectorStore,
    VectorStore,
    VectorStoreFactory,
    _create_vector_store,
)


class TestVectorStore:
    """Tests for VectorStore abstract interface."""

    def test_vector_store_interface(self):
        """Test that VectorStore requires implementation."""
        store = VectorStore()
        
        with pytest.raises(NotImplementedError):
            store.store(prompt="test", response="test", metadata={})


class TestNoOpVectorStore:
    """Tests for NoOpVectorStore."""

    def test_initialization(self):
        """Test NoOpVectorStore initialization."""
        store = NoOpVectorStore(provider="test-provider", reason="testing")
        
        assert store.provider == "test-provider"
        assert store.reason == "testing"
        assert store.events == []

    def test_initialization_with_defaults(self):
        """Test NoOpVectorStore with default reason."""
        store = NoOpVectorStore(provider="test")
        
        assert store.provider == "test"
        assert store.reason == "disabled"

    def test_store_records_event(self):
        """Test that store method records events."""
        store = NoOpVectorStore(provider="test", reason="testing")
        
        store.store(
            prompt="What is the capital of France?",
            response="Paris",
            metadata={"model": "test-model", "tokens": 100}
        )
        
        assert len(store.events) == 1
        event = store.events[0]
        assert event["prompt"] == "What is the capital of France?"
        assert event["response"] == "Paris"
        assert event["metadata"]["model"] == "test-model"
        assert event["reason"] == "testing"

    def test_store_multiple_events(self):
        """Test storing multiple events."""
        store = NoOpVectorStore(provider="test", reason="testing")
        
        store.store(prompt="Q1", response="A1", metadata={})
        store.store(prompt="Q2", response="A2", metadata={})
        store.store(prompt="Q3", response="A3", metadata={})
        
        assert len(store.events) == 3
        assert store.events[0]["prompt"] == "Q1"
        assert store.events[1]["prompt"] == "Q2"
        assert store.events[2]["prompt"] == "Q3"


class TestCreateVectorStore:
    """Tests for _create_vector_store function."""

    def test_create_pinecone_missing_api_key(self):
        """Test Pinecone vector store with missing API key."""
        settings = VectorStoreSettings(
            provider="pinecone",
            options={"pinecone_index": "test-index"}
        )
        
        store = _create_vector_store(settings)
        
        assert isinstance(store, NoOpVectorStore)
        assert store.provider == "pinecone"
        assert "missing options" in store.reason
        assert "pinecone_api_key" in store.reason

    def test_create_pinecone_missing_index(self):
        """Test Pinecone vector store with missing index."""
        settings = VectorStoreSettings(
            provider="pinecone",
            options={"pinecone_api_key": "test-key"}
        )
        
        store = _create_vector_store(settings)
        
        assert isinstance(store, NoOpVectorStore)
        assert "missing options" in store.reason
        assert "pinecone_index" in store.reason

    def test_create_pinecone_all_options(self):
        """Test Pinecone vector store with all required options."""
        settings = VectorStoreSettings(
            provider="pinecone",
            options={
                "pinecone_api_key": "test-key",
                "pinecone_index": "test-index"
            }
        )
        
        store = _create_vector_store(settings)
        
        assert isinstance(store, NoOpVectorStore)
        # Even with options, returns NoOp because client not installed
        assert "pinecone client not installed" in store.reason

    def test_create_weaviate_missing_url(self):
        """Test Weaviate vector store with missing URL."""
        settings = VectorStoreSettings(
            provider="weaviate",
            options={}
        )
        
        store = _create_vector_store(settings)
        
        assert isinstance(store, NoOpVectorStore)
        assert store.provider == "weaviate"
        assert "missing options" in store.reason
        assert "weaviate_url" in store.reason

    def test_create_weaviate_with_url(self):
        """Test Weaviate vector store with URL."""
        settings = VectorStoreSettings(
            provider="weaviate",
            options={"weaviate_url": "http://localhost:8080"}
        )
        
        store = _create_vector_store(settings)
        
        assert isinstance(store, NoOpVectorStore)
        # Even with URL, returns NoOp because client not installed
        assert "weaviate client not installed" in store.reason

    def test_create_unknown_provider(self):
        """Test creating vector store with unknown provider."""
        settings = VectorStoreSettings(
            provider="unknown-provider",
            options={}
        )
        
        store = _create_vector_store(settings)
        
        assert isinstance(store, NoOpVectorStore)
        assert store.provider == "unknown-provider"
        assert "unknown provider" in store.reason


class TestVectorStoreFactory:
    """Tests for VectorStoreFactory."""

    def test_create_with_none_settings(self):
        """Test factory with None vector store settings."""
        llm_settings = LLMSettings(
            provider_order=["openai-gpt4"],
            openai_api_key="test-key",
            vector_store=None
        )
        
        store = VectorStoreFactory.create(llm_settings)
        
        assert store is None

    def test_create_with_disabled_settings(self):
        """Test factory with disabled vector store."""
        # Empty provider string means disabled
        vec_settings = VectorStoreSettings(
            provider="",  # Empty provider is disabled
            options={}
        )
        
        llm_settings = LLMSettings(
            provider_order=["openai-gpt4"],
            openai_api_key="test-key",
            vector_store=vec_settings
        )
        
        store = VectorStoreFactory.create(llm_settings)
        
        assert store is None

    def test_create_with_enabled_pinecone(self):
        """Test factory with enabled Pinecone settings."""
        vec_settings = VectorStoreSettings(
            provider="pinecone",
            options={
                "pinecone_api_key": "test-key",
                "pinecone_index": "test-index"
            }
        )
        
        llm_settings = LLMSettings(
            provider_order=["openai-gpt4"],
            openai_api_key="test-key",
            vector_store=vec_settings
        )
        
        store = VectorStoreFactory.create(llm_settings)
        
        assert isinstance(store, NoOpVectorStore)
        assert store.provider == "pinecone"

    def test_create_with_enabled_weaviate(self):
        """Test factory with enabled Weaviate settings."""
        vec_settings = VectorStoreSettings(
            provider="weaviate",
            options={"weaviate_url": "http://localhost:8080"}
        )
        
        llm_settings = LLMSettings(
            provider_order=["openai-gpt4"],
            openai_api_key="test-key",
            vector_store=vec_settings
        )
        
        store = VectorStoreFactory.create(llm_settings)
        
        assert isinstance(store, NoOpVectorStore)
        assert store.provider == "weaviate"

    def test_vector_store_is_functional(self):
        """Test that created vector store can be used."""
        vec_settings = VectorStoreSettings(
            provider="test",
            options={}
        )
        
        llm_settings = LLMSettings(
            provider_order=["openai-gpt4"],
            openai_api_key="test-key",
            vector_store=vec_settings
        )
        
        store = VectorStoreFactory.create(llm_settings)
        
        # Should be able to use the store
        assert store is not None
        store.store(
            prompt="test prompt",
            response="test response",
            metadata={"test": "data"}
        )
        
        assert len(store.events) == 1
