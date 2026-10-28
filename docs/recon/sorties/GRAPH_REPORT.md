# Graph Report - exe-203  (2026-10-28)

## Corpus Check
- 314 files · ~328,489 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 7 file(s) not represented in the graph (top: (none) 3, .example 1, .toml 1)

## Summary
- 6436 nodes · 15888 edges · 242 communities (202 shown, 40 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 914 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `cfc1d41b`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [id].vue
- cv.py
- load_profile
- etats.py
- get_conn
- sqlite3
- test_exe184_cv_profil_claude.py
- storage.py
- test_exe158_juge_ressenti_recruteur.py
- boucle.py
- SkillGroup
- test_exe101_statut_piece.py
- canonicalize
- test_exe174_trace_lettre.py
- test_exe151_jeu_banc_lettre.py
- json
- test_exe162_boucle_app.py
- apply_hard_filters
- test_exe99_cascade_extraction.py
- banc.py
- AjoutNotifications.vue
- test_exe175_interprete_lettre_mieux_jugee.py
- test_exe171_angle_lettre.py
- test_exe164_forem.py
- ResultatBoucle
- JobOffer
- lettre/service.py
- test_exe202_navigateur.py
- get_offer
- test_exe147_boucle_lettre.py
- test_exe173_regenerer_depuis_ma_lettre.py
- test_exe167_avancement_lettre.py
- test_exe201_corrections_jet46.py
- test_exe200_api_decisions.py
- schemas.py
- test_exe195_decision_lettre.py
- init_db
- Export — 48 offre(s)
- save_offer
- test_exe198_suite_candidature.py
- offers.ts
- test_exe100_gemma_lots.py
- aliases
- test_exe148_banc_lettre.py
- test_exe194_suivi_candidat.py
- test_exe176_mail_depuis_lettre.py
- main
- run_lettre
- test_exe183_cv_anglais.py
- mail.py
- test_ajout_exe79.py
- test_exe160_verificateur_lettre.py
- test_cv_corrections.py
- test_exe193_api_suivi.py
- chargerPieces
- test_exe102_pdf_pieces.py
- test_exe176_lettre_pdf_entreprise.py
- example.yaml
- charger_repertoire
- test_exe161_fiche_sujets_lettre.py
- test_exe199_suivi_candidatures.py
- extractor.py
- derive_hors_perimetre
- test_exe98_extraction_retry.py
- test_ajout_exe82.py
- test_exe197_marquer_envoyee_datee.py
- OfferDetail.vue
- datetime
- test_exe139_candidature_envoyee.py
- manual.py
- test_exe155_redaction_lit_annonce.py
- api/avancement.py
- CODEMAP — job-search
- traces.py
- test_cv_exe63.py
- ReponseModele
- html_to_markdown
- IndeedFileSource
- run_fiche
- test_cv_corrections_service.py
- test_exe132_points_pour_lettre.py
- test_exe169_juge_opus_jugement_versions.py
- test_exe196_sans_lettre_pret.py
- test_exe200_reprise_securite.py
- get_mail_candidature
- test_exe116_sans_techno_seconde_passe.py
- FranceTravailSource
- test_exe105_mlflow_tracking.py
- get_fiche
- Pipeline — contrat par étage
- CascadeResult
- test_exe107_reference_replay.py
- test_exe150_boucle_lettre_manques.py
- test_exe123_reference_api.py
- create_lettre
- repertoire.py
- test_cv_groupes.py
- ajouts.py
- test_exe153_cv_sans_style_script.py
- _insert_offer
- _insert_offer
- test_exe163_actiris.py
- test_exe144_etape_candidature.py
- reference.vue
- IMPLEMENTATION — Chantier HTML→Markdown : nettoyage dans l'adapter Remotive
- experiment_tck200.py
- test_cv_service.py
- pathlib
- OffersTable.vue
- CARTE FACTUELLE V2 — job-search
- ExtractedFacts
- test_exe127_cascade.py
- test_exe201_garde_front_generique.py
- IMPLEMENTATION — Vue candidat (4 onglets par intention)
- ingestion.py
- _insert_offer
- ExportPopover.vue
- IMPLEMENTATION — Chantier review humaine : vérité terrain + suppression scoring + UI sortie LLM
- filter_new
- fiche/prompt.py
- package.json
- traces.vue
- identify_employer
- IMPLEMENTATION — Chantier 2 : refonte du profil + catégorisation
- IMPLEMENTATION — Interface de pilotage (Zone A)
- test_exe117_texte_manquant_tous_chemins.py
- test_exe106_extraction_version_filter.py
- test_exe200_tests_manquants_exe193.py
- reference.py
- E1 — FastAPI app (`api/main.py`)
- Taxonomie des erreurs — 7 buckets
- experiment_tck206_cv.py
- VerdictIn
- test_human_reviews.py
- test_exe165_actiris_entites.py
- Écriture
- IMPLEMENTATION — job-search-zone-a
- experiment_tck206.py
- .test_adresse_sans_http_ou_https_n_est_pas_gardee
- test_exe193_reprise.py
- IMPLEMENTATION — Rituel de calibration humain↔IA
- IMPLEMENTATION — Vue opérateur (élagage onglets, verdicts HP, tri & filtres)
- TraceNoteIn
- CODEMAP — job-search
- IMPLEMENTATION — Chantier 1 : refacto du scoring (filtres durs + désirabilité graduée)
- IMPLEMENTATION — Chantier hors-périmètre : bucket dérivé pour offres non-IC-techniques
- filename.py
- re
- cvUrl
- _compute_avancement
- API FastAPI
- detect_ad_language
- IMPLEMENTATION — Chantier traces viewer : page /traces + notes + retrait du faux-juge
- IMPLEMENTATION — Lot G : Gates éliminatoires hors_perimetre (langue + contrat)
- IMPLEMENTATION — Page offre retenue (emplacements phase 2)
- compute_permitted_additions
- _insert_offer
- Instructions
- settings.json
- IMPLEMENTATION — Bouton "voir la trace" sur le side panel offre
- IMPLEMENTATION — Export contextuel d'offres pour LLM
- IMPLEMENTATION — Export contextuel d'offres pour LLM
- IMPLEMENTATION — Séparation avis IA / avis humain + staleness post-rescore
- reprise.py
- _derive_score_breakdown
- TestDispatchModeleLocal
- run_ajout
- Stack — détails et contraintes
- ficheUrl
- ._map
- job-search
- Invariants détectés
- base.py
- _FakeResponse
- test_exe193_perimetre_sql.py
- Phase 1 — Récupération des offres Indeed via MCP
- Schéma de base
- Orchestrateur — CLI run matinal
- IMPLEMENTATION — Cristallisation rules/pipeline.md
- HANDOFF — Remédiation job-search
- pieces_a_envoyer
- test_exe194_front_sans_logique_metier.py
- extractDetail
- job-search
- Offers — Endpoints principaux
- Schémas de données (Pydantic)
- Gate Report — Lot G : rétro-attribution hors_perimetre (langue + contrat)
- .test_chaque_piece_generee_une_seule_fois
- run_harness
- VerdictBadge.vue
- Étage 5 : Scoring (Python pur, 0 LLM)
- Enum — valeurs fermées
- Scoring — décisions de calibration
- Phases
- IMPLEMENTATION — Tri colonnes Contrat et Verdict
- IMPLEMENTATION — Tri par lieu : grouper les remote
- STATE — job-search
- NotificationToast.vue
- scripts
- Frontend — conventions projet
- Barème niveau techno — 10 paliers
- _fait_depuis_point
- Nuxt Minimal Starter
- marked
- db_path
- db_path
- carte_lettre_for_offer
- barre.sh
- _jamais_appele
- .test_migration_idempotente_sans_marquer_les_offres_existantes
- _run
- _SpySource
- no_real_sleep
- .test_get_connection_sans_setup_pointe_hors_de_data
- tsconfig.json
- quality-gate.md
- JOURNAL.md
- intermediaires.yaml
- vue_candidat.yaml
- preflight.sh
- conn
- conn

## God Nodes (most connected - your core abstractions)
1. `init_db()` - 232 edges
2. `JobOffer` - 158 edges
3. `get_conn()` - 105 edges
4. `appliquer_geste()` - 71 edges
5. `run_lettre()` - 62 edges
6. `save_offer()` - 61 edges
7. `main()` - 58 edges
8. `ExtractedFacts` - 57 edges
9. `ReponseModele` - 49 edges
10. `Export — 48 offre(s)` - 49 edges

## Surprising Connections (you probably didn't know these)
- `Maintenant` --references--> `get_conn()`  [INFERRED]
  .claude/state/STATE.md → api/db.py
- `Point d'entrée` --references--> `_migrate_db()`  [INFERRED]
  .claude/docs/CODEMAP.md → api/main.py
- `Phase 1 — Helper API + champ schema (L1–L3)` --references--> `_load_scoring_context()`  [INFERRED]
  .claude/state/_archive/IMPLEMENTATION/IMPLEMENTATION_justification_categorie.md → api/offers.py
- `Champs dérivés : ne jamais persister` --references--> `_derive_review_fields()`  [INFERRED]
  .claude/rules/frontend.md → api/offers.py
- `Livrables détaillés` --references--> `_derive_review_fields()`  [INFERRED]
  .claude/state/_archive/IMPLEMENTATION/IMPLEMENTATION_staleness_rescore.md → api/offers.py

## Import Cycles
- None detected.

## Communities (242 total, 40 thin omitted)

### Community 0 - "[id].vue"
Cohesion: 0.01
Nodes (122): activeCard, addingIntermediaire, ajoutChoix, ajoutReferenceEnCours, ajoutReferenceStatut, angleBusy, angleEdit, angleEditRef (+114 more)

### Community 1 - "cv.py"
Cohesion: 0.03
Nodes (70): correct_cv_skill(), create_cv(), create_cv_en(), CvTitreIn, delete_cv_titre_defaut(), _generate(), get_cv_corrections(), get_cv_titre_defaut() (+62 more)

### Community 2 - "load_profile"
Cohesion: 0.04
Nodes (55): build_view_clauses(), Phase 2 — Intégration pipeline + repositionnement gate (L4–L5), Décision de bifurcation (Phase 0), 5.4 Profil et alias : chargés indépendamment en 4 endroits, 6.1 Modules et fonctions non appelés en production, E1d — `GET /offers/{offer_id}`, E1i — `GET /export/offers`, E2 — Orchestrator run (`orchestrator/job_search/run.py`) (+47 more)

### Community 3 - "etats.py"
Cohesion: 0.03
Nodes (36): _historique_affiche_depuis_hist(), _message_ecarter_refuse(), _tout_telecharger(), prete_a_l_envoi(), appliquer(), aujourd_hui_bruxelles(), DateEffetFuture, etape_affichee() (+28 more)

### Community 4 - "get_conn"
Cohesion: 0.04
Nodes (52): get_conn(), _compute_scores_line(), export_calibration(), export_offers(), _format_export_md(), _format_techs(), _parse_facts_raw(), health() (+44 more)

### Community 5 - "sqlite3"
Cohesion: 0.04
Nodes (29): launch_pieces(), add_intermediaire(), AvisPatch, create_fiche(), explain_point(), launch_fiche(), _load_points(), patch_point() (+21 more)

### Community 6 - "test_exe184_cv_profil_claude.py"
Cohesion: 0.06
Nodes (39): CvProfilIn, get_cv(), put_cv_profil(), TestCritere7ApiCreeLesTablesAuDemarrage, cv_fixture_paths(), _cvs_row(), db_path(), _fake_result() (+31 more)

### Community 7 - "storage.py"
Cohesion: 0.06
Nodes (35): cv_statut(), decision_lettre(), lettre_statut(), annuler_dernier_geste(), appliquer_geste(), date_envoyee(), dernier_ecart(), effacer_revue_hors_perimetre() (+27 more)

### Community 8 - "test_exe158_juge_ressenti_recruteur.py"
Cohesion: 0.06
Nodes (66): dessiner_graphe(), main(), test_critere27_dessin_du_graphe_montre_les_trois_noeuds_et_le_retour_du_juge(), banc_dir(), cv_path(), _entree_jeu(), FakeModeles, _jeu() (+58 more)

### Community 9 - "boucle.py"
Cohesion: 0.05
Nodes (49): _affirmations_releve_txt(), Appel, _appeler_claude(), appeler_modele(), _appeler_ollama(), AppelModeleError, _bloc_angle_redaction(), _bloc_ce_qui_est_vrai_sur_moi() (+41 more)

### Community 10 - "SkillGroup"
Cohesion: 0.06
Nodes (30): build_prompt(), Addition, block_canonicals(), compute_au_cv(), compute_requested_missing(), detect_location(), filter_model_groups(), generate_cv_html() (+22 more)

### Community 11 - "test_exe101_statut_piece.py"
Cohesion: 0.07
Nodes (39): _check_retenue(), get_pieces(), MarquePretIn, _now(), _piece_payload(), set_cv_pret(), set_lettre_pret(), _connect() (+31 more)

### Community 12 - "canonicalize"
Cohesion: 0.04
Nodes (55): classify(), edit_distance(), load_profile_skills(), main(), `alias.yaml` (déjà rédigé et figé — à déposer, pas à concevoir), Calage sur l'existant (note de reconnaissance — à REVÉRIFIER ligne à ligne en Phase 0), Décisions de cadrage (prises en chat, gravées ici), Dépendances critiques (+47 more)

### Community 13 - "test_exe174_trace_lettre.py"
Cohesion: 0.06
Nodes (44): _cout_total(), get_lettre_version_appels(), get_lettre_versions(), _experiment_id(), tracer_generation(), _artifact_root_for(), _isolate_db_path(), _isolate_mail_gabarit_paths() (+36 more)

### Community 14 - "test_exe151_jeu_banc_lettre.py"
Cohesion: 0.07
Nodes (50): _fmt_cout(), JeuExistantError, OffreJeuResolue, preparer_jeu(), _preparer_une_offre(), _resoudre_offre_pour_jeu(), ResultatPreparation, banc_dir() (+42 more)

### Community 15 - "json"
Cohesion: 0.06
Nodes (37): _points_avec_libelle(), _row_to_fiche(), _fait_retenu(), _fetch_fiche_points(), _fetch_stored_choice(), _fiche_statut_et_points(), _generate(), get_lettre_points() (+29 more)

### Community 16 - "test_exe162_boucle_app.py"
Cohesion: 0.07
Nodes (36): FaitEcarteIn, get_lettre(), remettre_fait(), _drain(), _insert_fiche(), _insert_offer(), _jugement(), _lettre_entry() (+28 more)

### Community 17 - "apply_hard_filters"
Cohesion: 0.06
Nodes (52): API — nouveaux query params sur `GET /offers` (`api/offers.py`), Dépendances critiques, Garde-fous, IMPLEMENTATION — TCK-162 Vue candidat — filtre géographique profil de vue, Livrables détaillés, Phase 1 — Back : profil de vue + filtre SQL, Phase 2 — Front : commandes candidat + fermeture fuite, Phases (+44 more)

### Community 18 - "test_exe99_cascade_extraction.py"
Cohesion: 0.06
Nodes (38): resolve_category_second_pass(), run_tri(), alias_table(), cascade(), _extract(), db_path(), _get_id(), loaded_profile() (+30 more)

### Community 19 - "banc.py"
Cohesion: 0.06
Nodes (38): _annexe_passage(), charger_jeu(), ConfigNommee, ConfigurationInvalideError, construire_rapport(), _cout_total(), _ecart_txt(), _ecrire_rapport() (+30 more)

### Community 20 - "AjoutNotifications.vue"
Cohesion: 0.05
Nodes (46): pinia, ajouts, form, texteInput, titreInput, urlInput, vide, ajouts (+38 more)

### Community 21 - "test_exe175_interprete_lettre_mieux_jugee.py"
Cohesion: 0.08
Nodes (49): valider_interprete(), _config(), _conn(), cv_path(), db_path(), db_path_service(), FakeModeles, FakeModelesBanc (+41 more)

### Community 22 - "test_exe171_angle_lettre.py"
Cohesion: 0.06
Nodes (38): LettreAngleIn, put_lettre_angle(), generer_lettre_depuis_donnees(), normaliser_angle(), raison_angle_trop_long(), save_angle(), _config(), cv_path() (+30 more)

### Community 23 - "test_exe164_forem.py"
Cohesion: 0.08
Nodes (36): ForemSource, _strip_gender_suffix(), db_path(), _detail(), _fake_requests(), fake_get(), _FakeResponse, no_real_sleep() (+28 more)

### Community 24 - "ResultatBoucle"
Cohesion: 0.07
Nodes (33): LettreTexteIn, put_lettre_texte(), Jugement, ResultatBoucle, _resultat_lettre(), _lettre_behavior(), _resultat_lettre_ok(), TestCritere12ReprisePdfMailFonctionnentSurLaBoucle (+25 more)

### Community 25 - "JobOffer"
Cohesion: 0.04
Nodes (35): CONSOMME, INTERDITS, INVARIANTS, PRODUIT, Étage 1 — Fetch (sources pluggables → JobOffer), Phase 1 — Rédaction de `.claude/rules/pipeline.md` (contrat 6 étages + invariants transversaux), Dépendances critiques, Garde-fous (+27 more)

### Community 26 - "lettre/service.py"
Cohesion: 0.06
Nodes (30): count_words(), exceeds_length(), load_tournures_interdites(), ajouter_fait_ecarte(), AngleTropLongError, _append_version(), _cle_fait(), _config_boucle() (+22 more)

### Community 27 - "test_exe202_navigateur.py"
Cohesion: 0.08
Nodes (27): _assert_pas_editeur_ni_regenerer(), _badge_lettre(), db_path(), _free_port(), front_url(), _historique_longueur(), _insert_fiche(), _insert_lettre() (+19 more)

### Community 28 - "get_offer"
Cohesion: 0.10
Nodes (30): check_expirations(), set_employer_url(), get_offer(), EmployerUrlIn, _fake_get(), fake_get(), _FakeResponse, _insert_offer() (+22 more)

### Community 29 - "test_exe147_boucle_lettre.py"
Cohesion: 0.08
Nodes (42): _config(), _conn(), cv_path(), db_path(), FakeModeles, _juge_remarques(), _lancer(), modeles() (+34 more)

### Community 30 - "test_exe173_regenerer_depuis_ma_lettre.py"
Cohesion: 0.06
Nodes (36): _config(), cv_path(), db_path(), _drain(), FakeModeles, _insert_fiche(), _insert_offer(), _lancer() (+28 more)

### Community 31 - "test_exe167_avancement_lettre.py"
Cohesion: 0.06
Nodes (26): ProgressionLettre, _config(), cv_path(), db_path(), FakeModeles, _generer_lettre_prete(), _insert_fiche(), _insert_offer() (+18 more)

### Community 32 - "test_exe201_corrections_jet46.py"
Cohesion: 0.06
Nodes (29): _bouton(), carte_lettre(), client(), db_path(), _drain(), _fiche_statut(), _geste(), _insert_fiche() (+21 more)

### Community 33 - "test_exe200_api_decisions.py"
Cohesion: 0.07
Nodes (24): _list_recent(), main(), _record_verdict(), client(), db_path(), _insert_offer(), _marquer_pieces_pretes(), _marquer_revue() (+16 more)

### Community 34 - "schemas.py"
Cohesion: 0.07
Nodes (27): _parse_expiration_checks(), _parse_facts(), CategoryReviewIn, CheckExpirationsIn, EvenementHistoriqueOut, ExpirationCheckSchema, ExtractedFactsSchema, GesteEtatSchema (+19 more)

### Community 35 - "test_exe195_decision_lettre.py"
Cohesion: 0.08
Nodes (32): ne_pas_faire_lettre(), revenir_sur_choix_lettre(), _creer_base_avant_exe195(), db_path(), _drain(), _fiche_statut(), _insert_fiche(), _insert_lettre() (+24 more)

### Community 36 - "init_db"
Cohesion: 0.06
Nodes (25): backfill(), backfill(), Schéma DB, Corrections après essai (post-livraison, 2026-09-28), main(), _fichier_source(), init_db(), migrate_ajouts_schema() (+17 more)

### Community 37 - "Export — 48 offre(s)"
Cohesion: 0.04
Nodes (49): AI Developer Technology Engineer — NVIDIA, AI Engineer — Remofirst, AI Engineer — SFEIR, AI Skills Engineer — QuadCode, AI Voice Data Trainer - Record From Home - French — Voices.com, Alternance Chargé de Data visualisation - Achenheim (F/H) (H/F), Alternance - Data Analyst (H/F), ANALYSTE DÉVELOPPEUR BI (H/F) — Randstad professional (+41 more)

### Community 38 - "save_offer"
Cohesion: 0.10
Nodes (31): _format_offer(), generate_digest(), process_offer(), rattraper_offres_categorisees_sans_texte(), Category, get_offers_since(), save_offer(), StoredOffer (+23 more)

### Community 39 - "test_exe198_suite_candidature.py"
Cohesion: 0.09
Nodes (22): client(), _connect(), db_path(), _en_candidature_envoyee(), _en_entretien(), _figer_horloge(), _geste(), _insert_offer() (+14 more)

### Community 40 - "offers.ts"
Cohesion: 0.05
Nodes (38): CANDIDATE_VIEWS, config, route, router, store, config, store, VIEWS (+30 more)

### Community 41 - "test_exe100_gemma_lots.py"
Cohesion: 0.09
Nodes (31): _second_pass_batches(), run(), alias_table(), cascade(), _extract(), db_path(), _entry(), _get_id() (+23 more)

### Community 42 - "aliases"
Cohesion: 0.04
Nodes (44): aliases, agents, aspnet, azure_ad, azure_ai_foundry, azure_devops, azure_openai, ci_cd (+36 more)

### Community 43 - "test_exe148_banc_lettre.py"
Cohesion: 0.11
Nodes (30): banc_dir(), cv_path(), _entree_jeu(), FakeModeles, _jeu(), _lancer(), modeles(), _programmer_passage_simple() (+22 more)

### Community 44 - "test_exe194_suivi_candidat.py"
Cohesion: 0.07
Nodes (20): client(), db_path(), _insert_offer(), _marquer_pieces_pretes(), _no_real_cascade(), TestCritere10RemettreATrierRevientDansLaVue, TestCritere11OffreRepriseSansMotifADateDeLAncienVerdict, TestCritere13VueOperateurGardeTout (+12 more)

### Community 45 - "test_exe176_mail_depuis_lettre.py"
Cohesion: 0.10
Nodes (27): get_mail_appel(), consigne_path(), coordonnees_path(), db_path(), _fake_result(), gabarit_path(), _generer(), _insert_lettre_done() (+19 more)

### Community 46 - "main"
Cohesion: 0.07
Nodes (15): replay_jeu(), _write_report(), main(), _resolve_second_pass_entry(), _SecondPassEntry, _SecondPassReport, _tri_phase(), _TriPhaseReport (+7 more)

### Community 47 - "run_lettre"
Cohesion: 0.13
Nodes (23): run_lettre(), _insert_fiche(), _insert_offer(), _jamais(), _lettre_row(), _marquer_demandee(), _resultat_ok(), TestCritere1DefautSonnet (+15 more)

### Community 48 - "test_exe183_cv_anglais.py"
Cohesion: 0.10
Nodes (21): cv_fixture_paths(), _cvs_row(), db_path(), _fake_result(), _insert_offer(), _make_query(), _query(), _run_cv() (+13 more)

### Community 49 - "mail.py"
Cohesion: 0.09
Nodes (21): _check_retenu(), MailIn, _offer_entreprise_intitule(), post_mail_generer(), put_mail_candidature(), _appeler_modele(), build_prompt(), ConsigneAbsenteError (+13 more)

### Community 50 - "test_ajout_exe79.py"
Cohesion: 0.11
Nodes (30): _ajouter(), _classement(), _count_offers(), db_path(), extraction(), _FakeResponse, _insert_ajout(), _job_posting() (+22 more)

### Community 51 - "test_exe160_verificateur_lettre.py"
Cohesion: 0.11
Nodes (34): banc_dir(), _config(), _conn(), cv_path(), db_path(), FakeModeles, _jeu_simple(), jeux_dir() (+26 more)

### Community 52 - "test_cv_corrections.py"
Cohesion: 0.12
Nodes (17): add_skill(), _all_items_lower(), CorrectionOutcome, remove_skill(), SkillAlreadyPresentError, SkillNotFoundError, UnknownGroupError, _groupes() (+9 more)

### Community 53 - "test_exe193_api_suivi.py"
Cohesion: 0.09
Nodes (16): client(), db_path(), _insert_offer(), _mark_pieces_pretes(), _no_real_cascade(), _now(), TestCritere12ListeEtDetailRendentTriEtapeEtGestes, TestCritere13ChaqueGesteDeLaTableSappliqueParLApi (+8 more)

### Community 54 - "chargerPieces"
Cohesion: 0.10
Nodes (39): actionLettreCarte(), annulerEnvoyee(), chargerAppelsVersion(), chargerAvancement(), chargerLettre(), chargerLettreMiseEnPage(), chargerLettreVersions(), chargerMail() (+31 more)

### Community 55 - "test_exe102_pdf_pieces.py"
Cohesion: 0.11
Nodes (21): get_lettre_pdf(), coordonnees_path(), cv_fixture_paths(), db_path(), _insert_cv_done(), _insert_fiche(), _insert_lettre_done(), intermediaires_path() (+13 more)

### Community 56 - "test_exe176_lettre_pdf_entreprise.py"
Cohesion: 0.09
Nodes (16): build_lettre_html(), format_date_fr(), _paragraphs(), ville_sans_departement(), coordonnees_path(), db_path(), _insert_fiche(), _insert_lettre_done() (+8 more)

### Community 57 - "example.yaml"
Cohesion: 0.05
Nodes (37): dept, insee, keywords, desire, level, desire, level, desire (+29 more)

### Community 58 - "charger_repertoire"
Cohesion: 0.17
Nodes (26): charger_repertoire(), main(), RepertoireError, sujet_libelle(), _valider_textes_types(), _ecrire(), _repertoire_bien_forme(), test_aucun_texte_type_generique() (+18 more)

### Community 59 - "test_exe161_fiche_sujets_lettre.py"
Cohesion: 0.14
Nodes (19): _cascade(), _ecrire_repertoire(), _fiche_result(), _fiche_row(), _insert_fiche_ancienne(), _insert_offer(), _make_query(), _offer_row() (+11 more)

### Community 60 - "test_exe199_suivi_candidatures.py"
Cohesion: 0.12
Nodes (15): client(), db_path(), _figer_horloge(), _geste(), _insert_offer(), _no_real_cascade(), _retenir(), TestCritere11ChampsEtComptesRendusParLApi (+7 more)

### Community 61 - "extractor.py"
Cohesion: 0.11
Nodes (23): Calage sur l'existant (à vérifier en Phase 0 — NON négociable), Dépendances critiques, Fichier de traces, Garde-fous, IMPLEMENTATION — Chantier traces LLM : instrumentation de `extract_facts`, Livrables détaillés, Phase 0 — Lecture du code réel (0 écriture), Phase 1 — Schéma + helper d'écriture (testés isolément, AVANT de toucher extract_facts) (+15 more)

### Community 62 - "derive_hors_perimetre"
Cohesion: 0.12
Nodes (9): Phase 1 — Modèle de données + migration (L1–L3), derive_hors_perimetre(), HorsPerimetreCause, _facts(), TestContrat, TestCumul, TestMgmtRole, TestNonRegression (+1 more)

### Community 63 - "test_exe98_extraction_retry.py"
Cohesion: 0.15
Nodes (27): extract_and_score(), register_offer(), alias_table(), _by_source_id(), db_path(), fake_extract(), _get_id(), _insert_legacy_offer() (+19 more)

### Community 64 - "test_ajout_exe82.py"
Cohesion: 0.12
Nodes (25): _ajouter(), db_path(), _FakeResponse, _kinds(), _offers(), _offre_de_source(), ollama_double(), page() (+17 more)

### Community 65 - "test_exe197_marquer_envoyee_datee.py"
Cohesion: 0.11
Nodes (19): client(), _connect(), db_path(), _figer_horloge(), _insert_cv(), _insert_lettre(), _insert_offer(), _no_real_cascade() (+11 more)

### Community 66 - "OfferDetail.vue"
Cohesion: 0.06
Nodes (26): annulerGeste, CATEGORIES, CATEGORY_LABELS, ecarterBusy, ecarterError, etatClass, etatLabel, HP_VERDICTS (+18 more)

### Community 67 - "datetime"
Cohesion: 0.12
Nodes (11): DECISIONS — job-search-zone-a, _collapse_spaces(), _strip_tags(), Source, _best_description(), _location_from_map(), fingerprint(), _normalize() (+3 more)

### Community 68 - "test_exe139_candidature_envoyee.py"
Cohesion: 0.14
Nodes (16): MarqueEnvoyeeIn, set_envoyee(), valider_effet_at_optionnel(), _connect(), _insert_cv(), _insert_lettre(), _insert_offer(), _marquer_envoyee_geste() (+8 more)

### Community 69 - "manual.py"
Cohesion: 0.10
Nodes (16): _address_label(), _company(), _employment_types(), fetch_html(), find_job_posting(), _full_time(), _is_job_posting(), _is_remote() (+8 more)

### Community 70 - "test_exe155_redaction_lit_annonce.py"
Cohesion: 0.12
Nodes (29): banc_dir(), _conn(), cv_path(), db_path(), _entree_jeu(), FakeModeles, _jeu(), _juge_remarques() (+21 more)

### Community 71 - "api/avancement.py"
Cohesion: 0.10
Nodes (16): _mail_avancement(), _etat(), generation_avancement(), lettre_avancement(), mail_avancement(), GabaritAbsentError, load_gabarit(), load_gabarit_sans_lettre() (+8 more)

### Community 72 - "CODEMAP — job-search"
Cohesion: 0.06
Nodes (33): Alias & canonicalisation, API FastAPI, Calibration & désaccord, Catégorisation, CODEMAP — job-search, Composants, Config, Digest (+25 more)

### Community 73 - "traces.py"
Cohesion: 0.11
Nodes (14): TraceOut, TraceParsedFacts, TraceVersionCount, export_traces_jsonl(), _fetch_annotations(), get_traces_counts(), get_traces_versions(), list_traces() (+6 more)

### Community 74 - "test_cv_exe63.py"
Cohesion: 0.09
Nodes (18): clean_title(), cv_fixture_paths(), _cvs_row(), db_path(), _fake_result(), _insert_offer(), _make_query(), _query() (+10 more)

### Community 75 - "ReponseModele"
Cohesion: 0.09
Nodes (19): ConfigBoucle, ReponseModele, FakeModeles, _config(), cv_path(), FakeModeles, _lancer(), modeles() (+11 more)

### Community 76 - "html_to_markdown"
Cohesion: 0.09
Nodes (8): Checklist nouvelle source, Contrat fingerprint, Sources — contrat adapter & fingerprint, html_to_markdown(), TestEdgeCases, TestIdempotencePlainText, TestMarkdownStructure, TestNoResidualHTML

### Community 77 - "IndeedFileSource"
Cohesion: 0.10
Nodes (25): Adapter `IndeedFileSource` (`sources/indeed_file.py`), Ancrage sur le code (Phase 0 skill — relecture faite), Artefact JSONL (`data/indeed_inbox/{YYYY-MM-DD_HHMM}.jsonl`), Dépendances critiques, Garde-fous, IMPLEMENTATION — Chantier source Indeed (via MCP, orchestration Claude), Livrables détaillés, Phase 0 — Test de couverture MCP Indeed (go/no-go, 0 code) (+17 more)

### Community 78 - "run_fiche"
Cohesion: 0.10
Nodes (22): Dépendances critiques, Garde-fous, IMPLEMENTATION — TCK-224 Fiche entreprise sur offre retenue, Livrables détaillés, Phase 1 — L-table : table `fiches_entreprise`, Phase 2 — L-cascade + L-skill, Phase 3 — L-appel + L-reprise, Phases (+14 more)

### Community 79 - "test_cv_corrections_service.py"
Cohesion: 0.13
Nodes (19): _correct(), _corrections_rows(), cv_fixture_paths(), _cvs_row(), db_path(), _fake_result(), _insert_offer(), _make_query() (+11 more)

### Community 80 - "test_exe132_points_pour_lettre.py"
Cohesion: 0.13
Nodes (19): _drain(), _fiche_result(), _fiche_row(), _insert_fiche(), _insert_lettre_choix_moi(), _insert_offer(), _lettre_row(), _make_query() (+11 more)

### Community 81 - "test_exe169_juge_opus_jugement_versions.py"
Cohesion: 0.14
Nodes (19): _drain(), _insert_fiche(), _insert_offer(), _lettre_row(), _marquer_demandee(), _resultat_avec_jugement(), TestBypassApiExposeModeleJugeSurLaLettre, _scenario() (+11 more)

### Community 82 - "test_exe196_sans_lettre_pret.py"
Cohesion: 0.11
Nodes (15): client(), db_path(), gabarit_avec_lettre(), gabarit_sans_lettre(), _insert_cv(), _insert_lettre(), _insert_offer(), _no_real_cascade() (+7 more)

### Community 83 - "test_exe200_reprise_securite.py"
Cohesion: 0.13
Nodes (13): _backup_path(), _creer_base_avant_la_fiche(), _offer(), TestCritere10BaseDejaRepriseNEstNiRecopieeNiRetouchee, TestCritere1CopieViseLeFichierDeLaConnexion, TestCritere3CoherenteAvecUneAutreConnexionOuverte, TestCritere4AucuneCopieHorsDuDossier, TestCritere6CoupureNeLaisseAucuneTableNiLigne (+5 more)

### Community 84 - "get_mail_candidature"
Cohesion: 0.12
Nodes (16): get_mail_candidature(), db_path(), gabarit_path(), _insert_fiche(), _insert_offer(), intermediaires_path(), _now(), TestCritere10AucunAppelModele (+8 more)

### Community 85 - "test_exe116_sans_techno_seconde_passe.py"
Cohesion: 0.15
Nodes (22): rattraper_sans_techno_tri(), alias_table(), cascade(), _extract(), db_path(), _get_id(), loaded_profile(), _offer() (+14 more)

### Community 86 - "FranceTravailSource"
Cohesion: 0.08
Nodes (22): Étage 1 : Fetch (sources pluggables), 1. Sources pluggables, 2. Profil cible mutable, 3. Scoring explicable par construction, 4. Frontière extraction / matching — 0 LLM au recalcul, Architecture — invariants non négociables, Exception encadrée : banc de la lettre (TCK-251), Exception encadrée — identification d'une offre ajoutée à la main sans titre (TCK-183) (+14 more)

### Community 87 - "test_exe105_mlflow_tracking.py"
Cohesion: 0.14
Nodes (21): extraction_version(), cascade(), _extract(), db_path(), loaded_profile(), no_sleep(), no_unload(), _offer() (+13 more)

### Community 88 - "get_fiche"
Cohesion: 0.11
Nodes (14): get_fiche(), _fiche_result(), _fiche_row(), _insert_fiche_ancienne(), _insert_offer(), _make_query(), TestCritere10AvisNAtteintAucunModele, TestCritere3ListeManquanteDevientVide (+6 more)

### Community 89 - "Pipeline — contrat par étage"
Cohesion: 0.07
Nodes (27): CONSOMME, CONSOMME, CONSOMME, CONSOMME, CONSOMME, INTERDITS, INTERDITS, INTERDITS (+19 more)

### Community 90 - "CascadeResult"
Cohesion: 0.08
Nodes (19): Pydantic `CascadeResult` (nouveau — `orchestrator/job_search/fiche/cascade.py`), Schéma JSON sortie SDK — `_FICHE_SCHEMA` (`orchestrator/job_search/fiche/service.py`), Schémas cibles, Table `fiches_entreprise` (SQL — `orchestrator/job_search/storage/db.py:init_db()`), CascadeResult, db_path(), lettre_fixture_paths(), _stub_cascade_employeur() (+11 more)

### Community 91 - "test_exe107_reference_replay.py"
Cohesion: 0.13
Nodes (18): OllamaUnavailable, _entry(), fake_extract(), no_ollama_check(), no_sleep(), no_unload(), _profile(), _run() (+10 more)

### Community 92 - "test_exe150_boucle_lettre_manques.py"
Cohesion: 0.15
Nodes (23): generer_lettre_boucle(), _config(), _conn(), cv_path(), db_path(), _lancer(), modeles(), _poser_offre_et_fiche() (+15 more)

### Community 93 - "test_exe123_reference_api.py"
Cohesion: 0.17
Nodes (20): load_jeu(), ReferenceEntry, save_jeu(), client(), db_path(), _insert_offer(), jeu_path(), test_ajout_necrit_rien_dans_offers() (+12 more)

### Community 94 - "create_lettre"
Cohesion: 0.14
Nodes (18): create_lettre(), ecarter_fait(), get_lettre_mise_en_page(), _launch_regeneration(), _lettre_page_ingredients(), _modele_choisi(), ModeleLettreIn, regenerer_depuis_ma_lettre() (+10 more)

### Community 95 - "repertoire.py"
Cohesion: 0.14
Nodes (20): _est_trou(), Exemple, ExempleRelecture, _formater_trou(), Forme, FormulationRejetee, Interprete, Juge (+12 more)

### Community 96 - "test_cv_groupes.py"
Cohesion: 0.15
Nodes (17): _correct(), cv_fixture_paths(), db_path(), _fake_result(), _get(), _insert_offer(), _make_query(), _query() (+9 more)

### Community 97 - "ajouts.py"
Cohesion: 0.12
Nodes (13): AjoutIn, create_ajout(), get_ajout(), list_ajouts(), _row_to_ajout(), _go(), test_ajout_inconnu_404(), test_ajout_orphelin_se_lit_echec() (+5 more)

### Community 98 - "test_exe153_cv_sans_style_script.py"
Cohesion: 0.15
Nodes (16): strip_html(), strip_style_and_script(), _config(), _cv_path(), _lancer(), modeles(), _repertoire_donnees(), repertoire_path() (+8 more)

### Community 99 - "_insert_offer"
Cohesion: 0.28
Nodes (11): _cv_ok(), _cv_row(), _fiche_ok(), _fiche_row(), _insert_offer(), _lettre_jamais_appelee(), _lettre_ok(), _lettre_row() (+3 more)

### Community 100 - "_insert_offer"
Cohesion: 0.13
Nodes (12): get_cv_pdf(), html_to_pdf(), _fake_result(), _insert_offer(), _make_query(), _run_cv(), TestCritere15CoordonneesAbsentes, TestCritere16Refus (+4 more)

### Community 101 - "test_exe163_actiris.py"
Cohesion: 0.25
Nodes (18): ActirisSource, _detail_html(), _fake_requests(), _list_item(), test_critere10_lieu_bruxelles_et_commune_lisible(), test_critere11_identifiant_et_url(), test_critere12_employeur_vide_si_rubrique_absente(), test_critere13_deja_vue_au_second_fetch() (+10 more)

### Community 102 - "test_exe144_etape_candidature.py"
Cohesion: 0.17
Nodes (14): client(), db_path(), _insert_cv(), _insert_lettre(), _insert_offer(), _now(), _offer(), _pretes() (+6 more)

### Community 103 - "reference.vue"
Cohesion: 0.09
Nodes (20): chargerListe(), config, detail, DOMAINS, enregistrerRelu(), entries, form, IMPORTANCES (+12 more)

### Community 104 - "IMPLEMENTATION — Chantier HTML→Markdown : nettoyage dans l'adapter Remotive"
Cohesion: 0.09
Nodes (21): Calage sur l'existant (à VÉRIFIER en Phase 0 — NON négociable), Décisions de cadrage (prises en chat, gravées ici), Dépendances critiques, Fonction de conversion partagée (cible universelle, appelée PAR les adapters), Garde-fous, Hors-scope — explicitement reporté, IMPLEMENTATION — Chantier HTML→Markdown : nettoyage dans l'adapter Remotive, Invariant du chantier (non négociable) (+13 more)

### Community 105 - "experiment_tck200.py"
Cohesion: 0.11
Nodes (16): Dépendances critiques, Garde-fous, IMPLEMENTATION — TCK-200 Expérience extraction 6 variantes × 3 répétitions, Livrables détaillés, Phase 1 — Script `experiment_tck200.py`, Phase 2 — Exécution et tableau récapitulatif, Phases, _build_user_prompt() (+8 more)

### Community 106 - "test_cv_service.py"
Cohesion: 0.14
Nodes (12): cv_fixture_paths(), _cvs_row(), db_path(), _fake_result(), _insert_offer(), _make_query(), _query(), TestCritere1Idempotence (+4 more)

### Community 107 - "pathlib"
Cohesion: 0.14
Nodes (9): _call(), _conn(), _counts(), _parse(), _report(), _run(), _sample(), _user_prompt() (+1 more)

### Community 108 - "OffersTable.vue"
Cohesion: 0.09
Nodes (15): Phase 2 — Tri colonnes + filtres enrichis (L6–L10), apply(), local, LocalFilters, reset(), store, COLS, ETAPE_FILTER_LABELS (+7 more)

### Community 109 - "CARTE FACTUELLE V2 — job-search"
Cohesion: 0.09
Nodes (22): 1. Points d'entrée (8), 3. Lignage de la donnée offre, 4. Sondes, 6.2 Endpoints API sans consommateur front, 6.3 Fichiers écrits jamais relus par le code, 6.4 Colonne DB écrite jamais lue explicitement, 6. Zones mortes / non-couvert, 7.1 Fermeture Invocation (+14 more)

### Community 110 - "ExtractedFacts"
Cohesion: 0.17
Nodes (11): add_offers(), AddReport, jeu_fingerprint(), ExtractedFacts, _insert_offer(), test_critere13_empreinte_change_si_un_attendu_change(), test_critere13_empreinte_stable_sur_un_jeu_inchange(), test_critere1_ajoute_une_offre_prereplie_non_relue() (+3 more)

### Community 111 - "test_exe127_cascade.py"
Cohesion: 0.10
Nodes (18): cv_fixture_paths(), db_path(), _erreur_result(), lettre_fixture_paths(), _stub_cascade_employeur(), _fake(), TestCritere10TexteOffreManquantPasDeLettre, TestCritere11PieceDejaTermineeNonRelancee (+10 more)

### Community 112 - "test_exe201_garde_front_generique.py"
Cohesion: 0.09
Nodes (8): _scan(), TestCritere17AucuneConditionNonExceptee, TestCritere18GardesExistantesRestentVertes, TestCritere7RevueActiveRetireLaRevueJamaisLeTri, TestCritere9RetenirRefuseAfficheSonMessage, TestCriteres10Et11BlocEnvoiDecideParLApi, TestMutantF6OffreTriReintroduitEstAttrape, TestMutantF7AvertissementEnvoiDepuisLeGesteRaison

### Community 113 - "IMPLEMENTATION — Vue candidat (4 onglets par intention)"
Cohesion: 0.10
Nodes (21): Phase 2 — Champ `ad_language` : colonne + module + pipeline + backfill + filtre candidat, Backend — migration `seen` → `seen_candidat`, Backend — nouveau param `GET /offers`, Backend — `VerdictIn` (schemas.py:52-53), Dettes ouvertes (à documenter dans DECISIONS.md), Dépendances critiques, Frontend — `ActiveView` + presets (stores/offers.ts), Frontend — `Filters` (stores/offers.ts:49-60) (+13 more)

### Community 114 - "ingestion.py"
Cohesion: 0.12
Nodes (9): _cleaned_text_len(), _extract_with_no_response_flag(), OfferOutcome, _persist_final(), rattraper_texte_recu(), RegisterOutcome, resolve_unreadable_with_precision(), TriOutcome (+1 more)

### Community 115 - "_insert_offer"
Cohesion: 0.16
Nodes (14): _cascade(), _ecrire_repertoire(), _insert_fiche_ancienne(), _insert_offer(), _offer_row(), _repertoire_bien_forme(), TestCritere11ChampATrouAbsentDeLaDemande, TestCritere12FicheAncienneSansFamilleNiDate (+6 more)

### Community 116 - "ExportPopover.vue"
Cohesion: 0.10
Nodes (19): Backend — `api/export.py` vs `api/offers.py`, Dépendances critiques, Frontend — `ExportPopover.vue:doCopy()` vs `stores/offers.ts:fetchOffers()`, Garde-fous, IMPLEMENTATION — Alignement endpoint export sur listing (bug copier hors-périmètre), Inventaire des écarts (Phase 0), Livrables détaillés, Phase 1 — Backend : aligner le sort et les filtres de l'export (L1–L3) (+11 more)

### Community 117 - "IMPLEMENTATION — Chantier review humaine : vérité terrain + suppression scoring + UI sortie LLM"
Cohesion: 0.10
Nodes (20): Badges techs (front), Calage sur l'existant (à VÉRIFIER en Phase 0 — NON négociable), Colonnes de review (SQLite, sur `offers` OU table dédiée — tranché en L2 selon Phase 0), Dépendances critiques, Garde-fous, IMPLEMENTATION — Chantier review humaine : vérité terrain + suppression scoring + UI sortie LLM, Invariant du chantier (non négociable), Livrables détaillés (+12 more)

### Community 118 - "filter_new"
Cohesion: 0.11
Nodes (15): Dépendances critiques, Garde-fous, IMPLEMENTATION — Dédup amont Indeed (anti rate-limit MCP), Livrables détaillés, Phase unique — Endpoint + mise à jour skill, Vue d'ensemble, Garde-fous, IMPLEMENTATION — Remédiation code mort (ChromaDB, purge, view) (+7 more)

### Community 119 - "fiche/prompt.py"
Cohesion: 0.13
Nodes (10): build_prompt(), _charger_repertoire_pour_prompt(), load_template(), _section_repertoire(), _sujets_non_generiques(), sujets_valides(), _parse_output(), rechercher_entreprise() (+2 more)

### Community 120 - "package.json"
Cohesion: 0.13
Nodes (18): dompurify, nuxt, @nuxtjs/tailwindcss, @pinia/nuxt, @tailwindcss/typography, vue, vue-router, dependencies (+10 more)

### Community 121 - "traces.vue"
Cohesion: 0.11
Nodes (13): expandedKeys, groups, localCauses, localNotes, localSeverites, route, savedKeys, store (+5 more)

### Community 122 - "identify_employer"
Cohesion: 0.16
Nodes (11): Étage 4 : LLM Extraction (faits intrinsèques), Corrections après essai — ajout intermédiaire (2026-09-28), _digest(), _fallback(), identify_employer(), _step3_llm(), _text(), add() (+3 more)

### Community 123 - "IMPLEMENTATION — Chantier 2 : refonte du profil + catégorisation"
Cohesion: 0.10
Nodes (19): Atteignabilité — refondue, Calage sur l'existant (lu dans le repo — NON négociable), Catégorie + score intra-case, Dépendances critiques, Faits extraits — enrichis (`ExtractedFacts`), Garde-fous, IMPLEMENTATION — Chantier 2 : refonte du profil + catégorisation, Livrables détaillés (+11 more)

### Community 124 - "IMPLEMENTATION — Interface de pilotage (Zone A)"
Cohesion: 0.10
Nodes (19): Contrat d'entrée (état de départ vérifié AVANT toute action), Dépendances critiques, Garde-fous, IMPLEMENTATION — Interface de pilotage (Zone A), Invariants de ce chantier, Livrables détaillés, Migration SQLite (L0), Phase 0 — Schéma + setup API (objectif : la base a `seen`, l'API démarre et lit la base) (+11 more)

