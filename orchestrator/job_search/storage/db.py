import sqlite3

from orchestrator.job_search.paths import DB_PATH


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS offers (
            id                   INTEGER PRIMARY KEY,
            source               TEXT NOT NULL,
            source_id            TEXT NOT NULL,
            fingerprint          TEXT NOT NULL,
            title                TEXT,
            company              TEXT,
            location             TEXT,
            remote               INTEGER,
            contract_type        TEXT,
            nature_contract      TEXT,
            alternance           INTEGER NOT NULL DEFAULT 0,
            full_time            INTEGER,
            company_size         TEXT,
            experience_required  TEXT,
            rome_code            TEXT,
            rome_label           TEXT,
            url                  TEXT,
            fetched_at           TEXT,
            description          TEXT,
            seen_candidat        INTEGER NOT NULL DEFAULT 0,
            extracted_facts_json TEXT,
            UNIQUE(source, source_id)
        );

        CREATE TABLE IF NOT EXISTS verdicts (
            id         INTEGER PRIMARY KEY,
            offer_id   INTEGER REFERENCES offers(id),
            status     TEXT,
            created_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_offers_fingerprint ON offers(fingerprint);

        CREATE TABLE IF NOT EXISTS expirations (
            id               INTEGER PRIMARY KEY,
            offer_id         INTEGER NOT NULL REFERENCES offers(id),
            employer_url     TEXT,
            expired          INTEGER NOT NULL DEFAULT 0,
            last_checked_at  TEXT,
            checks_json      TEXT,  -- JSON array [{url, status_code, checked_at}] (EXE-76)
            UNIQUE(offer_id)
        );

        CREATE TABLE IF NOT EXISTS human_reviews (
            offer_id          TEXT PRIMARY KEY,
            ratings_json      TEXT NOT NULL,
            ai_snapshot_json  TEXT NOT NULL,
            global_audit_text TEXT,
            global_score      INTEGER,
            seen_at_review    INTEGER NOT NULL DEFAULT 0,
            created_at        TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fiches_entreprise (
            id                    INTEGER PRIMARY KEY,
            offer_id              INTEGER NOT NULL REFERENCES offers(id),
            statut                TEXT NOT NULL DEFAULT 'pending', -- pending|done|error
            mode                  TEXT,   -- entreprise|offre_seule
            presentation          TEXT,   -- paragraphe de présentation de l'entreprise
            employeur_nom         TEXT,
            employeur_entite      TEXT,
            employeur_type_source TEXT,   -- direct|agence|agregateur|inconnu
            employeur_confiance   TEXT,   -- sur|probable|non_trouve
            employeur_methode     TEXT,
            employeur_urls_json   TEXT,   -- JSON array de strings
            points_json           TEXT,   -- JSON array [{position,citation,url,tas,explication,pour_lettre,famille,date}]
            session_id            TEXT,
            cost_usd              REAL,
            tools_called_json     TEXT,   -- JSON array des outils effectivement appelés
            api_key_source        TEXT,
            prompt_text           TEXT,   -- prompt envoyé (audit invariant)
            error_message         TEXT,
            created_at            TEXT NOT NULL,
            UNIQUE(offer_id)
        );

        CREATE TABLE IF NOT EXISTS cvs (
            id                       INTEGER PRIMARY KEY,
            offer_id                 INTEGER NOT NULL REFERENCES offers(id),
            statut                   TEXT NOT NULL DEFAULT 'pending', -- pending|done|error
            html                     TEXT,
            titre                    TEXT,
            localisation             TEXT,
            au_cv_json               TEXT,  -- JSON array : compétences du bloc généré (critère 19)
            demande_sans_y_etre_json TEXT,  -- JSON array : technos offre absentes du CV (critère 20)
            ajouts_permis_json       TEXT,  -- JSON array : ajouts calculés côté code (audit)
            groupes_json             TEXT,  -- JSON [{label, items}] : état courant du bloc (EXE-59)
            notions_json             TEXT,  -- JSON array : notions courantes (EXE-59)
            seuil_utilise            INTEGER, -- seuil de niveau au moment de ce calcul (critère 16)
            session_id               TEXT,
            cost_usd                 REAL,
            prompt_text              TEXT,  -- prompt envoyé (audit invariant)
            error_message            TEXT,
            created_at               TEXT NOT NULL,
            marque_pret_at           TEXT,  -- EXE-101 : date/heure de ma marque « Prête », NULL sinon
            UNIQUE(offer_id)
        );

        CREATE TABLE IF NOT EXISTS cv_settings (
            id           INTEGER PRIMARY KEY CHECK (id = 1), -- ligne unique (EXE-130)
            titre_defaut TEXT  -- titre des prochains CV générés, NULL = intitulé de l'offre
        );

        CREATE TABLE IF NOT EXISTS cv_corrections (
            id         INTEGER PRIMARY KEY,
            offer_id   INTEGER NOT NULL REFERENCES offers(id),
            action     TEXT NOT NULL, -- ajout|retrait (EXE-59)
            competence TEXT NOT NULL,
            maitrisee  INTEGER NOT NULL, -- 1 si dans un groupe, 0 si dans « Notions en : »
            groupe     TEXT, -- groupe touché ; NULL si l'action porte sur les notions
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS lettres (
            id                        INTEGER PRIMARY KEY,
            offer_id                  INTEGER NOT NULL REFERENCES offers(id),
            statut                    TEXT NOT NULL DEFAULT 'aucune', -- aucune|pending|done|error
            points_choisis_json       TEXT,  -- hérité (EXE-65 §H2) ; non lu par la génération depuis EXE-162
            points_choisis_origine    TEXT,  -- systeme|moi ; NULL = choix jamais posé (EXE-127)
            texte                     TEXT,
            tournures_signalees_json  TEXT,  -- JSON array des tournures interdites trouvées
            nb_mots                   INTEGER,
            depasse_longueur          INTEGER, -- 1 si nb_mots > 250 (EXE-162)
            modele                    TEXT,  -- nom du modèle fixé, enregistré (critère 21)
            session_id                TEXT,
            cost_usd                  REAL,
            prompt_text               TEXT,  -- hérité ; non écrit depuis EXE-162 (remplacé par appels_json)
            error_message             TEXT,
            created_at                TEXT NOT NULL,
            regeneration_en_cours     INTEGER NOT NULL DEFAULT 0, -- EXE-66
            regeneration_error        TEXT,  -- EXE-66 : dernier échec de régénération, distinct de error_message
            marque_pret_at            TEXT,  -- EXE-101 : date/heure de ma marque « Prête », NULL sinon
            fait_retenu_json          TEXT,  -- EXE-162 : fait de la fiche retenu par le tamis ; NULL = générique
            texte_type_id             TEXT,  -- EXE-162 : id du texte type du répertoire choisi par le tamis
            nb_tours                  INTEGER, -- EXE-162 : nombre de tours de la boucle (critère 5)
            raison_fin                TEXT,  -- EXE-162 : raison de fin de la boucle (critères 5, 9)
            jugement_json             TEXT,  -- EXE-162 : les quatre rubriques du juge sur la lettre finale
            releve_json               TEXT,  -- EXE-162 : dernier relevé du vérificateur (critère 5, 22)
            appels_json               TEXT,  -- EXE-162 : trace demande/réponse de chaque appel de la boucle
            faits_ecartes_json        TEXT NOT NULL DEFAULT '[]', -- EXE-162 : faits écartés (citation+lien)
            UNIQUE(offer_id)
        );

        CREATE TABLE IF NOT EXISTS lettre_versions (
            id                        INTEGER PRIMARY KEY,
            offer_id                  INTEGER NOT NULL REFERENCES offers(id),
            texte                     TEXT NOT NULL,
            tournures_signalees_json  TEXT,
            nb_mots                   INTEGER,
            depasse_longueur          INTEGER,
            origine                   TEXT NOT NULL, -- modele|moi (EXE-66)
            created_at                TEXT NOT NULL,
            fait_retenu_json          TEXT  -- EXE-162 : fait retenu derrière cette version (critère 7)
        );

        CREATE TABLE IF NOT EXISTS ajouts (
            id               INTEGER PRIMARY KEY,
            url              TEXT,  -- NULL : texte collé sans URL (EXE-82)
            texte            TEXT,  -- texte collé envoyé, rendu pour le reproposer (EXE-82)
            -- en_cours|termine|filtree|hors_perimetre|texte_a_coller|echec|deja_en_base (EXE-79)
            statut           TEXT NOT NULL DEFAULT 'en_cours',
            offer_id         INTEGER REFERENCES offers(id),
            categorie        TEXT,
            raison           TEXT,  -- raison du filtre dur si « filtrée »
            causes_json      TEXT,  -- JSON array des causes si « hors périmètre »
            message          TEXT,
            created_at       TEXT NOT NULL,
            finished_at      TEXT
        );
    """)
    migrate_offers_schema(conn)
    migrate_legacy_extraction_failures(conn)
    migrate_fiches_entreprise_schema(conn)
    migrate_cvs_schema(conn)
    migrate_lettres_schema(conn)
    migrate_lettre_versions_schema(conn)
    migrate_ajouts_schema(conn)
    migrate_verdicts_schema(conn)


def migrate_ajouts_schema(conn: sqlite3.Connection) -> None:
    """EXE-82 : `url` devient facultative et `texte` est ajoutée — idempotent.

    SQLite ne lève pas un NOT NULL par ALTER : la table est reconstruite, lignes
    conservées telles quelles (`texte` vide pour les ajouts d'avant)."""
    cols = {row[1]: row for row in conn.execute("PRAGMA table_info(ajouts)")}
    if "texte" in cols and not cols["url"][3]:
        return
    conn.executescript("""
        BEGIN;
        CREATE TABLE ajouts_exe82 (
            id               INTEGER PRIMARY KEY,
            url              TEXT,
            texte            TEXT,
            statut           TEXT NOT NULL DEFAULT 'en_cours',
            offer_id         INTEGER REFERENCES offers(id),
            categorie        TEXT,
            raison           TEXT,
            causes_json      TEXT,
            message          TEXT,
            created_at       TEXT NOT NULL,
            finished_at      TEXT
        );
        INSERT INTO ajouts_exe82 (id, url, statut, offer_id, categorie, raison,
                                  causes_json, message, created_at, finished_at)
            SELECT id, url, statut, offer_id, categorie, raison,
                   causes_json, message, created_at, finished_at
            FROM ajouts;
        DROP TABLE ajouts;
        ALTER TABLE ajouts_exe82 RENAME TO ajouts;
        COMMIT;
    """)


def migrate_verdicts_schema(conn: sqlite3.Connection) -> None:
    """EXE-139 : date/heure de ma marque « Candidature envoyée », distincte du
    statut retenu/rejeté/candidaté — idempotent."""
    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(verdicts)").fetchall()
    }
    if "envoyee_at" not in existing:
        conn.execute("ALTER TABLE verdicts ADD COLUMN envoyee_at TEXT")
    conn.commit()


def migrate_cvs_schema(conn: sqlite3.Connection) -> None:
    """Colonnes ajoutées après la première livraison (EXE-58, EXE-101) — idempotent."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(cvs)").fetchall()}
    for col in ("groupes_json", "notions_json", "marque_pret_at"):
        if col not in existing:
            conn.execute(f"ALTER TABLE cvs ADD COLUMN {col} TEXT")
    conn.commit()


def migrate_lettres_schema(conn: sqlite3.Connection) -> None:
    """Colonnes ajoutées après la première livraison (EXE-65, EXE-66, EXE-101) — idempotent."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(lettres)").fetchall()}
    if "regeneration_en_cours" not in existing:
        conn.execute(
            "ALTER TABLE lettres ADD COLUMN regeneration_en_cours "
            "INTEGER NOT NULL DEFAULT 0"
        )
    if "regeneration_error" not in existing:
        conn.execute("ALTER TABLE lettres ADD COLUMN regeneration_error TEXT")
    if "marque_pret_at" not in existing:
        conn.execute("ALTER TABLE lettres ADD COLUMN marque_pret_at TEXT")
    if "points_choisis_origine" not in existing:
        conn.execute("ALTER TABLE lettres ADD COLUMN points_choisis_origine TEXT")
    for col in (
        "fait_retenu_json",
        "texte_type_id",
        "raison_fin",
        "jugement_json",
        "releve_json",
        "appels_json",
    ):
        if col not in existing:
            conn.execute(f"ALTER TABLE lettres ADD COLUMN {col} TEXT")
    if "nb_tours" not in existing:
        conn.execute("ALTER TABLE lettres ADD COLUMN nb_tours INTEGER")
    if "faits_ecartes_json" not in existing:
        conn.execute(
            "ALTER TABLE lettres ADD COLUMN faits_ecartes_json TEXT NOT NULL DEFAULT '[]'"
        )
    conn.commit()


def migrate_lettre_versions_schema(conn: sqlite3.Connection) -> None:
    """Colonne ajoutée après la première livraison (EXE-162) — idempotente."""
    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(lettre_versions)").fetchall()
    }
    if "fait_retenu_json" not in existing:
        conn.execute("ALTER TABLE lettre_versions ADD COLUMN fait_retenu_json TEXT")
    conn.commit()


