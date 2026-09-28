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
            points_json           TEXT,   -- JSON array [{position,citation,url,tas,explication}]
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
            UNIQUE(offer_id)
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
    """)
    migrate_offers_schema(conn)
    migrate_fiches_entreprise_schema(conn)
    migrate_cvs_schema(conn)


def migrate_cvs_schema(conn: sqlite3.Connection) -> None:
    """Colonnes ajoutées après la première livraison (EXE-58) — idempotent."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(cvs)").fetchall()}
    for col in ("groupes_json", "notions_json"):
        if col not in existing:
            conn.execute(f"ALTER TABLE cvs ADD COLUMN {col} TEXT")
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
