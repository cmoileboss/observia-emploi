"""."""
import re
import unicodedata
import html
from bs4 import BeautifulSoup


def supprimer_diacritiques(texte: str) -> str:
    """Remove diacritical marks from text."""
    if not texte:
        return ""
    return "".join(c for c in unicodedata.normalize(
        "NFD", texte) if unicodedata.category(c) != "Mn")


def normaliser_entreprise(nom: str | None) -> str:
    """Normalize company names with NFKC, case-folding, accent removal, and legal form stripping."""
    if not nom:
        return ""
    s = str(nom)
    # Unicode normalize NFKC
    s = unicodedata.normalize("NFKC", s)
    # lowercase
    s = s.casefold()
    # accents
    s = supprimer_diacritiques(s)
    # apostrophes
    s = s.replace("'", " ").replace("’", " ")
    # symbols
    s = re.sub(r"[+&/]", " ", s)
    # legal forms
    s = re.sub(r"\b(sa|sas|sasu|sarl|eurl|snc|sci|selarl)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # terminal group
    s = re.sub(r"\bgroupe$", " ", s)
    # remaining punctuation
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def normaliser_localite(nom: str | None) -> str:
    """Normalize locality names by removing accents, decorative prefixes, and punctuation."""
    if not nom:
        return ""
    s = str(nom)
    s = unicodedata.normalize("NFKC", s).casefold()
    s = supprimer_diacritiques(s)
    s = s.replace("-", " ").replace("'", " ").replace("’", " ")
    # decorative prefixes/suffixes
    s = re.sub(r"\b(ville de|commune de|cedex)\b", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def extraire_departement(pc: str | None) -> str:
    """Extract 2 or 3 digit department code from postal code."""
    if not pc:
        return ""
    pc = str(pc).strip()
    if len(pc) >= 3 and (pc.startswith("97") or pc.startswith("98")):
        return pc[:3]
    return pc[:2]


def normaliser_titre(titre: str | None) -> str:
    """Normalize job titles by handling H/F markers, protecting tech terms, and removing punctuation."""
    if not titre:
        return ""
    s = str(titre)
    s = unicodedata.normalize("NFKC", s).casefold()
    s = supprimer_diacritiques(s)

    # H/F, F/H, M/F
    s = re.sub(r"\b(h/f/x|f/h/x|h/f|f/h|h-f|f-h|hf|fh|m/f)\b", " ", s)

    # Protect tech terms
    s = re.sub(r"\bc\+\+", "cpp", s)
    s = re.sub(r"\bc#", "csharp", s)
    s = re.sub(r"\b\.net\b", "net", s)
    s = re.sub(r"\bback[- ]end\b", "backend", s)
    s = re.sub(r"\bfront[- ]end\b", "frontend", s)

    # Replaces slashes and hyphens not between word characters with space
    s = re.sub(r"(?<!\w)/|/(?!\w)", " ", s)
    s = re.sub(r"(?<!\w)-|-(?!\w)", " ", s)
    s = re.sub(r"[^\w\s/-]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def normaliser_description(desc: str | None) -> str:
    """Normalize descriptions by unescaping HTML, removing tags, and normalizing text."""
    if not desc:
        return ""
    s = str(desc)
    s = html.unescape(s)
    # clean HTML
    try:
        soup = BeautifulSoup(s, "html.parser")
        for tag in soup.find_all(["p", "div", "br", "li", "ul", "ol",
                                 "h1", "h2", "h3", "h4", "h5", "h6"]):
            tag.insert_after(" ")
        s = soup.get_text()
    except Exception:
        # fallback regex strip
        s = re.sub(r"<[^>]+>", " ", s)

    s = unicodedata.normalize("NFKC", s).casefold()
    s = supprimer_diacritiques(s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()
