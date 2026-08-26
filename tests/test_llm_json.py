import json

from classiflow.llm_json import JSON_OBJECT_RE, strip_trailing_commas


class TestStripTrailingCommas:
    def test_removes_trailing_comma_before_closing_brace(self) -> None:
        text = '{"label": "decretos", "confidence": 0.9,}'
        assert json.loads(strip_trailing_commas(text)) == {"label": "decretos", "confidence": 0.9}

    def test_removes_trailing_comma_before_closing_bracket(self) -> None:
        text = '{"items": ["a", "b",]}'
        assert json.loads(strip_trailing_commas(text)) == {"items": ["a", "b"]}

    def test_leaves_valid_json_unchanged(self) -> None:
        text = '{"label": "decretos", "confidence": 0.9}'
        assert json.loads(strip_trailing_commas(text)) == {"label": "decretos", "confidence": 0.9}


class TestJsonObjectRe:
    def test_matches_a_json_object_embedded_in_surrounding_text(self) -> None:
        text = 'Here is the answer: {"label": "decretos"} -- hope that helps'
        match = JSON_OBJECT_RE.search(text)
        assert match is not None
        assert match.group() == '{"label": "decretos"}'
