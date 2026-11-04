"""Real SDK result models must retain their error and structured-result semantics."""

import pytest
from mcp_types import CallToolResult, TextContent

from deployment.verify import unpack


def test_verifier_handles_current_sdk_structured_and_text_results():
    assert unpack(CallToolResult(content=[], structured_content={"id": 7})) == {"id": 7}
    assert unpack(CallToolResult(content=[TextContent(type="text", text='{"id": 8}')])) == {"id": 8}


def test_verifier_refuses_error_even_when_content_looks_successful():
    with pytest.raises(RuntimeError):
        unpack(CallToolResult(content=[], structured_content={"id": 7}, is_error=True))
