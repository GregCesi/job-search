"""Identification de l'employeur réel d'une offre — cascade 3 étapes.

Les 3 étapes s'exécutent toujours dans l'ordre (de la moins chère à la plus chère) ;
le résultat agrège les trois, `methode` trace ce que chacune a observé.
"""

import hashlib
import json
import os
import sqlite3

import ollama
from pydantic import BaseModel

from orchestrator.job_search.fiche.intermediaires import load_normalized, normalize

_DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:12b")
_DEFAULT_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
_NUM_CTX = 8192
_TYPES = {"direct", "agence", "agregateur", "inconnu"}

_SYSTEM_PROMPT = """\
You read a job posting and say who really recruits. Reply with a single JSON object, nothing else:
{"type_source": "<direct|agence|agregateur|inconnu>", "employeur": "<name or null>"}
- direct: the company that posted the job is the employer.
- agence: a recruitment agency / staffing / consulting firm; the final employer is hidden or different.
- agregateur: a job board or channel, not an employer.
- inconnu: cannot tell.
- employeur: the real employer's name ONLY if the posting text names it. Never guess. null otherwise."""


class CascadeResult(BaseModel):
    nom: str | None
    entite: str | None
    confiance: str  # sur|probable|non_trouve
    type_source: str  # direct|agence|agregateur|inconnu
    methode: str
    etape: int  # 1|2|3 — étape identifiante (0 = fallback)


def _fallback(reason: str = "fallback") -> CascadeResult:
    return CascadeResult(
        nom=None,
        entite=None,
        confiance="non_trouve",
        type_source="inconnu",
        methode=reason,
        etape=0,
    )


def _text(row: sqlite3.Row) -> str:
    return (row["description_raw"] or row["description"] or "").strip()


def _digest(text: str) -> str:
    return hashlib.sha256(text[:500].encode("utf-8")).hexdigest()


def _step3_llm(row: sqlite3.Row, model: str, host: str) -> tuple[str, str | None]:
    """Retourne (type_source, employeur|None). Lève en cas d'échec — l'appelant l'absorbe."""
    client = ollama.Client(host=host, timeout=120)
    resp = client.chat(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Title: {row['title']}\nCompany shown: {row['company']}\n"
                    f"Description: {_text(row)[:6000]}\nAnswer now:"
                ),
            },
        ],
        options={"temperature": 0, "num_ctx": _NUM_CTX},
        format="json",
        think=False,
    )
    data = json.loads(resp.message.content)
    type_source = data.get("type_source")
    if type_source not in _TYPES:
        type_source = "inconnu"
    employeur = data.get("employeur")
    if (
        not isinstance(employeur, str)
        or not employeur.strip()
        or employeur.strip().lower() == "null"
    ):
        employeur = None
    return type_source, (employeur.strip() if employeur else None)


def identify_employer(
    offer_id: int,
    conn: sqlite3.Connection,
    model: str = _DEFAULT_MODEL,
    host: str = _DEFAULT_HOST,
) -> CascadeResult:
    """Identifie l'employeur. Ne lève jamais."""
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, source, title, company, description, description_raw "
            "FROM offers WHERE id = ?",
            (offer_id,),
        ).fetchone()
        if row is None:
            return _fallback("offre introuvable")

        trace: list[str] = []
        intermediaires = load_normalized()
        company = (row["company"] or "").strip()

        # Étape 1 — company vs liste d'intermédiaires connus
        is_intermediaire = normalize(company) in intermediaires
        if is_intermediaire:
            trace.append(
                f"1: « {company} » ∈ intermediaires.yaml → type_source=agregateur"
            )
        else:
            trace.append(f"1: « {company or '∅'} » absent de intermediaires.yaml")

        # Étape 2 — même annonce (500 premiers chars) ailleurs, autre source
        sibling: str | None = None
        text = _text(row)
        if text:
            target = _digest(text)
            for o in conn.execute(
                "SELECT id, company, description, description_raw FROM offers "
                "WHERE source != ? AND id != ?",
                (row["source"], offer_id),
            ):
                if _digest(_text(o)) != target:
                    continue
                other = (o["company"] or "").strip()
                if other and normalize(other) not in intermediaires:
                    sibling = other
                    trace.append(f"2: même annonce offre {o['id']} chez « {other} »")
                    break
            else:
                trace.append("2: aucune annonce identique dans une autre source")
        else:
            trace.append("2: description vide")

        # Étape 3 — Ollama : type de source + employeur nommé dans le texte
        llm_type: str | None = None
        llm_name: str | None = None
        try:
            llm_type, llm_name = _step3_llm(row, model, host)
            trace.append(f"3: LLM type_source={llm_type} employeur={llm_name or '∅'}")
        except Exception as exc:  # noqa: BLE001 — la cascade ne casse jamais
            trace.append(f"3: LLM en échec ({type(exc).__name__})")

        # Agrégat
        if is_intermediaire:
            type_source = "agregateur"
        elif llm_type in ("agence", "agregateur"):
            type_source = llm_type
        else:
            type_source = llm_type or "direct"

        masque = is_intermediaire or type_source in ("agence", "agregateur")
        if not masque and company:
            nom, etape = company, 1
            confiance = "sur" if llm_type == "direct" else "probable"
        elif sibling:
            nom, etape, confiance = sibling, 2, "probable"
        elif llm_name:
            nom, etape, confiance = llm_name, 3, "probable"
        else:
            nom, etape, confiance = None, 3, "non_trouve"

        return CascadeResult(
            nom=nom,
            entite=None,
            confiance=confiance,
            type_source=type_source,
            methode=" | ".join(trace),
            etape=etape,
        )
    except Exception as exc:  # noqa: BLE001
        return _fallback(f"fallback ({type(exc).__name__})")
