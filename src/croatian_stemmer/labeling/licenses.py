"""Licence compatibility for publishing labels derived from a source corpus.

Exported rows carry the source sentences, so a label release is an adaptation
of the source corpus: share-alike sources only allow share-alike releases.
"""

import re

CC0, BY, BY_SA = "CC0 1.0", "CC BY 4.0", "CC BY-SA 4.0"
LABEL_LICENSES = (CC0, BY, BY_SA)

_FAMILIES = {
    "cc0": ("CC0", "CC0 1.0", "CC0 1.0 UNIVERSAL", "CC ZERO", "PUBLIC DOMAIN", "PUBLIC DOMAIN MARK 1.0",
            "PDM 1.0", "CREATIVECOMMONS.ORG/PUBLICDOMAIN/ZERO/1.0", "CREATIVECOMMONS.ORG/PUBLICDOMAIN/MARK/1.0"),
    "by": ("CC BY 3.0", "CC BY 4.0", "CC BY 3.0 UNPORTED", "CC BY 4.0 INTERNATIONAL",
           "CREATIVE COMMONS ATTRIBUTION 3.0 UNPORTED", "CREATIVE COMMONS ATTRIBUTION 4.0 INTERNATIONAL",
           "CREATIVECOMMONS.ORG/LICENSES/BY/3.0", "CREATIVECOMMONS.ORG/LICENSES/BY/4.0"),
    "by-sa": ("CC BY SA 3.0", "CC BY SA 4.0", "CC BY SA 3.0 UNPORTED", "CC BY SA 4.0 INTERNATIONAL",
              "CREATIVE COMMONS ATTRIBUTION SHAREALIKE 3.0 UNPORTED",
              "CREATIVE COMMONS ATTRIBUTION SHAREALIKE 4.0 INTERNATIONAL",
              "CREATIVECOMMONS.ORG/LICENSES/BY SA/3.0", "CREATIVECOMMONS.ORG/LICENSES/BY SA/4.0"),
}
_ALLOWED = {"cc0": (CC0, BY, BY_SA), "by": (BY, BY_SA), "by-sa": (BY_SA,)}


def normalize(value: str) -> str:
    """Case, whitespace and separator variants: 'cc-by-sa-4.0' == 'CC BY-SA 4.0'."""
    value = value.strip().upper()
    value = re.sub(r"^HTTPS?://(WWW\.)?", "", value).rstrip("/")
    value = re.sub(r"[-_\s]+", " ", value)
    value = re.sub(r"\bCC ?0\b", "CC0", value)
    value = re.sub(r"\bSHARE ALIKE\b", "SHAREALIKE", value)
    value = re.sub(r"(\d) ?\. ?(\d)", r"\1.\2", value)
    return re.sub(r"\s*/\s*", "/", value).strip()


_LOOKUP = {normalize(name): family for family, names in _FAMILIES.items() for name in names}


def family(source_license: str) -> str | None:
    """'cc0', 'by', 'by-sa', or None for anything else (NC, ND, unknown)."""
    return _LOOKUP.get(normalize(source_license))


def allowed(source_license: str, *more: str | None) -> tuple[str, ...]:
    """Label licences a corpus under `source_license` may be published with; empty if none.
    Further licences (a lexicon whose suggestions the items carry) narrow it: the result is
    what every one of them allows, so the strictest wins."""
    result = None
    for value in (source_license, *more):
        if value is None:
            continue
        found = family(value)
        permitted = _ALLOWED[found] if found else ()
        result = permitted if result is None else tuple(x for x in result if x in permitted)
    return result or ()
