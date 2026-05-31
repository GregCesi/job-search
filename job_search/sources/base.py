from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel


class JobOffer(BaseModel):
    source: str           # "france_travail", futur: autre source
    source_id: str        # id natif stable côté source
    fingerprint: str      # hash(titre normalisé + entreprise + localisation) — crochet cross-source
    title: str
    description: str
    company: str | None
    location: str | None  # libellé brut
    remote: bool          # full-remote détecté
    contract_type: str | None
    url: str
    fetched_at: datetime


class Source(ABC):
    @abstractmethod
    def fetch(self) -> list[JobOffer]:
        ...
