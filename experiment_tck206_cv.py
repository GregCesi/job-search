"""
TCK-206-CV — CV adapté depuis une offre via claude -p (headless, sans outil).

Paramètres provisoires (hypothèses chat, 24 septembre 2026) :
  MAITRISEE_MIN = 6  (level ≥ 6 → maîtrisée)
  NOTIONS_MIN   = 3  (level 3-5 → notions ; level < 3 → non affichée)
  Techno absente du profil → inconnue (jamais dans le CV)
  Localisation : belgique_area → "Bruxelles, Belgique" ; strasbourg_area → "Strasbourg, France"

Lecture seule SQLite. Aucune écriture en base.
Sortie : data/experiment_tck206/cv/

Usage :
  python experiment_tck206_cv.py --dry-run
  python experiment_tck206_cv.py --offer 155
  python experiment_tck206_cv.py
"""
import argparse
import html as html_lib
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from orchestrator.job_search.matching.profile import load_profile
from orchestrator.job_search.scoring.aliases import AliasTable, canonicalize, load_alias_table

# ---------------------------------------------------------------------------
# Chemins & paramètres
# ---------------------------------------------------------------------------
ROOT          = Path(__file__).parent
DB_PATH       = ROOT / "data" / "job_search.sqlite"
PROFILE_PATH  = ROOT / "profiles" / "gregoire.yaml"
ALIAS_PATH    = ROOT / "profiles" / "alias.yaml"
CV_REF_PATH   = ROOT / "data" / "experiment_tck206" / "cv" / "cv_reference.html"
OUT_DIR       = ROOT / "data" / "experiment_tck206" / "cv"

OFFERS = [155, 2125, 27]
TIMEOUT_S = 300  # 5 min par offre (pas de recherche web)

# --- Paramètres provisoires (hypothèses chat — à corriger par Grégoire) ---
MAITRISEE_MIN = 6   # level ≥ 6 → maîtrisée
NOTIONS_MIN   = 3   # level 3-5 → notions ; level < 3 → non affichée

# Zones : nom de zone dans le profil → libellé à afficher dans le CV
_ZONE_DISPLAY = {
    "belgique_area":    "Bruxelles, Belgique",
    "strasbourg_area":  "Strasbourg, France",
}

