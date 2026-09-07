from langgraph.errors import GraphRecursionError

from src.agent.session_manager import workflow_agent_failure_error


def test_api_exception_keeps_upstream_inspection_text():
    error = Exception(
        "Error code: 400 - {'error': {'message': "
        "'Input text data may contain inappropriate content.', "
        "'type': 'data_inspection_failed'}}"
    )

    message = workflow_agent_failure_error(session_status="error", exception=error)

    assert "data_inspection_failed" in message
    assert "inappropriate content" in message
    assert "轮次上限" not in message


def test_recursion_error_keeps_round_limit_fallback():
    message = workflow_agent_failure_error(
        session_status="error",
        exception=GraphRecursionError("Recursion limit of 25 reached"),
    )

    assert message == "Agent 执行异常结束（可能是达到轮次上限）"