### Community 125 - "test_exe117_texte_manquant_tous_chemins.py"
Cohesion: 0.20
Nodes (14): alias_table(), db_path(), fake_extract(), _get_id(), loaded_profile(), _offer(), profil(), _row() (+6 more)

### Community 126 - "test_exe106_extraction_version_filter.py"
Cohesion: 0.14
Nodes (10): api_traces(), db_path(), TestCritere1ChaqueTracePorteSaVersion, TestCritere2TraceAncienneSansVersionDevinee, TestCritere3ListeDesVersionsAvecComptage, TestCritere4FiltreParVersion, TestCritere5FiltreSansVersion, TestCritere6SansFiltreRendTout (+2 more)

### Community 127 - "test_exe200_tests_manquants_exe193.py"
Cohesion: 0.13
Nodes (10): client(), db_path(), _insert_offer(), _now(), TestCritere24MotifEnregistreEtReluTelQuel, TestCritere25RetenirSeulLanceLaGenerationParLaRouteGenerique, TestCritere26SeptEtapesLecturesCommeOffreRetenue, TestCritere28RevuesEtEcarteesRepriseesVerifiees (+2 more)

### Community 128 - "reference.py"
Cohesion: 0.16
Nodes (10): add_offer_to_reference(), AddToReferenceOut, _AttenduIn, get_reference_entry(), list_reference(), ReferenceEntryIn, ReferenceEntryOut, ReferenceListOut (+2 more)

