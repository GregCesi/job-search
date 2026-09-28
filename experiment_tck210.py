"""
TCK-210 — Comparaison llama3 / gemma4:12b sur un échantillon d'offres.

Mêmes réglages que la prod depuis TCK-209 : prompt et few-shot de extractor.py,
temperature 0.1, num_ctx 8192, think=False. Une tentative par offre (la prod en fait
jusqu'à 3) : parse_failed mesure la première réponse.

Lecture seule SQLite, aucun appel à extract_facts, aucune trace de production.
Sortie : data/experiment_tck210/ (runs.jsonl + report.md). Le rapport mesure, il ne conclut pas.

Usage:
  python experiment_tck210.py            # 2 modèles × N offres
  python experiment_tck210.py --dry-run  # affiche l'échantillon, 0 appel Ollama
"""
import argparse
import json
import os
import random
import sqlite3
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import ollama

from orchestrator.job_search.scoring.extractor import (
    _SYSTEM_PROMPT, _FEW_SHOT, _EXPERIENCE_HINT, _NUM_CTX,
    _SENIORITY_VALID, _ROLE_VALID, _IMPORTANCE_VALID, _DOMAIN_VALID,
)

DB_PATH = Path(__file__).parent / "data" / "job_search.sqlite"
OUT_DIR = Path(__file__).parent / "data" / "experiment_tck210"
MODELS = ["llama3", "gemma4:12b"]
SEED = 210
PER_CATEGORY = {"parfait": 6, "reve": 6, "atteignable": 6, "hors": 5}
FORCED = [2874]  # offre de TCK-200


def _conn():
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _sample() -> list[sqlite3.Row]:
    c = _conn()
    rng = random.Random(SEED)
    ids = list(FORCED)
    for cat, n in PER_CATEGORY.items():
        pool = [r[0] for r in c.execute(
            "SELECT id FROM offers WHERE category = ? AND filtered_out = 0 "
            "AND description IS NOT NULL AND id NOT IN (%s) ORDER BY id" % ",".join("?" * len(FORCED)),
            (cat, *FORCED))]
        ids += rng.sample(pool, min(n, len(pool)))
    rows = [c.execute(
        "SELECT id, source, title, company, location, category, description, "
        "experience_required, rome_label, alternance FROM offers WHERE id = ?", (i,)).fetchone() for i in ids]
    c.close()
    return rows


def _user_prompt(o) -> str:
    hints = []
    if o["experience_required"]:
        hints.append(f"Experience hint: {_EXPERIENCE_HINT.get(o['experience_required'], o['experience_required'])}")
    if o["rome_label"]:
        hints.append(f"ROME classification: {o['rome_label']}")
    if o["alternance"]:
        hints.append("Note: this is an apprenticeship offer (alternance).")
    return (f"{_FEW_SHOT}\nTitle: {o['title']}\nDescription: {o['description'][:8000]}\n"
            + ("\n".join(hints) + "\n" if hints else "") + "Extract facts now:")


