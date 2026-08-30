from classiflow.classification.bert.text_cleaning import clean_text, detect_foreign_municipality
from classiflow.classification.config_classification import ClassificationConfig

_ROSARIO_CONFIG = ClassificationConfig(ood_trained_municipality="rosario")


class TestCleanText:
    def test_strips_form_feed_and_nbsp(self) -> None:
        assert clean_text("a\fb\xa0c") == "a b c"

    def test_collapses_triple_newlines(self) -> None:
        assert clean_text("a\n\n\n\nb") == "a\n\nb"

    def test_strips_markdown_table_separator_rows(self) -> None:
        assert not clean_text("| --- | --- |")


class TestDetectForeignMunicipality:
    def test_returns_none_when_only_trained_municipality_named(self) -> None:
        text = "La Municipalidad de Rosario informa..."
        assert detect_foreign_municipality(text, _ROSARIO_CONFIG) is None

    def test_returns_match_for_a_different_municipality(self) -> None:
        text = "La Municipalidad de Cordoba informa una nueva ordenanza."
        match = detect_foreign_municipality(text, _ROSARIO_CONFIG)
        assert match is not None
        assert match.name == "Cordoba"
        assert "Cordoba" in match.context

    def test_returns_none_when_no_municipalidad_phrase_present(self) -> None:
        assert detect_foreign_municipality("Texto sin mención alguna.", _ROSARIO_CONFIG) is None

    def test_returns_none_for_ocr_corrupted_rosario(self) -> None:
        # decreto_cm_69438_2026.pdf's scanner-corrupted text read "Rpsario" -- a
        # one-character misread of the home municipality's own name, not a genuine
        # foreign municipality.
        text = "La Municipalidad de Rpsario informa..."
        assert detect_foreign_municipality(text, _ROSARIO_CONFIG) is None

    def test_still_flags_a_genuinely_different_short_name(self) -> None:
        # Guards the fuzzy-match fix against becoming too lenient: a real foreign
        # municipality with a short name must still be flagged.
        text = "La Municipalidad de Funes informa..."
        match = detect_foreign_municipality(text, _ROSARIO_CONFIG)
        assert match is not None
        assert match.name == "Funes"
