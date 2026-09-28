"""
TCK-206 — Fiche entreprise via claude -p (headless, WebSearch + WebFetch).

Teste si Claude Code lancé en sous-processus peut identifier l'employeur réel,
chercher sur lui et restituer ses positions avec leurs sources.

Lecture seule SQLite. Aucun appel à l'orchestrateur, aucune écriture en base.
Sortie : data/experiment_tck206/ (runs.jsonl + report.md + schema.json).

Usage:
  python experiment_tck206.py                 # 3 offres (2874, 155, 2499)
  python experiment_tck206.py --offer 2874    # une seule offre
  python experiment_tck206.py --dry-run       # affiche offres + prompt, 0 appel claude
"""
import argparse
import json
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

DB_PATH = Path(__file__).parent / "data" / "job_search.sqlite"
OUT_DIR = Path(__file__).parent / "data" / "experiment_tck206"
OFFERS = [2874, 155, 2499]
TIMEOUT_S = 900  # 15 min par offre

# ---------------------------------------------------------------------------
# Schéma de sortie structurée
# ---------------------------------------------------------------------------
SCHEMA = {
    "type": "object",
    "properties": {
        "employeur": {
            "type": "object",
            "properties": {
                "nom":            {"type": ["string", "null"]},
                "entite_precise": {"type": ["string", "null"]},
                "type_source":    {"type": "string", "enum": ["direct", "agence", "agregateur", "inconnu"]},
                "methode":        {"type": "string"},
                "confiance":      {"type": "string", "enum": ["sur", "probable", "non_trouve"]},
                "urls":           {"type": "array", "items": {"type": "string"}},
            },
            "required": ["nom", "entite_precise", "type_source", "methode", "confiance", "urls"],
        },
        "points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "position": {"type": "string"},
                    "citation": {"type": "string"},
                    "url":      {"type": "string"},
                },
                "required": ["position", "citation", "url"],
            },
        },
        "manques":  {"type": "array", "items": {"type": "string"}},
        "requetes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["employeur", "points", "manques", "requetes"],
}

# ---------------------------------------------------------------------------
# Prompt — inchangé entre les offres (le jet mesure ce prompt-là)
# ---------------------------------------------------------------------------
_PROMPT_TEMPLATE = """\
Tu prépares la fiche d'une entreprise qui recrute, pour un candidat qui va y postuler. Tu ne rédiges rien pour lui et tu ne donnes pas ton avis.

Étapes, dans l'ordre :
1. Pars de l'annonce ci-dessous. Cherche qui recrute vraiment, pas qui diffuse l'annonce.
2. Classe la source : employeur direct, agence de recrutement (l'employeur final est masqué) ou agrégateur (un canal, pas un employeur). Si l'employeur est masqué, relève les indices de l'annonce (secteur, ville, taille, produit) et cherche avec.
3. Identifie l'entité précise qui recrute, pas seulement le groupe.
4. Ouvre son site propre, puis sa page carrière, puis le site corporate, dans cet ordre.
5. Note ce que ces sources ne donnent pas. Si elles sont pauvres, cherche ailleurs : entité sœur, presse, prises de parole publiques.
6. Cherche qui dirige le service qui recrute et ce que cette personne a publié.
7. Restitue les positions de l'entreprise et de ce dirigeant point par point, sans les commenter.

Règles :
- « non trouvé » est une réponse valide. Préfère-la à une supposition. Si tu hésites entre deux employeurs, mets la confiance à « probable » et dis pourquoi dans `methode`.
- Chaque point porte l'URL de la page d'où il vient et une citation courte copiée de cette page. Un point sans URL n'est pas rendu.
- Aucun point tiré de ta connaissance générale : seulement des pages ouvertes pendant cette recherche.

---
Titre : {title}
Entreprise annoncée : {company}
Lieu : {location}
{url_line}
Description :
{description}"""

