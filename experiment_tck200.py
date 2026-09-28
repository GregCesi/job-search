"""
TCK-200 — Expérience extraction 6 variantes × 3 répétitions.

Script autonome, lecture seule SQLite, 0 appel LLM via wrapper, 0 écriture trace.
Résultats dans data/experiment_tck200/.

Usage:
  python experiment_tck200.py           # 18 appels Ollama
  python experiment_tck200.py --dry-run # construit les 6 prompts, 0 appel Ollama
"""
import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import requests

import ollama

# ---------------------------------------------------------------------------
# Imports des constantes module-level uniquement (pas la fonction d'ingestion)
# ---------------------------------------------------------------------------
from orchestrator.job_search.scoring.extractor import (
    _SYSTEM_PROMPT,
    _FEW_SHOT,
    _EXPERIENCE_HINT,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
DB_PATH = Path(__file__).parent / "data" / "job_search.sqlite"
OUT_DIR = Path(__file__).parent / "data" / "experiment_tck200"
OFFER_ID = 2874

VARIANTS = {
    "A": ("llama3",      "current", {}),
    "B": ("gemma4:12b",  "current", {}),
    "C": ("llama3",      "skills",  {}),
    "D": ("gemma4:12b",  "skills",  {}),
    "E": ("llama3.1:8b", "current", {}),
    "F": ("llama3",      "current", {"num_ctx": 8192}),
}
REPS = 3

# ---------------------------------------------------------------------------
# Prompts variantes C / D — substitutions inline
# ---------------------------------------------------------------------------
def _make_skills_prompts() -> tuple[str, str]:
    """Retourne (_SYSTEM_PROMPT_C, _FEW_SHOT_C) avec substitutions C/D."""
    sp_c = _SYSTEM_PROMPT.replace(
        "techs_required", "skills_required"
    ).replace(
        "specific technology names only",
        "compétences techniques, outils ou pratiques",
    )
    fs_c = _FEW_SHOT.replace("techs_required", "skills_required")
    return sp_c, fs_c


_SYSTEM_PROMPT_C, _FEW_SHOT_C = _make_skills_prompts()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _read_offer() -> dict:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = conn.execute(
        "SELECT title, description, experience_required, rome_label, alternance "
        "FROM offers WHERE id = ?",
        (OFFER_ID,),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise RuntimeError(f"Offer {OFFER_ID} not found in {DB_PATH}")
    keys = ("title", "description", "experience_required", "rome_label", "alternance")
    return dict(zip(keys, row))


def _build_user_prompt(offer: dict, schema: str) -> str:
    """Reconstruit le user_prompt selon extractor.py lignes 123-131."""
    few_shot = _FEW_SHOT if schema == "current" else _FEW_SHOT_C
    hints: list[str] = []
    if offer["experience_required"]:
        hints.append(
            f"Experience hint: {_EXPERIENCE_HINT.get(offer['experience_required'], offer['experience_required'])}"
        )
    if offer["rome_label"]:
        hints.append(f"ROME classification: {offer['rome_label']}")
    if offer["alternance"]:
        hints.append("Note: this is an apprenticeship offer (alternance).")
    return (
        f"{few_shot}\n"
        f"Title: {offer['title']}\n"
        f"Description: {offer['description'][:8000]}\n"
        + ("\n".join(hints) + "\n" if hints else "")
        + "Extract facts now:"
    )


def _read_num_ctx(client: ollama.Client, model_name: str) -> str:
    try:
        params = client.show(model_name).parameters or ""
        for line in params.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] == "num_ctx":
                return parts[1]
    except Exception:
        pass
    return "non déclaré"


def _parse_techs(raw: str, schema: str) -> tuple[list[str], bool]:
    """Best-effort JSON parse, retourne (techs_lowercase, parse_failed)."""
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```")[1]
        if stripped.startswith("json"):
            stripped = stripped[4:]
    if stripped.startswith("→"):
        stripped = stripped.lstrip("→").strip()
    try:
        data = json.loads(stripped)
        raw_list = data.get("techs_required") or data.get("skills_required") or []
        techs = []
        for item in raw_list:
            if isinstance(item, dict):
                name = str(item.get("name", "")).lower().strip()
            elif isinstance(item, str):
                name = item.lower().strip()
            else:
                continue
            if name:
                techs.append(name)
        return techs, False
    except Exception:
        return [], True


def _detect(techs: list[str]) -> dict:
    mlops = any("mlops" in t for t in techs)
    mlflow = any("mlflow" in t for t in techs)
    cicd = any(
        tok in t for t in techs for tok in ("ci/cd", "ci_cd", "cicd", "ci-cd")
    )
    return {"mlops_found": mlops, "mlflow_found": mlflow, "cicd_found": cicd}


# ---------------------------------------------------------------------------
# Dry-run: vérification des substitutions
# ---------------------------------------------------------------------------
def _dry_run(offer: dict) -> None:
    print("=== DRY-RUN TCK-200 ===\n")

    # Compter occurrences dans _SYSTEM_PROMPT avant/après
    sp_count_before = _SYSTEM_PROMPT.count("specific technology names only")
    sp_techs_before = _SYSTEM_PROMPT.count("techs_required")
    print(f'_SYSTEM_PROMPT: "specific technology names only" count = {sp_count_before}')
    print(f'_SYSTEM_PROMPT: "techs_required" count = {sp_techs_before}')

    sp_c_techs = _SYSTEM_PROMPT_C.count("techs_required")
    sp_c_changed = _SYSTEM_PROMPT_C != _SYSTEM_PROMPT
    print(f'_SYSTEM_PROMPT_C != _SYSTEM_PROMPT : {sp_c_changed}')
    print(f'_SYSTEM_PROMPT_C: "techs_required" count = {sp_c_techs}  (expected 0)')

    fs_c_techs = _FEW_SHOT_C.count("techs_required")
    print(f'_FEW_SHOT_C: "techs_required" count = {fs_c_techs}  (expected 0)')

    print()
    for vid, (model, schema, _extra) in VARIANTS.items():
        up = _build_user_prompt(offer, schema)
        sp = _SYSTEM_PROMPT if schema == "current" else _SYSTEM_PROMPT_C
        print(
            f"Variant {vid} ({model}, {schema}): "
            f"system_prompt len={len(sp)}, user_prompt len={len(up)}"
        )
    print("\nDry-run OK — 0 appel Ollama.")


# ---------------------------------------------------------------------------
# Exécution principale
# ---------------------------------------------------------------------------
def _run(offer: dict, host: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    runs_path = OUT_DIR / "runs.jsonl"
    report_path = OUT_DIR / "report.md"

    client = ollama.Client(host=host)

    # Version Ollama
    try:
        ollama_version = requests.get(f"{host}/api/version", timeout=5).json().get(
            "version", "unknown"
        )
    except Exception:
        ollama_version = "unreachable"

    # num_ctx par modèle distinct
    distinct_models = {v[0] for v in VARIANTS.values()}
    num_ctx_by_model: dict[str, str] = {}
    for m in distinct_models:
        num_ctx_by_model[m] = _read_num_ctx(client, m)
        print(f"num_ctx {m}: {num_ctx_by_model[m]}")

    rows: list[dict] = []

    with runs_path.open("w", encoding="utf-8") as fp:
        for vid, (model, schema, extra_opts) in VARIANTS.items():
            system_prompt = _SYSTEM_PROMPT if schema == "current" else _SYSTEM_PROMPT_C
            user_prompt = _build_user_prompt(offer, schema)
            opts = {"temperature": 0.1, **extra_opts}
            num_ctx_force = extra_opts.get("num_ctx", None)

            for rep in range(1, REPS + 1):
                print(f"Running {vid}-{rep} ({model}, {schema}) …", end=" ", flush=True)
                raw_response = ""
                prompt_eval_count = None
                parse_failed = False
                techs: list[str] = []

                try:
                    resp = client.chat(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        options=opts,
                    )
                    raw_response = resp.message.content
                    prompt_eval_count = getattr(resp, "prompt_eval_count", None)
                    techs, parse_failed = _parse_techs(raw_response, schema)
                    print(f"OK — {len(techs)} techs, prompt_eval={prompt_eval_count}")
                except Exception as exc:
                    raw_response = str(exc)
                    parse_failed = True
                    print(f"ERROR — {exc}")

                detection = _detect(techs)
                row = {
                    "variant": vid,
                    "rep": rep,
                    "model": model,
                    "schema": schema,
                    "techs": techs,
                    **detection,
                    "prompt_eval_count": prompt_eval_count,
                    "num_ctx_declare_modelfile": num_ctx_by_model.get(model, "non déclaré"),
                    "num_ctx_force": num_ctx_force,
                    "ollama_version": ollama_version,
                    "parse_failed": parse_failed,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "raw_response": raw_response,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                fp.write(json.dumps(row, ensure_ascii=False) + "\n")
                fp.flush()
                rows.append(row)

    # Rapport Markdown
    _write_report(report_path, rows, ollama_version)
    print(f"\nRapport écrit dans {report_path}")


def _write_report(path: Path, rows: list[dict], ollama_version: str) -> None:
    lines = [
        "# TCK-200 — Rapport d'expérience\n",
        f"Ollama version : `{ollama_version}`\n",
        "Note : `num_ctx` non fixé dans les options sauf variante F (8192) "
        "— valeur déclarée par modèle lue via `client.show()`.\n",
        "",
        "| Variante | Rép | Modèle | Schéma | Techs extraites | mlops | mlflow | ci/cd "
        "| prompt_eval_count | num_ctx_declare_modelfile | num_ctx_force | parse_failed |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        techs_str = ", ".join(r["techs"]) if r["techs"] else "—"
        num_ctx_force = str(r["num_ctx_force"]) if r["num_ctx_force"] is not None else "—"
        pec = str(r["prompt_eval_count"]) if r["prompt_eval_count"] is not None else "—"
        lines.append(
            f"| {r['variant']} | {r['rep']} | {r['model']} | {r['schema']} "
            f"| {techs_str} "
            f"| {'✓' if r['mlops_found'] else '✗'} "
            f"| {'✓' if r['mlflow_found'] else '✗'} "
            f"| {'✓' if r['cicd_found'] else '✗'} "
            f"| {pec} "
            f"| {r['num_ctx_declare_modelfile']} "
            f"| {num_ctx_force} "
            f"| {'✓' if r['parse_failed'] else '✗'} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--host", default=os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    args = parser.parse_args()

    offer = _read_offer()

    if args.dry_run:
        _dry_run(offer)
    else:
        _run(offer, args.host)
