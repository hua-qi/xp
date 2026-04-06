from __future__ import annotations
from typing import Any, Callable


class UnregisteredCommandError(Exception):
    pass


class CommandBus:
    def __init__(self):
        self._handlers: dict[type, Callable] = {}

    def register(self, command_type: type, handler_fn: Callable) -> None:
        self._handlers[command_type] = handler_fn

    async def dispatch(self, command: Any) -> Any:
        handler = self._handlers.get(type(command))
        if handler is None:
            raise UnregisteredCommandError(f"No handler for {type(command).__name__}")
        return await handler(command)
