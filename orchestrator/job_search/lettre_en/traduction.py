"""Traduction anglaise de la lettre courante (EXE-209).

Appel de modèle unique (Sonnet, par claude-agent-sdk, sans outil), parti
uniquement du clic sur « Générer » ou « Régénérer la version anglaise » d'une
offre retenue (H2 du ticket). Jamais un modèle local : la lettre ne passe que
par Claude.

La traduction est pure : elle ne lit ni n'écrit la base. La connexion est
fermée par l'appelant pendant l'appel, comme pour le mail (mail/generation.py).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass

import claude_agent_sdk
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage

from orchestrator.job_search.paths import LETTRE_EN_CWD

MODELE = "sonnet"
TIMEOUT_S = 120

# Aucun outil : le texte à traduire est tout entier dans la demande.
_TOOLS: list[str] = []
_FORBIDDEN_TOOLS = ["Bash", "Write", "Edit", "NotebookEdit", "WebSearch", "WebFetch"]

_SCHEMA = {
    "type": "object",
    "properties": {"texte": {"type": "string"}},
    "required": ["texte"],
    "additionalProperties": False,
}

# H3 du ticket : consigne de traduction.
CONSIGNE = (
    "Traduis en anglais la lettre de motivation ci-dessous.\n"
    "- Traduction fidèle : n'ajoute aucune phrase, n'en retire aucune.\n"
    "- Garde le même registre.\n"
    "- Remplace la formule d'appel et la formule de politesse par les formules "
    "anglaises usuelles.\n"
    "- Laisse inchangés les noms propres, les noms de produits et les noms de "
    "technologies.\n"
    "- Garde le découpage en paragraphes, séparés par une ligne vide.\n"
    "Rends uniquement le texte anglais dans le champ `texte`."
)


class TraductionEchoueeError(Exception):
    """L'appel a échoué, a dépassé son délai ou n'a rendu aucun texte."""


@dataclass
class ResultatTraduction:
    texte: str
    modele: str
    duree_s: float
    cout_usd: float | None
    demande: str
    reponse: str


def build_prompt(texte_fr: str) -> str:
    return f"{CONSIGNE}\n\nLettre :\n{texte_fr}\n"


async def _appeler_modele(prompt_text: str) -> tuple[dict, float, float | None, str]:
    LETTRE_EN_CWD.mkdir(parents=True, exist_ok=True)
    options = ClaudeAgentOptions(
        tools=_TOOLS,
        allowed_tools=_TOOLS,
        disallowed_tools=_FORBIDDEN_TOOLS,
        output_format={"type": "json_schema", "schema": _SCHEMA},
        model=MODELE,
        setting_sources=[],
        cwd=str(LETTRE_EN_CWD),
        max_turns=5,
    )
    result: ResultMessage | None = None

    async def _consume() -> None:
        nonlocal result
        async for msg in claude_agent_sdk.query(prompt=prompt_text, options=options):
            if isinstance(msg, ResultMessage):
                result = msg

    debut = time.monotonic()
    await asyncio.wait_for(_consume(), timeout=TIMEOUT_S)
    duree = time.monotonic() - debut

    if result is None:
        raise TraductionEchoueeError("aucune réponse du modèle")
    if result.is_error:
        raise TraductionEchoueeError(
            f"le modèle a répondu en erreur ({result.subtype})"
        )

    reponse = result.result or ""
    out = result.structured_output
    if out is None and reponse:
        try:
            out = json.loads(reponse)
        except ValueError:
            out = None
    if not isinstance(out, dict):
        out = {}
    return out, duree, result.total_cost_usd, reponse


async def traduire(texte_fr: str) -> ResultatTraduction:
    """Un seul appel de modèle. Toute panne (erreur, délai, réponse vide) lève
    `TraductionEchoueeError` : rien n'est alors persisté par l'appelant."""
    prompt_text = build_prompt(texte_fr)
    try:
        out, duree_s, cout_usd, reponse = await _appeler_modele(prompt_text)
    except TraductionEchoueeError:
        raise
    except TimeoutError as exc:
        raise TraductionEchoueeError(f"délai de {TIMEOUT_S} secondes dépassé") from exc
    except Exception as exc:  # noqa: BLE001 — toute panne du SDK devient un échec
        raise TraductionEchoueeError(str(exc) or type(exc).__name__) from exc
    texte = (out.get("texte") or "").strip()
    if not texte:
        raise TraductionEchoueeError("réponse du modèle sans texte")
    return ResultatTraduction(
        texte=texte,
        modele=MODELE,
        duree_s=duree_s,
        cout_usd=cout_usd,
        demande=prompt_text,
        reponse=reponse,
    )
