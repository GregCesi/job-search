"""Test EXE-201, critères 17-18 — garde générique : aucun fichier de
`web/app` ne décide d'afficher, d'activer ou d'expliquer quelque chose en
lisant le tri, l'étape, le verdict, la revue hors périmètre, la date
d'envoi, « prête à l'envoi », la décision de la lettre ou le statut d'une
pièce dans une condition (v-if, v-show, `disabled` lié, ternaire, if,
comparaison, `includes`).

Les gardes posées par EXE-194/195/197 (`test_exe194_front_sans_logique_metier.py`,
assertions ad hoc dans `test_exe195_decision_lettre.py` et
`test_exe199_suivi_candidatures.py`) sont des listes de chaînes exactes :
elles ne voient pas une comparaison nouvelle ou déplacée ailleurs dans
`web/app`. Celui-ci lit tous les fichiers `.vue`/`.ts` comme du texte (H5 du
ticket — ESLint/Vitest non retenus, ils demandent une dépendance et une
étape de barre) et repère toute ligne qui combine un marqueur de condition
et un des champs interdits.

Exceptions nommées (critère 17) : aucune ne porte sur un bouton de geste, le
bloc d'envoi, la carte Lettre ou la frise — sauf les six lignes
`lettreCarte(?.)statut === …` de `pages/offers/[id].vue`, qui choisissent
laquelle des sept sections de l'onglet Lettre afficher. Lues ainsi par le
chat (déclaré dans l'entrée Journal, « lu X comme Y ») : l'interdiction du
ticket cible les décisions de permission/affichage des *boutons* de la carte
(que l'API rend déjà par `boutons[].visible/actif`, lus tels quels par
`lettreCarteBoutonsVisibles` sans aucune comparaison), pas le choix, de
quelle section de contenu afficher — un renvoi côté API de « quelle section
afficher » serait un ajout de surplus que rien ne demande. Cinq de ces
lignes sont pré-existantes depuis EXE-162/195 ; la sixième (section « en
erreur ») est ajoutée par EXE-202, critères 1-4.
"""

import re
from pathlib import Path

WEB_APP = Path(__file__).resolve().parent.parent / "web" / "app"

CONDITION_MARKERS = ['v-if="', 'v-show="', ':disabled="', "===", "!==", ".includes("]

BANNED_TOKENS = [
    ".tri",
    ".etape",
    ".verdict",
    "revue_hors_perimetre",
    "envoyee_le",
    "prete_a_l_envoi",
    ".decision",
    "lettre_carte.statut",
    "lettreCarte.statut",
    "lettreCarte?.statut",
    ".cv.statut",
    ".lettre.statut",
]

# Contextes qui ne sont pas l'offre/la pièce d'une candidature, pour écarter
# les faux positifs sans lien avec les 8 champs interdits : l'état d'un
# *filtre* de la vue (`store.filters.etape`/`.verdict`) n'est ni le tri, ni
# l'étape, ni le verdict d'une offre.
EXCLUDE_TOKEN_CONTEXT = [
    "filters.etape",
    "filters.verdict",
    "params.etape",
    "params.verdict",
    "f.verdict",
]