### Community 129 - "E1 — FastAPI app (`api/main.py`)"
Cohesion: 0.11
Nodes (18): _ensure_trace_notes_table(), 2. Traces par entrée, E1 — FastAPI app (`api/main.py`), E1a — `GET /health`, E1b — `GET /offers`, E1c — `POST /offers/check-known`, E1e — `PUT /offers/{offer_id}/verdict`, E1f — `DELETE /offers/{offer_id}/verdict` (+10 more)

### Community 130 - "Taxonomie des erreurs — 7 buckets"
Cohesion: 0.11
Nodes (18): A — Alias / normalisation (~11 mentions), Analyse de review — 48 offres annotées (2026-07-08), Chantier annexe, D — Domaine miscalibré (~9 offres), Distinction architecturale des leviers, G — Gates éliminatoires absents (~12 offres), P — Profil incomplet (~14 mentions), Priorité 1 — Critiques (parallélisables) (+10 more)

### Community 131 - "experiment_tck206_cv.py"
Cohesion: 0.13
Nodes (9): _classify_techs(), _clean_title(), _conn(), _fetch_offer(), _generate_cv_html(), _parse_ref_block(), _playwright_check(), _render_skills_html() (+1 more)

### Community 132 - "VerdictIn"
Cohesion: 0.24
Nodes (11): get_avancement(), upsert_verdict(), VerdictIn, _drain(), _en_erreur(), _scenario_retenir(), _scenario(), TestCritere14AvancementQuatreEtats (+3 more)

