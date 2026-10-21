"""Tests EXE-193 — la table des états du suivi des candidatures, en Python pur
(critères 1-7). Aucun accès disque, aucune base : `orchestrator.job_search.suivi.etats`
n'importe ni fastapi ni sqlite3 (critère 28)."""

import pytest

from orchestrator.job_search.suivi import etats

# Table H4 du ticket : (etat_depart, geste, etat_arrivee)
TRANSITIONS_ATTENDUES = [
    (etats.A_TRIER, etats.RETENIR, etats.RETENUE),
    (etats.A_TRIER, etats.ECARTER, etats.ECARTEE),
    (etats.ECARTEE, etats.REMETTRE_A_TRIER, etats.A_TRIER),
    (etats.RETENUE, etats.MARQUER_ENVOYEE, etats.CANDIDATURE_ENVOYEE),
    (etats.RETENUE, etats.ABANDONNER, etats.ABANDONNEE),
    (etats.CANDIDATURE_ENVOYEE, etats.RELANCER, etats.CANDIDATURE_ENVOYEE),
    (etats.CANDIDATURE_ENVOYEE, etats.ENTRETIEN_GESTE, etats.ENTRETIEN),
    (etats.CANDIDATURE_ENVOYEE, etats.REFUSER, etats.REFUSEE),
    (etats.CANDIDATURE_ENVOYEE, etats.SANS_SUITE_GESTE, etats.SANS_SUITE),
    (etats.CANDIDATURE_ENVOYEE, etats.ABANDONNER, etats.ABANDONNEE),
    (etats.ENTRETIEN, etats.ENTRETIEN_GESTE, etats.ENTRETIEN),
    (etats.ENTRETIEN, etats.RELANCER, etats.ENTRETIEN),
    (etats.ENTRETIEN, etats.OFFRE_RECUE_GESTE, etats.OFFRE_RECUE),
    (etats.ENTRETIEN, etats.REFUSER, etats.REFUSEE),
    (etats.ENTRETIEN, etats.SANS_SUITE_GESTE, etats.SANS_SUITE),
    (etats.ENTRETIEN, etats.ABANDONNER, etats.ABANDONNEE),
]

TERMINAUX = [etats.OFFRE_RECUE, etats.REFUSEE, etats.SANS_SUITE, etats.ABANDONNEE]


class TestCritere1TableDesTransitions:
    @pytest.mark.parametrize("etat_depart,geste,etat_arrivee", TRANSITIONS_ATTENDUES)
    def test_chaque_ligne_mene_au_bon_etat(self, etat_depart, geste, etat_arrivee):
        assert (
            etats.appliquer(etat_depart, geste, cv_pret=True, lettre_pret=True)
            == etat_arrivee
        )


class TestCritere2GesteAbsentRefuse:
    @pytest.mark.parametrize(
        "etat,geste",
        [
            (etats.A_TRIER, etats.MARQUER_ENVOYEE),
            (etats.A_TRIER, etats.ABANDONNER),
            (etats.ECARTEE, etats.RETENIR),
            (etats.RETENUE, etats.RETENIR),
            (etats.RETENUE, etats.ECARTER),
            (etats.CANDIDATURE_ENVOYEE, etats.RETENIR),
            *[(t, g) for t in TERMINAUX for g in (etats.RELANCER, etats.ABANDONNER)],
        ],
    )
    def test_geste_hors_table_refuse_nomme_etat_et_geste(self, etat, geste):
        with pytest.raises(etats.GesteRefuse) as exc_info:
            etats.appliquer(etat, geste, cv_pret=True, lettre_pret=True)
        message = str(exc_info.value)
        # EXE-194, critère 20 : le message nomme l'état et le geste par leur
        # libellé, jamais par leur code interne (contredit par ce ticket le
        # choix du jet 45 — H4 du ticket).
        assert etats.LIBELLES_ETATS[etat] in message
        assert etats.LIBELLES_GESTES[geste] in message

    def test_gestes_permis_exclut_ce_qui_nest_pas_dans_la_table(self):
        assert etats.MARQUER_ENVOYEE not in etats.gestes_permis(etats.A_TRIER)
        assert etats.RETENIR not in etats.gestes_permis(etats.RETENUE)


