"""Test EXE-194, critère 23 — un fichier du front ne recalcule plus le
libellé d'un bouton ou l'acquis d'une frise à partir du tri/de l'étape d'une
offre : il lit la décision déjà rendue par l'API (`gestes`, `tri`, `etape`,
`etapes_acquises`, `revue_hors_perimetre`). Portée ciblée sur les deux défauts
nommés par le Problème et les mutants H7 N1/N6 (bouton Retenir/Voir la page,
frise d'une offre abandonnée) : un lint général sur toute comparaison de tri
dans web/ casserait des usages pré-existants et non visés par ce ticket
(`isRetenue`, les `v-if` de visibilité) — lu ainsi par le chat, déclaré dans
l'entrée Journal."""

import re
from pathlib import Path

WEB_APP = Path(__file__).resolve().parent.parent / "web" / "app"

OFFER_DETAIL = WEB_APP / "components" / "OfferDetail.vue"
OFFER_PAGE = WEB_APP / "pages" / "offers" / "[id].vue"
VERDICT_BADGE = WEB_APP / "components" / "VerdictBadge.vue"


class TestCritere23EtMutantN1BoutonRetenirNeComparePlusLeTri:
    def test_offer_detail_ne_choisit_plus_le_libelle_par_comparaison_du_tri(self):
        texte = OFFER_DETAIL.read_text(encoding="utf-8")
        # Mutant N1 (H7) : « un composant du front choisit le libellé d'un
        # bouton par une comparaison du tri d'une offre à "retenue" ».
        assert not re.search(r"tri\s*===\s*'retenue'\s*\?", texte)
        # Le choix passe par la décision que l'API a déjà rendue.
        assert "gestes_permis.includes('retenir')" in texte


class TestCritere23EtMutantN6FriseNeComputePlusDepuisLetape:
    def test_page_offre_ne_recalcule_plus_lacquis_depuis_la_sequence(self):
        texte = OFFER_PAGE.read_text(encoding="utf-8")
        # Ancien calcul fautif (H2 du ticket) : une étape hors séquence
        # rendait toute la frise acquise.
        assert "idxEtape" not in texte
        assert "sequence.indexOf(etape)" not in texte
        # La frise lit l'acquis que l'API a déjà résolu (critère 22).
        assert "etapes_acquises" in texte


class TestCritere21VerdictBadgeNeFusionnePlusTriEtRevue:
    def test_verdict_badge_ne_prend_plus_un_prop_verdict_fusionne(self):
        texte = VERDICT_BADGE.read_text(encoding="utf-8")
        # L'ancien prop unique masquait le tri derrière la revue hors
        # périmètre (H2 du ticket) ; les deux axes sont désormais distincts.
        assert not re.search(r"defineProps<\{\s*verdict\s*:", texte)
        assert "tri: string" in texte
        assert "revue" in texte
