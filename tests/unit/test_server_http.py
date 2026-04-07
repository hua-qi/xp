def test_server_has_search_tool():
    import inspect
    import src.server as server_mod
    source = inspect.getsource(server_mod)
    assert "search" in source


def test_server_has_save_tool():
    import inspect
    import src.server as server_mod
    source = inspect.getsource(server_mod)
    assert "save" in source


def test_server_has_feedback_tool():
    import inspect
    import src.server as server_mod
    source = inspect.getsource(server_mod)
    assert "feedback" in source


def test_server_does_not_use_stdio_transport():
    import inspect
    import src.server as server_mod
    source = inspect.getsource(server_mod)
    assert "StdioServerTransport" not in source
    assert "stdio_server" not in source
