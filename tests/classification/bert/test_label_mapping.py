from classiflow.classification.bert.label_mapping import (
    classifier_disagreement,
    normalize_bert_label,
)


class TestNormalizeBertLabel:
    def test_maps_known_beto_label_to_classiflow_taxonomy(self) -> None:
        assert normalize_bert_label("ordenanza") == "ordenanzas"
        assert normalize_bert_label("decreto") == "decretos"
        assert normalize_bert_label("resolucion_concejo_municipal") == (
            "resoluciones_concejo_municipal"
        )

    def test_otro_normalizes_to_itself(self) -> None:
        assert normalize_bert_label("otro") == "otro"

    def test_unrecognized_label_normalizes_to_none(self) -> None:
        assert normalize_bert_label("not_a_real_beto_label") is None


class TestClassifierDisagreement:
    def test_agreement_when_labels_match(self) -> None:
        assert classifier_disagreement("ordenanzas", "ordenanza") is False

    def test_disagreement_when_labels_differ(self) -> None:
        assert classifier_disagreement("decretos", "ordenanza") is True

    def test_disagreement_when_beto_label_is_otro_and_primary_is_a_real_category(self) -> None:
        assert classifier_disagreement("decretos", "otro") is True

    def test_agreement_when_both_say_otro(self) -> None:
        assert classifier_disagreement("otro", "otro") is False

    def test_disagreement_when_primary_says_otro_and_beto_says_a_real_category(self) -> None:
        assert classifier_disagreement("otro", "decreto") is True

    def test_no_disagreement_when_primary_label_outside_beto_taxonomy(self) -> None:
        assert classifier_disagreement("convenios", "ordenanza") is False
        assert classifier_disagreement("compendios_de_boletines", "decreto") is False