# Signature exacte des faits de repli produits par l'ancien `_fallback()` d'une
# extraction en échec, avant EXE-98 (scoring/extractor.py, historique figé ici).
_LEGACY_FALLBACK_FACTS_JSON = (
    '{"seniority_required":"intermediate","techs_required":[],"domain":"other",'
    '"role_level":"ic","langues_requises":[],"parse_failed":true}'
)


def migrate_legacy_extraction_failures(conn: sqlite3.Connection) -> None:
    """EXE-98 (architecture.md, exception TCK-273) : avant ce ticket, une extraction
    en échec persistait des faits de repli et finissait rangée « sans techno »,
    indiscernable d'une vraie offre sans technologie exigée. Toute offre non filtrée,
    jamais réextraite (`extraction_version IS NULL`), dont les faits enregistrés sont
    EXACTEMENT ce signal, repasse « à refaire » avec 1 essai et perd sa cause
    hors-périmètre. Idempotent : les faits sont effacés, un second passage ne
    retrouve plus la correspondance exacte."""
    conn.execute(
        """
        UPDATE offers
        SET extraction_status     = 'retry',
            extraction_attempts   = 1,
            extracted_facts_json  = NULL,
            hors_perimetre_reason = NULL,
            perimetre_causes      = NULL
        WHERE filtered_out = 0
          AND extraction_version IS NULL
          AND extraction_status IS NULL
          AND extracted_facts_json = ?
        """,
        (_LEGACY_FALLBACK_FACTS_JSON,),
    )
    conn.commit()


