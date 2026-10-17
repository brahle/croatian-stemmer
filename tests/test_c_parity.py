"""Cross-check the C stemmer (pg/croatian_stemmer.c) against the Python one.

Builds a tiny driver with the system C compiler and compares both stemmers on
every stop word plus synthetic inflections built from each rule's suffix
set and each transformation. Skipped when no C compiler is available.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from croatian_stemmer import stem
from croatian_stemmer.rules import STOP_WORDS, TRANSFORMATIONS, _RULES

PG_DIR = Path(__file__).resolve().parent.parent / "pg"

DRIVER = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "croatian_stemmer.h"

int main(void)
{
    char buf[512];

    while (fgets(buf, sizeof buf, stdin))
    {
        char *s;

        buf[strcspn(buf, "\n")] = '\0';
        s = croatian_stem(buf);
        printf("%s\n", s ? s : "(null)");
        free(s);
    }
    return 0;
}
"""

# Stems chosen to reach the different rule families (palatal, -ov/-ev,
# fleeting a, syllabic r, comparatives) once suffixes are attached.
BASES = [
    "grad", "kuć", "lijep", "velik", "nov", "star", "brz", "plan", "rat",
    "kralj", "važn", "slobodn", "trg", "krv", "prst", "šum", "duš", "riječ",
    "metr", "centr", "gradov", "učitelj", "pjesnik", "zakon", "polj", "more",
    "rad", "pis", "čit", "gled", "prič", "jezik", "pjesm", "dobr", "mlad",
    # Thematic vowel, -ova-/-uj- and -je- verbs (radi-la, djelova-ti,
    # djeluj-e, vidje-ti, donije-la), -stati and velar -gn presents.
    "radi", "gleda", "djelova", "djeluj", "pokaziva", "vidje", "donije",
    "posta", "postan", "pomogn",
    # Passive participles: jotated, palatal, -iran, -ivan, -nut, a-verb.
    "objavljen", "učinjen", "vraćen", "izgrađen", "završen", "korišten",
    "otvoren", "razvijen", "doveden", "organiziran", "očekivan",
    "spomenut", "napisan",
    # Fleeting a: -ak/-ac/-tak nouns, -tar/-bar/-dar, -ao, -stan, -ij.
    "postupak", "odlazak", "kupac", "stranac", "podatak", "metar", "dobar",
    "zadar", "kupc", "postupk", "posao", "pos", "topao", "došao", "koristan", "starij",
    "laks", "materijal", "program", "dijalog",
    # -aj nouns (slučaj-u, kraj-u), -dak nouns, -ozil, soft -eg/-ega
    # (naš-eg, snijeg, starij-eg, koleg-a), the checked -je- theme
    # (posjet, savjet, umrije), -ići -šl- (došl), -šljen participles,
    # a non-syllabic r before -at (brat) and a syllabic one (cvrč).
    "slučaj", "kraj", "igraj", "pogodak", "napredak", "vozil", "naš",
    "boljeg", "snijeg", "kolega", "posje", "savje", "umrije", "podije",
    "došl", "prošl", "mišljen", "struj", "bra", "cvrčak", "rđ",
]


def _words() -> list[str]:
    words = set(STOP_WORDS)
    suffixes = {"", "naj"}
    for _, alternatives in _RULES:
        suffixes.update(alternatives.split("|"))
    for base in BASES:
        for suffix in suffixes:
            words.add(base + suffix)
            words.add("naj" + base + suffix)
    for source in TRANSFORMATIONS:
        for base in ("gra", "pje", "uči", "ko"):
            words.add(base + source)
    return sorted(w for w in words if w and w != "naj")


@pytest.fixture(scope="module")
def c_stemmer(tmp_path_factory):
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        pytest.skip("no C compiler available")
    build = tmp_path_factory.mktemp("c_stemmer")
    driver = build / "driver.c"
    driver.write_text(DRIVER)
    binary = build / "driver"
    subprocess.run(
        [cc, "-O2", "-Wall", "-Werror", "-I", str(PG_DIR), "-o", str(binary),
         str(driver), str(PG_DIR / "croatian_stemmer.c")],
        check=True,
    )
    return binary


def test_c_matches_python(c_stemmer):
    words = _words()
    out = subprocess.run(
        [str(c_stemmer)], input="\n".join(words) + "\n",
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout.splitlines()
    assert len(out) == len(words)
    mismatches = [(w, c, stem(w)) for w, c in zip(words, out) if c != stem(w)]
    assert not mismatches, f"{len(mismatches)} mismatches, first: {mismatches[:10]}"
