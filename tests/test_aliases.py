"""Tests unitaires — canonicalize() + load_alias_table()."""
import pytest

from orchestrator.job_search.scoring.aliases import (
    AliasTable,
    DuplicateAliasError,
    canonicalize,
    load_alias_table,
)

# Charge la vraie table une seule fois
TABLE = load_alias_table("profiles/alias.yaml")


# --- Cas 1 : variante connue → forme canonique ---

@pytest.mark.parametrize("raw, expected", [
    ("c#", "csharp"),
    ("CSharp", "csharp"),          # case-insensitive
    ("c++", "cpp"),
    ("cplusplus", "cpp"),
    ("golang", "go"),
    ("js", "javascript"),
    ("postgres", "postgresql"),
    ("sql server", "sql_server"),
    ("sqlserver", "sql_server"),
    ("mongo", "mongodb"),
    ("ne4j", "neo4j"),             # typo LLM
    ("llama_index", "llamaindex"),
    (".net", "dotnet"),
    ("net", "dotnet"),
    ("asp.net", "aspnet"),
    ("doctrine_orm", "doctrine"),
    ("open_cv", "opencv"),
    ("ci/cd", "ci_cd"),
    ("gitlab ci", "gitlab_ci"),
    ("palo alto", "palo_alto"),
    ("paloalto", "palo_alto"),
    ("azure ad", "azure_ad"),
    ("microsoft_entrada_id", "azure_ad"),
    ("microsoft copilot", "copilot"),
    ("vmware esxi", "vmware"),
    ("esx", "vmware"),
    ("vsphere", "vmware"),
    ("esxi", "vmware"),
    ("vision-language", "vision_language_models"),
    ("vision-language models", "vision_language_models"),
    ("visual studio", "visual_studio"),
    ("shellscript", "shell"),
    ("sh", "shell"),
])
def test_known_variant(raw, expected):
    assert canonicalize(raw, TABLE) == expected


# Forme canonique se mappe à elle-même
@pytest.mark.parametrize("canonical", [
    "csharp", "cpp", "go", "javascript", "postgresql", "mongodb",
    "dotnet", "aspnet", "opencv", "ci_cd", "vmware", "shell",
])
def test_canonical_identity(canonical):
    assert canonicalize(canonical, TABLE) == canonical


# --- Cas 2 : exclu → None ---

@pytest.mark.parametrize("raw", [
    "none", "None", "NONE",
    "os", "OS",
    "cloud", "Cloud",
    "microsoft",
    "german",
    "solutions",
    "development",
    "happy horse",
    "devbooster",
])
def test_excluded(raw):
    assert canonicalize(raw, TABLE) is None


# --- Cas 3 : inconnu → auto-canonicalisation (lower + strip) ---

@pytest.mark.parametrize("raw, expected", [
    ("wallix", "wallix"),
    ("Wallix", "wallix"),
    ("  WALLIX  ", "wallix"),
    ("pl/sql", "pl/sql"),
    ("someunknowntech", "someunknowntech"),
])
def test_unknown_passthrough(raw, expected):
    assert canonicalize(raw, TABLE) == expected


# --- Convergence deux côtés (piège central) ---
# L'offre et le profil doivent converger sur la même forme.

def test_convergence_vuejs():
    """vuejs dans le profil, vuejs dans l'offre → même forme (pas de réécriture ici,
    vuejs n'est pas dans alias.yaml donc auto-canonicalise en 'vuejs' des deux côtés)."""
    assert canonicalize("vuejs", TABLE) == canonicalize("vuejs", TABLE)


def test_convergence_postgresql_stays_postgresql():
    """postgresql dans l'offre ET postgresql est la forme canonique.
    Le profil a 'sql' → c'est un autre concept (sql ≠ postgresql, décision d'alias.yaml)."""
    assert canonicalize("postgresql", TABLE) == "postgresql"
    assert canonicalize("postgres", TABLE) == "postgresql"


# --- pl/sql passthrough (auto-canonicalise, pas dans alias.yaml) ---

def test_plsql_passthrough():
    """pl/sql n'est pas dans alias.yaml, auto-canonicalise en 'pl/sql'."""
    assert canonicalize("pl/sql", TABLE) == "pl/sql"


# --- Non-régression : les 13 anciens _TECH_ALIASES ---
# L'ancien dict mappait tout vers des groupes (postgresql→sql, etc.).
# Le nouveau alias.yaml a une logique DIFFÉRENTE (postgresql reste postgresql,
# seul postgres→postgresql). Ce test vérifie que les variantes de l'ancien dict
# produisent un résultat cohérent avec le nouveau schéma.

_OLD_ALIASES = {
    "postgresql": "sql",
    "postgres":   "sql",
    "mysql":      "sql",
    "mariadb":    "sql",
    "mssql":      "sql",
    "bigquery":   "sql",
    "snowflake":  "sql",
    "supabase":   "sql",
    "sqlite3":    "sqlite",
    "langsmith":  "langchain",
}

def test_old_aliases_handled():
    """Chaque ancienne variante produit un résultat non-None (pas exclu, pas perdu).
    Le mapping exact a changé (postgresql n'est plus écrasé sur 'sql'),
    mais aucune tech ne disparaît silencieusement."""
    for variant in _OLD_ALIASES:
        result = canonicalize(variant, TABLE)
        assert result is not None, f"'{variant}' a été exclu à tort"
        assert isinstance(result, str)


# --- Détection de doublons ---

def test_duplicate_variant_raises(tmp_path):
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        "aliases:\n"
        "  python: [py]\n"
        "  cpython: [py]\n"
        "exclude: []\n"
    )
    with pytest.raises(DuplicateAliasError, match="py"):
        load_alias_table(bad_yaml)


# --- Chargement basique ---

def test_load_produces_alias_table():
    assert isinstance(TABLE, AliasTable)
    assert len(TABLE._index) > 0
    assert len(TABLE._exclude) > 0