def _parse(raw: str) -> tuple[list[str], bool]:
    """Même logique que extractor.py : (techs, parse_failed) — dégradation incluse."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```")[1]
        if s.startswith("json"):
            s = s[4:]
    if s.startswith("→"):
        s = s.lstrip("→").strip()
    try:
        d = json.loads(s)
    except Exception:
        return [], True
    degraded = False
    techs = []
    for it in d.get("techs_required", []) or []:
        if isinstance(it, str):
            if it.strip():
                techs.append(it.lower().strip()); degraded = True
        elif isinstance(it, dict):
            n = str(it.get("name", "")).lower().strip()
            if n:
                techs.append(n)
                if str(it.get("importance", "")).lower() not in _IMPORTANCE_VALID:
                    degraded = True
    if str(d.get("seniority_required", "")).lower() not in _SENIORITY_VALID: degraded = True
    if str(d.get("domain", "")).lower() not in _DOMAIN_VALID: degraded = True
    if str(d.get("role_level", "ic")).lower() not in _ROLE_VALID: degraded = True
    return techs, degraded


def _call(client, model, o) -> dict:
    t0 = time.perf_counter()
    try:
        r = client.chat(model=model,
                        messages=[{"role": "system", "content": _SYSTEM_PROMPT},
                                  {"role": "user", "content": _user_prompt(o)}],
                        options={"temperature": 0.1, "num_ctx": _NUM_CTX}, think=False)
        wall = time.perf_counter() - t0
        raw = r.message.content or ""
        techs, pf = _parse(raw)
        ns = lambda k: (getattr(r, k, None) or 0) / 1e9
        return {"raw_response": raw, "techs": techs, "parse_failed": pf, "error": None,
                "wall_s": round(wall, 2), "total_s": round(ns("total_duration"), 2),
                "load_s": round(ns("load_duration"), 2),
                "prompt_eval_count": getattr(r, "prompt_eval_count", None),
                "eval_count": getattr(r, "eval_count", None),
                "done_reason": getattr(r, "done_reason", None)}
    except Exception as e:
        return {"raw_response": "", "techs": [], "parse_failed": True, "error": str(e),
                "wall_s": round(time.perf_counter() - t0, 2), "total_s": None, "load_s": None,
                "prompt_eval_count": None, "eval_count": None, "done_reason": None}


def _counts() -> dict:
    c = _conn()
    q = lambda sql: c.execute(sql).fetchone()[0]
    out = {
        "toute la base": q("SELECT count(*) FROM offers"),
        "filtered_out = 0": q("SELECT count(*) FROM offers WHERE filtered_out = 0"),
        "filtered_out = 0, catégorie ≠ hors": q("SELECT count(*) FROM offers WHERE filtered_out = 0 AND category IN ('parfait','reve','atteignable')"),
        "source eures (Belgique)": q("SELECT count(*) FROM offers WHERE source = 'eures'"),
    }
    c.close()
    return out


def _run(host: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    offers = _sample()
    client = ollama.Client(host=host)
    version = "?"
    try:
        import requests
        version = requests.get(f"{host}/api/version", timeout=5).json().get("version", "?")
    except Exception:
        pass
    results: dict[tuple[int, str], dict] = {}
    with (OUT_DIR / "runs.jsonl").open("w", encoding="utf-8") as fp:
        for model in MODELS:  # un modèle à la fois : un seul chargement
            print(f"== {model} : chauffe (appel jeté) …", flush=True)
            _call(client, model, offers[0])
            for i, o in enumerate(offers, 1):
                res = _call(client, model, o)
                results[(o["id"], model)] = res
                print(f"{model} {i}/{len(offers)} offre {o['id']} — {res['wall_s']}s, "
                      f"{len(res['techs'])} techs, parse_failed={res['parse_failed']}", flush=True)
                fp.write(json.dumps({"offer_id": o["id"], "model": model, **res,
                                     "timestamp": datetime.now(timezone.utc).isoformat()},
                                    ensure_ascii=False) + "\n")
                fp.flush()
    _report(offers, results, version)
    print(f"Rapport : {OUT_DIR / 'report.md'}")


def _report(offers, results, version) -> None:
    L = ["# TCK-210 — llama3 contre gemma4:12b\n",
         f"Ollama `{version}` · temperature 0.1 · num_ctx {_NUM_CTX} · think=False · 1 tentative par offre · "
         f"{len(offers)} offres (graine {SEED}, offre 2874 forcée) · {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n",
         "Temps d'appel = `total_duration` Ollama hors chargement du modèle (un appel de chauffe jeté par modèle).\n",
         "## Par offre\n",
         "| Offre | Source | Cat. actuelle | Titre | llama3 | gemma4:12b | Seulement llama3 | Seulement gemma4 | parse_failed l / g | Temps l / g (s) |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for o in offers:
        a, b = results[(o["id"], "llama3")], results[(o["id"], "gemma4:12b")]
        sa, sb = set(a["techs"]), set(b["techs"])
        f = lambda xs: ", ".join(xs) if xs else "—"
        t = lambda r: r["total_s"] - (r["load_s"] or 0) if r["total_s"] is not None else None
        ts = lambda v: f"{v:.1f}" if v is not None else "err"
        L.append(f"| {o['id']} | {o['source']} | {o['category']} | {o['title'][:50].replace('|','/')} "
                 f"| {f(a['techs'])} | {f(b['techs'])} | {f(sorted(sa - sb))} | {f(sorted(sb - sa))} "
                 f"| {'✓' if a['parse_failed'] else '✗'} / {'✓' if b['parse_failed'] else '✗'} "
                 f"| {ts(t(a))} / {ts(t(b))} |")
    L += ["", "## Totaux\n", "| | llama3 | gemma4:12b |", "|---|---|---|"]
    stats = {}
    for m in MODELS:
        ts_ = [r["total_s"] - (r["load_s"] or 0) for (oid, mm), r in results.items() if mm == m and r["total_s"] is not None]
        stats[m] = {"mean": statistics.mean(ts_) if ts_ else 0, "median": statistics.median(ts_) if ts_ else 0,
                    "max": max(ts_) if ts_ else 0,
                    "pf": sum(r["parse_failed"] for (oid, mm), r in results.items() if mm == m),
                    "err": sum(r["error"] is not None for (oid, mm), r in results.items() if mm == m),
                    "n_techs": statistics.mean([len(r["techs"]) for (oid, mm), r in results.items() if mm == m])}
    rowf = lambda label, key, fmt: L.append(f"| {label} | {fmt(stats['llama3'][key])} | {fmt(stats['gemma4:12b'][key])} |")
    rowf("Temps moyen par offre (s)", "mean", lambda v: f"{v:.1f}")
    rowf("Temps médian par offre (s)", "median", lambda v: f"{v:.1f}")
    rowf("Temps max (s)", "max", lambda v: f"{v:.1f}")
    rowf("parse_failed", "pf", str)
    rowf("Erreurs d'appel", "err", str)
    rowf("Techs extraites par offre (moyenne)", "n_techs", lambda v: f"{v:.1f}")
    L += ["", "## Temps estimé de réextraction\n",
          "Le périmètre de TCK-211 n'est pas choisi au 22 septembre 2026. Estimation = nombre d'offres × temps moyen mesuré.\n",
          "| Périmètre candidat | Offres | llama3 | gemma4:12b |", "|---|---|---|---|"]
    h = lambda s: f"{s/3600:.1f} h" if s >= 3600 else f"{s/60:.0f} min"
    for label, n in _counts().items():
        L.append(f"| {label} | {n} | {h(n*stats['llama3']['mean'])} | {h(n*stats['gemma4:12b']['mean'])} |")
    (OUT_DIR / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--host", default=os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    a = p.parse_args()
    if a.dry_run:
        for o in _sample():
            print(o["id"], o["source"], o["category"], o["title"][:60])
        print(_counts())
    else:
        _run(a.host)
