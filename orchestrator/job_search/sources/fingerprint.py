import hashlib
import unicodedata


def _normalize(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def fingerprint(title: str, company: str, location: str) -> str:
    key = "|".join([_normalize(title), _normalize(company), _normalize(location)])
    return hashlib.sha256(key.encode()).hexdigest()[:16]
