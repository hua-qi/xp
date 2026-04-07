import pytest


def test_server_uses_fastmcp():
    import src.server as server_module
    assert hasattr(server_module, "mcp")


def test_server_has_run_function():
    import src.server as server_module
    assert callable(server_module.run)


def test_server_tools_are_registered():
    import inspect
    import src.server as server_module
    source = inspect.getsource(server_module)
    assert "async def search" in source
    assert "async def save" in source
    assert "async def feedback" in source


def test_server_does_not_depend_on_edge_client():
    import inspect
    import src.server as server_module
    source = inspect.getsource(server_module)
    assert "EdgeFunctionClient" not in source
