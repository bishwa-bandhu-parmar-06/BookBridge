"""Legacy (non-Unicode) Hindi font → Unicode conversion.

Many Hindi books are typeset in legacy fonts that draw Devanagari glyphs on top of Latin
code points, so the extracted text is gibberish (e.g. APS-DV-Priyanka "Fefleneme" is
really "इतिहास").

Implemented:
  * APS-DV family (APS-DV-Priyanka, -PriyankaRoman, -SURESH, -Yogita …), used by many
    UP/Prayagraj exam-book publishers (e.g. YCT). Mapping derived glyph-by-glyph from a
    real book and verified against the rendered pages.

Not implemented yet (books are rejected with a clear message):
  * Kruti Dev / DevLys, Chanakya / Walkman-Chanakya, Shusha …
    TODO: add converters here; nothing else in the app needs to change.

How the APS-DV encoding works
-----------------------------
Glyphs are *visual pieces*, not letters:
  * "e" is the vertical stem. A half-letter glyph + "e" = the full consonant
    ("m" स्, "me" स). After a complete consonant, "e" is the ा sign.
  * क / फ are left part + stem + right hook: "keâ" = क, "Heâ" = फ (without "â", "He" = प).
    Vowel marks can sit between stem and hook: "kesâ" = के, "kegâ" = कु.
  * ि is drawn before the consonant ("ef"), ी is "er", ो is "es" (ा + े).
  * Reph (र् on top) is typed after the syllable ("&"); the subscript ्र is typed after
    the consonant ("Ç"); the nukta is typed before it ("Ì").
The converter tokenises glyphs into syllable clusters and then reorders them into
Unicode logical order.
"""

from __future__ import annotations

import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class LegacyFontConverter(ABC):
    """Converts text extracted from one legacy font family into Unicode Devanagari."""

    #: normalised font-name substrings this converter handles
    font_patterns: tuple[str, ...] = ()
    name: str = "legacy"

    def can_convert(self, font_name: str) -> bool:
        n = re.sub(r"[\s\-_,]", "", font_name).lower()
        return any(p in n for p in self.font_patterns)

    @abstractmethod
    def convert(self, text: str) -> str:
        """Return the Unicode Devanagari equivalent of `text`."""


# --------------------------------------------------------------------------------------------
# APS-DV
# --------------------------------------------------------------------------------------------

HALANT = "्"
NUKTA = "़"
I_SIGN = "ि"  # ि
ANUSVARA = "ं"  # ं
CANDRABINDU = "ँ"  # ँ

# Half-letter glyphs: become full with a following stem "e"; otherwise half (+ ्).
APS_HALF: dict[str, str] = {
    "k": "क", "H": "प", "›": "क्र", "ø": "फ्र",
    "m": "स", "v": "न", "c": "म", "l": "त", "Ù": "य", "u": "ल", "J": "व", "h": "प",
    "L": "थ", "p": "ज", "i": "ग", "M": "श", "y": "ब", "O": "ध", "Y": "भ", "Ø": "प्र",
    "Û": "च", "C": "ण", "K": "ख", "<": "ष", "$": "त्र", "#": "क्ष", "ò": "त्त", "I": "घ",
    "%": "ज्ञ", "P": "झ", "ß": "श्र", "ë": "श्र", "å": "ल", "œ": "स्र", "Œ": "स्र", "»": "ज्र",
    "V": "न्न", "«": "ग्र", "ÿ": "ह्म", "Å": "द्य", "¢": "ह्य", "£": "ह्व", "_": "ञ",
    "§": "श्च", "©": "द्म", "Õ": "श्व", "¡": "ख्र",
    "D": "अ",
}
# Full glyphs without a stem (complete on their own).
APS_FULL: dict[str, str] = {
    "j": "र", "o": "द", "n": "ह", "š": "ट", '"': "ठ", "[": "ड", "{": "ढ", "Ú": "छ", "*": "ङ",
    "É": "द्व", "ô": "द्व", "æ": "द्ध", "õ": "द्र", "ö": "द्द", "ó": "ट्ट", "ñ": "ड्ड",
    "°": "ष्ट", "„": "ष्ट", "‰": "ष्ठ", "…": "ष्ठ", "ù": "हृ", "Â": "दृ", "Ü": "ह्र",
    "ª": "ट्ठ", "ú": "ट्ठ", "º": "ड्ढ", "Æ": "द्भ", "}": "ल",
    "™": "रू", "¤": "रू", "®": "रु",
    "F": "इ", "G": "उ", "T": "ऊ", "S": "ए",
}
# Signs written after the consonant.
APS_POST: dict[str, str] = {
    "s": "े", "w": "ै", "W": "ें", "Q": "ैं", "g": "ु", "t": "ू", "=": "ृ",
    "b": ANUSVARA, "B": CANDRABINDU, "@": "ॅ", "Î": "ु", "Ò": "ू", "Ï": "ौ",
}
# Signs that also put a reph on the current syllable.
APS_POST_REPH: dict[str, str] = {"x": "े", "X": "ें", "Ë": ANUSVARA, "&": ""}
# "e" + next char pairs.
APS_E_PRE: dict[str, tuple[str, bool]] = {  # pre-base ि forms: (sign, reph on next syllable)
    "f": (I_SIGN, False), "q": (I_SIGN, False),
    "E": (I_SIGN + ANUSVARA, False), "é": (I_SIGN + ANUSVARA, False),
    "|": (I_SIGN, True), "\\": (I_SIGN + ANUSVARA, True),
}
APS_E_POST: dict[str, tuple[str, bool]] = {"r": ("ी", False), "R": ("ीं", False), "a": ("ी", True)}
APS_RAKAR = {"Ç": "्र", "ü": "्र", "^": "्र"}
APS_PUNCT: dict[str, str] = {
    "~": "।", "`": "‘", "'": "’", "Š": ":", "·": "=", "±": "+", "³": "%",
}
# Glyphs whose meaning changes when the right hook "â"/"ä" follows: "He" प → "Heâ" फ,
# "òe" त्त → "òeâ" क्त.
_HOOK_SWAP: dict[str, tuple[str, str]] = {"H": ("प", "फ"), "h": ("प", "फ"), "ò": ("त्त", "क्त")}