# ---------------------------------------------------------------------------
# Schéma de sortie structurée
# ---------------------------------------------------------------------------
SCHEMA = {
    "type": "object",
    "properties": {
        "groupes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "items": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["label", "items"],
                "additionalProperties": False,
            },
        },
        "notions": {"type": "array", "items": {"type": "string"}},
        "retires": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["groupes", "notions", "retires"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
_PROMPT_TEMPLATE = """\
Tu adaptes le bloc compétences d'un CV à une offre d'emploi.

**Offre** : {offer_title}

**(a) Bloc compétences actuel du CV (source de vérité à conserver) :**
{ref_block_json}

**(b) Technos de l'offre classées par niveau dans le profil :**

Maîtrisées (level ≥ 6) — à intégrer dans les groupes :
{maitrisees_lines}

Notions (level 3-5) — à intégrer dans la liste "notions" :
{notions_lines}

Inconnues (absentes du profil) — ne figurent PAS dans le CV :
{inconnues_lines}

Non affichées (level ≤ 2) — ne figurent PAS dans le CV :
{non_affichees_lines}

**Instructions :**
1. Pars du bloc (a) tel quel.
2. Ajoute dans le groupe le plus pertinent chaque techno maîtrisée de (b) absente du bloc.
3. Ajoute dans la liste "notions" chaque techno notions de (b) absente du bloc.
4. Dans chaque groupe, remonte en tête ce que l'offre exige le plus (core d'abord, puis required, puis nice_to_have).
5. Garde le style exact des libellés du bloc (a) (ex : "IA & LLM", "Python (FastAPI, Pydantic)").
6. Si le bloc risque d'être trop long pour tenir dans la sidebar A4 (64 mm de large, env. 180 mm de haut), \
tu peux retirer des items peu importants du bloc (a) ; liste chaque retrait dans `retires`.
7. N'invente aucun item absent de (a) et de (b). Ne modifie pas le texte des items, \
seulement leur ordre et leur présence.
"""


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
def _conn():
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _fetch_offer(offer_id: int) -> dict | None:
    c = _conn()
    row = c.execute(
        "SELECT id, title, company, location, extracted_facts_json "
        "FROM offers WHERE id = ?",
        (offer_id,),
    ).fetchone()
    c.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Parsing du CV de référence
# ---------------------------------------------------------------------------
def _parse_ref_block(cv_html: str) -> dict:
    """Extrait groupes + notions du bloc Compétences du CV de référence."""
    m = re.search(r"<h2>Compétences</h2>(.*?)<h2>Formation</h2>", cv_html, re.DOTALL)
    if not m:
        raise ValueError("Bloc <h2>Compétences</h2> introuvable dans cv_reference.html")

    block = m.group(1)

    groupes = []
    for gm in re.finditer(
        r'<div class="grp">\s*'
        r'<div class="grp-label">(.*?)</div>\s*'
        r'<div class="grp-list">(.*?)</div>\s*'
        r'</div>',
        block, re.DOTALL,
    ):
        label = html_lib.unescape(gm.group(1).strip())
        raw   = html_lib.unescape(gm.group(2).strip())
        items = [i.strip() for i in raw.split(" · ") if i.strip()]
        groupes.append({"label": label, "items": items})

    notions = []
    nm = re.search(r'<div class="grp-notions">Notions en\s*:\s*(.*?)</div>', block)
    if nm:
        raw = html_lib.unescape(nm.group(1).strip())
        notions = [n.strip() for n in raw.split(", ") if n.strip()]

    return {"groupes": groupes, "notions": notions}


# ---------------------------------------------------------------------------
# Localisation
# ---------------------------------------------------------------------------
def _detect_location(offer_location: str, profile) -> str:
    loc_lower = (offer_location or "").lower()
    for zone_name, display in _ZONE_DISPLAY.items():
        zone = profile.zones.get(zone_name)
        if zone:
            for kw in zone.keywords:
                if kw.lower() in loc_lower:
                    return display
    return offer_location or "—"


# ---------------------------------------------------------------------------
# Classification des technos
# ---------------------------------------------------------------------------
def _classify_techs(techs_required: list[dict], profile, alias_table: AliasTable) -> list[dict]:
    """Classifie chaque techno de l'offre selon le niveau déclaré dans le profil."""
    # Index canonicalisé : canonical_form → level
    canonical_levels: dict[str, int] = {}
    for name, entry in profile.skills.items():
        c = canonicalize(name, alias_table)
        if c is not None:
            canonical_levels[c] = entry.level

    results = []
    for tech in techs_required:
        raw_name   = tech["name"]
        importance = tech.get("importance", "required")
        c          = canonicalize(raw_name, alias_table)

        if c is None:
            classe = "exclu"
            level  = None
        else:
            level = canonical_levels.get(c)
            if level is None:
                classe = "inconnue"
            elif level >= MAITRISEE_MIN:
                classe = "maitrisee"
            elif level >= NOTIONS_MIN:
                classe = "notions"
            else:
                classe = "non_affichee"

        results.append({
            "name":       raw_name,
            "canonical":  c,
            "importance": importance,
            "level":      level,
            "classe":     classe,
        })

    return results


# ---------------------------------------------------------------------------
# Titre propre
# ---------------------------------------------------------------------------
def _clean_title(raw: str) -> str:
    t = re.sub(r"\s*[\(\-]\s*[HhFf]/[HhFf]\s*[)]?", "", raw)
    t = re.sub(r"\s+[HhFf]/[HhFf]\s*$", "", t)
    return t.strip()


# ---------------------------------------------------------------------------
# Construction du prompt
# ---------------------------------------------------------------------------
_IMP_LABELS = {"core": "core", "required": "requis", "nice_to_have": "atout"}
_IMP_ORDER  = {"core": 0, "required": 1, "nice_to_have": 2}


def _build_prompt(offer_title: str, ref_block: dict, classified: list[dict]) -> str:
    def _sorted(techs):
        return sorted(techs, key=lambda t: _IMP_ORDER.get(t["importance"], 9))

    def _fmt(techs):
        if not techs:
            return "  aucune"
        return "\n".join(
            f"  - {t['name']} [{_IMP_LABELS.get(t['importance'], t['importance'])}]"
            for t in techs
        )

    return _PROMPT_TEMPLATE.format(
        offer_title=offer_title,
        ref_block_json=json.dumps(ref_block, ensure_ascii=False, indent=2),
        maitrisees_lines=_fmt(_sorted([t for t in classified if t["classe"] == "maitrisee"])),
        notions_lines=   _fmt(_sorted([t for t in classified if t["classe"] == "notions"])),
        inconnues_lines= _fmt(_sorted([t for t in classified if t["classe"] == "inconnue"])),
        non_affichees_lines=_fmt([t for t in classified if t["classe"] == "non_affichee"]),
    )


# ---------------------------------------------------------------------------
# Appel Claude
# ---------------------------------------------------------------------------
def _parse_claude_output(stdout: str) -> tuple[dict | None, str | None, float | None, int | None, bool]:
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
        try:
            result_obj = json.loads(stdout.strip())
        except Exception:
            return None, None, None, None, True

    model    = result_obj.get("model")
    cost     = result_obj.get("total_cost_usd") or result_obj.get("cost_usd")
    turns    = result_obj.get("num_turns")
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
                    "--permission-mode", "dontAsk",
                ],
                input=prompt,
                capture_output=True,
                text=True,
                cwd=tmpdir,
                timeout=TIMEOUT_S,
            )
            wall   = round(time.perf_counter() - t0, 1)
            stdout = proc.stdout or ""
            stderr = (proc.stderr or "").strip()

            structured, model, cost, turns, is_error = _parse_claude_output(stdout)
            if proc.returncode != 0 and not is_error:
                is_error = True

            return {
                "offer_id":         offer_id,
                "wall_s":           wall,
                "total_cost_usd":   cost,
                "num_turns":        turns,
                "is_error":         is_error,
                "model":            model,
                "structured_output": structured,
                "raw_output":       None if structured else stdout[:4000],
                "stderr":           stderr[:500] if stderr else None,
                "timestamp":        datetime.now(timezone.utc).isoformat(),
            }

        except subprocess.TimeoutExpired:
            return {
                "offer_id": offer_id,
                "wall_s":   round(time.perf_counter() - t0, 1),
                "total_cost_usd": None, "num_turns": None,
                "is_error": True, "model": None, "structured_output": None,
                "raw_output": f"TIMEOUT (>{TIMEOUT_S // 60} min)",
                "stderr": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except FileNotFoundError:
            return {
                "offer_id": offer_id,
                "wall_s":   round(time.perf_counter() - t0, 1),
                "total_cost_usd": None, "num_turns": None,
                "is_error": True, "model": None, "structured_output": None,
                "raw_output": "COMMAND_NOT_FOUND: `claude` absent du PATH",
                "stderr": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _validate(structured: dict, ref_block: dict, classified: list[dict]) -> list[str]:
    """
    Retourne les violations : items dans la sortie absents de (a) ET de (b).
    Matching case-insensitive exact.
    """
    # Ensemble valide pour les groupes : (a) groupes + (b) maîtrisées
    valid_grp: set[str] = set()
    for grp in ref_block["groupes"]:
        for item in grp["items"]:
            valid_grp.add(item.lower())
    for t in classified:
        if t["classe"] == "maitrisee":
            valid_grp.add(t["name"].lower())
            if t["canonical"]:
                valid_grp.add(t["canonical"].lower())

    # Ensemble valide pour les notions : (a) notions + (b) notions
    valid_not: set[str] = set()
    for item in ref_block["notions"]:
        valid_not.add(item.lower())
    for t in classified:
        if t["classe"] == "notions":
            valid_not.add(t["name"].lower())
            if t["canonical"]:
                valid_not.add(t["canonical"].lower())

    violations: list[str] = []
    for grp in (structured.get("groupes") or []):
        for item in (grp.get("items") or []):
            if item.lower() not in valid_grp:
                violations.append(
                    f"groupe « {grp.get('label', '?')} » : item « {item} » absent de (a) et (b)"
                )
    for item in (structured.get("notions") or []):
        if item.lower() not in valid_not:
            violations.append(f"notions : item « {item} » absent de (a) et (b)")

    return violations


# ---------------------------------------------------------------------------
# Rendu HTML du bloc compétences
# ---------------------------------------------------------------------------
def _render_skills_html(groupes: list, notions: list) -> str:
    lines = ["<h2>Compétences</h2>"]
    for grp in groupes:
        label     = html_lib.escape(grp["label"])
        items_str = " · ".join(html_lib.escape(item) for item in grp["items"])
        lines.append('  <div class="grp">')
        lines.append(f'    <div class="grp-label">{label}</div>')
        lines.append(f'    <div class="grp-list">{items_str}</div>')
        lines.append('  </div>')
    if notions:
        notions_str = ", ".join(html_lib.escape(n) for n in notions)
        lines.append(f'  <div class="grp-notions">Notions en : {notions_str}</div>')
    return "\n".join(lines)


def _generate_cv_html(
    cv_html_ref: str, clean_title: str, location: str,
    groupes: list, notions: list,
) -> str:
    html = cv_html_ref

    # 1. Titre (div.role)
    html = re.sub(
        r'(<div class="role">).*?(</div>)',
        lambda m: m.group(1) + html_lib.escape(clean_title) + m.group(2),
        html,
    )

    # 2. Localisation (3ème row Contact — ligne ville, fixe dans le CV de référence)
    html = html.replace(
        '<div class="row"><b>Bruxelles, Belgique</b></div>',
        f'<div class="row"><b>{html_lib.escape(location)}</b></div>',
    )

    # 3. Bloc compétences
    new_block = _render_skills_html(groupes, notions)
    html = re.sub(
        r"<h2>Compétences</h2>.*?(?=<h2>Formation</h2>)",
        new_block + "\n\n  ",
        html,
        flags=re.DOTALL,
    )

    return html


# ---------------------------------------------------------------------------
# Playwright (facultatif)
# ---------------------------------------------------------------------------
def _playwright_check(html_path: Path) -> tuple[bool | None, str]:
    """(overflow | None, note). None = playwright absent."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        return None, "playwright absent — rendu non vérifié"

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page    = browser.new_page()
        page.goto(f"file://{html_path.resolve()}")
        page.wait_for_load_state("networkidle")

        overflow = page.evaluate("""() => {
            const el = document.querySelector('.page');
            return el ? el.scrollHeight > el.offsetHeight : null;
        }""")

        png_path = html_path.with_suffix(".png")
        page.screenshot(path=str(png_path))
        browser.close()

    if overflow is None:
        return None, "élément .page introuvable"
    return bool(overflow), (
        f"{'débordement détecté' if overflow else 'pas de débordement'}"
        f" · capture : {png_path.name}"
    )


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------
def _report(results: list[dict]) -> None:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# TCK-206-CV — CV adapté via `claude -p`\n",
        f"Run du {now_str} · {len(results)} offre(s) · MAITRISEE_MIN={MAITRISEE_MIN}, NOTIONS_MIN={NOTIONS_MIN}\n",
        "_Le rapport mesure, il ne conclut pas._\n",
    ]

    for r in results:
        oid          = r["offer_id"]
        o            = r["offer"]
        classified   = r["classified"]
        run          = r["run"]
        violations   = r["violations"]
        location     = r["location"]
        clean_title  = r["clean_title"]
        overflow     = r["overflow"]
        overflow_note = r["overflow_note"]
        s            = run.get("structured_output") or {}

        lines += [
            f"## Offre {oid} — {o['title']}\n",
            f"**Titre CV** : {clean_title}  ",
            f"**Localisation** : {location}\n",
            "### Classement des technos\n",
            "| Techno (offre) | Canonique | Importance | Level | Classe |",
            "|---|---|---|---|---|",
        ]
        for t in classified:
            lines.append(
                f"| {t['name']} | {t['canonical'] or '—'} | {t['importance']} "
                f"| {t['level'] if t['level'] is not None else '—'} | {t['classe']} |"
            )
        lines.append("")

        inconnues = [t["name"] for t in classified if t["classe"] == "inconnue"]
        retires   = s.get("retires") or []

        lines.append(
            f"**Inconnues** (à classer par Grégoire) : "
            f"{', '.join(inconnues) if inconnues else 'aucune'}\n"
        )
        lines.append(
            f"**Retirées du bloc de référence** : "
            f"{', '.join(retires) if retires else 'aucune'}\n"
        )
        lines.append(f"**Violations** : {len(violations)}")
        for v in violations:
            lines.append(f"  - {v}")
        lines.append("")

        lines += [
            "### Mesures\n",
            "| Champ | Valeur |",
            "|---|---|",
            f"| Coût (USD) | {run['total_cost_usd'] if run['total_cost_usd'] is not None else '—'} |",
            f"| Durée (s) | {run['wall_s']} |",
            f"| Tours | {run['num_turns'] if run['num_turns'] is not None else '—'} |",
            f"| Modèle | {run['model'] or '—'} |",
            f"| Erreur | {'oui' if run['is_error'] else 'non'} |",
            f"| Débordement | {'oui' if overflow is True else 'non' if overflow is False else 'non vérifié'} |",
            f"| Note rendu | {overflow_note} |",
        ]
        if run.get("raw_output"):
            lines.append(
                f"| Sortie brute (tronquée) | `{run['raw_output'][:300].replace('|', '/')}` |"
            )
        if run.get("stderr"):
            lines.append(f"| Stderr | `{run['stderr'][:200].replace('|', '/')}` |")
        lines.append("")

    (OUT_DIR / "report_cv.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Affiche les infos et le prompt, 0 appel claude.")
    ap.add_argument("--offer", type=int, metavar="ID",
                    help="Une seule offre (ex : 155).")
    args = ap.parse_args()

    if not CV_REF_PATH.exists():
        raise SystemExit(f"CV de référence manquant : {CV_REF_PATH}")

    cv_html_ref = CV_REF_PATH.read_text(encoding="utf-8")
    ref_block   = _parse_ref_block(cv_html_ref)
    profile, _  = load_profile(PROFILE_PATH)
    alias_table = load_alias_table(ALIAS_PATH)

    offer_ids = [args.offer] if args.offer else OFFERS
    offers: dict[int, dict] = {}
    for oid in offer_ids:
        row = _fetch_offer(oid)
        if row is None:
            print(f"ERREUR : offre {oid} introuvable en base.", file=sys.stderr)
        else:
            offers[oid] = row

    if not offers:
        raise SystemExit("Aucune offre trouvée.")

    # ---- Dry-run ----
    if args.dry_run:
        print(f"CV de référence  : {CV_REF_PATH}")
        print(f"Profil           : {PROFILE_PATH}")
        print(f"Bloc de référence: {len(ref_block['groupes'])} groupes, {len(ref_block['notions'])} notions")
        for oid, o in offers.items():
            facts          = json.loads(o["extracted_facts_json"] or "{}")
            techs_required = facts.get("techs_required") or []
            classified     = _classify_techs(techs_required, profile, alias_table)
            location       = _detect_location(o["location"], profile)
            clean_title    = _clean_title(o["title"] or "")

            print(f"\n{'='*60}")
            print(f"Offre {oid} — {o['title']}")
            print(f"  Titre CV    : {clean_title}")
            print(f"  Localisation: {location}")
            for t in classified:
                lv = str(t["level"]) if t["level"] is not None else "—"
                print(f"  {t['name']:35s} {t['importance']:12s} lv={lv:<3} → {t['classe']}")

            prompt = _build_prompt(clean_title, ref_block, classified)
            print(f"\n--- PROMPT (600 premiers car.) ---")
            print(prompt[:600])
            print("…")

        schema_json = json.dumps(SCHEMA, ensure_ascii=False, separators=(",", ":"))
        print(f"\n{'='*60}")
        print("Commande qui serait lancée :")
        print(
            "  claude -p --output-format json"
            f" --json-schema '{schema_json[:80]}...'"
            " --permission-mode dontAsk < <prompt>"
        )
        sys.exit(0)

    # ---- Run réel ----
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    schema_json = json.dumps(SCHEMA, ensure_ascii=False, separators=(",", ":"))

    results: list[dict] = []
    runs_path = OUT_DIR / "runs_cv.jsonl"

    with runs_path.open("w", encoding="utf-8") as fp:
        for oid in offer_ids:
            if oid not in offers:
                continue
            o              = offers[oid]
            facts          = json.loads(o["extracted_facts_json"] or "{}")
            techs_required = facts.get("techs_required") or []
            classified     = _classify_techs(techs_required, profile, alias_table)
            location       = _detect_location(o["location"], profile)
            clean_title    = _clean_title(o["title"] or "")
            prompt         = _build_prompt(clean_title, ref_block, classified)

            print(f"\n{'='*60}", flush=True)
            print(f"Offre {oid} — {o['title']}", flush=True)
            print(f"  Titre CV    : {clean_title}", flush=True)
            print(f"  Localisation: {location}", flush=True)

            run = _call_claude(oid, prompt, schema_json)
            fp.write(json.dumps(run, ensure_ascii=False, default=str) + "\n")
            fp.flush()

            s          = run.get("structured_output") or {}
            violations = _validate(s, ref_block, classified) if s else []

            overflow, overflow_note = None, "run en erreur — non vérifié"
            cv_path = None

            if not run["is_error"] and s.get("groupes") is not None:
                cv_html = _generate_cv_html(
                    cv_html_ref, clean_title, location,
                    s["groupes"], s.get("notions") or [],
                )
                cv_path = OUT_DIR / f"cv_{oid}.html"
                cv_path.write_text(cv_html, encoding="utf-8")
                overflow, overflow_note = _playwright_check(cv_path)

            result = {
                "offer_id":     oid,
                "offer":        o,
                "classified":   classified,
                "run":          run,
                "violations":   violations,
                "location":     location,
                "clean_title":  clean_title,
                "cv_path":      str(cv_path) if cv_path else None,
                "overflow":     overflow,
                "overflow_note": overflow_note,
            }
            results.append(result)

            status = "✓" if not run["is_error"] else "✗"
            print(
                f"  {status} {run['wall_s']}s | violations={len(violations)} "
                f"| coût={run['total_cost_usd']} | erreur={run['is_error']}",
                flush=True,
            )
            for v in violations:
                print(f"    ⚠ {v}", flush=True)

    if results:
        _report(results)
        print(f"\nRapport : {OUT_DIR / 'report_cv.md'}")
