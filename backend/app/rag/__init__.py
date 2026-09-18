"""LangChain integration boundary for the RAG implementation."""

from app.rag.providers import build_chat_model, build_embeddings

__all__ = ["build_chat_model", "build_embeddings"]
