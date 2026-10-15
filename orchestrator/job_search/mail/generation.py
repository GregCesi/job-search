"""Génération du mail de candidature depuis la lettre courante (EXE-176).

Appel modèle unique (Sonnet), déclenché uniquement par une action explicite
(POST .../mail/generer) — jamais par un changement de profil ni un rescore
(architecture.md, exceptions encadrées). La consigne vit hors git
(`MAIL_CONSIGNE_PATH`) : lue ici, jamais écrite ni complétée par le code
(critère 4).

La connexion DB n'est jamais tenue ouverte pendant l'appel modèle : la
génération (`generer_depuis_lettre`) est pure, la persistance
(`persister_generation`) est une étape séparée — même séparation que la fiche
entreprise et le CV.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from orchestrator.job_search.paths import MAIL_CONSIGNE_PATH, MAIL_CWD
from orchestrator.job_search.pdf.coordonnees import Coordonnees

MODELE = "sonnet"
TIMEOUT_S = 120

# Aucun outil nécessaire : tout ce qu'il faut (consigne, lettre, coordonnées)
# est déjà dans le prompt — même convention que cv/service.py.
_TOOLS: list[str] = []
_FORBIDDEN_TOOLS = ["Bash", "Write", "Edit", "NotebookEdit", "WebSearch", "WebFetch"]

_SCHEMA = {
    "type": "object",
    "properties": {
        "objet": {"type": "string"},
        "corps": {"type": "string"},
    },
    "required": ["objet", "corps"],
    "additionalProperties": False,
}


class ConsigneAbsenteError(Exception):
    def __init__(self, path) -> None:
        super().__init__(f"Fichier de consigne du mail absent : {path}")
        self.path = path


class ReponseIncompleteError(Exception):
    def __init__(self) -> None:
        super().__init__("Réponse du modèle sans objet ou sans corps")


@dataclass
class ResultatGeneration:
    objet: str
    corps: str
    modele: str
    duree_s: float
    cout_usd: float | None
    demande: str
    reponse: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_consigne() -> str:
    """Lit `MAIL_CONSIGNE_PATH` (module global, monkeypatché dans les tests —
    même convention que `candidature.load_gabarit`)."""
    if not MAIL_CONSIGNE_PATH.exists():
        raise ConsigneAbsenteError(MAIL_CONSIGNE_PATH)
    return MAIL_CONSIGNE_PATH.read_text(encoding="utf-8")


def build_prompt(
    consigne: str,
    intitule: str,
    entreprise: str | None,
    texte_lettre: str,
    coordonnees: Coordonnees,
) -> str:
    chez = f" chez {entreprise}" if entreprise else ""
    return (
        f"{consigne}\n\n"
        f"Poste : {intitule}{chez}\n\n"
        f"Mes coordonnées :\n{coordonnees.nom}\n{coordonnees.mail}\n{coordonnees.telephone}\n\n"
        f"Ma lettre de candidature pour cette offre :\n{texte_lettre}\n"
    )


async def _appeler_modele(prompt_text: str) -> tuple[dict, float, float | None, str]:
    MAIL_CWD.mkdir(parents=True, exist_ok=True)
    options = ClaudeAgentOptions(
        tools=_TOOLS,
        allowed_tools=_TOOLS,
        disallowed_tools=_FORBIDDEN_TOOLS,
        output_format={"type": "json_schema", "schema": _SCHEMA},
        model=MODELE,
        setting_sources=[],
        cwd=str(MAIL_CWD),
        max_turns=5,
    )
    result: ResultMessage | None = None

    async def _consume() -> None:
        nonlocal result
        async for msg in query(prompt=prompt_text, options=options):
            if isinstance(msg, ResultMessage):
                result = msg

    debut = time.monotonic()
    await asyncio.wait_for(_consume(), timeout=TIMEOUT_S)
    duree = time.monotonic() - debut

    if result is None:
        raise RuntimeError("aucun ResultMessage reçu du SDK")
    if result.is_error:
        raise RuntimeError(f"SDK en erreur ({result.subtype})")

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


async def generer_depuis_lettre(
    intitule: str,
    entreprise: str | None,
    texte_lettre: str,
    coordonnees: Coordonnees,
) -> ResultatGeneration:
    """Un seul appel modèle (Sonnet). Lève `ConsigneAbsenteError` avant tout
    appel si la consigne manque (critère 4). Lève `ReponseIncompleteError`
    sans rien persister si la réponse n'a pas d'objet ou de corps (critère 5)."""
    consigne = load_consigne()
    prompt_text = build_prompt(
        consigne, intitule, entreprise, texte_lettre, coordonnees
    )
    out, duree_s, cout_usd, reponse = await _appeler_modele(prompt_text)
    objet = (out.get("objet") or "").strip()
    corps = (out.get("corps") or "").strip()
    if not objet or not corps:
        raise ReponseIncompleteError()
    return ResultatGeneration(
        objet=objet,
        corps=corps,
        modele=MODELE,
        duree_s=duree_s,
        cout_usd=cout_usd,
        demande=prompt_text,
        reponse=reponse,
    )


def _row_to_mail(row: sqlite3.Row) -> dict:
    return {
        "objet": row["objet"],
        "corps": row["corps"],
        "origine": row["origine"],
        "modele": row["modele"],
        "created_at": row["created_at"],
    }


def get_mail(conn: sqlite3.Connection, offer_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM mails WHERE offer_id = ?", (offer_id,)).fetchone()
    return _row_to_mail(row) if row else None


def get_appel(conn: sqlite3.Connection, offer_id: int) -> dict | None:
    row = conn.execute(
        "SELECT appel_json FROM mails WHERE offer_id = ?", (offer_id,)
    ).fetchone()
    if row is None or not row["appel_json"]:
        return None
    return json.loads(row["appel_json"])


def persister_generation(
    conn: sqlite3.Connection, offer_id: int, resultat: ResultatGeneration
) -> dict:
    """Remplace le mail courant de l'offre, généré ou à la main (critère 11)."""
    appel = {
        "modele": resultat.modele,
        "duree_s": resultat.duree_s,
        "cout_usd": resultat.cout_usd,
        "demande": resultat.demande,
        "reponse": resultat.reponse,
    }
    conn.execute(
        """
        INSERT INTO mails (offer_id, objet, corps, origine, modele, appel_json, created_at)
        VALUES (?, ?, ?, 'modele', ?, ?, ?)
        ON CONFLICT(offer_id) DO UPDATE SET
            objet=excluded.objet, corps=excluded.corps, origine='modele',
            modele=excluded.modele, appel_json=excluded.appel_json, created_at=excluded.created_at
        """,
        (
            offer_id,
            resultat.objet,
            resultat.corps,
            resultat.modele,
            json.dumps(appel, ensure_ascii=False),
            _now(),
        ),
    )
    conn.commit()
    return get_mail(conn, offer_id)


def enregistrer_manuel(
    conn: sqlite3.Connection, offer_id: int, objet: str, corps: str
) -> dict:
    """Enregistre une version écrite à la main, qui remplace la précédente quelle
    que soit son origine (critères 7, 8, 11)."""
    conn.execute(
        """
        INSERT INTO mails (offer_id, objet, corps, origine, modele, appel_json, created_at)
        VALUES (?, ?, ?, 'moi', NULL, NULL, ?)
        ON CONFLICT(offer_id) DO UPDATE SET
            objet=excluded.objet, corps=excluded.corps, origine='moi',
            modele=NULL, appel_json=NULL, created_at=excluded.created_at
        """,
        (offer_id, objet, corps, _now()),
    )
    conn.commit()
    return get_mail(conn, offer_id)