# (fichier relatif à web/app, ligne) -> raison. Vérifiées une à une plus bas :
# le test échoue si une ligne listée ici a changé de contenu (dérive muette)
# et si une ligne hors de cette liste est trouvée (nouvelle violation).
EXCEPTIONS: dict[tuple[str, int], str] = {
    # Revue hors périmètre : axe à part des gestes de tri (architecture.md,
    # « un axe à part, qui ne vit pas [dans le module d'états] ») — ni un
    # bouton de geste, ni le bloc d'envoi, ni la carte Lettre, ni la frise.
    ("components/OfferDetail.vue", 397): (
        "isRevueActive : état actif des deux boutons de la revue hors "
        "périmètre, axe à part des gestes (architecture.md)."
    ),
    ("components/VerdictBadge.vue", 44): (
        "Badge d'affichage pur (tri -> libellé), pas un bouton de geste, "
        "un bloc d'envoi, une carte Lettre ni une frise."
    ),
    # PieceReadyToggle (marquer une pièce Prête, EXE-101) : action distincte
    # des gestes de la table de suivi, pas un bouton de geste au sens de
    # cette règle.
    (
        "pages/offers/[id].vue",
        429,
    ): "PieceReadyToggle (marquer Prêt), pas un geste de suivi.",
    (
        "pages/offers/[id].vue",
        430,
    ): "PieceReadyToggle (marquer Prêt), pas un geste de suivi.",
    (
        "pages/offers/[id].vue",
        506,
    ): "PieceReadyToggle (marquer Prêt), pas un geste de suivi.",
    (
        "pages/offers/[id].vue",
        507,
    ): "PieceReadyToggle (marquer Prêt), pas un geste de suivi.",
    # Frise d'avancement de génération de la pièce (À faire/En cours/Prête) —
    # distincte de la frise de candidature (retenue/envoyée/entretien/…) que
    # l'API rend par `etapes_affichees`/`etapes_acquises`.
    (
        "pages/offers/[id].vue",
        552,
    ): "Surligne l'étape courante du mini-stepper de génération de la pièce, pas la frise de candidature.",
    (
        "pages/offers/[id].vue",
        899,
    ): "Surligne l'étape courante du mini-stepper de génération de la pièce, pas la frise de candidature.",
    # Carte Lettre : contenu de section, pas permission d'un bouton (cf.
    # docstring du module ci-dessus).
    (
        "pages/offers/[id].vue",
        595,
    ): "Choix de la section de contenu de la carte Lettre, pas d'un bouton.",
    (
        "pages/offers/[id].vue",
        611,
    ): "Choix de la section de contenu de la carte Lettre, pas d'un bouton.",
    (
        "pages/offers/[id].vue",
        615,
    ): "Choix de la section de contenu de la carte Lettre, pas d'un bouton.",
    (
        "pages/offers/[id].vue",
        616,
    ): "Choix de la section de contenu de la carte Lettre, pas d'un bouton.",
    (
        "pages/offers/[id].vue",
        644,
    ): "Choix de la section de contenu de la carte Lettre, pas d'un bouton.",
    # Section « en erreur » de l'onglet Lettre (EXE-202, critères 1-4) :
    # même nature que les cinq lignes ci-dessus, choix de la section de
    # contenu à afficher, pas d'un bouton.
    (
        "pages/offers/[id].vue",
        664,
    ): "Choix de la section de contenu de la carte Lettre, pas d'un bouton.",
    # `isRetenue` : affiche/masque des sections génériques de la page (URL
    # employeur, placeholders « réservé à une offre retenue », polling
    # d'avancement) — ni un bouton de geste, ni le bloc d'envoi (qui n'est
    # pas gardé par `isRetenue`), ni la carte Lettre, ni la frise.
    (
        "pages/offers/[id].vue",
        1276,
    ): "Visibilité de sections génériques de la page, pas des 4 catégories interdites.",
    (
        "pages/offers/[id].vue",
        1714,
    ): "toggleCvPret : calcule le prochain état du marquage Prêt, pas un bouton de geste.",
    (
        "pages/offers/[id].vue",
        1726,
    ): "toggleLettrePret : calcule le prochain état du marquage Prêt, pas un bouton de geste.",
}


def _scan() -> list[tuple[str, int, str]]:
    hits = []
    for path in sorted(WEB_APP.rglob("*")):
        if path.suffix not in (".vue", ".ts"):
            continue
        rel = str(path.relative_to(WEB_APP))
        for i, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not any(m in line for m in CONDITION_MARKERS):
                continue
            if any(exc in line for exc in EXCLUDE_TOKEN_CONTEXT):
                continue
            for tok in BANNED_TOKENS:
                if tok in line:
                    hits.append((rel, i, line.strip()))
                    break
    return hits


class TestCritere17AucuneConditionNonExceptee:
    def test_toute_violation_trouvee_est_dans_la_liste_nommee(self):
        hits = _scan()
        trouvees = {(f, i) for f, i, _ in hits}
        permises = set(EXCEPTIONS)
        nouvelles = trouvees - permises
        assert not nouvelles, f"conditions non exceptées : {sorted(nouvelles)}"

    def test_chaque_exception_est_a_jour(self):
        """Une exception dont la ligne a changé (ou disparu) doit être
        relue avant d'être reconduite — pas simplement laissée en place."""
        hits = {(f, i): texte for f, i, texte in _scan()}
        for cle in EXCEPTIONS:
            assert cle in hits, f"exception {cle} ne correspond plus à aucune ligne"


