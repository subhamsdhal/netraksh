from edge.main import EdgePipeline


def test_edge_auth_header_uses_configured_token_without_logging_it():
    pipeline = object.__new__(EdgePipeline)
    pipeline._edge_auth_token = "test-edge-token"

    assert pipeline._edge_auth_headers() == {
        "Authorization": "Bearer test-edge-token"
    }


def test_edge_auth_header_is_absent_without_a_token():
    pipeline = object.__new__(EdgePipeline)
    pipeline._edge_auth_token = ""

    assert pipeline._edge_auth_headers() == {}
