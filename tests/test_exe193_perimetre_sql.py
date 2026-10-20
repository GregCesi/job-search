"""Tests EXE-193 — critères 28 et 29 : seule la persistance du module d'états
et le code de la reprise touchent le tri, l'étape, l'historique des gestes, la
revue hors périmètre ou la table `verdicts` (architecture.md, TCK-311)."""

import ast
import inspect
import re

from orchestrator.job_search.paths import REPO_ROOT
from orchestrator.job_search.suivi import etats

_TABLES = ["verdicts", "etats_offre", "historique_gestes", "revues_hors_perimetre"]
_SQL_PATTERN = re.compile(
    r"(FROM|JOIN|INTO|UPDATE|TABLE)\s+(" + "|".join(_TABLES) + r")\b",
    re.IGNORECASE,
)

_EXEMPTS = {
    REPO_ROOT / "orchestrator" / "job_search" / "suivi" / "storage.py",
    REPO_ROOT / "orchestrator" / "job_search" / "suivi" / "reprise.py",
    REPO_ROOT / "orchestrator" / "job_search" / "storage" / "db.py",
}


class TestCritere29SeuleLaPersistanceToucheLeTriEtLetape:
    def test_aucune_requete_sql_ailleurs_dans_api_et_orchestrator(self):
        violations = []
        for base in (REPO_ROOT / "api", REPO_ROOT / "orchestrator"):
            for path in base.rglob("*.py"):
                if path in _EXEMPTS:
                    continue
                text = path.read_text(encoding="utf-8")
                if _SQL_PATTERN.search(text):
                    violations.append(str(path.relative_to(REPO_ROOT)))
        assert violations == []


class TestCritere28ModuleEtatsPur:
    def test_etats_nimporte_ni_fastapi_ni_sqlite3(self):
        source = inspect.getsource(etats)
        tree = ast.parse(source)
        noms_importes = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                noms_importes.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                noms_importes.add(node.module)
        assert not any("fastapi" in n or "sqlite3" in n for n in noms_importes)