### Community 133 - "test_human_reviews.py"
Cohesion: 0.17
Nodes (8): get_review(), upsert_review(), conn(), test_get_missing_returns_none(), test_migration_idempotent(), test_offers_verdicts_untouched(), test_upsert_is_idempotent(), test_upsert_then_get_round_trip()

### Community 134 - "test_exe165_actiris_entites.py"
Cohesion: 0.26
Nodes (13): _detail_html(), _fake_requests(), fake_get(), fake_post(), _FakeResponse, _list_item(), test_critere1_titre_fr_entites_decodees(), test_critere2_entite_esperluette_decodee() (+5 more)

### Community 135 - "Écriture"
Cohesion: 0.12
Nodes (16): 1. Barre, 2. Confrontation, 3. Hors demande, 4. Hypothèses tombées, 5. Règles permanentes, Ce qui n'est pas un arrêt, Git, Invariants (+8 more)

### Community 136 - "IMPLEMENTATION — job-search-zone-a"
Cohesion: 0.12
Nodes (15): Dépendances critiques, Garde-fous, IMPLEMENTATION — job-search-zone-a, `JobOffer` (schéma neutre — Pydantic), Livrables détaillés, Persistance (SQLite — 2 tables), Phase 1 — Socle de domaine, Phase 2 — Ingestion & dédup (+7 more)