class TestCritere5AnnulerSansHistoriqueNonPermis:
    def test_permis_annuler_faux_sans_evenement(self):
        assert etats.permis_annuler([]) is False

    def test_permis_annuler_faux_si_tout_est_annule(self):
        evt = etats.EvenementHistorique(
            id=1,
            geste=etats.RETENIR,
            etat_depart=etats.A_TRIER,
            etat_arrivee=etats.RETENUE,
            effet_at="2026-01-01",
            enregistre_at="2026-01-01",
            motif=None,
            annule_at="2026-01-02",
        )
        assert etats.permis_annuler([evt]) is False

    def test_permis_annuler_vrai_si_un_evenement_non_annule(self):
        evt = etats.EvenementHistorique(
            id=1,
            geste=etats.RETENIR,
            etat_depart=etats.A_TRIER,
            etat_arrivee=etats.RETENUE,
            effet_at="2026-01-01",
            enregistre_at="2026-01-01",
            motif=None,
            annule_at=None,
        )
        assert etats.permis_annuler([evt]) is True


class TestCritere6PreteALEnvoiDerivee:
    def test_retenue_sans_pieces_pretes_reste_retenue(self):
        assert (
            etats.etape_affichee(etats.RETENUE, cv_pret=False, lettre_pret=True)
            == etats.RETENUE
        )
        assert (
            etats.etape_affichee(etats.RETENUE, cv_pret=True, lettre_pret=False)
            == etats.RETENUE
        )

    def test_retenue_avec_les_deux_pieces_pretes_devient_prete_a_lenvoi(self):
        assert (
            etats.etape_affichee(etats.RETENUE, cv_pret=True, lettre_pret=True)
            == etats.PRETE_A_L_ENVOI
        )

    def test_a_trier_et_ecartee_nont_pas_detape(self):
        assert (
            etats.etape_affichee(etats.A_TRIER, cv_pret=True, lettre_pret=True) is None
        )
        assert (
            etats.etape_affichee(etats.ECARTEE, cv_pret=True, lettre_pret=True) is None
        )

    def test_etape_posterieure_a_la_candidature_envoyee_passe_telle_quelle(self):
        assert (
            etats.etape_affichee(etats.ENTRETIEN, cv_pret=False, lettre_pret=False)
            == etats.ENTRETIEN
        )


class TestCritere7MarquerEnvoyeeGatePieces:
    def test_refuse_si_cv_et_lettre_pas_prets(self):
        with pytest.raises(etats.PiecesNonPretes) as exc_info:
            etats.appliquer(
                etats.RETENUE, etats.MARQUER_ENVOYEE, cv_pret=False, lettre_pret=False
            )
        assert "Le CV et la lettre ne sont pas prêts" in str(exc_info.value)

    def test_refuse_si_seul_le_cv_manque(self):
        with pytest.raises(etats.PiecesNonPretes) as exc_info:
            etats.appliquer(
                etats.RETENUE, etats.MARQUER_ENVOYEE, cv_pret=False, lettre_pret=True
            )
        assert "Le CV n'est pas prêt" in str(exc_info.value)

    def test_refuse_si_seule_la_lettre_manque(self):
        with pytest.raises(etats.PiecesNonPretes) as exc_info:
            etats.appliquer(
                etats.RETENUE, etats.MARQUER_ENVOYEE, cv_pret=True, lettre_pret=False
            )
        assert "La lettre n'est pas prête" in str(exc_info.value)

    def test_permet_si_les_deux_pieces_sont_pretes(self):
        assert (
            etats.appliquer(
                etats.RETENUE, etats.MARQUER_ENVOYEE, cv_pret=True, lettre_pret=True
            )
            == etats.CANDIDATURE_ENVOYEE
        )


class TestNoImportFastapiOuSqlite3:
    def test_module_etats_nimporte_ni_fastapi_ni_sqlite3(self):
        import ast
        import inspect

        source = inspect.getsource(etats)
        tree = ast.parse(source)
        noms_importes = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                noms_importes.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                noms_importes.add(node.module)
        assert not any("fastapi" in n or "sqlite3" in n for n in noms_importes)
