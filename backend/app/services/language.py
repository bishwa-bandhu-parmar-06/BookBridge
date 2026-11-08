"""Language detection and legacy (non-Unicode) Hindi font detection.

Pure functions on strings so they are easy to unit-test. PDF-specific checks
(font names) live in pdf_reader.py and call into this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Lang = Literal["hi", "en"]

DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
LATIN_RE = re.compile(r"[A-Za-z]")
PUA_RE = re.compile(r"[-]")

# A text is Hindi if at least this share of its letters are Devanagari.
# Matras count as Devanagari characters, so genuine Hindi text scores ~0.85+
# even with English terms mixed in, and English books score ~0.0.
HINDI_THRESHOLD = 0.40
MIN_LETTERS = 20


@dataclass
class LanguageGuess:
    lang: Lang | None
    devanagari_ratio: float
    letters: int


def detect_language(text: str) -> LanguageGuess:
    deva = len(DEVANAGARI_RE.findall(text))
    latin = len(LATIN_RE.findall(text))
    letters = deva + latin
    if letters < MIN_LETTERS:
        return LanguageGuess(lang=None, devanagari_ratio=0.0, letters=letters)
    ratio = deva / letters
    return LanguageGuess(lang="hi" if ratio >= HINDI_THRESHOLD else "en", devanagari_ratio=ratio, letters=letters)


def other_lang(lang: Lang) -> Lang:
    return "en" if lang == "hi" else "hi"


def private_use_ratio(text: str) -> float:
    """Share of non-space characters in the Unicode Private Use Area.

    A high value means the PDF's fonts map glyphs to private codepoints and the
    text cannot be extracted meaningfully.
    """
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    return len(PUA_RE.findall(text)) / len(chars)


# --------------------------------------------------------------------------------------------
# Legacy font detection
# --------------------------------------------------------------------------------------------

# Normalised (lowercase, no spaces/hyphens/underscores) substrings of known legacy
# non-Unicode Devanagari font families.
LEGACY_FONT_PATTERNS: tuple[str, ...] = (
    "krutidev",
    "kruti",
    "devlys",
    "chanakya",
    "walkman",
    "shusha",
    "akruti",
    "apsdv",
    "shreedev",
    "dvtt",          # ISM "DV-TT..." fonts (but not "DVOT...", which are Unicode)
    "sushma",
    "shivaji",
    "kundli",
)


def normalise_font_name(name: str) -> str:
    # Drop subset prefix like "ABCDEF+KrutiDev010".
    if "+" in name and len(name.split("+", 1)[0]) == 6:
        name = name.split("+", 1)[1]
    return re.sub(r"[\s\-_,]", "", name).lower()


def is_legacy_font_name(name: str) -> bool:
    n = normalise_font_name(name)
    return any(p in n for p in LEGACY_FONT_PATTERNS)


# ~200 most frequent English words. Real English prose has 35–55% of its tokens in this set;
# Kruti Dev / Chanakya gibberish has almost none.
COMMON_EN_WORDS: frozenset[str] = frozenset(
    """
    a about above after again all also an and any are as at be because been before being below
    between both but by can could did do does each few for from further had has have having he her
    here him his how i if in into is it its itself just more most my no nor not now of off on once
    only or other our out over own same she should so some such than that the their them then there
    these they this those through to too under until up very was we were what when where which while
    who whom why will with would you your
    one two three four five six seven eight nine ten first second called use used using shown given
    find show example fig figure table chapter unit lesson activity exercise question answer
    water energy force body cell plant plants animals light heat time number numbers made make many
    new may must way different form forms called known like same also such each other per value
    """.split()
)

_TOKEN_RE = re.compile(r"\S+")
_STRIP_PUNCT = ".,;:!?\"'()[]{}«»“”‘’"
# Characters that legacy fonts map Devanagari glyphs to and that rarely occur inside English words.
_WEIRD_INNER = set("';/~]}[{|\\@#$^&*=<>`")
_LATIN1_SUPP_RE = re.compile(r"[À-ÿŒœŸ™¡-¿]")
_VOWELS = set("aeiouAEIOU")


@dataclass
class LegacyTextStats:
    latin_tokens: int
    common_word_ratio: float
    weird_token_ratio: float
    vowel_ratio: float
    is_legacy: bool


def _is_weird_token(tok: str) -> bool:
    core = tok.strip(_STRIP_PUNCT.replace("'", "").replace(",", ""))
    if not core:
        return False
    # ",d" (एक in Kruti Dev): a comma glued to the front of a word
    if len(core) > 1 and core[0] == "," and core[1].isalpha():
        return True
    inner = core[1:-1]
    if any(c in _WEIRD_INNER for c in inner):
        return True
    # lowercase followed by uppercase inside a token: "gSA", "dqN", "eSa"
    for a, b in zip(core, core[1:]):
        if a.islower() and b.isupper():
            return True
    if _LATIN1_SUPP_RE.search(core):
        return True
    return False


def legacy_text_stats(text: str) -> LegacyTextStats:
    tokens = [t for t in _TOKEN_RE.findall(text) if LATIN_RE.search(t) and not DEVANAGARI_RE.search(t)]
    n = len(tokens)
    if n == 0:
        return LegacyTextStats(0, 0.0, 0.0, 0.0, False)

    words = [t.strip(_STRIP_PUNCT).lower() for t in tokens]
    common = sum(1 for w in words if w in COMMON_EN_WORDS)
    weird = sum(1 for t in tokens if _is_weird_token(t))
    letters = [c for t in tokens for c in t if c.isascii() and c.isalpha()]
    vowels = sum(1 for c in letters if c in _VOWELS)

    common_ratio = common / n
    weird_ratio = weird / n
    vowel_ratio = vowels / len(letters) if letters else 0.0

    is_legacy = (
        n >= 10
        and common_ratio < 0.10
        and (weird_ratio >= 0.15 or vowel_ratio < 0.28)
    )
    return LegacyTextStats(n, common_ratio, weird_ratio, vowel_ratio, is_legacy)


def looks_like_legacy_hindi(text: str) -> bool:
    """True if `text` is mostly Latin letters that look like legacy-font Hindi gibberish."""
    guess = detect_language(text)
    if guess.lang == "hi":
        return False
    return legacy_text_stats(text).is_legacy
