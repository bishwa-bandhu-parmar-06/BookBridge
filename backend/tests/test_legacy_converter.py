"""APS-DV (APS-DV-Priyanka family) → Unicode. Pairs are real raw strings extracted from a
YCT history book, checked against the rendered pages."""

import pytest

from app.services.legacy_font_converter import APSDVConverter, get_converter

CASES = {
    "mece«e Fefleneme": "समग्र इतिहास",
    "efpeme keâeue keâe keâesF& efueefKele mee#Ùe veneR Øeehle neslee nw, Gmes": "जिस काल का कोई लिखित साक्ष्य नहीं प्राप्त होता है, उसे",
    "keânles nQ": "कहते हैं",
    "– ueieYeie 30 ueeKe F&0het0": "– लगभग 30 लाख ई०पू०",
    "Øeeiewefleneefmekeâ keâeue keâes efkeâleves YeeieeW ceW yeeBše ieÙee nw": "प्रागैतिहासिक काल को कितने भागों में बाँटा गया है",
    "Yeejle ceW meJe&ØeLece efkeâme Je<e& mes Øemlej Ùegie kesâ mevoYe& ceW": "भारत में सर्वप्रथम किस वर्ष से प्रस्तर युग के सन्दर्भ में",
    "– jeyeš& yeÇtme Hegâš ves": "– राबर्ट ब्रूस फुट ने",
    "[sveceeke&â kesâ keâeshesvensieve meb«eneueÙe keâer meece«eer mes hee<eeCe, keâebmÙe": "डेनमार्क के कोपेनहेगन संग्रहालय की सामग्री से पाषाण, कांस्य",
    # The book itself prints "रॉर्बट" here (reph typed on ब); the converter stays faithful.
    "Yet-Jew%eeefvekeâ hegjelelJeefJeo je@ye&š yeÇgme Hegâš": "भू-वैज्ञानिक पुरातत्वविद रॉर्बट ब्रुस फुट",
    "nQ[Sskeäme Øeehle efkeâÙee Lee": "हैंडऐक्स प्राप्त किया था",
    "Deemš^sueesefheLeskeâme": "आस्ट्रेलोपिथेकस",
    "efJeefueÙece eEkeâie": "विलियम किंग",
    "efMeJeepeer Depeg&ve efJeMJeveeLe": "शिवाजी अर्जुन विश्वनाथ",
    "efmekeäKe GòejeefOekeâejer": "सिक्ख उत्तराधिकारी",
    "hejJeleea ceewÙe& ÙepegJexo ceewÙeexòej": "परवर्ती मौर्य यजुर्वेद मौर्योत्तर",
    "Meelekeâe|Ce pÙeeseflee\\ueie ne@e\\[ie": "शातकर्णि ज्योतिर्लिंग हॉर्डिंग",
    "DeeÙeeX cegoeX leerLeËkeâj FËš": "आर्यों मुर्दों तीर्थंकर ईंट",
    "$e+iJeso Ùegæ Deb«espe Ûevõ efÉleerÙe KesÌ[e ÚesÌ[es": "ऋग्वेद युद्ध अंग्रेज चन्द्र द्वितीय खेड़ा छोड़ो",
    "je°^erÙe meeceüepÙe MewueeßeÙeeW DeJe%ee eEmen DeeoceieÌ{ DeefOekeâebMele:": "राष्ट्रीय साम्राज्य शैलाश्रयों अवज्ञा सिंह आदमगढ़ अधिकांशतः",
    "Åeeslekeâ (neJexmšj) yeÇÿeefieefj ¤he mecePeewlee ueKeveT": "द्योतक (हार्वेस्टर) ब्रह्मगिरि रूप समझौता लखनऊ",
    "meJe&ßes‰ œeesle øeâebmeermeer Âef° menŒe Je»eOeejer ie=¢e ëe=bieJesjhegj £eruej efYeVelee": "सर्वश्रेष्ठ स्रोत फ्रांसीसी दृष्टि सहस्र वज्रधारी गृह्य श्रृंगवेरपुर ह्वीलर भिन्नता",
    "heåueJe nñer De°ebieùoÙe yeÏæ keâesequ[nJee mJeerkeâejeseqkeäle efo*dveeie Ie_ed": "पल्लव हड्डी अष्टांगहृदय बौद्ध कोल्डिहवा स्वीकारोक्ति दिङ्नाग घञ्",
    "nseémšime SC[Ípe Heâ¡e <e[Ÿeb$e he§eele he©emebYeJe efJeÕe DeÆgle šÎLe DeôwleJeeo }eiet DeúejnJeeR efmeæÒ": "हेस्टिंग्स एण्ड्रूज फख्र षड्यंत्र पश्चात पद्मसंभव विश्व अद्भुत टुथ अद्वैतवाद लागू अट्ठारहवीं सिद्धू",
    "Üeme meesºue `Deª keâLeeSB'": "ह्रास सोड्ढल ‘अट्ठ कथाएँ’",
    "›eâebeflekeâejer ceje\"e nesce™ue ieg® Hegjehee<eeCe": "क्रांतिकारी मराठा होमरूल गुरु पुरापाषाण",
    "nQ~ (20³) 1±30 Š": "हैं। (20%) 1+30 :",
    "ceWs cesW cegbgb[e": "में में मुंडा",
    "DeefOeJeòeâe Meeòeâ Gòej meb«eneueÙe «eeefheâkeäme Heâuekeâ": "अधिवक्ता शाक्त उत्तर संग्रहालय ग्राफिक्स फलक",
}


@pytest.mark.parametrize("raw, expected", list(CASES.items()))
def test_aps_dv(raw: str, expected: str) -> None:
    assert APSDVConverter().convert(raw) == expected


def test_registry() -> None:
    for name in ["GRPGWU+APS-DV-PriyankaRoman", "APS-DV-Priyanka,Bold", "APS-DV-SURESH", "IHNVPB+APS-DV-Yogita,Bold"]:
        assert isinstance(get_converter(name), APSDVConverter), name
    for name in ["KrutiDev010", "TimesNewRoman", "NotoSansDevanagari", "Symbol"]:
        assert get_converter(name) is None, name


def test_digits_and_latin_punctuation_survive() -> None:
    assert APSDVConverter().convert("(1627-1707) 1863, 5-10") == "(1627-1707) 1863, 5-10"
