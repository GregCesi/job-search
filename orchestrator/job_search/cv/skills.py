"""Génération de CV adapté — calculs Python purs (EXE-58).

Frontière (architecture.md §4) : le LLM ne décide jamais QUELLES compétences
ajouter — la liste d'ajouts autorisés est un calcul Python sur le profil et
les technos exigées déjà extraites à l'ingestion. Le LLM ne fait que choisir
où placer ces ajouts dans les groupes existants (cf. cv/service.py).
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass

from orchestrator.job_search.matching.profile import Profile
from orchestrator.job_search.scoring.aliases import AliasTable, canonicalize

# Formes canoniques génériques jamais ajoutées, même maîtrisées (H2 du ticket) :
# trop de bruit pour être des ajouts significatifs sur un CV.
GENERIC_EXCLUDED = frozenset({"llm", "rest_api", "json"})

# Zone du profil → libellé affiché dans le CV (H1 : seuls titre/localisation/compétences
# changent ; ce mapping n'est pas piloté par la config, seul le seuil l'est — critère 16).
_ZONE_DISPLAY = {
    "belgique_area": "Bruxelles, Belgique",
    "strasbourg_area": "Strasbourg, France",
}


@dataclass(frozen=True)
class SkillGroup:
    label: str
    items: list[str]


@dataclass(frozen=True)
class ReferenceBlock:
    groupes: list[SkillGroup]
    notions: list[str]


@dataclass(frozen=True)
class Addition:
    """Un ajout autorisé : libellé tel qu'extrait de l'offre (H5), jamais reformulé."""

    raw_name: str
    canonical: str


def _split_top_level(raw: str, sep: str = ",") -> list[str]:
    """Découpe `raw` sur `sep` en ignorant les occurrences à l'intérieur de parenthèses.

    Évite de couper « environnement cloud (AWS, Azure) » en deux items (H7 — bug
    identifié dans experiment_tck206_cv.py, qui découpait sur ", " sans tenir compte
    des parenthèses).
    """
    items: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(raw):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == sep and depth == 0:
            items.append(raw[start:i].strip())
            start = i + 1
    items.append(raw[start:].strip())
    return [it for it in items if it]


def parse_reference_block(cv_html: str) -> ReferenceBlock:
    """Extrait groupes + notions du bloc <h2>Compétences</h2> du CV de référence."""
    m = re.search(r"<h2>Compétences</h2>(.*?)<h2>Formation</h2>", cv_html, re.DOTALL)
    if not m:
        raise ValueError(
            "Bloc <h2>Compétences</h2> introuvable dans le CV de référence"
        )
    block = m.group(1)

    groupes: list[SkillGroup] = []
    for gm in re.finditer(
        r'<div class="grp">\s*'
        r'<div class="grp-label">(.*?)</div>\s*'
        r'<div class="grp-list">(.*?)</div>\s*'
        r"</div>",
        block,
        re.DOTALL,
    ):
        label = html_lib.unescape(gm.group(1).strip())
        raw_items = html_lib.unescape(gm.group(2).strip())
        items = [i.strip() for i in raw_items.split(" · ") if i.strip()]
        groupes.append(SkillGroup(label=label, items=items))

    notions: list[str] = []
    nm = re.search(r'<div class="grp-notions">Notions en\s*:\s*(.*?)</div>', block)
    if nm:
        raw_notions = html_lib.unescape(nm.group(1).strip())
        notions = _split_top_level(raw_notions, ",")

    return ReferenceBlock(groupes=groupes, notions=notions)


def clean_title(raw: str) -> str:
    """Retire ce qui suit un premier « | » — nom de l'employeur ou de l'agrégateur
    (EXE-63 H2) — puis le suffixe H/F sous ses formes usuelles (« H/F », « (H/F) »,
    « - H/F »).
    """
    t = (raw or "").split("|", 1)[0]
    t = re.sub(r"\s*[\(\-]\s*[HhFf]/[HhFf]\s*[)]?", "", t)
    t = re.sub(r"\s+[HhFf]/[HhFf]\s*$", "", t)
    return t.strip()


def detect_location(offer_location: str | None, profile: Profile) -> str:
    """Zone du profil matchée par mot-clé dans la localisation brute de l'offre → libellé CV."""
    loc_lower = (offer_location or "").lower()
    for zone_name, display in _ZONE_DISPLAY.items():
        zone = profile.zones.get(zone_name)
        if zone:
            for kw in zone.keywords:
                if kw.lower() in loc_lower:
                    return display
    return offer_location or "—"


