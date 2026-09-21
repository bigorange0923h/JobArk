"""失败响应契约：错误码、状态码与信息泄露边界。"""

from fastapi.testclient import TestClient


def _assert_error_envelope(response_json: dict) -> dict:
    """断言失败响应的通用形状。

    参数:
        response_json: 响应体。

    返回:
        dict: 便于进一步断言错误对象。
    """
    assert response_json["success"] is False
    assert "data" not in response_json
    assert response_json["meta"]["request_id"]
    error = response_json["error"]
    assert error["code"]
    assert error["message"]
    assert isinstance(error["details"], list)
    return error


def test_unknown_route_returns_route_not_found(client: TestClient) -> None:
    """未匹配的路由应映射为 ROUTE_NOT_FOUND（404）。"""
    response = client.get("/not-a-real-route")

    assert response.status_code == 404
    assert _assert_error_envelope(response.json())["code"] == "ROUTE_NOT_FOUND"


def test_method_not_allowed_is_mapped(client: TestClient) -> None:
    """不支持的方法应映射为 METHOD_NOT_ALLOWED（405）。"""
    response = client.post("/health")

    assert response.status_code == 405
    assert _assert_error_envelope(response.json())["code"] == "METHOD_NOT_ALLOWED"


def test_validation_error_reports_fields_without_echoing_input(client: TestClient) -> None:
    """校验失败应返回字段级细节，且不回显用户输入原文。"""
    response = client.get("/_probe/echo", params={"limit": "secret-value"})

    assert response.status_code == 422
    error = _assert_error_envelope(response.json())
    assert error["code"] == "VALIDATION_ERROR"
    assert any(detail["field"] == "query.limit" for detail in error["details"])
    assert "secret-value" not in response.text


def test_domain_error_uses_its_code_and_message(client: TestClient) -> None:
    """领域异常应使用声明在子类上的错误码与自定义提示。"""
    response = client.get("/_probe/missing")

    assert response.status_code == 404
    error = _assert_error_envelope(response.json())
    assert error["code"] == "RESOURCE_NOT_FOUND"
    assert error["message"] == "测试用的资源不存在。"


def test_unhandled_exception_hides_internals_and_keeps_request_id(client: TestClient) -> None:
    """未捕获异常应返回通用 500，且不泄露堆栈、异常类型或实现细节。"""
    response = client.get("/_probe/crash")

    assert response.status_code == 500
    error = _assert_error_envelope(response.json())
    assert error["code"] == "INTERNAL_ERROR"
    assert error["message"] == "服务器内部错误，请稍后重试。"
    assert response.headers["X-Request-ID"] == response.json()["meta"]["request_id"]
    for leaked in ("RuntimeError", "Traceback", "内部实现细节", "_probe", "test_error_contract"):
        assert leaked not in response.text