### Community 137 - "experiment_tck206.py"
Cohesion: 0.19
Nodes (10): _call_claude(), _check_urls(), _collect_urls(), _conn(), _call_claude(), _parse_claude_output(), _fetch_offer(), _parse_claude_output() (+2 more)

### Community 138 - ".test_adresse_sans_http_ou_https_n_est_pas_gardee"
Cohesion: 0.17
Nodes (7): _fiche_result(), _insert_fiche_ancienne(), _insert_offer(), _make_query(), TestCritere1AdresseSauvegardeeEtRendue, TestCritere2AdresseSansSchemeHttpEcartee, TestCritere3AbsenceDAdresseSansErreur

### Community 139 - "test_exe193_reprise.py"
Cohesion: 0.20
Nodes (9): base_avant_la_fiche(), _creer_base_avant_la_fiche(), _offer(), TestCritere20DateDenvoiTelleQuelle, TestCritere22RejeteesEcarteesSansMotif, TestCritere24CandidateEtMasqueRepris, TestCritere25SecondDemarrageNeReprendRien, TestCritere26PiecesInchangeesOffresSansVerdictRestentATrier (+1 more)

### Community 140 - "IMPLEMENTATION — Rituel de calibration humain↔IA"
Cohesion: 0.13
Nodes (14): Chantier C-1 — Stockage `human_reviews`, Chantier C-2 — Capture en page détail (cockpit), Chantier C-3 — Persistance & garde-fou, Chantier C-4 — Désaccord & export, Chantiers, Dépendances critiques, Garde-fous, IMPLEMENTATION — Rituel de calibration humain↔IA (+6 more)

