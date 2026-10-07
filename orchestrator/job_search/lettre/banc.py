"""Banc de la lettre (EXE-148, refait EXE-151) : passe les offres d'un jeu
d'évaluation figé dans la boucle LangGraph (EXE-147) sous plusieurs
configurations de modèles, pour comparer leurs lettres, leur durée et leur
coût sur une seule page et dans MLflow (architecture.md, « Exception
encadrée : banc de la lettre »).

Part uniquement d'une commande lancée à la main (`python -m
orchestrator.job_search.lettre.banc --jeu ... --config ...`). N'ouvre aucune
connexion à la base — toutes les offres (titre, entreprise, texte, faits de la
recherche d'entreprise) viennent du jeu, préparé à part par
`lettre/jeu.py`. Un seul rapport est écrit pour toutes les configurations ;
chaque configuration a en plus son propre run MLflow, sous l'expérience
« lettre-banc », qui porte le même rapport et le jeu en pièce.

Une offre du jeu marquée d'une raison d'échec de recherche, ou absente du
jeu, est sautée pour toutes les configurations (une seule fois, avant
d'itérer les configurations) : ce calcul partagé garantit que chaque run
MLflow porte la même liste d'offres, dans le même ordre.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.job_search.lettre.boucle import (
    GENERIQUE_ID,
    MAX_TOURS,
    MODELES_CLAUDE,
    RAISON_PLAFOND,
    RAISON_RIEN_A_REDIRE,
    Appel,
    ConfigBoucle,
    ResultatBoucle,
    generer_lettre_depuis_donnees,
)
from orchestrator.job_search.lettre.redaction import ecart_longueur_mots
from orchestrator.job_search.lettre.repertoire import (
    RepertoireError,
    charger_repertoire,
)
from orchestrator.job_search.paths import (
    CV_REFERENCE_PATH,
    LETTRE_BANC_JEUX_DIR,
    LETTRE_BANC_REPORTS_DIR,
    LETTRE_TOURNURES_PATH,
    REPERTOIRE_LETTRE_PATH,
)
from orchestrator.job_search.tracking.mlflow_tracking import RunTracker

EXPERIMENT_NAME = "lettre-banc"

RAISON_ABSENTE_DU_JEU = "cette offre n'est pas dans le jeu"


class ConfigurationInvalideError(ValueError):
    """Une configuration passée à `--config` n'est pas lisible (H2 du ticket)."""


class JeuIntrouvableError(ValueError):
    """Le jeu désigné par `--jeu` n'existe pas ou n'est pas un JSON lisible (EXE-151)."""


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

    # EXE-155, H2 : « generique » n'est le nom d'aucun modèle — il ne vaut que
    # pour le rôle tamis (critères 5-10). Pour redaction/juge, explicite ou via le
    # modèle de base, c'est une configuration invalide.
    for role, valeur in roles.items():
        if role != "tamis" and valeur == GENERIQUE_ID:
            raise ConfigurationInvalideError(f"configuration invalide : « {spec} »")

    return ConfigNommee(
        label=spec,
        config=ConfigBoucle(
            modele_tamis=roles["tamis"],
            modele_redaction=roles["redaction"],
            modele_juge=roles["juge"],
        ),
    )


def charger_jeu(nom: str, jeux_dir: str | Path) -> dict:
    """Lit le jeu `nom` sous `jeux_dir` (critères 15, 16 — refuse sans appeler
    aucun modèle si le nom est absent ou le fichier illisible)."""
    chemin = Path(jeux_dir) / f"{nom}.json"
    if not chemin.exists():
        raise JeuIntrouvableError(f"jeu introuvable : « {nom} » ({chemin})")
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise JeuIntrouvableError(f"jeu illisible : « {nom} » ({exc})") from exc


@dataclass(frozen=True)
class OffreBanc:
    """Résolution d'une offre du jeu, partagée par toutes les configurations :
    soit prête à passer dans la boucle, soit sautée avec sa raison (jeu
    absent, ou raison d'échec de recherche portée par le jeu)."""

    offer_id: int
    skip_reason: str | None
    titre: str = ""
    entreprise: str = ""
    texte_offre: str = ""
    faits: list = field(default_factory=list)


def _resoudre_offres_depuis_jeu(jeu: dict, offer_ids: list[int]) -> list[OffreBanc]:
    par_id = {entree["offer_id"]: entree for entree in jeu.get("offres", [])}
    offres = []
    for offer_id in offer_ids:
        entree = par_id.get(offer_id)
        if entree is None:
            offres.append(OffreBanc(offer_id, RAISON_ABSENTE_DU_JEU))
            continue
        offres.append(
            OffreBanc(
                offer_id,
                entree.get("raison_echec_recherche"),
                entree.get("intitule") or "",
                entree.get("entreprise") or "",
                entree.get("texte_offre") or "",
                entree.get("faits") or [],
            )
        )
    return offres


