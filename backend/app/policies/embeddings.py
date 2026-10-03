"""Local deterministic embedding service for policy retrieval in development."""

from __future__ import annotations

import hashlib
import math
import re

from app.config import get_settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "before",
    "by",
    "do",
    "for",
    "from",
    "if",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "without",
    "you",
    "your",
}


class LocalHashEmbeddingService:
    """Simple deterministic embedding service without external API dependencies."""

    def __init__(self, dimensions: int = 128) -> None:
        settings = get_settings()
        self.dimensions = dimensions
        self.provider = (settings.embedding_provider or "local").strip() or "local"
        self.model = (settings.embedding_model or "local-hash").strip() or "local-hash"

    def embed_text(self, text: str) -> list[float]:
        """Return a stable vector representation of the text."""
        tokens = [token for token in _TOKEN_RE.findall((text or "").lower()) if token not in _STOPWORDS]
        if not tokens:
            return [0.0] * self.dimensions

        weights: dict[int, int] = {}
        for token in tokens:
            index = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % self.dimensions
            weights[index] = weights.get(index, 0) + 1

        max_weight = max(weights.values())
        vector = [0.0] * self.dimensions
        for position, count in weights.items():
            vector[position] = count / max_weight

        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0:
            vector = [value / norm for value in vector]
        return vector


def get_embedding_service() -> LocalHashEmbeddingService:
    """Return the configured local embedding service."""
    return LocalHashEmbeddingService()
