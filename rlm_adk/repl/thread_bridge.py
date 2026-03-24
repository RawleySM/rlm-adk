"""Thread bridge: sync wrappers for cross-thread async dispatch.

This module provides factory functions that create synchronous callables
which dispatch work to an asyncio event loop from a worker thread using
``asyncio.run_coroutine_threadsafe()``.

ContextVar visibility boundary
------------------------------
ContextVars set in the event-loop thread are NOT visible in the worker
thread, and vice versa. The thread bridge crosses this boundary via
``run_coroutine_threadsafe`` -- the submitted coroutine runs in the
event-loop thread (where ADK's invocation context, tool context, and
session state live), while the calling code runs in a worker thread
(where the REPL executes user code). Data flows across this boundary
only through function arguments and return values.
"""

from __future__ import annotations

import asyncio
import contextvars
import os
from collections.abc import Callable
from typing import Any

# Thread-depth counter to prevent runaway recursive dispatch.
_THREAD_DEPTH: contextvars.ContextVar[int] = contextvars.ContextVar(
    "_THREAD_DEPTH", default=0
)


def make_sync_llm_query(
    llm_query_async: Callable[..., Any],
    loop: asyncio.AbstractEventLoop,
    *,
    timeout: float = 300.0,
    max_thread_depth: int | None = None,
) -> Callable[..., Any]:
    """Create a sync ``llm_query()`` callable that dispatches to *loop*.

    Parameters
    ----------
    llm_query_async:
        The async dispatch coroutine (e.g. from ``dispatch.py``).
    loop:
        The running event loop (must be alive in another thread).
    timeout:
        Seconds to wait for the async dispatch to complete.
    max_thread_depth:
        Maximum recursive thread-bridge depth.  Defaults to
        ``RLM_MAX_THREAD_DEPTH`` env var, then 10.

    Returns
    -------
    A sync callable ``llm_query(prompt, **kwargs) -> result`` that blocks
    the calling (worker) thread until the async dispatch completes.
    """
    _timeout = timeout
    _max_depth = max_thread_depth if max_thread_depth is not None else int(
        os.environ.get("RLM_MAX_THREAD_DEPTH", "10")
    )

    def llm_query(prompt: str, **kwargs: Any) -> Any:
        depth = _THREAD_DEPTH.get(0)
        if depth >= _max_depth:
            raise RuntimeError(
                f"Thread depth limit exceeded: {depth}/{_max_depth}"
            )
        _THREAD_DEPTH.set(depth + 1)
        try:
            future = asyncio.run_coroutine_threadsafe(
                llm_query_async(prompt, **kwargs), loop
            )
            return future.result(timeout=_timeout)
        finally:
            _THREAD_DEPTH.set(depth)

    return llm_query


def make_sync_llm_query_batched(
    llm_query_batched_async: Callable[..., Any],
    loop: asyncio.AbstractEventLoop,
    *,
    timeout: float = 300.0,
) -> Callable[..., Any]:
    """Create a sync ``llm_query_batched()`` callable that dispatches to *loop*.

    Parameters
    ----------
    llm_query_batched_async:
        The async batched dispatch coroutine (e.g. from ``dispatch.py``).
    loop:
        The running event loop (must be alive in another thread).
    timeout:
        Seconds to wait for the async dispatch to complete.

    Returns
    -------
    A sync callable ``llm_query_batched(prompts, **kwargs) -> list`` that
    blocks the calling (worker) thread until all children complete.
    """
    _timeout = timeout

    def llm_query_batched(prompts: list[str], **kwargs: Any) -> list[Any]:
        future = asyncio.run_coroutine_threadsafe(
            llm_query_batched_async(prompts, **kwargs), loop
        )
        return future.result(timeout=_timeout)

    return llm_query_batched
