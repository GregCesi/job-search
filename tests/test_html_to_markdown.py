"""Tests unitaires — html_to_markdown (L2, chantier HTML→Markdown).

Fixtures tirées d'offres réelles en base (Remotive) + texte plat France Travail.
"""

import pytest

from orchestrator.job_search.sources._clean import html_to_markdown


# ── Fixtures réelles ─────────────────────────────────────────────────────

# Offre « Assistant Accounts Payable » — classes Google OOyDTc/ejCXj + pixel de tracking
ACCOUNTS_PAYABLE_HTML = (
    '<p><strong><span class="OOyDTc" style="line-height: 22px; color: #474747;">'
    "This role may require you to be on site at times.</span></strong></p>\n"
    '<p> </p>\n'
    '<p><span class="OOyDTc" style="line-height: 22px; color: #474747;">'
    "The Accounts Payable Assistant performs accounting and clerical tasks.</span>"
    '<span class="ejCXj" id="tsuid_3" style="overflow: hidden;">'
    "<br><br><strong>Key Responsibilities:</strong></span></p>\n"
    '<p><span class="ejCXj">• Office Support - filing, data retention.<br>'
    "• Conduct company business according to policies.</span></p>\n"
    '<img src="https://remotive.com/job/track/2090989/blank.gif?source=public_api" alt=""/>'
)

# Offre « Head of Sales » — div.h3 + styles inline lourds
HEAD_OF_SALES_HTML = (
    '<div class="h3" dir="ltr" style="line-height: 1.2;">'
    '<span style="color: #ff683d; font-weight: bold;">Who We Are</span></div>\n'
    '<p dir="ltr"><span style="color: #000000;">We build great products.</span></p>\n'
    "<ul><li>Remote first</li><li>Competitive salary</li></ul>"
)

# Offre « Inside Sales » — p + span + bold
INSIDE_SALES_HTML = (
    '<p dir="ltr" style="background-color: #ffffff;">'
    '<span style="color: #2d2d2d; font-weight: bold;">About Us</span></p>\n'
    '<p dir="ltr"><span style="color: #2d2d2d;">'
    "We help companies grow.</span></p>"
)

# Texte plat France Travail (aucun HTML)
FT_PLAIN = (
    "Votre futur environnement de travail :\n"
    "Sopra Steria accompagne la transformation Data.\n"
    "Votre rôle et vos missions:\n"
    "Vous participez à toutes les phases du développement."
)


# ── Tests ─────────────────────────────────────────────────────────────────


class TestNoResidualHTML:
    """Aucune balise HTML ne survit à la conversion."""

    @pytest.mark.parametrize("html", [ACCOUNTS_PAYABLE_HTML, HEAD_OF_SALES_HTML, INSIDE_SALES_HTML])
    def test_no_html_tags(self, html):
        md = html_to_markdown(html)
        assert "<" not in md, f"Balise résiduelle trouvée dans:\n{md}"

    def test_no_blank_gif(self):
        md = html_to_markdown(ACCOUNTS_PAYABLE_HTML)
        assert "blank.gif" not in md

    def test_no_google_classes(self):
        md = html_to_markdown(ACCOUNTS_PAYABLE_HTML)
        assert "OOyDTc" not in md
        assert "ejCXj" not in md


class TestMarkdownStructure:
    """Le Markdown conserve la hiérarchie (gras, listes)."""

    def test_bold_preserved(self):
        md = html_to_markdown(ACCOUNTS_PAYABLE_HTML)
        assert "**" in md, "Le gras (strong) doit produire du **bold**"

    def test_list_items_preserved(self):
        md = html_to_markdown(HEAD_OF_SALES_HTML)
        assert "Remote first" in md
        assert "Competitive salary" in md

    def test_content_preserved(self):
        md = html_to_markdown(ACCOUNTS_PAYABLE_HTML)
        assert "Accounts Payable Assistant" in md
        assert "Key Responsibilities" in md
        assert "Office Support" in md


class TestIdempotencePlainText:
    """Du texte déjà propre (FT) ne doit PAS être dégradé."""

    def test_ft_unchanged(self):
        md = html_to_markdown(FT_PLAIN)
        assert md == FT_PLAIN.strip()

    def test_ft_newlines_preserved(self):
        md = html_to_markdown(FT_PLAIN)
        assert "\n" in md, "Les retours à la ligne FT doivent être préservés"

    def test_plain_sentence(self):
        text = "Senior Python Developer — 5 ans d'expérience requis."
        assert html_to_markdown(text) == text


class TestEdgeCases:
    """Cas limites : vide, pixel seul, texte minimal."""

    def test_empty_string(self):
        assert html_to_markdown("") == ""

    def test_none_guard(self):
        # Le champ peut être None en théorie
        assert html_to_markdown(None) == ""

    def test_whitespace_only(self):
        assert html_to_markdown("   \n  ") == ""

    def test_tracking_pixel_only(self):
        pixel = '<img src="https://remotive.com/job/track/123/blank.gif?source=public_api" alt=""/>'
        assert html_to_markdown(pixel).strip() == ""

    def test_pixel_variants(self):
        for src in [
            '<img src="https://example.com/track/pixel.gif" />',
            '<img src="https://example.com/1x1.gif" alt="" />',
            '<img src="https://example.com/blank.gif?s=api" />',
        ]:
            md = html_to_markdown(src)
            assert "img" not in md.lower(), f"Pixel résiduel pour: {src}"
