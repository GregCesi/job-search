"""Chargement du répertoire de la lettre (EXE-146) : textes types, posture, sujets
interdits — écrits à la main dans data/lettre/repertoire.yaml (hors git, TCK-251).

Un champ dont la valeur porte le marqueur de trou (`[À COMPLÉTER`) est rendu absent
du chargement, jamais comblé par le code (architecture.md, exceptions encadrées de
la lettre) : voir `_nettoyer()`.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from orchestrator.job_search.paths import REPERTOIRE_LETTRE_PATH

TROU_MARQUEUR = "[À COMPLÉTER"

_ABSENT = object()


class RepertoireError(ValueError):
    """Répertoire de la lettre refusé : message lisible, sans trace Python."""


class FormulationRejetee(BaseModel):
    model_config = ConfigDict(extra="allow")

    texte: str | None = None
    motif: str | None = None


class Posture(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str | None = None
    quatre_temps: list[str] = Field(default_factory=list)
    regles: list[str] = Field(default_factory=list)
    formulations_rejetees: list[FormulationRejetee] = Field(default_factory=list)


class SujetInterdit(BaseModel):
    model_config = ConfigDict(extra="allow")

    sujet: str | None = None
    motif: str | None = None
    exception: str | None = None


class PourEntretien(BaseModel):
    model_config = ConfigDict(extra="allow")

    sujet: str | None = None
    position: str | None = None


class Forme(BaseModel):
    model_config = ConfigDict(extra="allow")

    blocs: list[str] = Field(default_factory=list)
    longueur_cible_mots: int | None = None
    lettre_de_reference: str | None = None


class Exemple(BaseModel):
    model_config = ConfigDict(extra="allow")

    entreprise: str | None = None
    fait: str | None = None
    citation: str | None = None
    url: str | None = None
    texte: str | None = None
    avis_gregoire: str | None = None
    source: str | None = None
    citation_controlee_a_l_oeil: bool | None = None
    a_corriger: str | None = None
    a_respecter: str | None = None


class TexteType(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    sujet: str
    etat: str | None = None
    conviction: str | None = None
    ce_que_j_ai_fait: str | None = None
    s_applique_si: str | None = None
    s_applique_si_propose_par_le_chat: str | None = None
    ne_s_applique_pas_si: str | None = None
    texte: str | None = None
    exemples: list[Exemple] = Field(default_factory=list)


class ExempleRelecture(BaseModel):
    model_config = ConfigDict(extra="allow")

    titre: str | None = None
    passage_lu: str | None = None
    relecture: str | None = None


class Juge(BaseModel):
    model_config = ConfigDict(extra="allow")

    consigne: str | None = None
    contexte: str | None = None
    exemples: list[ExempleRelecture] = Field(default_factory=list)


class Redaction(BaseModel):
    model_config = ConfigDict(extra="allow")

    consigne_reprise: str | None = None


class Repertoire(BaseModel):
    model_config = ConfigDict(extra="allow")

    version: int | None = None
    posture: Posture = Field(default_factory=Posture)
    ce_qui_fait_une_bonne_accroche: list[str] = Field(default_factory=list)
    ce_qui_est_vrai_sur_moi: list[str] = Field(default_factory=list)
    sujets_interdits: list[SujetInterdit] = Field(default_factory=list)
    conditions_generales: list[str] = Field(default_factory=list)
    pour_l_entretien_pas_pour_la_lettre: list[PourEntretien] = Field(
        default_factory=list
    )
    forme: Forme = Field(default_factory=Forme)
    textes_types: list[TexteType] = Field(default_factory=list)
    juge: Juge = Field(default_factory=Juge)
    redaction: Redaction = Field(default_factory=Redaction)


@dataclass(frozen=True)
class Trou:
    """L'endroit d'un champ comblé par le marqueur de trou, jamais par le code."""

    champ: str
    texte_type: str | None = None
    exemple: str | None = None


@dataclass(frozen=True)
class RepertoireCharge:
    repertoire: Repertoire
    trous: list[Trou]


def _est_trou(valeur: Any) -> bool:
    return isinstance(valeur, str) and TROU_MARQUEUR in valeur


def _nettoyer_valeur(
    valeur: Any,
    champ: str,
    texte_type_id: str | None,
    exemple_id: str | None,
    trous: list[Trou],
) -> Any:
    if _est_trou(valeur):
        trous.append(Trou(champ=champ, texte_type=texte_type_id, exemple=exemple_id))
        return _ABSENT
    if isinstance(valeur, dict):
        nettoye: dict[str, Any] = {}
        for cle, sous_valeur in valeur.items():
            resultat = _nettoyer_valeur(
                sous_valeur, f"{champ}.{cle}", texte_type_id, exemple_id, trous
            )
            if resultat is not _ABSENT:
                nettoye[cle] = resultat
        return nettoye
    if isinstance(valeur, list):
        nettoye_liste = []
        for item in valeur:
            resultat = _nettoyer_valeur(item, champ, texte_type_id, exemple_id, trous)
            if resultat is not _ABSENT:
                nettoye_liste.append(resultat)
        return nettoye_liste
    return valeur


def _nettoyer_exemple(
    exemple_brut: dict, texte_type_id: str | None, trous: list[Trou]
) -> dict:
    entreprise = exemple_brut.get("entreprise")
    exemple_id = entreprise if isinstance(entreprise, str) else None
    nettoye: dict[str, Any] = {}
    for cle, valeur in exemple_brut.items():
        resultat = _nettoyer_valeur(valeur, cle, texte_type_id, exemple_id, trous)
        if resultat is not _ABSENT:
            nettoye[cle] = resultat
    return nettoye


def _nettoyer_texte_type(texte_type_brut: dict, trous: list[Trou]) -> dict:
    identifiant = texte_type_brut.get("id")
    texte_type_id = identifiant if isinstance(identifiant, str) else None
    nettoye: dict[str, Any] = {}
    for cle, valeur in texte_type_brut.items():
        if cle == "exemples" and isinstance(valeur, list):
            nettoye[cle] = [
                _nettoyer_exemple(ex, texte_type_id, trous)
                for ex in valeur
                if isinstance(ex, dict)
            ]
            continue
        resultat = _nettoyer_valeur(valeur, cle, texte_type_id, None, trous)
        if resultat is not _ABSENT:
            nettoye[cle] = resultat
    return nettoye


def _nettoyer(donnees: dict) -> tuple[dict, list[Trou]]:
    """Retire du répertoire toute valeur portant le marqueur de trou (critère 7),
    en gardant trace de son endroit (texte type, exemple, champ — critère 8)."""
    trous: list[Trou] = []
    nettoye: dict[str, Any] = {}
    textes_types_bruts = donnees.get("textes_types")
    for cle, valeur in donnees.items():
        if cle == "textes_types" and isinstance(textes_types_bruts, list):
            nettoye[cle] = [
                _nettoyer_texte_type(tt, trous)
                for tt in textes_types_bruts
                if isinstance(tt, dict)
            ]
            continue
        resultat = _nettoyer_valeur(valeur, cle, None, None, trous)
        if resultat is not _ABSENT:
            nettoye[cle] = resultat
    return nettoye, trous


def _valider_textes_types(textes_types_bruts: list[Any]) -> None:
    """Règles de forme que Pydantic seul ne peut pas refuser avec le message exact
    demandé par le ticket (critères 10 à 13)."""
    ids_vus: set[str] = set()
    a_generique = False
    for rang0, texte_type in enumerate(textes_types_bruts):
        rang = rang0 + 1
        identifiant = texte_type.get("id") if isinstance(texte_type, dict) else None
        if not identifiant:
            raise RepertoireError(f"le texte type au rang {rang} n'a pas d'identifiant")
        if identifiant in ids_vus:
            raise RepertoireError(
                f"identifiant de texte type en double : {identifiant}"
            )
        ids_vus.add(identifiant)
        if not texte_type.get("sujet"):
            raise RepertoireError(f"le texte type « {identifiant} » n'a pas de sujet")
        if identifiant == "generique":
            a_generique = True
    if not a_generique:
        raise RepertoireError("aucun texte type ne porte l'identifiant « generique »")


def valider_juge_et_redaction(repertoire: Repertoire) -> None:
    """EXE-158, critères 13-14 : sans ces trois champs, aucun appel de modèle ne
    doit partir — la raison nomme ce qui manque, avant tout appel.

    Volontairement hors de `charger_repertoire` : ce chargeur est aussi celui de
    la fiche entreprise (`fiche/prompt.py`), qui ne lit que `textes_types` et
    `sujets_interdits` et n'a aucune raison de connaître le juge ou la reprise
    de la rédaction. Le banc et la boucle appellent cette fonction eux-mêmes."""
    if not (repertoire.juge.consigne or "").strip():
        raise RepertoireError("le répertoire de la lettre n'a pas de consigne du juge")
    if not (repertoire.juge.contexte or "").strip():
        raise RepertoireError("le répertoire de la lettre n'a pas de contexte du juge")
    if not (repertoire.redaction.consigne_reprise or "").strip():
        raise RepertoireError(
            "le répertoire de la lettre n'a pas de consigne de reprise pour la "
            "rédaction"
        )


def charger_repertoire(chemin: str | Path) -> RepertoireCharge:
    """Charge et valide le répertoire de la lettre. Refuse avec une phrase lisible
    (jamais une trace Python) les cas listés aux critères 9 à 14 du ticket EXE-146."""
    chemin = Path(chemin)
    if not chemin.exists():
        raise RepertoireError(f"répertoire de la lettre introuvable : {chemin}")

    texte_brut = chemin.read_text(encoding="utf-8")
    try:
        donnees = yaml.safe_load(texte_brut)
    except yaml.YAMLError as exc:
        raise RepertoireError(
            f"le répertoire de la lettre n'est pas un YAML lisible : {chemin}"
        ) from exc

    if not isinstance(donnees, dict):
        raise RepertoireError(
            f"le répertoire de la lettre n'est pas un YAML lisible : {chemin}"
        )

    nettoye, trous = _nettoyer(donnees)
    _valider_textes_types(nettoye.get("textes_types") or [])

    try:
        repertoire = Repertoire.model_validate(nettoye)
    except ValidationError as exc:
        raise RepertoireError(f"répertoire de la lettre invalide : {exc}") from exc

    return RepertoireCharge(repertoire=repertoire, trous=trous)


def _formater_trou(trou: Trou) -> str:
    if trou.texte_type and trou.exemple:
        return (
            f"texte type « {trou.texte_type} », exemple « {trou.exemple} » : "
            f"champ « {trou.champ} »"
        )
    if trou.texte_type:
        return f"texte type « {trou.texte_type} » : champ « {trou.champ} »"
    return f"champ « {trou.champ} »"


def main() -> int:
    """python -m orchestrator.job_search.lettre.repertoire [chemin] — commande de
    contrôle (critères 15, 16) : imprime le nombre de textes types, le nombre
    d'exemples et la liste des trous, rend 0 ; sur un répertoire refusé, imprime la
    raison du refus et rend 1."""
    parser = argparse.ArgumentParser(description="Contrôle le répertoire de la lettre")
    parser.add_argument("chemin", nargs="?", default=str(REPERTOIRE_LETTRE_PATH))
    args = parser.parse_args()

    try:
        charge = charger_repertoire(args.chemin)
    except RepertoireError as exc:
        print(str(exc))
        return 1

    n_textes_types = len(charge.repertoire.textes_types)
    n_exemples = sum(len(tt.exemples) for tt in charge.repertoire.textes_types)
    print(f"{n_textes_types} texte(s) type(s)")
    print(f"{n_exemples} exemple(s)")
    if charge.trous:
        print(f"{len(charge.trous)} trou(s) :")
        for trou in charge.trous:
            print(f"- {_formater_trou(trou)}")
    else:
        print("0 trou")
    return 0


if __name__ == "__main__":
    sys.exit(main())
