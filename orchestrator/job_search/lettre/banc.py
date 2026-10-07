"""Banc de la lettre (EXE-148) : passe les mêmes offres dans la boucle LangGraph
(EXE-147) sous plusieurs configurations de modèles, pour comparer leurs lettres,
leur durée et leur coût sur une seule page et dans MLflow (architecture.md,
« Exception encadrée : banc de la lettre »).

Part uniquement d'une commande lancée à la main (`python -m
orchestrator.job_search.lettre.banc --offres ... --config ...`). Lecture seule
de `offers`, `verdicts`, `fiches_entreprise` — n'écrit dans aucune table. Un
seul rapport est écrit pour toutes les configurations ; chaque configuration a
en plus son propre run MLflow, sous l'expérience « lettre-banc », qui porte le
même rapport en pièce.

Une offre non retenue, sans fiche entreprise terminée, sans texte ou absente
de la base est sautée pour toutes les configurations (une seule fois, avant
d'itérer les configurations) : ce calcul partagé garantit que chaque run
MLflow porte la même liste d'offres, dans le même ordre (critère 19).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.job_search.lettre.boucle import (
    GENERIQUE_ID,
    MAX_TOURS,
    RAISON_PLAFOND,
    Appel,
    ConfigBoucle,
    ResultatBoucle,
    generer_lettre_boucle,
)
from orchestrator.job_search.lettre.redaction import (
    RAISON_FICHE_NON_TERMINEE,
    RAISON_TEXTE_MANQUANT,
    resolve_offer_text,
)
from orchestrator.job_search.lettre.repertoire import (
    RepertoireError,
    charger_repertoire,
)
from orchestrator.job_search.paths import (
    CV_REFERENCE_PATH,
    LETTRE_BANC_REPORTS_DIR,
    LETTRE_TOURNURES_PATH,
    REPERTOIRE_LETTRE_PATH,
)
from orchestrator.job_search.storage.db import DB_PATH, init_db
from orchestrator.job_search.tracking.mlflow_tracking import RunTracker

EXPERIMENT_NAME = "lettre-banc"

RAISON_OFFRE_INTROUVABLE = "aucune offre ne correspond à ce numéro"
RAISON_NON_RETENUE = "l'offre n'est pas retenue"


class ConfigurationInvalideError(ValueError):
    """Une configuration passée à `--config` n'est pas lisible (H2 du ticket)."""


@dataclass(frozen=True)
class ConfigNommee:
    """Une configuration du banc : son libellé tel que tapé sur la ligne de
    commande (critère 16, nom du run) et les trois modèles qu'elle résout."""

    label: str
    config: ConfigBoucle


def parser_config(spec: str) -> ConfigNommee:
    """Une configuration est un modèle, suivi au besoin de `tamis=`,
    `redaction=` ou `juge=` séparés par des virgules (H2 du ticket) ; les
    rôles non nommés gardent le modèle de base (critères 2, 3)."""
    morceaux = [m.strip() for m in spec.split(",")]
    base = morceaux[0]
    if not base or "=" in base:
        raise ConfigurationInvalideError(f"configuration invalide : « {spec} »")

    roles = {"tamis": base, "redaction": base, "juge": base}
    for morceau in morceaux[1:]:
        if "=" not in morceau:
            raise ConfigurationInvalideError(f"configuration invalide : « {spec} »")
        cle, _, valeur = morceau.partition("=")
        cle, valeur = cle.strip(), valeur.strip()
        if cle not in roles or not valeur:
            raise ConfigurationInvalideError(f"configuration invalide : « {spec} »")
        roles[cle] = valeur

    return ConfigNommee(
        label=spec,
        config=ConfigBoucle(
            modele_tamis=roles["tamis"],
            modele_redaction=roles["redaction"],
            modele_juge=roles["juge"],
        ),
    )


@dataclass(frozen=True)
class OffreBanc:
    """Résolution d'un numéro d'offre, partagée par toutes les configurations
    (critères 4 à 7) : soit prête à passer dans la boucle, soit sautée avec sa
    raison."""

    offer_id: int
    skip_reason: str | None
    titre: str = ""
    entreprise: str = ""