@dataclass
class Passage:
    """Un passage = une offre sous une configuration (critère 1). `resultat`
    est `None` quand l'offre a été sautée — `skip_reason` porte alors la
    raison affichée (critère 9) et écrite au rapport."""

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
    sans appeler la boucle."""
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
                resultat = generer_lettre_depuis_donnees(
                    offre.titre,
                    offre.texte_offre,
                    offre.entreprise,
                    offre.faits,
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
    # EXE-152, critères 10-15 : mesures de tenue de la lettre, sans aucun modèle.
    lettres_sans_tournures: int
    total_tournures: int
    ecart_moyen_abs_mots: float | None
    juge_rien_a_redire: int
    erreurs_reponse_illisible: int
    erreurs_appel_echoue: int
    table: dict[str, list] = field(default_factory=dict)


def _fait_retenu_texte(fait_retenu) -> str:
    if fait_retenu is None or fait_retenu == GENERIQUE_ID:
        return ""
    if isinstance(fait_retenu, dict):
        return fait_retenu.get("citation") or fait_retenu.get("position") or ""
    return str(fait_retenu)


def resumer_config(
    config_nommee: ConfigNommee,
    offres: list[OffreBanc],
    passages: list[Passage],
    longueur_cible_mots: int | None = None,
) -> ResumeConfig:
    """Les observables du tableau de comparaison (critères 11, 10-15) et la
    table du run MLflow, une ligne par offre dans l'ordre demandé
    (critères 17-19). Aucune mesure n'appelle de modèle : tout vient des
    champs déjà calculés par la boucle (tournures, mots) ou d'un calcul
    Python pur sur eux (écart à `longueur_cible_mots`)."""
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
        "tournures_lettre_finale": [],
        "ecart_mots": [],
    }
    par_offre = {p.offer_id: p for p in de_cette_config}
    ecarts_abs: list[int] = []
    for offre in offres:
        passage = par_offre[offre.offer_id]
        resultat = passage.resultat
        derniere = resultat.lettres[-1] if resultat and resultat.lettres else None
        ecart = (
            ecart_longueur_mots(derniere["nb_mots"], longueur_cible_mots)
            if derniere
            else None
        )
        if ecart is not None:
            ecarts_abs.append(abs(ecart))
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
        table["tournures_lettre_finale"].append(
            derniere["tournures_signalees"] if derniere else None
        )
        table["ecart_mots"].append(ecart)

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
        lettres_sans_tournures=sum(
            1 for p in avec_lettres if not p.resultat.lettres[-1]["tournures_signalees"]
        ),
        total_tournures=sum(
            len(p.resultat.lettres[-1]["tournures_signalees"]) for p in avec_lettres
        ),
        ecart_moyen_abs_mots=(
            sum(ecarts_abs) / len(ecarts_abs) if ecarts_abs else None
        ),
        juge_rien_a_redire=sum(
            1 for p in avec_lettres if p.resultat.raison_fin == RAISON_RIEN_A_REDIRE
        ),
        erreurs_reponse_illisible=sum(
            1 for p in ran if p.resultat.erreur_type == "reponse_illisible"
        ),
        erreurs_appel_echoue=sum(
            1 for p in ran if p.resultat.erreur_type == "appel_echoue"
        ),
        table=table,
    )


# --- le rapport (critères 10-15, 21) ----------------------------------------


def _fmt(valeur, suffixe: str = "", precision: int = 1) -> str:
    if valeur is None:
        return "—"
    if isinstance(valeur, float):
        return f"{valeur:.{precision}f}{suffixe}"
    return f"{valeur}{suffixe}"


def _tableau_comparaison(resumes: list[ResumeConfig]) -> str:
    lignes = [
        "| Configuration | Lettres produites | Durée totale | Durée moyenne/lettre "
        "| Coût total | Tours en moyenne | Plafonds atteints | Lettres génériques "
        "| Lettres sans tournure interdite | Tournures interdites trouvées "
        "| Écart moyen (abs) à la longueur cible | Lettres sans rien à redire "
        "| Réponses illisibles | Appels échoués |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for resume in resumes:
        lignes.append(
            f"| {resume.config_nommee.label} | {resume.lettres_produites} "
            f"| {_fmt(resume.duree_totale_s, 's')} "
            f"| {_fmt(resume.duree_moyenne_par_lettre_s, 's')} "
            f"| {_fmt(resume.cout_total_usd, '$', 4)} "
            f"| {_fmt(resume.tours_moyen, '', 1)} "
            f"| {resume.plafonds_atteints} | {resume.lettres_generiques} "
            f"| {resume.lettres_sans_tournures} | {resume.total_tournures} "
            f"| {_fmt(resume.ecart_moyen_abs_mots, ' mot(s)', 1)} "
            f"| {resume.juge_rien_a_redire} "
            f"| {resume.erreurs_reponse_illisible} | {resume.erreurs_appel_echoue} |"
        )
    return "\n".join(lignes)


def _tournures_txt(tournures: list[str]) -> str:
    """EXE-152, critères 6, 7 : les tournures interdites sont citées telles
    qu'écrites dans la lettre, jamais corrigées — ou leur absence est dite."""
    if not tournures:
        return "Aucune tournure interdite."
    citations = ", ".join(f"« {t} »" for t in tournures)
    return f"Tournures interdites : {citations}"


