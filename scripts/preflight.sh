#!/usr/bin/env bash
# Pré-vol d'aptitude de l'environnement d'exécution, version Python — TCK-235.
# Répond à « mon environnement est-il apte », jamais à « mon travail est-il bon ».
# Lancé par jet.sh dans le worktree avant l'agent, et à la racine après chaque merge.
# Codes lus par jet.sh : 0 apte, 2 requirements.txt absent (rien à vérifier),
# tout autre code = inapte.
#
# Un worktree est une copie fraîche : .venv/ est ignoré par git, donc absent. Ce
# script le pose, y installe exactement requirements.txt et requirements-dev.txt,
# puis vérifie que la suite de tests passe sur l'état d'entrée. Une suite rouge à
# l'entrée rendrait la barre rouge pour tout ticket, quel que soit son travail.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

[ -f "$ROOT/requirements.txt" ] || {
  echo "PRÉ-VOL: requirements.txt absent à $ROOT — environnement non initialisé." >&2
  exit 2
}

VENV="$ROOT/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "PRÉ-VOL: .venv absent, création."
  if command -v uv >/dev/null 2>&1; then
    uv venv --quiet --python 3.14 "$VENV" || uv venv --quiet "$VENV"
  else
    PYBIN=""
    for c in python3.14 python3.13 python3.12 python3; do
      command -v "$c" >/dev/null 2>&1 && { PYBIN="$c"; break; }
    done
    [ -n "$PYBIN" ] || { echo "PRÉ-VOL: aucun python3 trouvé." >&2; exit 1; }
    "$PYBIN" -m venv "$VENV"
  fi
fi

echo "PRÉ-VOL: installation de requirements.txt et requirements-dev.txt"
if command -v uv >/dev/null 2>&1; then
  uv pip install --quiet --python "$VENV/bin/python" -r requirements.txt -r requirements-dev.txt
else
  "$VENV/bin/python" -m pip install --quiet -r requirements.txt -r requirements-dev.txt
fi

"$VENV/bin/ruff" --version

echo "PRÉ-VOL: suite de tests sur l'état d'entrée"
PYTHONDONTWRITEBYTECODE=1 "$VENV/bin/python" -m pytest -q

echo "PRÉ-VOL: apte."
