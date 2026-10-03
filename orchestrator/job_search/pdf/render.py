"""Rendu HTML -> PDF via Chromium headless (EXE-102, H3 du ticket).

Un navigateur Playwright par appel : l'usage est une action humaine explicite sur
une offre retenue, pas un run en volume — pas de process partagé entre requêtes.
"""

from __future__ import annotations

from playwright.sync_api import sync_playwright


def html_to_pdf(html: str) -> bytes:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            return page.pdf(format="A4", print_background=True)
        finally:
            browser.close()