# ा + other sign → combined sign
_VOWEL_MERGE = {("ा", "े"): "ो", ("ा", "ै"): "ौ", ("ा", "ॅ"): "ॉ"}
_INDEPENDENT = {
    ("अ", "ा"): "आ", ("अ", "ो"): "ओ", ("अ", "ौ"): "औ", ("अ", "ॉ"): "ऑ",
    ("ए", "ै"): "ऐ", ("ए", "े"): "ऐ",
}
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


@dataclass
class _Syllable:
    cons: str = ""
    pre: str = ""  # ि or िं typed before the consonant
    reph: bool = False
    signs: list[str] = field(default_factory=list)
    open: bool = False  # ends with a half consonant: the next consonant joins this syllable
    last_src: str = ""  # glyph that produced the last consonant (the "â" hook can change it)

    def render(self) -> str:
        vowels: list[str] = []
        nasal = ""
        pre = self.pre
        if pre.endswith(ANUSVARA):
            pre, nasal = pre[:-1], ANUSVARA
        if pre:
            vowels.append(pre)
        for s in self.signs:
            for ch in s:
                if ch in (ANUSVARA, CANDRABINDU):
                    nasal = ch
                elif vowels and vowels[-1] == ch:
                    continue  # the same sign typed twice prints on top of itself ("ceWs" = में)
                elif vowels and (vowels[-1], ch) in _VOWEL_MERGE:
                    vowels[-1] = _VOWEL_MERGE[(vowels[-1], ch)]
                else:
                    vowels.append(ch)
        cons = self.cons
        if cons in ("इ",) and self.reph:  # "F&" is ई, "FË" is ईं
            return "ई" + nasal
        if vowels and (cons, vowels[0]) in _INDEPENDENT:
            cons, vowels = _INDEPENDENT[(cons, vowels[0])], vowels[1:]
        return ("र" + HALANT if self.reph else "") + cons + "".join(vowels) + nasal


def _swap_hook(syl: _Syllable) -> None:
    swap = _HOOK_SWAP.get(syl.last_src)
    if swap:
        old, new = swap
        base = syl.cons.removesuffix(HALANT)
        if base.endswith(old):
            syl.cons = base[: -len(old)] + new + syl.cons[len(base):]
        syl.last_src = ""