def item_canonicals(item: str, alias_table: AliasTable) -> set[str]:
    """Formes canoniques couvertes par un item de CV, y compris les items composés.

    « Python (FastAPI, Pydantic) » couvre python, fastapi et pydantic ; « SQL / SQLite »
    couvre sql et sqlite (H3 — règle générique : un terme suivi d'une parenthèse, ou
    séparé par « / » entouré d'espaces, couvre chacune de ses parties). Un « / » collé
    (« CI/CD », « HTML/CSS ») reste un terme unique — ce n'est pas une composition.
    """
    m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", item)
    if m:
        main, paren = m.group(1).strip(), m.group(2)
        parts = [main, *_split_top_level(paren, ",")]
    elif re.search(r"\s/\s", item):
        parts = [p.strip() for p in re.split(r"\s/\s", item)]
    else:
        parts = [item]

    covered: set[str] = set()
    for part in parts:
        part = part.strip()
        if not part:
            continue
        c = canonicalize(part, alias_table)
        if c is not None:
            covered.add(c)
    return covered


def block_canonicals(
    groupes: list[SkillGroup], notions: list[str], alias_table: AliasTable
) -> set[str]:
    """Union des formes canoniques couvertes par un bloc compétences (groupes + notions)."""
    result: set[str] = set()
    for grp in groupes:
        for item in grp.items:
            result |= item_canonicals(item, alias_table)
    for n in notions:
        result |= item_canonicals(n, alias_table)
    return result


def compute_permitted_additions(
    techs_required: list[dict],
    profile: Profile,
    alias_table: AliasTable,
    covered: set[str],
    threshold: int,
) -> list[Addition]:
    """Ajouts autorisés : technos exigées par l'offre, niveau ≥ seuil dans le profil,
    absentes du CV de référence, hors formes génériques (GENERIC_EXCLUDED).

    Calcul 100% Python (architecture.md §3-4) : le LLM ne choisit jamais cette liste.
    """
    canonical_levels: dict[str, int] = {}
    for name, entry in profile.skills.items():
        c = canonicalize(name, alias_table)
        if c is not None:
            canonical_levels[c] = max(canonical_levels.get(c, entry.level), entry.level)

    seen: set[str] = set()
    additions: list[Addition] = []
    for tech in techs_required:
        raw_name = tech["name"]
        c = canonicalize(raw_name, alias_table)
        if c is None or c in GENERIC_EXCLUDED or c in covered or c in seen:
            continue
        level = canonical_levels.get(c)
        if level is None or level < threshold:
            continue
        seen.add(c)
        additions.append(Addition(raw_name=raw_name, canonical=c))
    return additions


