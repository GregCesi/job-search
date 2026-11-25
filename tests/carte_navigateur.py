"""Outils des tests navigateur de la carte dessinée (EXE-216).

La page s'ouvre depuis le disque, sans serveur. Le dessin vit dans `#dessin`
(un SVG), le texte dans `#panneau`, les trois autres onglets dans `.page`. Les
éléments du dessin portent des attributs qui disent ce qu'ils sont :
`data-bloc`, `data-systeme`, `data-fichier`, `data-route`, `data-table`, et
`data-de` / `data-vers` sur les flèches.
"""

from __future__ import annotations

import re

from playwright.sync_api import expect


def ouvrir(page, sortie, ancre=""):
    assert sortie.is_file(), f"page absente : {sortie}"
    page.goto(sortie.as_uri() + ancre)
    page.wait_for_load_state("load")
    return page


def aller(page, ancre):
    page.evaluate("a => { location.hash = a }", ancre)


def dessin(page):
    return page.locator("#dessin svg")


def panneau(page):
    return page.locator("#panneau")


def section(page, titre, dans="#panneau"):
    entete = page.get_by_role("heading", name=re.compile("^" + re.escape(titre) + " "))
    conteneurs = ", ".join(f"{c.strip()} section.liens" for c in dans.split(","))
    return page.locator(conteneurs, has=entete)


def bloc(page, attribut, valeur):
    return page.locator(f'#dessin g.bloc[{attribut}="{valeur}"]')


def fleche(page, de, vers):
    return page.locator(f'#dessin path.fl[data-de="{de}"][data-vers="{vers}"]')


def boite(locator):
    expect(locator).to_be_visible()
    b = locator.bounding_box()
    assert b is not None
    return b


def cliquer_coin(page, locator, coin="haut-gauche"):
    """Clique à 5 pixels d'un coin du rectangle d'un bloc, loin de son titre."""
    b = boite(locator.locator("rect.fond").first)
    x = b["x"] + 5 if "gauche" in coin else b["x"] + b["width"] - 5
    y = b["y"] + 5 if "haut" in coin else b["y"] + b["height"] - 5
    page.mouse.click(x, y)


def style(locator, propriete):
    return locator.evaluate("(e, p) => getComputedStyle(e)[p]", propriete)


def niveau(page):
    return page.locator("#dessin").get_attribute("data-niveau")


def attendre_dessin(page, nom):
    expect(page.locator(f'#dessin svg[data-dessin="{nom}"]')).to_have_count(1)
