"""Policy ingestion, vector retrieval, and grounded policy Q&A support."""

from app.policies.embeddings import LocalHashEmbeddingService, get_embedding_service
from app.policies.ingestion import ingest_repository_policy_documents
from app.policies.retrieval import PolicyRetrievalResult, retrieve_policy_context
from app.policies.vector_store import LocalPolicyVectorStore, PolicyMatch

__all__ = [
    "LocalHashEmbeddingService",
    "LocalPolicyVectorStore",
    "PolicyMatch",
    "PolicyRetrievalResult",
    "get_embedding_service",
    "ingest_repository_policy_documents",
    "retrieve_policy_context",
]