# ---------------------------------------------------------------------------
# Attendus (fiche manuelle du 10 septembre 2026)
# ---------------------------------------------------------------------------
EXPECTED = {
    2874: {
        "employeur": "Proximus Ada, équipe Machine Learning Enablers",
        "detail": "article de Benoît Hespel, Head of AI — leçon « Commencez par le problème, pas par le modèle »",
    },
    155: {
        "employeur": "inconnu d'avance (néo-cabinet de conseil)",
        "detail": "attendu : un nom avec méthode, ou non_trouve",
    },
    2499: {
        "employeur": "masqué (secteur médical, suivi de milliers de patients, Nivelles)",
        "detail": "attendu : un nom avec méthode, ou non_trouve",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _conn():
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _fetch_offer(offer_id: int):
    c = _conn()
    row = c.execute(
        "SELECT id, title, company, location, url, description_raw, description "
        "FROM offers WHERE id = ?",
        (offer_id,),
    ).fetchone()
    c.close()
    return row


def _build_prompt(o) -> str:
    desc = (o["description_raw"] or o["description"] or "").strip()
    url_line = f"URL de l'annonce : {o['url']}" if o["url"] else ""
    return _PROMPT_TEMPLATE.format(
        title=o["title"] or "—",
        company=o["company"] or "non précisée",
        location=o["location"] or "non précisé",
        url_line=url_line,
        description=desc[:12000],
    )


def _collect_urls(s: dict) -> list[str]:
    seen = set()
    urls = []
    for u in (s.get("employeur") or {}).get("urls") or []:
        if u and u not in seen:
            seen.add(u); urls.append(u)
    for pt in s.get("points") or []:
        u = pt.get("url")
        if u and u not in seen:
            seen.add(u); urls.append(u)
    return urls


def _check_urls(urls: list[str]) -> list[dict]:
    results = []
    for url in urls:
        try:
            r = requests.get(
                url, timeout=10, allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            results.append({"url": url, "status": r.status_code, "error": None})
        except Exception as e:
            results.append({"url": url, "status": None, "error": str(e)[:200]})
    return results


def _parse_claude_output(stdout: str) -> tuple[dict | None, str | None, float | None, int | None, bool]:
    """
    Retourne (structured, model, total_cost_usd, num_turns, is_error).
    La sortie JSON de claude -p est du NDJSON ; le dernier objet type=result porte le résultat.
    """
    result_obj = None
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("type") == "result":
                result_obj = obj
                break
        except Exception:
            continue

    if result_obj is None:
        # Tentative : stdout entier est un seul JSON
        try:
            result_obj = json.loads(stdout.strip())
        except Exception:
            return None, None, None, None, True

    model = result_obj.get("model")
    cost = result_obj.get("total_cost_usd") or result_obj.get("cost_usd")
    turns = result_obj.get("num_turns")
    is_error = result_obj.get("subtype") == "error" or result_obj.get("is_error", False)

    raw_result = result_obj.get("result")
    structured = None
    if isinstance(raw_result, dict):
        structured = raw_result
    elif isinstance(raw_result, str):
        try:
            structured = json.loads(raw_result)
        except Exception:
            pass

    return structured, model, cost, turns, is_error


def _call_claude(offer_id: int, prompt: str, schema_json: str) -> dict:
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            proc = subprocess.run(
                [
                    "claude", "-p",
                    "--output-format", "json",
                    "--json-schema", schema_json,
                    "--allowedTools", "WebSearch,WebFetch",
                    "--permission-mode", "dontAsk",
                ],
                input=prompt,
                capture_output=True,
                text=True,
                cwd=tmpdir,
                timeout=TIMEOUT_S,
            )
            wall = round(time.perf_counter() - t0, 1)
            stdout = proc.stdout or ""
            stderr = (proc.stderr or "").strip()

            structured, model, cost, turns, is_error = _parse_claude_output(stdout)
            if proc.returncode != 0 and not is_error:
                is_error = True

            url_checks = []
            if structured:
                urls = _collect_urls(structured)
                if urls:
                    print(f"  Vérification de {len(urls)} URL(s)…", flush=True)
                    url_checks = _check_urls(urls)

            return {
                "offer_id": offer_id,
                "wall_s": wall,
                "total_cost_usd": cost,
                "num_turns": turns,
                "is_error": is_error,
                "model": model,
                "structured_output": structured,
                "url_checks": url_checks,
                "raw_output": None if structured else stdout[:4000],
                "stderr": stderr[:500] if stderr else None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except subprocess.TimeoutExpired:
            return {
                "offer_id": offer_id,
                "wall_s": round(time.perf_counter() - t0, 1),
                "total_cost_usd": None, "num_turns": None,
                "is_error": True, "model": None, "structured_output": None,
                "url_checks": [],
                "raw_output": "TIMEOUT (>15 min)",
                "stderr": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except FileNotFoundError:
            return {
                "offer_id": offer_id,
                "wall_s": round(time.perf_counter() - t0, 1),
                "total_cost_usd": None, "num_turns": None,
                "is_error": True, "model": None, "structured_output": None,
                "url_checks": [],
                "raw_output": "COMMAND_NOT_FOUND: `claude` absent du PATH",
                "stderr": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------
def _verdict_2874(raw_str: str) -> str:
    has_proximus = "proximus" in raw_str
    has_ada = "ada" in raw_str
    has_hespel = "hespel" in raw_str
    if has_proximus and has_ada and has_hespel:
        return "juste (Proximus Ada + Hespel trouvés)"
    if has_proximus and has_ada:
        return "partiel (Proximus Ada trouvé, Hespel absent)"
    if has_proximus:
        return "partiel (groupe Proximus seulement)"
    return "faux"


def _report(runs: list[dict], offers: dict) -> None:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# TCK-206 — Fiche entreprise via `claude -p`\n",
        f"Run du {now_str} · {len(runs)} offre(s) · timeout {TIMEOUT_S // 60} min par offre\n",
        "_Le rapport mesure, il ne conclut pas._\n",
    ]

    for r in runs:
        oid = r["offer_id"]
        o = offers[oid]
        s = r.get("structured_output") or {}
        emp = s.get("employeur") or {}
        pts = s.get("points") or []
        uc = r.get("url_checks") or []
        n_ok = sum(1 for u in uc if u["status"] and 200 <= u["status"] < 400)
        n_dead = sum(1 for u in uc if u["status"] and u["status"] >= 400)
        n_err = sum(1 for u in uc if u["error"])

        lines += [
            f"## Offre {oid} — {o['title']}\n",
            "| Champ | Valeur |",
            "|---|---|",
            f"| Entreprise annoncée | {o['company'] or '—'} |",
            f"| Employeur trouvé (`nom`) | {emp.get('nom') or '—'} |",
            f"| Entité précise | {emp.get('entite_precise') or '—'} |",
            f"| Confiance | {emp.get('confiance') or '—'} |",
            f"| Type source | {emp.get('type_source') or '—'} |",
            f"| Méthode | {str(emp.get('methode') or '—')[:200]} |",
            f"| Nb points | {len(pts)} |",
            f"| URLs — OK (2xx/3xx) / mortes (4xx+) / erreur réseau | {n_ok} / {n_dead} / {n_err} |",
            f"| Coût (USD) | {r['total_cost_usd'] if r['total_cost_usd'] is not None else '—'} |",
            f"| Durée (s) | {r['wall_s']} |",
            f"| Tours | {r['num_turns'] if r['num_turns'] is not None else '—'} |",
            f"| Modèle | {r['model'] or '—'} |",
            f"| Erreur | {'oui' if r['is_error'] else 'non'} |",
        ]
        if r.get("raw_output"):
            lines.append(f"| Sortie brute (tronquée) | `{r['raw_output'][:300].replace('|', '/')}` |")
        if r.get("stderr"):
            lines.append(f"| Stderr | `{r['stderr'][:200].replace('|', '/')}` |")
        lines.append("")

        if uc:
            lines += ["### URLs vérifiées\n", "| URL | Statut HTTP | Erreur |", "|---|---|---|"]
            for u in uc:
                lines.append(f"| {u['url'][:100]} | {u['status'] or '—'} | {u['error'] or '—'} |")
            lines.append("")

        if s.get("requetes"):
            lines += ["### Requêtes faites\n"]
            for q in s["requetes"]:
                lines.append(f"- {q}")
            lines.append("")

        if s.get("manques"):
            lines += ["### Manques signalés\n"]
            for m in s["manques"]:
                lines.append(f"- {m}")
            lines.append("")

    lines += [
        "## Confrontation aux attendus (fiche manuelle du 10 septembre 2026)\n",
        "| Offre | Attendu | Trouvé | Confiance | Verdict |",
        "|---|---|---|---|---|",
    ]
    for r in runs:
        oid = r["offer_id"]
        exp = EXPECTED[oid]
        s = r.get("structured_output") or {}
        emp = s.get("employeur") or {}
        found = emp.get("nom") or emp.get("entite_precise") or "—"
        confiance = emp.get("confiance") or "—"

        if r["is_error"] or not s:
            verdict = "non trouvé (erreur)"
        elif confiance == "non_trouve":
            verdict = "non trouvé"
        elif oid == 2874:
            verdict = _verdict_2874(json.dumps(s, ensure_ascii=False).lower())
        else:
            verdict = f"trouvé : {found}" if found != "—" else "non trouvé"

        lines.append(f"| {oid} | {exp['employeur']} | {found} | {confiance} | {verdict} |")

    lines.append("")
    (OUT_DIR / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="Affiche les offres et le prompt sans appeler claude.")
    p.add_argument("--offer", type=int, metavar="ID",
                   help="Lancer une seule offre (ex: 2874).")
    a = p.parse_args()

    offer_ids = [a.offer] if a.offer else OFFERS
    offers: dict = {}
    for oid in offer_ids:
        row = _fetch_offer(oid)
        if row is None:
            print(f"ERREUR : offre {oid} introuvable dans la base.")
        else:
            offers[oid] = dict(row)

    if not offers:
        raise SystemExit("Aucune offre trouvée.")

    if a.dry_run:
        for oid, o in offers.items():
            print(f"\n{'='*60}")
            print(f"Offre {oid} — {o['title']}")
            print(f"  company  : {o['company']}")
            print(f"  location : {o['location']}")
            print(f"  url      : {o['url']}")
            desc = (o["description_raw"] or o["description"] or "").strip()
            print(f"  desc_raw : {'oui' if o['description_raw'] else 'non'} "
                  f"({len(desc)} car.)")
            print()
            prompt = _build_prompt(o)
            print("--- PROMPT (800 premiers caractères) ---")
            print(prompt[:800])
            print("…")
        print(f"\n{'='*60}")
        print(f"Schéma JSON (premiers 400 car.) :")
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False)[:400], "…")
        print(f"\nCommande qui serait lancée :")
        print(
            "  claude -p "
            "--output-format json "
            "--json-schema data/experiment_tck206/schema.json "
            "--allowedTools WebSearch,WebFetch "
            "--permission-mode dontAsk "
            "< <(prompt passé sur stdin)"
        )
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        schema_path = OUT_DIR / "schema.json"
        schema_path.write_text(json.dumps(SCHEMA, ensure_ascii=False, indent=2))
        schema_json = json.dumps(SCHEMA, ensure_ascii=False, separators=(",", ":"))

        runs: list[dict] = []
        with (OUT_DIR / "runs.jsonl").open("w", encoding="utf-8") as fp:
            for oid in offer_ids:
                if oid not in offers:
                    continue
                o = offers[oid]
                prompt = _build_prompt(o)
                print(f"\n{'='*60}", flush=True)
                print(f"Offre {oid} — {o['title']}", flush=True)
                run = _call_claude(oid, prompt, schema_json)
                runs.append(run)
                fp.write(json.dumps(run, ensure_ascii=False, default=str) + "\n")
                fp.flush()
                status = "✓" if not run["is_error"] else "✗"
                pts = len((run.get("structured_output") or {}).get("points") or [])
                print(
                    f"  {status} {run['wall_s']}s | {pts} points | "
                    f"coût={run['total_cost_usd']} | erreur={run['is_error']}",
                    flush=True,
                )

        if runs:
            _report(runs, offers)
            print(f"\nRapport : {OUT_DIR / 'report.md'}")
