"""Utilitaire de nettoyage HTML → Markdown, appelé PAR les adapters (pas par le pipeline aval).

Python pur, 0 LLM, 0 dépendance réseau.
"""

import re

import html2text


def html_to_markdown(raw: str) -> str:
    """HTML brut → Markdown propre.

    Supprime le tracking pixel et le balisage parasite.
    Idempotent sur du texte déjà propre (pas de dégradation).
    """
    if not raw or not raw.strip():
        return ""

    # Pas de HTML détecté → retourner tel quel (préserve le texte plat FT)
    if not re.search(r"<[a-zA-Z][^>]*>", raw):
        return raw.strip()

    # Suppression explicite des tracking pixels AVANT conversion
    # (img 1x1 / blank.gif / pixels de suivi courants)
    cleaned = re.sub(
        r'<img\s[^>]*?src=["\'][^"\']*(?:blank\.gif|track|pixel|1x1)[^"\']*["\'][^>]*/?\s*>',
        "",
        raw,
        flags=re.IGNORECASE,
    )

    h = html2text.HTML2Text()
    h.ignore_images = True       # supprime toute <img> résiduelle (décorative, etc.)
    h.body_width = 0             # pas de wrapping artificiel
    h.ignore_links = False       # conserve les liens utiles
    h.protect_links = True       # ne pas couper les URLs
    h.unicode_snob = True        # caractères Unicode plutôt qu'entités HTML
    h.skip_internal_links = True # ignore les ancres internes (#...)

    md = h.handle(cleaned)

    # Nettoyage post-conversion : collapse des sauts de ligne excessifs
    md = re.sub(r"\n{3,}", "\n\n", md)

    return md.strip()
