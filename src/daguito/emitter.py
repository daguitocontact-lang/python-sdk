"""Typed event emitter — mirrors sdks/js/src/emitter.ts.

Each session class composes an Emitter so integrators get a callable-based
`on('event', listener)` API. We don't try to recreate TS generics — payloads
are typed as `dict[str, Any]` and documented per event.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

Listener = Callable[[Any], None]

log = logging.getLogger("daguito.emitter")


class Emitter:
    """Tiny event emitter. Sync listeners only; async work belongs in the caller."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[Listener]] = {}

    def on(self, event: str, listener: Listener) -> Callable[[], None]:
        """Subscribe to an event. Returns an unsubscribe function."""
        self._listeners.setdefault(event, []).append(listener)

        def unsubscribe() -> None:
            self.off(event, listener)

        return unsubscribe

    def off(self, event: str, listener: Listener) -> None:
        bucket = self._listeners.get(event)
        if not bucket:
            return
        try:
            bucket.remove(listener)
        except ValueError:
            pass

    def emit(self, event: str, payload: Any) -> None:
        """Notify all listeners for `event`. A throwing listener doesn't stop the others."""
        bucket = self._listeners.get(event)
        if not bucket:
            return
        # Copy to allow listeners to unsubscribe during iteration.
        for listener in list(bucket):
            try:
                listener(payload)
            except Exception:
                log.exception("listener for event %r threw", event)

    def remove_all(self) -> None:
        self._listeners.clear()
