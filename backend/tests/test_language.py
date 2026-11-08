from app.services.language import (
    detect_language,
    is_legacy_font_name,
    legacy_text_stats,
    looks_like_legacy_hindi,
    private_use_ratio,
)

HINDI = "प्रकाश संश्लेषण वह प्रक्रिया है जिसमें हरे पौधे सूर्य के प्रकाश की उपस्थिति में भोजन बनाते हैं।"
HINDI_WITH_EN = "प्रकाश संश्लेषण (Photosynthesis) वह प्रक्रिया है जिसमें हरे पौधे (green plants) भोजन बनाते हैं। CO2 और H2O का उपयोग होता है।"
ENGLISH = "Photosynthesis is the process by which green plants make their food in the presence of sunlight."

# Real Kruti Dev style gibberish (what a legacy-font Hindi PDF extracts to).
KRUTI_SAMPLES = [
    "Hkkjr ,d fo'kky ns'k gSA ;gk¡ dbZ Hkk\"kk,¡ cksyh tkrh gSaA Hkkjr dh laL—fr cgqr iqjkuh gSA",
    "izdk'k la'ys\"k.k ,d tSo jklk;fud izfØ;k gS ftlesa gjs ikS/ks Hkkstu cukrs gSaA iÙkh gjs jax dh gksrh gSA",
    "dqN tkudkjh ;gk¡ nh xbZ gSA v/;k; 1 foKku vkSj rduhdh ds ckjs esa gSA Nk= /;ku ls i<+saA",
]


def test_detect_hindi() -> None:
    g = detect_language(HINDI)
    assert g.lang == "hi" and g.devanagari_ratio > 0.95


def test_detect_hindi_with_english_terms() -> None:
    assert detect_language(HINDI_WITH_EN).lang == "hi"


def test_detect_english() -> None:
    g = detect_language(ENGLISH)
    assert g.lang == "en" and g.devanagari_ratio == 0


def test_english_with_some_hindi_terms_is_english() -> None:
    text = ENGLISH + " Photosynthesis (प्रकाश संश्लेषण) is important. " + ENGLISH
    assert detect_language(text).lang == "en"


def test_too_little_text_is_undetermined() -> None:
    assert detect_language("12 34 ab").lang is None


def test_legacy_font_names() -> None:
    for name in ["KrutiDev010", "ABCDEF+Kruti Dev 010", "Walkman-Chanakya905", "DevLys 010", "CHANAKYA", "DV-TTSurekh"]:
        assert is_legacy_font_name(name), name
    for name in ["NotoSansDevanagari-Regular", "Mangal", "Nirmala UI", "TimesNewRomanPSMT", "DVOT-SurekhMR", "Arial-BoldMT"]:
        assert not is_legacy_font_name(name), name


def test_kruti_dev_gibberish_is_detected() -> None:
    for s in KRUTI_SAMPLES:
        stats = legacy_text_stats(s)
        assert stats.is_legacy, (s, stats)
        assert looks_like_legacy_hindi(s)


def test_short_gibberish_from_spec() -> None:
    # Too short on its own, but repeated it is clearly legacy text
    assert looks_like_legacy_hindi(" ".join(["dqN tkudkjh"] * 6))


def test_english_is_not_legacy() -> None:
    samples = [
        ENGLISH * 3,
        "Newton's second law states that the rate of change of momentum of a body is directly proportional "
        "to the applied force and takes place in the direction in which the force acts. F = ma, where m is mass.",
        "Let us consider a right-angled triangle ABC in which angle B is 90 degrees. Then AC² = AB² + BC². "
        "This is known as the Pythagoras theorem and it is used in many problems of geometry.",
    ]
    for s in samples:
        assert not legacy_text_stats(s).is_legacy, s
        assert not looks_like_legacy_hindi(s)


def test_unicode_hindi_is_not_legacy() -> None:
    assert not looks_like_legacy_hindi(HINDI * 3)


def test_private_use_ratio() -> None:
    assert private_use_ratio("abc") == 0
    assert private_use_ratio("ab") == 0.5