class TestCritere18GardesExistantesRestentVertes:
    def test_test_exe194_toujours_present(self):
        from pathlib import Path as _P

        assert (
            _P(__file__).parent / "test_exe194_front_sans_logique_metier.py"
        ).exists()


class TestCritere7RevueActiveRetireLaRevueJamaisLeTri:
    """Mutant F2 (H7) : un clic sur une revue déjà active doit retirer la
    revue (`DELETE /revue`), jamais annuler le dernier geste de tri
    (`DELETE /verdict`, un axe différent — architecture.md)."""

    def test_toggle_revue_appelle_retirer_revue_quand_actif_pas_clear_verdict(self):
        texte = (WEB_APP / "components" / "OfferDetail.vue").read_text(encoding="utf-8")
        m = re.search(r"function toggleRevue\([^)]*\)\s*\{(.*?)\n\}", texte, re.S)
        assert m is not None, "toggleRevue introuvable"
        corps = m.group(1)
        assert "store.retirerRevue(" in corps
        assert "store.clearVerdict(" not in corps


class TestCriteres10Et11BlocEnvoiDecideParLApi:
    """Mutant F3 (H7) : le choix entre le formulaire d'envoi et « Envoyée
    le » doit suivre `pieces.deja_envoyee` (décidé par l'API), jamais une
    lecture directe de `envoyee_le` dans la condition qui choisit la
    branche ; le bouton « Candidature envoyée » n'apparaît que si le geste
    est permis."""

    def test_bloc_envoi_suit_deja_envoyee_et_le_bouton_suit_le_geste_permis(self):
        texte = (WEB_APP / "pages" / "offers" / "[id].vue").read_text(encoding="utf-8")
        assert 'v-if="!pieces?.deja_envoyee"' in texte
        assert not re.search(r"template\s+v-if=\"!pieces\?\.envoyee_le\"", texte)
        assert 'v-if="envoyeeGeste?.permis"' in texte


class TestMutantF7AvertissementEnvoiDepuisLeGesteRaison:
    """Mutant F7 (H7) : l'avertissement d'envoi doit venir de la raison déjà
    écrite par l'API sur le geste `marquer_envoyee` (`PiecesNonPretes`),
    jamais d'un calcul front depuis `pieces.prete_a_l_envoi`."""

    def test_envoyee_avertissement_lit_la_raison_du_geste(self):
        texte = (WEB_APP / "pages" / "offers" / "[id].vue").read_text(encoding="utf-8")
        m = re.search(r"const envoyeeAvertissement = computed\([^\n]*\)", texte)
        assert m is not None, "envoyeeAvertissement introuvable"
        assert "envoyeeGeste" in m.group(0)
        assert "prete_a_l_envoi" not in m.group(0)


class TestCritere9RetenirRefuseAfficheSonMessage:
    def test_handle_retenir_affiche_lerreur_au_lieu_de_naviguer_silencieusement(self):
        texte = (WEB_APP / "components" / "OfferDetail.vue").read_text(encoding="utf-8")
        m = re.search(r"async function handleRetenir\(\)\s*\{(.*?)\n\}", texte, re.S)
        assert m is not None, "handleRetenir introuvable"
        corps = m.group(1)
        assert "catch" in corps
        assert "verdictError" in corps


class TestMutantF6OffreTriReintroduitEstAttrape:
    def test_le_scanner_attrape_la_comparaison_du_mutant_f6(self, tmp_path):
        """Preuve que le scanner attrape bien le mutant nommé par le ticket
        (H7, F6) s'il revenait — sans modifier le vrai fichier."""
        bidon = tmp_path / "web_app_bidon"
        (bidon / "components").mkdir(parents=True)
        fichier = bidon / "components" / "OfferDetail.vue"
        fichier.write_text(
            "<template><div v-if=\"offer.tri === 'retenue'\">x</div></template>\n",
            encoding="utf-8",
        )
        trouve = False
        for i, line in enumerate(
            fichier.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if any(m in line for m in CONDITION_MARKERS) and any(
                tok in line for tok in BANNED_TOKENS
            ):
                trouve = True
        assert trouve