class APSDVConverter(LegacyFontConverter):
    name = "APS-DV"
    font_patterns = ("apsdv",)

    def convert(self, text: str) -> str:
        out: list[str] = []
        syl: list[_Syllable] = []
        pending_pre = ""
        pending_reph = False
        pending_nukta = False

        def flush() -> None:
            nonlocal pending_pre, pending_reph
            out.extend(s.render() for s in syl)
            syl.clear()
            if pending_pre:  # stray ि with nothing after it
                out.append(pending_pre)
            pending_pre, pending_reph = "", False

        def add_consonant(cons: str, *, half: bool, src: str) -> None:
            nonlocal pending_pre, pending_reph, pending_nukta
            if pending_nukta:
                cons = cons[0] + NUKTA + cons[1:]
                pending_nukta = False
            if syl and syl[-1].open:
                cur = syl[-1]
                cur.cons += cons
            else:
                cur = _Syllable(cons=cons)
                syl.append(cur)
            if pending_pre:
                cur.pre, pending_pre = pending_pre, ""
            if pending_reph:
                cur.reph, pending_reph = True, False
            cur.last_src = src
            cur.open = half
            if half:
                cur.cons += HALANT

        def add_sign(sign: str) -> None:
            if syl and not syl[-1].open:
                syl[-1].signs.append(sign)
            elif syl:  # sign after a half consonant: treat the consonant as full
                syl[-1].cons = syl[-1].cons.removesuffix(HALANT)
                syl[-1].open = False
                syl[-1].signs.append(sign)
            else:
                out.append(sign)

        i, n = 0, len(text)
        while i < n:
            c = text[i]
            nxt = text[i + 1] if i + 1 < n else ""
            nxt2 = text[i + 2] if i + 2 < n else ""

            if c == "e":
                if nxt in APS_E_PRE:
                    sign, reph = APS_E_PRE[nxt]
                    pending_pre, pending_reph = sign, pending_reph or reph
                    i += 2
                    continue
                if nxt in APS_E_POST:
                    sign, reph = APS_E_POST[nxt]
                    add_sign(sign)
                    if reph and syl:
                        syl[-1].reph = True
                    i += 2
                    continue
                add_sign("ा")
                i += 1
                continue

            if c in APS_HALF or c == "Ÿ":
                # A following "e" is this glyph's stem, unless it belongs to an "e?" pair.
                has_stem = nxt == "e" and nxt2 not in APS_E_PRE and nxt2 not in APS_E_POST
                if c == "Ÿ":  # ्य attaches to the previous consonant
                    if syl:
                        syl[-1].cons = syl[-1].cons.removesuffix(HALANT) + HALANT + "य"
                        syl[-1].open = not has_stem
                        if not has_stem:
                            syl[-1].cons += HALANT
                    i += 2 if has_stem else 1
                    continue
                add_consonant(APS_HALF[c], half=not has_stem, src=c)
                i += 2 if has_stem else 1
                continue

            if c in APS_FULL:
                add_consonant(APS_FULL[c], half=False, src=c)
                i += 1
                continue

            if c == "â":  # right hook completing क / फ / क्त
                if syl:
                    _swap_hook(syl[-1])
                i += 1
                continue
            if c in ("ä", "d"):  # half hook / explicit halant
                if syl:
                    cur = syl[-1]
                    if c == "ä":
                        _swap_hook(cur)
                    if not cur.cons.endswith(HALANT):
                        cur.cons += HALANT
                    cur.open = True
                else:
                    out.append(HALANT)
                i += 1
                continue
            if c in APS_RAKAR:
                if syl:
                    syl[-1].cons = syl[-1].cons.removesuffix(HALANT) + APS_RAKAR[c]
                    syl[-1].open = False
                i += 1
                continue
            if c == "Í":  # ्रू
                if syl:
                    syl[-1].cons = syl[-1].cons.removesuffix(HALANT) + "्र"
                    syl[-1].open = False
                    syl[-1].signs.append("ू")
                i += 1
                continue
            if c == "Ì":
                pending_nukta = True
                i += 1
                continue
            if c == "]":
                if syl:
                    cur = syl[-1]
                    base = cur.cons.removesuffix(HALANT)
                    cur.cons = base + NUKTA + (HALANT if cur.cons.endswith(HALANT) else "")
                i += 1
                continue
            if c in APS_POST:
                add_sign(APS_POST[c])
                i += 1
                continue
            if c in APS_POST_REPH:
                if c == "&" and syl and syl[-1].cons == "इ":
                    syl[-1].reph = True  # ई
                    i += 1
                    continue
                if APS_POST_REPH[c]:
                    add_sign(APS_POST_REPH[c])
                if syl:
                    syl[-1].reph = True
                i += 1
                continue
            if c == "+" and syl and syl[-1].cons == "त्र" and not syl[-1].signs:
                syl[-1].cons = "ऋ"  # "$e+"
                i += 1
                continue

            # Not a glyph: punctuation, digits, spaces.
            flush()
            if c in APS_PUNCT:
                out.append(APS_PUNCT[c])
            elif c == ":" and out and _DEVANAGARI.match(out[-1][-1:] or ""):
                out.append("ः")
            elif c == "0" and out and _DEVANAGARI.match(out[-1][-1:] or "") and not (nxt.isdigit()):
                out.append("०")  # abbreviation mark, as in ई०पू०
            else:
                out.append(c)
            i += 1
        flush()
        return unicodedata.normalize("NFC", "".join(out))


_CONVERTERS: list[LegacyFontConverter] = [APSDVConverter()]


def get_converter(font_name: str) -> LegacyFontConverter | None:
    """Return a converter for `font_name`, or None if the font is not supported."""
    for conv in _CONVERTERS:
        if conv.can_convert(font_name):
            return conv
    return None