def _resoudre_offre(conn: sqlite3.Connection, offer_id: int) -> OffreBanc:
    offer = conn.execute(
        "SELECT title, company, description_raw, description FROM offers WHERE id = ?",
        (offer_id,),
    ).fetchone()
    if offer is None:
        return OffreBanc(offer_id, RAISON_OFFRE_INTROUVABLE)

    titre = offer["title"] or ""

    verdict = conn.execute(
        "SELECT status FROM verdicts WHERE offer_id = ? ORDER BY id DESC LIMIT 1",
        (offer_id,),
    ).fetchone()
    if verdict is None or verdict["status"] != "retenu":
        return OffreBanc(offer_id, RAISON_NON_RETENUE, titre, offer["company"] or "")

    fiche = conn.execute(
        "SELECT statut, employeur_nom FROM fiches_entreprise WHERE offer_id = ?",
        (offer_id,),
    ).fetchone()
    entreprise = (fiche["employeur_nom"] if fiche else None) or offer["company"] or ""
    if fiche is None or fiche["statut"] != "done":
        return OffreBanc(offer_id, RAISON_FICHE_NON_TERMINEE, titre, entreprise)

    texte = resolve_offer_text(offer["description_raw"], offer["description"])
    if not texte:
        return OffreBanc(offer_id, RAISON_TEXTE_MANQUANT, titre, entreprise)

    return OffreBanc(offer_id, None, titre, entreprise)


@dataclass
class Passage:
    """Un passage = une offre sous une configuration (critère 1). `resultat`
    est `None` quand l'offre a été sautée (critères 4 à 7) — `skip_reason`
    porte alors la raison affichée (critère 9) et écrite au rapport."""

    config_label: str
    offer_id: int
    titre: str
    entreprise: str
    skip_reason: str | None
    resultat: ResultatBoucle | None
    duree_s: float
    cout_total_usd: float | None


def _cout_total(appels: list[Appel]) -> float | None:
    """Le coût d'un appel local est absent, pas nul (H9 du ticket) : le total
    ne compte que les appels qui en rendent un, et vaut `None` si aucun ne
    rend de coût."""
    couts = [a.cout_usd for a in appels if a.cout_usd is not None]
    return sum(couts) if couts else None


def _ligne_passage(passage: Passage) -> str:
    nb_tours = passage.resultat.nb_tours if passage.resultat else 0
    raison = passage.skip_reason or (
        passage.resultat.raison_fin if passage.resultat else ""
    )
    return (
        f"[{passage.config_label}] offre {passage.offer_id} ({passage.entreprise}) — "
        f"{nb_tours} tour(s) — {passage.duree_s:.1f}s — {raison}"
    )


def executer_passages(
    conn: sqlite3.Connection,
    offres: list[OffreBanc],
    configs: list[ConfigNommee],
    *,
    repertoire_path: str | Path,
    cv_reference_path: str | Path,
    tournures_path: str | Path,
) -> list[Passage]:
    """Fait tourner la boucle pour chaque offre résolue sous chaque
    configuration (critère 1), dans l'ordre configurations × offres. Une
    offre sautée (`skip_reason` posé) l'est pour toutes les configurations,
    sans appeler la boucle (critères 4 à 7)."""
    passages: list[Passage] = []
    for config in configs:
        for offre in offres:
            if offre.skip_reason is not None:
                passage = Passage(
                    config.label,
                    offre.offer_id,
                    offre.titre,
                    offre.entreprise,
                    offre.skip_reason,
                    None,
                    0.0,
                    None,
                )
            else:
                debut = time.perf_counter()
                resultat = generer_lettre_boucle(
                    conn,
                    offre.offer_id,
                    config.config,
                    repertoire_path=repertoire_path,
                    cv_reference_path=cv_reference_path,
                    tournures_path=tournures_path,
                )
                duree = time.perf_counter() - debut
                passage = Passage(
                    config.label,
                    offre.offer_id,
                    offre.titre,
                    offre.entreprise,
                    None,
                    resultat,
                    duree,
                    _cout_total(resultat.appels),
                )
            passages.append(passage)
            print(_ligne_passage(passage))
    return passages


# --- synthèse par configuration (critères 11, 16-19) ------------------------


@dataclass
class ResumeConfig:
    config_nommee: ConfigNommee
    lettres_produites: int
    duree_totale_s: float
    duree_moyenne_par_lettre_s: float | None
    cout_total_usd: float | None
    tours_moyen: float | None
    plafonds_atteints: int
    lettres_generiques: int
    table: dict[str, list] = field(default_factory=dict)


