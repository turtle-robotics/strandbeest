import asyncio
import contextvars
import functools
import sys
from typing import Optional

class _Timeout:
    def __init__(self, when: Optional[float]) -> None:
        self._when = when
        self._timeout_handler = None
        self._expired = False

    def reschedule(self, when: Optional[float]) -> None:
        self._when = when

        if self._timeout_handler is not None:
            self._timeout_handler.cancel()

        if when is None:
            self._timeout_handler = None
        else:
            loop = asyncio.get_running_loop()
            if when <= loop.time():
                self._timeout_handler = loop.call_soon(self._on_timeout)
            else:
                self._timeout_handler = loop.call_at(when, self._on_timeout)

    async def __aenter__(self):
        self._task = asyncio.current_task()
        self.reschedule(self._when)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> Optional[bool]:
        if self._timeout_handler is not None:
            self._timeout_handler.cancel()
            self._timeout_handler = None

        if self._expired and exc_type is asyncio.CancelledError:
            raise TimeoutError from exc_val

        return None

    def _on_timeout(self) -> None:
        self._task.cancel()
        self._expired = True
        self._timeout_handler = None

def _timeout(delay: Optional[float] = None):
    loop = asyncio.get_running_loop()
    return _Timeout(loop.time() + delay if delay is not None else None)

async def _to_thread(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    func_call = functools.partial(ctx.run, func, *args, **kwargs)
    return await loop.run_in_executor(None, func_call)

if sys.version_info < (3, 8):
    import typing
    class Subscriptable:
        def __getitem__(self, arg):
            pass
    typing.Literal = Subscriptable()

if sys.version_info < (3, 9):
    asyncio.to_thread = _to_thread

if sys.version_info < (3, 11):
    asyncio.timeout = _timeout
