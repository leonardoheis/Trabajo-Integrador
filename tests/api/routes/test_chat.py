from fastapi.testclient import TestClient

_OK = 200
_UNAUTHORIZED = 401


class TestChatEndpoint:
    def test_requires_authentication(self, client: TestClient) -> None:
        response = client.post("/chat", json={"question": "¿Qué dice la ordenanza?"})

        assert response.status_code == _UNAUTHORIZED

    def test_answers_with_sources_field(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/chat",
            json={"question": "¿Cuál es el presupuesto?"},
            headers=auth_headers,
        )

        assert response.status_code == _OK
        body = response.json()
        assert isinstance(body["answer"], str)
        assert isinstance(body["sources"], list)

    def test_accepts_metadata_filters(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/chat",
            json={"question": "¿Cuál es el presupuesto?", "filters": {"doc_type": "Ordenanza"}},
            headers=auth_headers,
        )

        assert response.status_code == _OK

    def test_stream_emits_tokens_then_sources_then_done(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/chat/stream",
            json={"question": "¿Cuál es el presupuesto?"},
            headers=auth_headers,
        )

        assert response.status_code == _OK
        assert response.headers["content-type"].startswith("text/event-stream")
        events = [line for line in response.text.splitlines() if line.startswith("event: ")]
        assert "event: token" in events
        assert events[-2:] == ["event: sources", "event: done"]
