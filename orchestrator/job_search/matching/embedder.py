import json
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

from orchestrator.job_search.matching.profile import Profile
from orchestrator.job_search.sources.base import JobOffer

_CHROMA_PATH = Path("data/chroma")
_PROFILE_CACHE = Path("data/profile_cache.json")
_COLLECTION = "job_offers"


def _offer_text(offer: JobOffer) -> str:
    return "\n".join(filter(None, [offer.title, offer.company, offer.location, offer.description]))


def _profile_text(profile: Profile) -> str:
    techs = ", ".join(f"{t} (level={s.level}, desire={s.desire})" for t, s in profile.skills.items())
    return (
        f"Role: AI Engineer ({profile.role_ceiling.value} level)\n"
        f"Skills: {techs}\n"
        f"Domains: {', '.join(profile.search_criteria.domains)}\n"
        f"Locations: {', '.join(profile.search_criteria.locations)}"
    )


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x**2 for x in a) ** 0.5
    nb = sum(x**2 for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


class Embedder:
    def __init__(self) -> None:
        _CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(_CHROMA_PATH))
        self._ef = embedding_functions.DefaultEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            _COLLECTION,
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )
        self._profile_hash: str | None = None
        self._profile_embedding: list[float] | None = None
        self._restore_profile_cache()

    # ------------------------------------------------------------------
    # Profile — ré-embed uniquement si hash change
    # ------------------------------------------------------------------

    def _restore_profile_cache(self) -> None:
        if _PROFILE_CACHE.exists():
            data = json.loads(_PROFILE_CACHE.read_text())
            self._profile_hash = data.get("hash")
            self._profile_embedding = data.get("embedding")

    def _persist_profile_cache(self) -> None:
        _PROFILE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _PROFILE_CACHE.write_text(
            json.dumps({"hash": self._profile_hash, "embedding": self._profile_embedding})
        )

    def embed_profile(self, profile: Profile, profile_hash: str) -> bool:
        """Embed profile if hash changed. Returns True if re-embedded."""
        if self._profile_hash == profile_hash and self._profile_embedding is not None:
            return False
        self._profile_embedding = [float(x) for x in self._ef([_profile_text(profile)])[0]]
        self._profile_hash = profile_hash
        self._persist_profile_cache()
        return True

    # ------------------------------------------------------------------
    # Offers
    # ------------------------------------------------------------------

    def add_offer(self, offer: JobOffer) -> None:
        """Upsert offer embedding into ChromaDB."""
        self._collection.upsert(
            ids=[f"{offer.source}:{offer.source_id}"],
            documents=[_offer_text(offer)],
            metadatas=[{"source": offer.source, "source_id": offer.source_id}],
        )

    # ------------------------------------------------------------------
    # Similarity
    # ------------------------------------------------------------------

    def similarity(self, offer: JobOffer) -> float:
        """Cosine similarity [0, 1] between offer and profile."""
        if self._profile_embedding is None:
            raise RuntimeError("Call embed_profile before similarity()")
        result = self._collection.get(
            ids=[f"{offer.source}:{offer.source_id}"],
            include=["embeddings"],
        )
        embeddings = result.get("embeddings")
        if embeddings is None or len(embeddings) == 0:
            return 0.0
        return _cosine(self._profile_embedding, [float(x) for x in embeddings[0]])
