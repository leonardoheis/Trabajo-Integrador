import pytest

from classiflow.classification.domain.categories import DocumentCategory
from classiflow.classification.ground_truth import expected_category, expected_label


class TestExpectedCategory:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("boletin_980_2019.pdf", DocumentCategory.BOLETINES),
            ("convenio_394_2023.pdf", DocumentCategory.CONVENIOS),
            (
                "declaracion_5920_2022.pdf",
                DocumentCategory.DECLARACIONES_CONCEJO_MUNICIPAL,
            ),
            ("decreto_989_2013.pdf", DocumentCategory.DECRETOS),
            ("ordenanza_9964_2019.pdf", DocumentCategory.ORDENANZAS),
            ("resolucion_1_2021.pdf", DocumentCategory.RESOLUCIONES),
        ],
    )
    def test_matches_each_plain_prefix(self, filename: str, expected: DocumentCategory) -> None:
        assert expected_category(filename) == expected

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            # Both start with "decreto_" -- the longer prefixes must win, or every
            # council decree and decree-ordinance collapses into plain "decretos".
            ("decreto_cm_68770_2025.pdf", DocumentCategory.DECRETOS_CONCEJO_MUNICIPAL),
            ("decreto_ordenanza_47614_1973.pdf", DocumentCategory.DECRETO_ORDENANZAS),
            # Starts with "resolucion_".
            (
                "resolucion_cm_6086_2026.pdf",
                DocumentCategory.RESOLUCIONES_CONCEJO_MUNICIPAL,
            ),
        ],
    )
    def test_longer_prefix_wins_over_the_prefix_it_starts_with(
        self, filename: str, expected: DocumentCategory
    ) -> None:
        assert expected_category(filename) == expected

    @pytest.mark.parametrize(
        "filename",
        [
            "A0470.pdf",  # Banco Central "Comunicación A 470"
            "Informe_Agosto_2021.pdf",
            "DIA_A_Grupos_ACTUALIZADOS.xlsx",
            "v-reqcac_17-08-24.pdf",
        ],
    )
    def test_non_municipal_documents_are_labelled_otro(self, filename: str) -> None:
        # OTRO is a real category the classifier predicts (and which the confidence gate
        # always routes to human_review), so these are labelled examples to score
        # against -- not documents to exclude from the measurement.
        assert expected_category(filename) == DocumentCategory.OTRO

    def test_returns_none_for_names_the_convention_says_nothing_about(self) -> None:
        # None means "unlabelled", not "out of scope" -- it keeps the document out of the
        # accuracy denominator instead of guessing.
        assert expected_category("test.txt") is None

    def test_is_case_insensitive(self) -> None:
        assert expected_category("BOLETIN_980_2019.PDF") == DocumentCategory.BOLETINES

    def test_bare_category_word_without_separator_does_not_match(self) -> None:
        # The trailing underscore in every prefix means "decretos_report.pdf" (a plural,
        # not the singular the convention uses) is not silently labelled.
        assert expected_category("decretos.pdf") is None


class TestExpectedLabel:
    def test_returns_the_string_value(self) -> None:
        assert expected_label("ordenanza_9964_2019.pdf") == "ordenanzas"

    def test_returns_otro_for_a_non_municipal_document(self) -> None:
        assert expected_label("A0470.pdf") == "otro"

    def test_returns_none_when_no_category_matches(self) -> None:
        assert expected_label("test.txt") is None
