"""Appel d'identification d'une offre ajoutée à la main sans titre (EXE-82).

Exception encadrée de architecture.md (TCK-183) : un appel au même modèle Ollama que
l'extraction, avec son propre prompt système, qui ne rend que le titre, l'entreprise et
le lieu lus dans le texte collé. Il part uniquement d'un ajout à la main sans titre
saisi — jamais d'une offre de source ni d'un rescore — et ne rend aucun fait qui entre
dans le scoring. L'extraction qui suit est l'extraction ordinaire, prompt inchangé.

Un seul appel, sans relance. Tracé comme l'extraction (`LLMTrace`), dans son propre
fichier.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone

import ollama

from orchestrator.job_search.paths import IDENTIFICATION_TRACES_PATH
from orchestrator.job_search.scoring.tracing import LLMTrace, _write_trace

TRACE_PATH = IDENTIFICATION_TRACES_PATH
_TEMPERATURE = 0.1
_NUM_CTX = 8192

_SYSTEM_PROMPT = """\
You read a job offer pasted as plain text and identify it. No analysis, no opinion.
Reply with a single valid JSON object, nothing else:
{"titre": "<job title>", "entreprise": "<hiring company or null>", "lieu": "<work location or null>"}

Rules:
- Copy each value as written in the text, in the text's language. Never translate, never invent.
- titre: the title of the position offered. null if the text states none.
- entreprise: the company that hires. null if the text does not name it.
- lieu: the city or place of work as written. null if the text does not state it.
"""


@dataclass(frozen=True)
class Identification:
    titre: str
    entreprise: str | None
    lieu: str | None


def _text(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    return None


def _parse(raw: str) -> Identification | None:
    body = raw.strip()
    if body.startswith("```"):
        body = body.split("```")[1]
        if body.startswith("json"):
            body = body[4:]
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    titre = _text(data.get("titre"))
    if titre is None:
        return None
    return Identification(
        titre=titre,
        entreprise=_text(data.get("entreprise")),
        lieu=_text(data.get("lieu")),
    )


def identify_offer(
    texte: str, *, offer_id: str, model: str, host: str
) -> Identification | None:
    """Titre, entreprise et lieu lus dans le texte, ou None si aucun titre n'est rendu
    (réponse sans titre, illisible, ou appel en erreur). Ne lève jamais."""
    user_prompt = f"Job offer:\n{texte[:8000]}\n\nIdentify it now:"
    raw = ""
    try:
        resp = ollama.Client(host=host).chat(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            options={"temperature": _TEMPERATURE, "num_ctx": _NUM_CTX},
            think=False,
        )
        raw = resp.message.content or ""
        identification = _parse(raw)
    except Exception:
        identification = None

    _write_trace(
        LLMTrace(
            offer_id=offer_id,
            model=model,
            temperature=_TEMPERATURE,
            prompt_system=_SYSTEM_PROMPT,
            prompt_user=user_prompt,
            raw_response=raw,
            parsed_facts=(
                {
                    "titre": identification.titre,
                    "entreprise": identification.entreprise,
                    "lieu": identification.lieu,
                }
                if identification is not None
                else {}
            ),
            parse_failed=identification is None,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
        TRACE_PATH,
    )
    return identification
