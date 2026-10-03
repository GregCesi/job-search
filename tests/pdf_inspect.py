"""Inspection d'un PDF produit par Chromium (EXE-102) — stdlib seulement (re +
zlib), pour ne pas ajouter de dépendance de lecture de PDF aux tests alors que
H3 n'autorise que celle qui produit le PDF (Playwright).

Chromium encode le texte en Identity-H (CID = index de glyphe, pas le caractère) :
retrouver le texte affiché suppose de suivre, pour chaque bloc BT/police
sélectionnée (Tf), la table ToUnicode du font correspondant. Un nouveau bloc BT
sépare les lignes de texte (un Td interne au même bloc ne sépare jamais : Chromium
le réutilise pour des ajustements de crénage à l'intérieur d'un même mot).
"""

from __future__ import annotations

import re
import zlib

_OBJ_RE = re.compile(rb"(\d+)\s+0\s+obj(.*?)endobj", re.DOTALL)
_STREAM_RE = re.compile(rb"stream\r?\n(.*?)endstream", re.DOTALL)
_CONTENT_OP_RE = re.compile(
    rb"(BT)"
    rb"|/(F\d+)\s+[\d.]+\s+Tf"
    rb"|\[((?:<[0-9A-Fa-f]+>|\([^)]*\)|[-\d.]+)*)\]\s*TJ"
    rb"|<([0-9A-Fa-f]+)>\s*Tj"
)


def _stream_data(body: bytes | None) -> bytes | None:
    if body is None:
        return None
    m = _STREAM_RE.search(body)
    if not m:
        return None
    raw = m.group(1)
    try:
        return zlib.decompress(raw)
    except zlib.error:
        return raw


def _parse_tounicode(data: bytes) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for m in re.finditer(rb"beginbfchar(.*?)endbfchar", data, re.DOTALL):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", m.group(1)):
            cid = int(src, 16)
            units = [int(dst[i : i + 4], 16) for i in range(0, len(dst), 4)]
            mapping[cid] = "".join(chr(u) for u in units)
    for m in re.finditer(rb"beginbfrange(.*?)endbfrange", data, re.DOTALL):
        for lo, hi, dst in re.findall(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", m.group(1)
        ):
            lo_i, hi_i = int(lo, 16), int(hi, 16)
            base = int(dst, 16)
            for offset, cid in enumerate(range(lo_i, hi_i + 1)):
                mapping[cid] = chr(base + offset)
    return mapping


def _parse_objects(pdf_bytes: bytes) -> dict[int, bytes]:
    return {int(num): body for num, body in _OBJ_RE.findall(pdf_bytes)}


def _font_cmaps(objects: dict[int, bytes]) -> dict[int, dict[int, str]]:
    cmaps: dict[int, dict[int, str]] = {}
    for num, body in objects.items():
        if b"/Type /Font" not in body and b"/Type/Font" not in body:
            continue
        m = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", body)
        if not m:
            continue
        data = _stream_data(objects.get(int(m.group(1))))
        if data:
            cmaps[num] = _parse_tounicode(data)
    return cmaps


def _ordered_page_numbers(objects: dict[int, bytes]) -> list[int]:
    for body in objects.values():
        if re.search(rb"/Type\s*/Pages\b", body) and b"/Kids" in body:
            m = re.search(rb"/Kids\s*\[(.*?)\]", body, re.DOTALL)
            if m:
                return [int(x) for x in re.findall(rb"(\d+)\s+0\s+R", m.group(1))]
    return []


def extract_text(pdf_bytes: bytes) -> str:
    """Texte affiché, lignes séparées par des sauts de ligne, pages concaténées
    dans l'ordre. Best-effort : suffisant pour vérifier qu'un mot ou qu'une phrase
    apparaît, pas un rendu fidèle des espacements."""
    objects = _parse_objects(pdf_bytes)
    font_cmaps = _font_cmaps(objects)

    out: list[str] = []
    for pnum in _ordered_page_numbers(objects):
        page_body = objects.get(pnum, b"")
        font_tag_to_obj = {
            tag.decode(): int(objnum)
            for tag, objnum in re.findall(rb"/(F\d+)\s+(\d+)\s+0\s+R", page_body)
        }
        content_nums: list[int] = []
        m = re.search(rb"/Contents\s+(\d+)\s+0\s+R", page_body)
        if m:
            content_nums = [int(m.group(1))]
        else:
            m = re.search(rb"/Contents\s*\[(.*?)\]", page_body, re.DOTALL)
            if m:
                content_nums = [
                    int(x) for x in re.findall(rb"(\d+)\s+0\s+R", m.group(1))
                ]

        current_cmap: dict[int, str] = {}
        for cnum in content_nums:
            data = _stream_data(objects.get(cnum))
            if not data:
                continue
            for m in _CONTENT_OP_RE.finditer(data):
                bt, font_tag, tj_array, tj_hex = m.groups()
                if bt:
                    if out:
                        out.append("\n")
                elif font_tag:
                    obj = font_tag_to_obj.get(font_tag.decode())
                    current_cmap = font_cmaps.get(obj, {}) if obj else {}
                elif tj_array is not None:
                    for hexs in re.findall(rb"<([0-9A-Fa-f]+)>", tj_array):
                        for i in range(0, len(hexs), 4):
                            out.append(current_cmap.get(int(hexs[i : i + 4], 16), ""))
                elif tj_hex is not None:
                    for i in range(0, len(tj_hex), 4):
                        out.append(current_cmap.get(int(tj_hex[i : i + 4], 16), ""))
    return "".join(out)


def page_count(pdf_bytes: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf_bytes))


def media_box(pdf_bytes: bytes) -> tuple[float, float]:
    m = re.search(
        rb"/MediaBox\s*\[\s*[\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)\s*\]", pdf_bytes
    )
    assert m, "MediaBox introuvable dans le PDF"
    return float(m.group(1)), float(m.group(2))


_A4_WIDTH_PT = 595.28
_A4_HEIGHT_PT = 841.89


def is_a4(pdf_bytes: bytes, tolerance: float = 2.0) -> bool:
    width, height = media_box(pdf_bytes)
    return (
        abs(width - _A4_WIDTH_PT) <= tolerance
        and abs(height - _A4_HEIGHT_PT) <= tolerance
    )