### Community 141 - "IMPLEMENTATION — Vue opérateur (élagage onglets, verdicts HP, tri & filtres)"
Cohesion: 0.14
Nodes (14): Backend — `_SORT_COLS` (offers.py:25), Dépendances critiques, Frontend — colonnes triables (OffersTable.vue), Frontend — FiltersPanel enrichi, Frontend — `OperatorView` + presets (stores/offers.ts), Frontend — Verdicts HP dans OfferDetail (mode opérateur, onglet HP), Garde-fous, IMPLEMENTATION — Vue opérateur (élagage onglets, verdicts HP, tri & filtres) (+6 more)

### Community 142 - "TraceNoteIn"
Cohesion: 0.16
Nodes (11): TraceNoteIn, _upsert_note(), upsert_trace_note(), Phase 1 — Route API `GET /traces` (read-only, dé-échappe, join offre), Phase 2 — Persistance des notes (`trace_notes` + routes), Phase 3 — Page `/traces` (front Nuxt), Phase 4 — Retrait du faux-juge en page offre, Phase 5 — Clôture (+3 more)

### Community 143 - "CODEMAP — job-search"
Cohesion: 0.14
Nodes (13): Calibration — étude IA, Chemins canoniques, CODEMAP — job-search, Composants, Configuration, Disagreement score, Dépendances, Frontend — Nuxt 4 + Pinia v3 (+5 more)

### Community 144 - "IMPLEMENTATION — Chantier 1 : refacto du scoring (filtres durs + désirabilité graduée)"
Cohesion: 0.14
Nodes (13): Dépendances critiques, Garde-fous, Grille de désirabilité — après refacto, HORS-SCOPE — gravé pour le chantier 2 (refonte profil), NE PAS traiter ici, IMPLEMENTATION — Chantier 1 : refacto du scoring (filtres durs + désirabilité graduée), `JobOffer` — champs touchés, Phase 1 — Filtres durs (contrat, lieu, full_time) — défaut 2, Phase 2 — Désirabilité graduée par distance au domaine — défaut 1 (+5 more)

### Community 145 - "IMPLEMENTATION — Chantier hors-périmètre : bucket dérivé pour offres non-IC-techniques"
Cohesion: 0.14
Nodes (13): Calage sur l'existant (à VÉRIFIER en Phase 0 — NON négociable), Décision de cadrage (prise en chat, gravée ici), Dépendances critiques, Dérivation (Python pur, fonction unique), Garde-fous, Hors-scope — explicitement reporté, IMPLEMENTATION — Chantier hors-périmètre : bucket dérivé pour offres non-IC-techniques, Invariant du chantier (non négociable) (+5 more)

### Community 146 - "filename.py"
Cohesion: 0.22
Nodes (5): Coordonnees, piece_filename(), resolve_piece_filename(), sanitize_part(), TestCritere14Assainissement

### Community 147 - "re"
Cohesion: 0.30
Nodes (9): extract_text(), _font_cmaps(), is_a4(), media_box(), _ordered_page_numbers(), page_count(), _parse_objects(), _parse_tounicode() (+1 more)

### Community 148 - "cvUrl"
Cohesion: 0.21
Nodes (14): ajouterCompetence(), changerCvProfil(), chargerCv(), chargerCvTitreDefaut(), cvLangueParDefaut(), cvUrl(), effacerCvTitreDefaut(), enregistrerCvTitre() (+6 more)

### Community 149 - "_compute_avancement"
Cohesion: 0.18
Nodes (11): _compute_avancement(), list_avancement(), is_running(), running_offer_ids(), is_running(), running_offer_ids(), is_running(), running_offer_ids() (+3 more)

### Community 150 - "API FastAPI"
Cohesion: 0.15
Nodes (13): API FastAPI, Export — endpoints, GET /export/calibration (CSV), GET /export/offers (Markdown), GET /traces/counts, GET /traces/export (export JSONL), GET /traces (list), Point d'entrée (+5 more)

### Community 151 - "detect_ad_language"
Cohesion: 0.18
Nodes (9): Dépendances critiques, Garde-fous, IMPLEMENTATION — Belge dans le périmètre (gate langue · ad_language · EURES), Livrables détaillés, Phase 1 — Retrait de la cause `langue` + rescore des 29 libérées, Phase 3 — Source EURES + câblage run.py, Phases, Vue d'ensemble (+1 more)

### Community 152 - "IMPLEMENTATION — Chantier traces viewer : page /traces + notes + retrait du faux-juge"
Cohesion: 0.15
Nodes (12): Calage sur l'existant (lu dans le repo — reconnaissance Claude Code), Dépendances critiques, Garde-fous, Hors-scope — explicitement reporté, IMPLEMENTATION — Chantier traces viewer : page /traces + notes + retrait du faux-juge, Invariant du chantier (non négociable), Livrables détaillés, Réponse API `GET /traces` (Pydantic, `api/schemas.py`) (+4 more)

