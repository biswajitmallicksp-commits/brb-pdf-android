"""Memory-bounded LRU cache for rendered pages and thumbnails.

Only the pages you look at are rendered, and the oldest images are thrown
away once the memory budget is reached. This is what lets the viewer open
500+ page and scanned documents without filling RAM.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Callable, Hashable


class RenderCache:
    def __init__(self, budget_mb: int, size_of: Callable[[Any], int]):
        self._budget = budget_mb * 1024 * 1024
        self._size_of = size_of
        self._items: OrderedDict[Hashable, Any] = OrderedDict()
        self._sizes: dict[Hashable, int] = {}
        self._used = 0
        self._lock = threading.Lock()

    def get(self, key: Hashable):
        with self._lock:
            value = self._items.get(key)
            if value is not None:
                self._items.move_to_end(key)
            return value

    def __contains__(self, key: Hashable) -> bool:
        with self._lock:
            return key in self._items

    def put(self, key: Hashable, value: Any) -> None:
        size = max(1, int(self._size_of(value)))
        with self._lock:
            if key in self._items:
                self._used -= self._sizes.pop(key)
                del self._items[key]
            self._items[key] = value
            self._sizes[key] = size
            self._used += size
            while self._used > self._budget and len(self._items) > 1:
                old_key, _ = self._items.popitem(last=False)
                self._used -= self._sizes.pop(old_key)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._sizes.clear()
            self._used = 0

    @property
    def used_bytes(self) -> int:
        return self._used

    def __len__(self) -> int:
        return len(self._items)
