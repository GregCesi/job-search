"""Jeu de référence d'offres annotées (TCK-221, EXE-107, architecture.md
exception « rejeu du jeu de référence »).

Vit dans data/reference/jeu.json, hors git comme tout data/ (H6 du ticket).
Un seul fichier JSON pretty-printé — pas du JSONL — pour rester relisible et
corrigible à la main dans un éditeur de texte : chaque entrée est un bloc
indenté, pas une ligne compacte.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from orchestrator.job_search.paths import REPO_ROOT
from orchestrator.job_search.sources.base import ExtractedFacts

JEU_PATH = REPO_ROOT / "data" / "reference" / "jeu.json"


class ReferenceEntry(BaseModel):
    """Une offre du jeu : son texte, l'attendu humain, et sa marque de relecture.

    `relu=False` au préremplissage (critère 1) — seule une main humaine la
    passe à `True`, jamais le code (« ce qui ne doit pas arriver » du ticket).
    """

    title: str
    text: str
    attendu: ExtractedFacts
    relu: bool = False


@dataclass
class AddReport:
    added: list[int] = field(default_factory=list)
    skipped_existing: list[int] = field(default_factory=list)
    skipped_no_facts: list[int] = field(default_factory=list)


def load_jeu(path: Path = JEU_PATH) -> dict[str, ReferenceEntry]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        key: ReferenceEntry.model_validate(value)
        for key, value in data.get("entries", {}).items()
    }


def save_jeu(entries: dict[str, ReferenceEntry], path: Path = JEU_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "entries": {
            key: json.loads(entries[key].model_dump_json())
            for key in sorted(entries, key=int)
        }
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def jeu_fingerprint(entries: dict[str, ReferenceEntry]) -> str:
    """Empreinte du jeu : change si un attendu (ou tout autre champ d'une
    entrée) change ; stable sur un jeu inchangé (critère 13)."""
    canonical = {
        key: json.loads(entries[key].model_dump_json())
        for key in sorted(entries, key=int)
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return digest[:16]


def add_offers(
    conn: sqlite3.Connection, ids: list[int], jeu_path: Path = JEU_PATH
) -> AddReport:
    """Ajoute au jeu les offres `ids` absentes du jeu, préremplies avec les
    faits enregistrés en base et marquées « non relu » (critère 1). Une
    entrée déjà présente garde son attendu et sa marque (critère 2). Une
    offre sans faits extraits en base (jamais extraite) est ignorée."""
    entries = load_jeu(jeu_path)
    report = AddReport()

    for offer_id in ids:
        key = str(offer_id)
        if key in entries:
            report.skipped_existing.append(offer_id)
            continue
        row = conn.execute(
            "SELECT title, description, extracted_facts_json FROM offers WHERE id = ?",
            (offer_id,),
        ).fetchone()
        if row is None or not row["extracted_facts_json"]:
            report.skipped_no_facts.append(offer_id)
            continue
        attendu = ExtractedFacts.model_validate_json(row["extracted_facts_json"])
        entries[key] = ReferenceEntry(
            title=row["title"] or "", text=row["description"] or "", attendu=attendu
        )
        report.added.append(offer_id)

    save_jeu(entries, jeu_path)
    return report