### Community 153 - "IMPLEMENTATION — Lot G : Gates éliminatoires hors_perimetre (langue + contrat)"
Cohesion: 0.15
Nodes (12): Dépendances critiques, `ExtractedFacts` — champ flux futur, Garde-fous, `hors_perimetre.py` — retour multi-causes, IMPLEMENTATION — Lot G : Gates éliminatoires hors_perimetre (langue + contrat), Livrables détaillés, Phase 3 — Rétro-attribution + script de mesure + rapport (L6–L8), Phase 4 — Flux futur extraction + tests (L9–L10) (+4 more)

### Community 154 - "IMPLEMENTATION — Page offre retenue (emplacements phase 2)"
Cohesion: 0.15
Nodes (12): Dépendances critiques, Garde-fous, IMPLEMENTATION — Page offre retenue (emplacements phase 2), Livrables détaillés, Phase 1 — Route paramétrée + layout plein-écran, Phase 2 — Colonne gauche : frise de statut + synthèse + annonce, Phase 3 — Colonne droite : cartes vides + bouton Envoyer, Phase 4 — Comportements existants modifiés (+4 more)

### Community 155 - "compute_permitted_additions"
Cohesion: 0.40
Nodes (3): compute_permitted_additions(), _techs(), TestComputePermittedAdditions

### Community 156 - "_insert_offer"
Cohesion: 0.21
Nodes (7): _insert_lettre_done(), _insert_offer(), _now(), TestCritere1MemePageQueLePdf, TestCritere2LettreNonGeneree, TestCritere3OffreNonRetenue, TestCritere4CoordonneesManquantes

### Community 157 - "Instructions"
Cohesion: 0.17
Nodes (10): 1. Recherche d'offres, 2. Filtrage des offres déjà connues (dédup amont), 3. Récupération des détails (avec throttle), 4. Écriture du JSONL, 5. Résultat, Fréquence suggérée, Instructions, Prérequis (+2 more)

### Community 158 - "settings.json"
Cohesion: 0.17
Nodes (11): enabledPlugins, ecc@ecc, env, ECC_DISABLED_HOOKS, ECC_HOOK_PROFILE, includeCoAuthoredBy, permissions, allow (+3 more)

### Community 159 - "IMPLEMENTATION — Bouton "voir la trace" sur le side panel offre"
Cohesion: 0.17
Nodes (11): Garde-fous, Hors scope (reporté, adossé ici), IMPLEMENTATION — Bouton "voir la trace" sur le side panel offre, L1 — `source_id` dans le schéma `OfferDetail`, L2 — Endpoint `GET /traces/counts`, L3 — Store : charger les counts une fois, L4 — Bouton dans la meta bar `OfferDetail.vue`, L5 — Ancrage cible dans `traces.vue` (+3 more)

### Community 160 - "IMPLEMENTATION — Export contextuel d'offres pour LLM"
Cohesion: 0.17
Nodes (11): Dépendances critiques, Endpoint `GET /export/offers`, Format de sortie (Markdown), Garde-fous, IMPLEMENTATION — Export contextuel d'offres pour LLM, Livrables détaillés, Phase 1 — Backend : endpoint `/export/offers` (L1–L3), Phase 2 — Frontend : composant ExportPopover + intégration (L4–L6) (+3 more)

### Community 161 - "IMPLEMENTATION — Export contextuel d'offres pour LLM"
Cohesion: 0.17
Nodes (11): Dépendances critiques, Endpoint `GET /export/offers`, Format de sortie (Markdown), Garde-fous, IMPLEMENTATION — Export contextuel d'offres pour LLM, Livrables détaillés, Phase 1 — Backend : endpoint `/export/offers` (L1–L3), Phase 2 — Frontend : composant ExportPopover + intégration (L4–L6) (+3 more)

### Community 162 - "IMPLEMENTATION — Séparation avis IA / avis humain + staleness post-rescore"
Cohesion: 0.17
Nodes (11): API — nouveaux champs dérivés (jamais persistés), Dépendances critiques, Garde-fous, IMPLEMENTATION — Séparation avis IA / avis humain + staleness post-rescore, Livrables détaillés, Phase 2 — Frontend : séparation visuelle + gestion staleness (L5–L9), Phases, Pydantic — OfferRow / OfferDetail (api/schemas.py) (+3 more)

### Community 163 - "reprise.py"
Cohesion: 0.26
Nodes (5): _ecrire_evenement(), migrer_verdicts(), _poser_etat(), valider_verdicts(), VerdictInutilisable

### Community 164 - "_derive_score_breakdown"
Cohesion: 0.22
Nodes (9): _derive_score_breakdown(), Dépendances critiques, Garde-fous, IMPLEMENTATION — Ligne de justification catégorie (vue opérateur), Livrables détaillés, Phase 1 — Helper API + champ schema (L1–L3), Phase 2 — Rendu frontend (L4–L5), Phases (+1 more)

### Community 166 - "run_ajout"
Cohesion: 0.27
Nodes (7): _process(), create_ajout(), _finish(), _now(), run_ajout(), test_critere16_ajout_ne_marque_aucune_pause(), test_critere16_ajout_dont_extraction_echoue_finit_en_echec()