def _ecart_txt(nb_mots: int, longueur_cible_mots: int | None) -> str | None:
    """EXE-152, critères 8, 9 : `None` quand le répertoire ne porte pas de
    longueur cible — absent du rapport, jamais remplacé par un zéro."""
    ecart = ecart_longueur_mots(nb_mots, longueur_cible_mots)
    if ecart is None:
        return None
    signe = "+" if ecart >= 0 else ""
    return f"Écart à la longueur cible : {signe}{ecart} mot(s)"


def _section_offre(
    offre: OffreBanc,
    configs: list[ConfigNommee],
    passages: list[Passage],
    longueur_cible_mots: int | None,
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
        lignes_lettres.append(_tournures_txt(derniere["tournures_signalees"]))
        ecart_txt = _ecart_txt(derniere["nb_mots"], longueur_cible_mots)
        if ecart_txt is not None:
            lignes_lettres.append(ecart_txt)
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
        # EXE-152, critères 19, 20 : jetons lus, seulement pour un modèle local
        # et seulement s'ils sont rendus — jamais un zéro à la place.
        jetons_txt = ""
        if appel.modele not in MODELES_CLAUDE and appel.nb_jetons is not None:
            jetons_txt = f", {appel.nb_jetons} jeton(s) lus"
        lignes.append(
            f"- {appel.noeud} ({appel.modele}) : {appel.duree_s:.2f}s{jetons_txt}"
        )
    if resultat.lettres == [] and resultat.raison_fin:
        lignes.append(f"\nArrêt sans lettre : {resultat.raison_fin}")
    return "\n".join(lignes)


def construire_rapport(
    jeu_nom: str,
    offer_ids: list[int],
    configs: list[ConfigNommee],
    offres: list[OffreBanc],
    passages: list[Passage],
    resumes: list[ResumeConfig],
    horodatage: str,
    longueur_cible_mots: int | None = None,
) -> str:
    entete = (
        f"# Banc de la lettre — {horodatage}\n\n"
        f"Jeu : {jeu_nom}\n"
        f"Offres : {', '.join(str(o) for o in offer_ids)}\n"
        f"Configurations : {', '.join(c.label for c in configs)}\n"
    )
    tableau = "## Tableau de comparaison\n\n" + _tableau_comparaison(resumes)
    sections_offres = "\n\n".join(
        _section_offre(offre, configs, passages, longueur_cible_mots)
        for offre in offres
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


# --- MLflow (critères 16-22) -------------------------------------------------


def _logger_config(
    resume: ResumeConfig,
    offer_ids: list[int],
    jeu_nom: str,
    rapport_path: Path,
    jeu_path: Path | None,
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
            "jeu": jeu_nom,
        },
        run_name=resume.config_nommee.label,
    )
    metrics = {
        "lettres_produites": float(resume.lettres_produites),
        "duree_totale_s": resume.duree_totale_s,
        "plafonds_atteints": float(resume.plafonds_atteints),
        "lettres_generiques": float(resume.lettres_generiques),
        # EXE-152, critère 16 : les six mesures 10-15 du tableau de comparaison.
        "lettres_sans_tournures": float(resume.lettres_sans_tournures),
        "total_tournures": float(resume.total_tournures),
        "juge_rien_a_redire": float(resume.juge_rien_a_redire),
        "erreurs_reponse_illisible": float(resume.erreurs_reponse_illisible),
        "erreurs_appel_echoue": float(resume.erreurs_appel_echoue),
    }
    if resume.duree_moyenne_par_lettre_s is not None:
        metrics["duree_moyenne_par_lettre_s"] = resume.duree_moyenne_par_lettre_s
    if resume.cout_total_usd is not None:
        metrics["cout_total_usd"] = resume.cout_total_usd
    if resume.tours_moyen is not None:
        metrics["tours_moyen"] = resume.tours_moyen
    if resume.ecart_moyen_abs_mots is not None:
        metrics["ecart_moyen_abs_mots"] = resume.ecart_moyen_abs_mots
    tracker.log_metrics(metrics)
    tracker.log_table(resume.table, artifact_file="passages.json")
    tracker.log_artifact(rapport_path)
    if jeu_path is not None:
        tracker.log_artifact(jeu_path)
    tracker.end()


# --- orchestration (critère 10 : un seul rapport pour toutes les configs) --


@dataclass
class ResultatBanc:
    passages: list[Passage]
    resumes: list[ResumeConfig]
    rapport_path: Path


def lancer_banc(
    jeu: dict,
    offer_ids: list[int] | None,
    config_specs: list[str],
    *,
    repertoire_path: str | Path = REPERTOIRE_LETTRE_PATH,
    cv_reference_path: str | Path = CV_REFERENCE_PATH,
    tournures_path: str | Path = LETTRE_TOURNURES_PATH,
    banc_dir: str | Path = LETTRE_BANC_REPORTS_DIR,
    jeu_path: str | Path | None = None,
    tracker_factory=RunTracker,
) -> ResultatBanc:
    """Point d'entrée du banc : résout les offres du jeu une seule fois
    (partagée par toutes les configurations, critère 19), fait tourner chaque
    passage, écrit le rapport unique (critère 10) puis un run MLflow par
    configuration. `offer_ids` limite et ordonne le sous-ensemble du jeu à
    jouer (critère 19) ; `None` joue le jeu entier, dans son ordre
    (critère 13). Une panne MLflow ne doit jamais empêcher le rapport d'être
    écrit : le rapport est déjà sur disque avant que la boucle MLflow ne
    démarre."""
    configs = [parser_config(spec) for spec in config_specs]
    ids_resolus = (
        offer_ids
        if offer_ids is not None
        else [entree["offer_id"] for entree in jeu.get("offres", [])]
    )
    offres = _resoudre_offres_depuis_jeu(jeu, ids_resolus)

    # EXE-152, critères 8, 9, 12, 17 : la longueur cible vient du répertoire,
    # lu une seule fois ici — calcul Python pur, aucun modèle appelé.
    longueur_cible_mots = charger_repertoire(
        repertoire_path
    ).repertoire.forme.longueur_cible_mots

    passages = executer_passages(
        offres,
        configs,
        repertoire_path=repertoire_path,
        cv_reference_path=cv_reference_path,
        tournures_path=tournures_path,
    )
    resumes = [
        resumer_config(config, offres, passages, longueur_cible_mots)
        for config in configs
    ]

    horodatage = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    texte_rapport = construire_rapport(
        jeu.get("nom", ""),
        ids_resolus,
        configs,
        offres,
        passages,
        resumes,
        horodatage,
        longueur_cible_mots,
    )
    rapport_path = _ecrire_rapport(texte_rapport, Path(banc_dir), horodatage)

    for resume in resumes:
        _logger_config(
            resume,
            ids_resolus,
            jeu.get("nom", ""),
            rapport_path,
            Path(jeu_path) if jeu_path is not None else None,
            tracker_factory,
        )

    return ResultatBanc(passages=passages, resumes=resumes, rapport_path=rapport_path)


# --- CLI ----------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
    *,
    repertoire_path: str | Path = REPERTOIRE_LETTRE_PATH,
    cv_reference_path: str | Path = CV_REFERENCE_PATH,
    tournures_path: str | Path = LETTRE_TOURNURES_PATH,
    banc_dir: str | Path = LETTRE_BANC_REPORTS_DIR,
    jeux_dir: str | Path = LETTRE_BANC_JEUX_DIR,
    tracker_factory=RunTracker,
) -> int:
    """python -m orchestrator.job_search.lettre.banc --jeu essai1 --config
    sonnet --config opus --config sonnet,juge=opus [--offres 179,1677] (H2 du ticket)."""
    parser = argparse.ArgumentParser(
        description="Banc de la lettre (comparaison de modèles)"
    )
    parser.add_argument("--jeu", required=True, help="nom du jeu d'évaluation figé")
    parser.add_argument(
        "--offres",
        required=False,
        default=None,
        help="sous-ensemble d'offres du jeu, séparées par des virgules (optionnel)",
    )
    parser.add_argument(
        "--config",
        dest="configs",
        action="append",
        required=True,
        help="une configuration de modèles, répétable",
    )
    args = parser.parse_args(argv)

    offer_ids: list[int] | None = None
    if args.offres:
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

    try:
        jeu = charger_jeu(args.jeu, jeux_dir)
    except JeuIntrouvableError as exc:
        print(str(exc))
        return 1

    jeu_path = Path(jeux_dir) / f"{args.jeu}.json"
    resultat = lancer_banc(
        jeu,
        offer_ids,
        args.configs,
        repertoire_path=repertoire_path,
        cv_reference_path=cv_reference_path,
        tournures_path=tournures_path,
        banc_dir=banc_dir,
        jeu_path=jeu_path,
        tracker_factory=tracker_factory,
    )

    print(f"Rapport écrit : {resultat.rapport_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