def _fait_retenu_texte(fait_retenu) -> str:
    if fait_retenu is None or fait_retenu == GENERIQUE_ID:
        return ""
    if isinstance(fait_retenu, dict):
        return fait_retenu.get("citation") or fait_retenu.get("position") or ""
    return str(fait_retenu)


def resumer_config(
    config_nommee: ConfigNommee, offres: list[OffreBanc], passages: list[Passage]
) -> ResumeConfig:
    """Les sept observables du tableau de comparaison (critère 11) et la table
    du run MLflow, une ligne par offre dans l'ordre demandé (critères 17-19)."""
    de_cette_config = [p for p in passages if p.config_label == config_nommee.label]
    ran = [p for p in de_cette_config if p.resultat is not None]
    avec_lettres = [p for p in ran if p.resultat.lettres]

    duree_totale = sum(p.duree_s for p in de_cette_config)
    couts = [p.cout_total_usd for p in de_cette_config if p.cout_total_usd is not None]

    table: dict[str, list] = {
        "offre": [],
        "entreprise": [],
        "intitule": [],
        "fait_retenu": [],
        "texte_type": [],
        "lettre_finale": [],
        "tours": [],
        "mots": [],
        "duree_s": [],
        "cout_usd": [],
        "raison_fin": [],
    }
    par_offre = {p.offer_id: p for p in de_cette_config}
    for offre in offres:
        passage = par_offre[offre.offer_id]
        resultat = passage.resultat
        derniere = resultat.lettres[-1] if resultat and resultat.lettres else None
        table["offre"].append(offre.offer_id)
        table["entreprise"].append(offre.entreprise)
        table["intitule"].append(offre.titre)
        table["fait_retenu"].append(
            _fait_retenu_texte(resultat.fait_retenu) if resultat else None
        )
        table["texte_type"].append(resultat.texte_type_id if resultat else None)
        table["lettre_finale"].append(derniere["texte"] if derniere else None)
        table["tours"].append(resultat.nb_tours if resultat else 0)
        table["mots"].append(derniere["nb_mots"] if derniere else None)
        table["duree_s"].append(passage.duree_s)
        table["cout_usd"].append(passage.cout_total_usd)
        table["raison_fin"].append(
            passage.skip_reason or (resultat.raison_fin if resultat else None)
        )

    return ResumeConfig(
        config_nommee=config_nommee,
        lettres_produites=len(avec_lettres),
        duree_totale_s=duree_totale,
        duree_moyenne_par_lettre_s=(
            duree_totale / len(avec_lettres) if avec_lettres else None
        ),
        cout_total_usd=sum(couts) if couts else None,
        tours_moyen=(sum(p.resultat.nb_tours for p in ran) / len(ran) if ran else None),
        plafonds_atteints=sum(
            1 for p in ran if p.resultat.raison_fin == RAISON_PLAFOND
        ),
        lettres_generiques=sum(
            1 for p in avec_lettres if p.resultat.texte_type_id == GENERIQUE_ID
        ),
        table=table,
    )


# --- le rapport (critères 10-15) --------------------------------------------


def _fmt(valeur, suffixe: str = "", precision: int = 1) -> str:
    if valeur is None:
        return "—"
    if isinstance(valeur, float):
        return f"{valeur:.{precision}f}{suffixe}"
    return f"{valeur}{suffixe}"