def migrate_fiches_entreprise_schema(conn: sqlite3.Connection) -> None:
    """Colonnes ajoutées après la première livraison + migration de données (idempotentes)."""
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(fiches_entreprise)").fetchall()
    }
    if "presentation" not in existing:
        conn.execute("ALTER TABLE fiches_entreprise ADD COLUMN presentation TEXT")

    # Corrections post-essai (2026-09-28) : tas 'ne_se_pretend_pas' → 'rien'. Les champs `reaction`
    # restent tels quels dans le JSON existant — plus lus ni écrits, mais non purgés (pas de perte).
    import json as _json

    for row in conn.execute(
        "SELECT offer_id, points_json FROM fiches_entreprise WHERE points_json IS NOT NULL"
    ):
        points = _json.loads(row["points_json"])
        changed = False
        for p in points:
            if p.get("tas") == "ne_se_pretend_pas":
                p["tas"] = "rien"
                changed = True
        if changed:
            conn.execute(
                "UPDATE fiches_entreprise SET points_json = ? WHERE offer_id = ?",
                (_json.dumps(points, ensure_ascii=False), row["offer_id"]),
            )
    conn.commit()


def migrate_offers_schema(conn: sqlite3.Connection) -> None:
    """Apply incremental column additions/removals to an existing offers table."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(offers)").fetchall()}

    add_cols = [
        ("description", "TEXT"),
        ("seen_candidat", "INTEGER NOT NULL DEFAULT 0"),
        ("nature_contract", "TEXT"),
        ("alternance", "INTEGER NOT NULL DEFAULT 0"),
        ("full_time", "INTEGER"),
        ("company_size", "TEXT"),
        ("experience_required", "TEXT"),
        ("rome_code", "TEXT"),
        ("rome_label", "TEXT"),
        ("extracted_facts_json", "TEXT"),
        ("filtered_out", "INTEGER NOT NULL DEFAULT 0"),
        ("filter_reason", "TEXT"),
        ("category", "TEXT"),
        # chantier hors-périmètre — dérivé, recalculé à chaque rescore
        ("hors_perimetre_reason", "TEXT"),
        # chantier review humaine — colonnes d'interaction (comme seen_candidat)
        ("categorie_suggeree", "TEXT"),
        ("categorie_corrigee", "TEXT"),
        ("remarque", "TEXT"),
        ("reviewed_at", "TEXT"),
        # chantier HTML→Markdown — brut source conservé, description = dérivé MD
        ("description_raw", "TEXT"),
        # chantier divergence front — matching techs persisté au (re)score
        ("techs_matched_json", "TEXT"),
        ("techs_missing_json", "TEXT"),
        # lot G — gates éliminatoires : causes multiples (JSON list)
        ("perimetre_causes", "TEXT"),
        # staleness : timestamp du dernier (re)score — comparé à reviewed_at
        ("rescored_at", "TEXT"),
        # chantier belge — langue de rédaction de l'annonce (fr|en|nl|other)
        ("ad_language", "TEXT"),
        # TCK-211 — version de l'extraction (modèle + empreinte prompt + schéma)
        ("extraction_version", "TEXT"),
        # EXE-98/EXE-99 — état d'une extraction qui n'a pas (encore) produit de
        # faits définitifs : NULL (normal) | pending | retry | unreadable |
        # second_pass_pending (architecture.md TCK-273) | missing_text (EXE-115,
        # architecture.md « Offre sans texte »)
        ("extraction_status", "TEXT"),
        ("extraction_attempts", "INTEGER NOT NULL DEFAULT 0"),
        # EXE-99 — essais du modèle de précision sur une offre classée
        # parfait/rêve par le tri, indépendant d'extraction_attempts (lecture)
        ("second_pass_attempts", "INTEGER NOT NULL DEFAULT 0"),
    ]
    for col, col_type in add_cols:
        if col not in existing:
            conn.execute(f"ALTER TABLE offers ADD COLUMN {col} {col_type}")

    # Renommage seen → seen_candidat (chantier vue candidat)
    if "seen" in existing and "seen_candidat" not in existing:
        conn.execute("ALTER TABLE offers RENAME COLUMN seen TO seen_candidat")

    # Suppression des anciens champs de scoring Zone A
    for col in ("score", "criteria_json"):
        if col in existing:
            conn.execute(f"ALTER TABLE offers DROP COLUMN {col}")

    # Chantier review humaine — drop scoring /10-/100 (L5)
    for col in (
        "desirability",
        "desirability_detail",
        "attainability",
        "attainability_detail",
        "score_in_category",
        "attain_tech",
        "attain_role",
        "blocked_by",
    ):
        if col in existing:
            conn.execute(f"ALTER TABLE offers DROP COLUMN {col}")

    conn.commit()
