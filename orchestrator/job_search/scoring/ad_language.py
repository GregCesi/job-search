"""
Détection de la langue de rédaction d'une annonce — offline, 0 LLM.

Retourne "fr" | "en" | "nl" | "other".
- Texte < 100 caractères → "other" (trop court pour langdetect)
- Toute exception langdetect → "other"
"""
import logging
import warnings

logger = logging.getLogger(__name__)

_SUPPORTED = {"fr", "en", "nl"}


def detect_ad_language(text: str) -> str:
    """Détecte la langue de rédaction. Retourne fr | en | nl | other."""
    if len(text) < 100:
        logger.warning("ad_language: texte trop court (%d chars) → other", len(text))
        return "other"

    try:
        # Supprime le warning nondeterministic de langdetect
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from langdetect import detect
            lang = detect(text)
        return lang if lang in _SUPPORTED else "other"
    except Exception:
        return "other"