def _tableau_comparaison(resumes: list[ResumeConfig]) -> str:
    lignes = [
        "| Configuration | Lettres produites | Durée totale | Durée moyenne/lettre "
        "| Coût total | Tours en moyenne | Plafonds atteints | Lettres génériques |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for resume in resumes:
        lignes.append(
            f"| {resume.config_nommee.label} | {resume.lettres_produites} "
            f"| {_fmt(resume.duree_totale_s, 's')} "
            f"| {_fmt(resume.duree_moyenne_par_lettre_s, 's')} "
            f"| {_fmt(resume.cout_total_usd, '$', 4)} "
            f"| {_fmt(resume.tours_moyen, '', 1)} "
            f"| {resume.plafonds_atteints} | {resume.lettres_generiques} |"
        )
    return "\n".join(lignes)


def _section_offre(
    offre: OffreBanc, configs: list[ConfigNommee], passages: list[Passage]
) -> str:
    titre_section = f"## Offre {offre.offer_id} — {offre.entreprise or offre.titre}"
    if offre.skip_reason is not None:
        return (
            f"{titre_section}\n\n"
            f"Sautée pour toutes les configurations : {offre.skip_reason}\n"
        )

    par_config = {p.config_label: p for p in passages if p.offer_id == offre.offer_id}

    lignes_fait = ["### Fait retenu et texte type", ""]
    for config in configs:
        passage = par_config[config.label]
        resultat = passage.resultat
        fait = _fait_retenu_texte(resultat.fait_retenu) or "(aucun — générique)"
        lignes_fait.append(
            f"- {config.label} : texte type « {resultat.texte_type_id} », "
            f"fait retenu : {fait}"
        )

    lignes_lettres = ["", "### Lettres finales", ""]
    for config in configs:
        passage = par_config[config.label]
        resultat = passage.resultat
        if not resultat.lettres:
            lignes_lettres.append(
                f"#### {config.label} — aucune lettre ({resultat.raison_fin})\n"
            )
            continue
        derniere = resultat.lettres[-1]
        lignes_lettres.append(
            f"#### {config.label} ({resultat.nb_tours} tour(s), "
            f"{derniere['nb_mots']} mots, {passage.duree_s:.1f}s, "
            f"{_fmt(passage.cout_total_usd, '$', 4)})\n"
        )
        lignes_lettres.append(derniere["texte"])
        lignes_lettres.append("")

    return titre_section + "\n\n" + "\n".join(lignes_fait) + "\n".join(lignes_lettres)


def _annexe_passage(passage: Passage) -> str:
    titre = f"### {passage.config_label} — offre {passage.offer_id}"
    if passage.skip_reason is not None:
        return f"{titre}\n\nSautée : {passage.skip_reason}\n"

    resultat = passage.resultat
    lignes = [titre, ""]
    for i, lettre in enumerate(resultat.lettres, start=1):
        lignes.append(f"**Tour {i}** ({lettre['nb_mots']} mots) :\n")
        lignes.append(lettre["texte"])
        if lettre["remarques_juge"]:
            lignes.append(f"\nRemarques du juge : {lettre['remarques_juge']}")
        lignes.append("")
    lignes.append("Durée des nœuds :")
    for appel in resultat.appels:
        lignes.append(f"- {appel.noeud} ({appel.modele}) : {appel.duree_s:.2f}s")
    if resultat.lettres == [] and resultat.raison_fin:
        lignes.append(f"\nArrêt sans lettre : {resultat.raison_fin}")
    return "\n".join(lignes)


def construire_rapport(
    offer_ids: list[int],
    configs: list[ConfigNommee],
    offres: list[OffreBanc],
    passages: list[Passage],
    resumes: list[ResumeConfig],
    horodatage: str,
) -> str:
    entete = (
        f"# Banc de la lettre — {horodatage}\n\n"
        f"Offres : {', '.join(str(o) for o in offer_ids)}\n"
        f"Configurations : {', '.join(c.label for c in configs)}\n"
    )
    tableau = "## Tableau de comparaison\n\n" + _tableau_comparaison(resumes)
    sections_offres = "\n\n".join(
        _section_offre(offre, configs, passages) for offre in offres
    )
    annexe = "## Annexe — détail de chaque passage\n\n" + "\n\n".join(
        _annexe_passage(p) for p in passages
    )
    return f"{entete}\n{tableau}\n\n{sections_offres}\n\n{annexe}\n"


def _ecrire_rapport(texte: str, banc_dir: Path, horodatage: str) -> Path:
    banc_dir.mkdir(parents=True, exist_ok=True)
    chemin = banc_dir / f"banc_{horodatage}.md"
    chemin.write_text(texte, encoding="utf-8")
    return chemin


# --- MLflow (critères 16-21) -------------------------------------------------


def _logger_config(
    resume: ResumeConfig,
    offer_ids: list[int],
    rapport_path: Path,
    tracker_factory,
) -> None:
    tracker = tracker_factory(experiment_name=EXPERIMENT_NAME)
    tracker.start(
        {
            "modele_tamis": resume.config_nommee.config.modele_tamis,
            "modele_redaction": resume.config_nommee.config.modele_redaction,
            "modele_juge": resume.config_nommee.config.modele_juge,
            "plafond_tours": MAX_TOURS,
            "offres": ",".join(str(o) for o in offer_ids),
        },
        run_name=resume.config_nommee.label,
    )
    metrics = {
        "lettres_produites": float(resume.lettres_produites),
        "duree_totale_s": resume.duree_totale_s,
        "plafonds_atteints": float(resume.plafonds_atteints),
        "lettres_generiques": float(resume.lettres_generiques),
    }
    if resume.duree_moyenne_par_lettre_s is not None:
        metrics["duree_moyenne_par_lettre_s"] = resume.duree_moyenne_par_lettre_s
    if resume.cout_total_usd is not None:
        metrics["cout_total_usd"] = resume.cout_total_usd
    if resume.tours_moyen is not None:
        metrics["tours_moyen"] = resume.tours_moyen
    tracker.log_metrics(metrics)
    tracker.log_table(resume.table, artifact_file="passages.json")
    tracker.log_artifact(rapport_path)
    tracker.end()


# --- orchestration (critère 10 : un seul rapport pour toutes les configs) --


@dataclass
class ResultatBanc:
    passages: list[Passage]
    resumes: list[ResumeConfig]
    rapport_path: Path


def lancer_banc(
    conn: sqlite3.Connection,
    offer_ids: list[int],
    config_specs: list[str],
    *,
    repertoire_path: str | Path = REPERTOIRE_LETTRE_PATH,
    cv_reference_path: str | Path = CV_REFERENCE_PATH,
    tournures_path: str | Path = LETTRE_TOURNURES_PATH,
    banc_dir: str | Path = LETTRE_BANC_REPORTS_DIR,
    tracker_factory=RunTracker,
) -> ResultatBanc:
    """Point d'entrée du banc : résout les offres une seule fois (partagée par
    toutes les configurations, critères 4-7, 19), fait tourner chaque passage,
    écrit le rapport unique (critère 10) puis un run MLflow par configuration
    (critères 16-20). Une panne MLflow ne doit jamais empêcher le rapport
    d'être écrit (critère 21) : le rapport est déjà sur disque avant que la
    boucle MLflow ne démarre."""
    configs = [parser_config(spec) for spec in config_specs]
    offres = [_resoudre_offre(conn, offer_id) for offer_id in offer_ids]

    passages = executer_passages(
        conn,
        offres,
        configs,
        repertoire_path=repertoire_path,
        cv_reference_path=cv_reference_path,
        tournures_path=tournures_path,
    )
    resumes = [resumer_config(config, offres, passages) for config in configs]

    horodatage = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    texte_rapport = construire_rapport(
        offer_ids, configs, offres, passages, resumes, horodatage
    )
    rapport_path = _ecrire_rapport(texte_rapport, Path(banc_dir), horodatage)

    for resume in resumes:
        _logger_config(resume, offer_ids, rapport_path, tracker_factory)

    return ResultatBanc(passages=passages, resumes=resumes, rapport_path=rapport_path)


# --- CLI ----------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
    *,
    repertoire_path: str | Path = REPERTOIRE_LETTRE_PATH,
    cv_reference_path: str | Path = CV_REFERENCE_PATH,
    tournures_path: str | Path = LETTRE_TOURNURES_PATH,
    banc_dir: str | Path = LETTRE_BANC_REPORTS_DIR,
    db_path: str | Path = DB_PATH,
    tracker_factory=RunTracker,
) -> int:
    """python -m orchestrator.job_search.lettre.banc --offres 179,1677 --config
    sonnet --config opus --config sonnet,juge=opus (H2 du ticket)."""
    parser = argparse.ArgumentParser(
        description="Banc de la lettre (comparaison de modèles)"
    )
    parser.add_argument(
        "--offres", required=True, help="numéros d'offres séparés par des virgules"
    )
    parser.add_argument(
        "--config",
        dest="configs",
        action="append",
        required=True,
        help="une configuration de modèles, répétable",
    )
    args = parser.parse_args(argv)

    try:
        offer_ids = [
            int(morceau.strip())
            for morceau in args.offres.split(",")
            if morceau.strip()
        ]
    except ValueError:
        print(f"liste d'offres invalide : « {args.offres} »")
        return 1

    try:
        for spec in args.configs:
            parser_config(spec)
    except ConfigurationInvalideError as exc:
        print(str(exc))
        return 1

    try:
        charger_repertoire(repertoire_path)
    except RepertoireError as exc:
        print(str(exc))
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        resultat = lancer_banc(
            conn,
            offer_ids,
            args.configs,
            repertoire_path=repertoire_path,
            cv_reference_path=cv_reference_path,
            tournures_path=tournures_path,
            banc_dir=banc_dir,
            tracker_factory=tracker_factory,
        )
    finally:
        conn.close()

    print(f"Rapport écrit : {resultat.rapport_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