def filter_model_groups(
    ref_groups: list[SkillGroup],
    model_groups: list[SkillGroup],
    additions: list[Addition],
) -> list[SkillGroup]:
    """Groupes finaux : items d'origine intacts dans leur groupe d'origine (critère 7),
    plus les ajouts autorisés que le modèle a effectivement placés — sous leur libellé
    exact (H5), jamais celui rendu par le modèle. Tout item non reconnu est ignoré
    (critère 17) : le modèle ne peut ni retirer, ni déplacer, ni inventer un item.
    """
    permitted_by_lower = {a.raw_name.lower(): a.raw_name for a in additions}
    model_by_label = {g.label.lower(): g for g in model_groups}

    result: list[SkillGroup] = []
    for ref_grp in ref_groups:
        items = list(ref_grp.items)
        model_grp = model_by_label.get(ref_grp.label.lower())
        if model_grp is not None:
            existing_lower = {i.lower() for i in items}
            for model_item in model_grp.items:
                permitted_label = permitted_by_lower.get(model_item.lower())
                if (
                    permitted_label is not None
                    and model_item.lower() not in existing_lower
                ):
                    items.append(permitted_label)
                    existing_lower.add(model_item.lower())
        result.append(SkillGroup(label=ref_grp.label, items=items))
    return result


def compute_au_cv(groupes: list[SkillGroup], notions: list[str]) -> list[str]:
    """Chaque compétence du bloc généré, groupe par groupe, plus les notions (critère 19)."""
    result: list[str] = []
    for grp in groupes:
        result.extend(grp.items)
    result.extend(notions)
    return result


def compute_requested_missing(
    techs_required: list[dict],
    alias_table: AliasTable,
    present: set[str],
) -> list[str]:
    """Technos demandées par l'offre absentes du CV final, dédupliquées (critère 20).

    Une techno exclue de la canonicalisation (alias.yaml#exclude, ex. « cloud ») n'est
    jamais « présente » : elle reste listée, car elle a bien été demandée sans y être.
    """
    seen: set[str] = set()
    missing: list[str] = []
    for tech in techs_required:
        raw_name = tech["name"]
        c = canonicalize(raw_name, alias_table)
        key = c if c is not None else raw_name.lower().strip()
        if key in seen:
            continue
        seen.add(key)
        if c is None or c not in present:
            missing.append(raw_name)
    return missing


def render_skills_html(groupes: list[SkillGroup], notions: list[str]) -> str:
    lines = ["<h2>Compétences</h2>"]
    for grp in groupes:
        label = html_lib.escape(grp.label)
        items_str = " · ".join(html_lib.escape(i) for i in grp.items)
        lines.append('  <div class="grp">')
        lines.append(f'    <div class="grp-label">{label}</div>')
        lines.append(f'    <div class="grp-list">{items_str}</div>')
        lines.append("  </div>")
    if notions:
        notions_str = ", ".join(html_lib.escape(n) for n in notions)
        lines.append(f'  <div class="grp-notions">Notions en : {notions_str}</div>')
    return "\n".join(lines)


_ROW_RE = re.compile(r'<div class="row"><b>(.*?)</b></div>')


def generate_cv_html(
    cv_html_ref: str,
    title: str,
    location: str,
    groupes: list[SkillGroup],
    notions: list[str],
) -> str:
    """Substitue titre, localisation et bloc compétences ; le reste du CV de référence
    est repris octet pour octet (critère 21).
    """
    out = re.sub(
        r'(<div class="role">).*?(</div>)',
        lambda m: m.group(1) + html_lib.escape(title) + m.group(2),
        cv_html_ref,
        count=1,
    )

    # Localisation : 3ème ligne "row" du bloc Contact du CV de référence — structure
    # connue de data/cv/cv_reference.html (cf. experiment_tck206_cv.py::_generate_cv_html,
    # même hypothèse de structure, H7).
    matches = list(_ROW_RE.finditer(out))
    if len(matches) < 3:
        raise ValueError(
            "Structure Contact inattendue : moins de 3 lignes 'row' dans le CV de référence"
        )
    target = matches[2]
    out = (
        out[: target.start()]
        + f'<div class="row"><b>{html_lib.escape(location)}</b></div>'
        + out[target.end() :]
    )

    new_block = render_skills_html(groupes, notions)
    out = re.sub(
        r"<h2>Compétences</h2>.*?(?=<h2>Formation</h2>)",
        lambda _m: new_block + "\n\n  ",
        out,
        flags=re.DOTALL,
    )
    return out
