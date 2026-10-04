"""Endpoints relecture du jeu de référence (EXE-123, architecture.md exception
« rejeu du jeu de référence », TCK-221).

Lit et écrit le même fichier que la CLI (orchestrator/job_search/reference/dataset.py,
JEU_PATH) : une correction enregistrée ici est donc vue sans changement par le rejeu
en ligne de commande (critère 10). L'ajout réutilise `add_offers()` posé par EXE-107 —
mêmes règles de préremplissage / skip que la CLI `ajouter.py` (critères 7-9). Aucune
des deux routes n'appelle de modèle ni n'écrit dans `offers`.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from orchestrator.job_search.reference.dataset import (
    JEU_PATH,
    ReferenceEntry,
    add_offers,
    load_jeu,
    save_jeu,
)
from orchestrator.job_search.scoring.extractor import _DOMAIN_VALID
from orchestrator.job_search.sources.base import ExtractedFacts

from .db import get_conn

router = APIRouter()


class _AttenduIn(ExtractedFacts):
    """Même vocabulaire que l'extraction. Séniorité, rôle et importance sont déjà
    fermés par les types de `ExtractedFacts` (enum / Literal, 422 automatique sur
    valeur inconnue) — seul `domain` est du texte libre côté modèle et doit être
    fermé ici (critère 6)."""

    @field_validator("domain")
    @classmethod
    def _domain_connu(cls, v: str) -> str:
        if v not in _DOMAIN_VALID:
            raise ValueError(
                f"domain invalide : {v!r} (valeurs acceptées : {sorted(_DOMAIN_VALID)})"
            )
        return v


class ReferenceEntryIn(BaseModel):
    attendu: _AttenduIn
    relu: bool


class ReferenceSummary(BaseModel):
    id: int
    title: str
    relu: bool


class ReferenceListOut(BaseModel):
    entries: list[ReferenceSummary]
    relues: int
    total: int


class ReferenceEntryOut(BaseModel):
    title: str
    text: str
    attendu: ExtractedFacts


class AddToReferenceOut(BaseModel):
    statut: str  # ajoutee | deja_presente | sans_faits


@router.get("/reference", response_model=ReferenceListOut)
def list_reference() -> ReferenceListOut:
    entries = load_jeu(JEU_PATH)
    summaries = [
        ReferenceSummary(id=int(key), title=entry.title, relu=entry.relu)
        for key, entry in sorted(entries.items(), key=lambda kv: int(kv[0]))
    ]
    return ReferenceListOut(
        entries=summaries,
        relues=sum(1 for e in entries.values() if e.relu),
        total=len(entries),
    )


@router.get("/reference/{entry_id}", response_model=ReferenceEntryOut)
def get_reference_entry(entry_id: int) -> ReferenceEntryOut:
    entry = load_jeu(JEU_PATH).get(str(entry_id))
    if entry is None:
        raise HTTPException(
            status_code=404, detail="entrée absente du jeu de référence"
        )
    return ReferenceEntryOut(title=entry.title, text=entry.text, attendu=entry.attendu)


@router.put("/reference/{entry_id}", status_code=204)
def update_reference_entry(entry_id: int, body: ReferenceEntryIn) -> None:
    entries = load_jeu(JEU_PATH)
    key = str(entry_id)
    existing = entries.get(key)
    if existing is None:
        raise HTTPException(
            status_code=404, detail="entrée absente du jeu de référence"
        )
    entries[key] = ReferenceEntry(
        title=existing.title,
        text=existing.text,
        attendu=ExtractedFacts.model_validate(body.attendu.model_dump()),
        relu=body.relu,
    )
    save_jeu(entries, JEU_PATH)


@router.post("/offers/{offer_id}/reference", response_model=AddToReferenceOut)
def add_offer_to_reference(offer_id: int) -> AddToReferenceOut:
    with get_conn() as conn:
        report = add_offers(conn, [offer_id], jeu_path=JEU_PATH)
    if report.added:
        return AddToReferenceOut(statut="ajoutee")
    if report.skipped_existing:
        return AddToReferenceOut(statut="deja_presente")
    return AddToReferenceOut(statut="sans_faits")
