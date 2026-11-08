from app.services.glossary import as_list, merge_model_terms, relevant_terms, replace_with_user_terms


def test_model_terms_do_not_override_existing() -> None:
    g = {"Photosynthesis": {"target": "प्रकाश संश्लेषण", "origin": "user"}}
    added = merge_model_terms(g, {"photosynthesis": "फोटोसिंथेसिस", "Chlorophyll": "पर्णहरित"})
    assert added == 1
    assert g["Photosynthesis"]["target"] == "प्रकाश संश्लेषण"
    assert g["Chlorophyll"] == {"target": "पर्णहरित", "origin": "model"}


def test_user_replacement_marks_changes_as_user() -> None:
    g = {"Cell": {"target": "कोशिका", "origin": "model"}, "Tissue": {"target": "ऊतक", "origin": "model"}}
    new = replace_with_user_terms(g, [("Cell", "कोशिका"), ("Tissue", "उतक"), ("Organ", "अंग"), ("  ", "x")])
    assert new == {
        "Cell": {"target": "कोशिका", "origin": "model"},
        "Tissue": {"target": "उतक", "origin": "user"},
        "Organ": {"target": "अंग", "origin": "user"},
    }


def test_relevant_terms_only_matching_user_first() -> None:
    g = {
        "Cell": {"target": "कोशिका", "origin": "model"},
        "Cell wall": {"target": "कोशिका भित्ति", "origin": "user"},
        "Gravity": {"target": "गुरुत्व", "origin": "model"},
    }
    r = relevant_terms(g, ["The cell wall protects the cell."])
    assert list(r) == ["Cell wall", "Cell"]


def test_as_list_sorted() -> None:
    g = {"b": {"target": "2", "origin": "user"}, "A": {"target": "1", "origin": "model"}}
    assert [t["source"] for t in as_list(g)] == ["A", "b"]