### Community 167 - "Stack — détails et contraintes"
Cohesion: 0.20
Nodes (9): Boucle de la lettre — LangGraph (TCK-251), Embeddings — ChromaDB, Fiche entreprise — Claude Agent SDK, Frontend — Nuxt 4 + Pinia v3, LLM — Ollama local, Persistance — SQLite, Runtime & langage, Source externe — API France Travail (Offres d'emploi v2) (+1 more)

### Community 168 - "ficheUrl"
Cohesion: 0.27
Nodes (10): Phase 4 — L-écran, ajouterIntermediaire(), annoter(), chargerFiche(), enregistrerAvis(), expliquer(), ficheUrl(), preparerFiche() (+2 more)

### Community 170 - "job-search"
Cohesion: 0.20
Nodes (9): Comment ça marche, Deux vues, Installation, Jeu de référence, job-search, Lancer, Le profil, Recalculer sans recollecter (+1 more)

### Community 171 - "Invariants détectés"
Cohesion: 0.22
Nodes (9): 1. Scoring explicable par construction, 2. Sources pluggables, 3. Profil YAML = source unique de pilotage, 4. Zéro LLM au rescore, 5. Trace brute sacrée, 6. Gates post-scoring observables, 7. Données d'interaction isolées, 8. Dédup multi-source (+1 more)

### Community 172 - "base.py"
Cohesion: 0.36
Nodes (3): Sources & offres neutres, RoleLevel, SeniorityLevel

### Community 173 - "_FakeResponse"
Cohesion: 0.28
Nodes (5): fake_get(), fake_post(), _FakeResponse, test_critere16_detail_injoignable_titre_seul_et_avertissement(), fake_post()

### Community 175 - "Phase 1 — Récupération des offres Indeed via MCP"
Cohesion: 0.25
Nodes (7): 1.1 Recherche d'offres, 1.2 Récupération des détails, 1.3 Écriture du JSONL, 1.4 Bilan intermédiaire, Phase 1 — Récupération des offres Indeed via MCP, Phase 2 — Pipeline orchestrator, Run complet quotidien

### Community 176 - "Schéma de base"
Cohesion: 0.25
Nodes (8): Connexion, Migration incrémentale, Persistance — SQLite, Schéma de base, Table : human_reviews, Table : offers, Table : trace_notes, Table : verdicts

### Community 177 - "Orchestrateur — CLI run matinal"
Cohesion: 0.25
Nodes (8): Orchestrateur — CLI run matinal, Point d'entrée principal, Rescore — recalcul Python sans LLM, Verdict humain — statut + annotation, Étage 2 : Dédup, Étage 3 : Hard filters (localisation + contrat), Étage 6 : Persistance, Étage 7 : Digest (sortie matinale)

### Community 178 - "IMPLEMENTATION — Cristallisation rules/pipeline.md"
Cohesion: 0.25
Nodes (7): Dépendances critiques, Garde-fous, IMPLEMENTATION — Cristallisation rules/pipeline.md, Livrables détaillés, Phase 2 — Mise à jour STATE + DECISIONS, Phases, Vue d'ensemble

### Community 179 - "HANDOFF — Remédiation job-search"
Cohesion: 0.25
Nodes (7): A. REGISTRE DES DÉCISIONS ACTÉES, B. PROMPT VAGUE 1 — Nettoyage (code mort), C. PROMPT VAGUE 2 — Zones géo source unique + contract_types, D. PROMPT CHANTIER 3 — Cristallisation des règles, E. VAGUE 4 — Persistance & exposition (PARKÉE, pas de prompt), F. RÈGLES DE CONDUITE (toutes vagues), HANDOFF — Remédiation job-search

### Community 180 - "pieces_a_envoyer"
Cohesion: 0.29
Nodes (3): libelle_tout_telecharger(), pieces_a_envoyer(), TestCriteres7A10PiecesEtLibelle

### Community 181 - "test_exe194_front_sans_logique_metier.py"
Cohesion: 0.25
Nodes (3): TestCritere21VerdictBadgeNeFusionnePlusTriEtRevue, TestCritere23EtMutantN1BoutonRetenirNeComparePlusLeTri, TestCritere23EtMutantN6FriseNeComputePlusDepuisLetape

### Community 182 - "extractDetail"
Cohesion: 0.29
Nodes (8): emit, extractDetail(), handleClearVerdict(), handleEcarter(), handleRemettreATrier(), handleTriGeste(), isRevueActive(), toggleRevue()

### Community 183 - "job-search"
Cohesion: 0.29
Nodes (6): Architecture — 3 briques autour d'une base partagée, Ce que tu ne décides pas, Contexte, job-search, Où sont les règles, Stack

### Community 184 - "Offers — Endpoints principaux"
Cohesion: 0.29
Nodes (7): DELETE /offers/{offer_id}/verdict (delete verdict), GET /offers (list), GET /offers/{offer_id} (détail), GET /offers/{offer_id}/review (read human review), Offers — Endpoints principaux, PUT /offers/{offer_id}/category-review (upsert human review par-critère), PUT /offers/{offer_id}/verdict (upsert verdict)

### Community 185 - "Schémas de données (Pydantic)"
Cohesion: 0.29
Nodes (7): ExtractedFacts — faits intrinsèques extraits par LLM, JobOffer — schéma neutre source-agnostique, Profile — profil cible mutable, Schémas de données (Pydantic), SearchCriteria — critères de recherche immuables, TechRequirement — technologie exigée avec poids, Zone — localisation recherche

### Community 186 - "Gate Report — Lot G : rétro-attribution hors_perimetre (langue + contrat)"
Cohesion: 0.29
Nodes (6): Cas corpus — contrat (stage/alternance/MIS), Cas corpus — langue tierce (4 attendus), Distribution avant / après, Gate Report — Lot G : rétro-attribution hors_perimetre (langue + contrat), Offres nouvellement gatées (changement de bucket), Vérification non-régression

### Community 187 - ".test_chaque_piece_generee_une_seule_fois"
Cohesion: 0.29
Nodes (5): _cv_result(), _fiche_result(), TestCritere12DeuxAppelsConsecutifs, _cv_behavior(), _fiche_behavior()

### Community 188 - "run_harness"
Cohesion: 0.29
Nodes (3): db_path(), no_real_sleep(), run_harness()

### Community 189 - "VerdictBadge.vue"
Cohesion: 0.29
Nodes (6): ECARTEE_ENTRY, ETAPE_MAP, props, REVUE_MAP, revueEntry, triEntry

### Community 190 - "Étage 5 : Scoring (Python pur, 0 LLM)"
Cohesion: 0.33
Nodes (6): Atteignabilité (techs + rôle + séniorité), Canonicalisation technos, Catégorisation (2×2), Désirabilité (envie × domaine), Gate hors-périmètre (post-scoring), Étage 5 : Scoring (Python pur, 0 LLM)

### Community 191 - "Enum — valeurs fermées"
Cohesion: 0.33
Nodes (6): Category (catégorisation), Enum — valeurs fermées, HorsPerimetreCause (gates éliminatoires), RoleCeiling, RoleLevel, SeniorityLevel

### Community 192 - "Scoring — décisions de calibration"
Cohesion: 0.33
Nodes (5): `min()` non-compensatoire, `parse_failed`, Règle de modification, Scoring — décisions de calibration, Seuils de catégorisation : 50/40

### Community 193 - "Phases"
Cohesion: 0.33
Nodes (6): Phase 0 — Lecture de l'état réel (0 écriture), Phase 1 — Dérivation + gate (Python pur, cœur du chantier), Phase 2 — Persistance + verdict de validation, Phase 3 — Rescore + restitution cockpit, Phase 4 — Clôture, Phases

### Community 194 - "IMPLEMENTATION — Tri colonnes Contrat et Verdict"
Cohesion: 0.33
Nodes (5): IMPLEMENTATION — Tri colonnes Contrat et Verdict, Livrables, Phase 1 — Ajout du tri sémantique backend + activation frontend, ✋ Verify before continuing:, Vue d'ensemble

### Community 195 - "IMPLEMENTATION — Tri par lieu : grouper les remote"
Cohesion: 0.33
Nodes (5): IMPLEMENTATION — Tri par lieu : grouper les remote, Livrables, Phase 1 — Cas spécial `location` dans le tri SQL, ✋ Verify before continuing:, Vue d'ensemble

### Community 196 - "STATE — job-search"
Cohesion: 0.33
Nodes (5): Maintenant, Mémoire, Phase en cours, Sessions récentes, STATE — job-search

### Community 197 - "NotificationToast.vue"
Cohesion: 0.47
Nodes (4): demarrer(), emit, props, reprendre()

### Community 198 - "scripts"
Cohesion: 0.33
Nodes (6): scripts, build, dev, generate, postinstall, preview

### Community 199 - "Frontend — conventions projet"
Cohesion: 0.40
Nodes (4): Champs dérivés : ne jamais persister, Frontend — conventions projet, Stores API-driven, zéro logique métier côté front, VIEW_PRESETS = source de vérité des vues

### Community 200 - "Barème niveau techno — 10 paliers"
Cohesion: 0.40
Nodes (4): Barème niveau techno — 10 paliers, Mapping indicatif depuis l'ancien format (v1 → v2), Paliers, Règles de saisie

### Community 202 - "Nuxt Minimal Starter"
Cohesion: 0.40
Nodes (4): Development Server, Nuxt Minimal Starter, Production, Setup

### Community 203 - "marked"
Cohesion: 0.50
Nodes (4): marked, renderedDescription, renderedDescription, marked@^18.0.5

### Community 208 - "_jamais_appele"
Cohesion: 0.67
Nodes (3): _jamais_appele(), behavior(), _query()

### Community 210 - "_run"
Cohesion: 0.67
Nodes (3): _run(), test_critere1_source_interrogee_et_loggee(), test_critere2_no_actiris_desactive_la_source()

## Knowledge Gaps
- **40 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `init_db()` connect `init_db` to `cv.py`, `load_profile`, `get_conn`, `sqlite3`, `test_exe184_cv_profil_claude.py`, `storage.py`, `test_exe158_juge_ressenti_recruteur.py`, `test_exe101_statut_piece.py`, `test_exe174_trace_lettre.py`, `test_exe151_jeu_banc_lettre.py`, `json`, `test_exe162_boucle_app.py`, `apply_hard_filters`, `test_exe99_cascade_extraction.py`, `test_exe175_interprete_lettre_mieux_jugee.py`, `test_exe171_angle_lettre.py`, `test_exe164_forem.py`, `ResultatBoucle`, `lettre/service.py`, `test_exe202_navigateur.py`, `get_offer`, `test_exe147_boucle_lettre.py`, `test_exe173_regenerer_depuis_ma_lettre.py`, `test_exe167_avancement_lettre.py`, `test_exe201_corrections_jet46.py`, `test_exe200_api_decisions.py`, `schemas.py`, `test_exe195_decision_lettre.py`, `save_offer`, `test_exe198_suite_candidature.py`, `test_exe100_gemma_lots.py`, `test_exe194_suivi_candidat.py`, `test_exe176_mail_depuis_lettre.py`, `main`, `run_lettre`, `test_exe183_cv_anglais.py`, `test_ajout_exe79.py`, `test_exe160_verificateur_lettre.py`, `test_exe193_api_suivi.py`, `test_exe102_pdf_pieces.py`, `test_exe176_lettre_pdf_entreprise.py`, `test_exe161_fiche_sujets_lettre.py`, `test_exe199_suivi_candidatures.py`, `derive_hors_perimetre`, `test_exe98_extraction_retry.py`, `test_ajout_exe82.py`, `test_exe197_marquer_envoyee_datee.py`, `test_exe139_candidature_envoyee.py`, `test_exe155_redaction_lit_annonce.py`, `test_cv_exe63.py`, `run_fiche`, `test_cv_corrections_service.py`, `test_exe132_points_pour_lettre.py`, `test_exe169_juge_opus_jugement_versions.py`, `test_exe196_sans_lettre_pret.py`, `test_exe200_reprise_securite.py`, `get_mail_candidature`, `test_exe116_sans_techno_seconde_passe.py`, `test_exe105_mlflow_tracking.py`, `Pipeline — contrat par étage`, `CascadeResult`, `test_exe150_boucle_lettre_manques.py`, `test_exe123_reference_api.py`, `test_cv_groupes.py`, `test_exe163_actiris.py`, `test_exe144_etape_candidature.py`, `test_cv_service.py`, `ExtractedFacts`, `test_exe127_cascade.py`, `test_exe117_texte_manquant_tous_chemins.py`, `test_exe106_extraction_version_filter.py`, `test_exe200_tests_manquants_exe193.py`, `test_human_reviews.py`, `test_exe165_actiris_entites.py`, `test_exe193_reprise.py`, `IMPLEMENTATION — Lot G : Gates éliminatoires hors_perimetre (langue + contrat)`, `run_harness`, `db_path`, `db_path`, `.test_migration_idempotente_sans_marquer_les_offres_existantes`, `.test_get_connection_sans_setup_pointe_hors_de_data`, `conn`, `conn`?**
  _High betweenness centrality (0.172) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `init_db()` (e.g. with `Étage 6 — Persistance` and `Livrables détaillés`) actually correct?**
  _`init_db()` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Should `[id].vue` be split into smaller, more focused modules?**
  _Cohesion score 0.014471639471639472 - nodes in this community are weakly interconnected._
- **Why does `run_fiche()` connect `run_fiche` to `cv.py`, `load_profile`, `init_db`, `sqlite3`, `ficheUrl`, `.test_adresse_sans_http_ou_https_n_est_pas_gardee`, `json`, `test_exe132_points_pour_lettre.py`, `fiche/prompt.py`, `get_fiche`, `test_exe161_fiche_sujets_lettre.py`?**
  _High betweenness centrality (0.091) - this node is a cross-community bridge._
- **Are the 83 inferred relationships involving `JobOffer` (e.g. with `2. Sources pluggables` and `1. Sources pluggables`) actually correct?**
  _`JobOffer` has 83 INFERRED edges - model-reasoned connections that need verification._
- **Should `cv.py` be split into smaller, more focused modules?**
  _Cohesion score 0.03461578563236367 - nodes in this community are weakly interconnected._
- **Why does `Livrables détaillés` connect `run_fiche` to `CascadeResult`, `identify_employer`?**
  _High betweenness centrality (0.081) - this node is a cross-community bridge._