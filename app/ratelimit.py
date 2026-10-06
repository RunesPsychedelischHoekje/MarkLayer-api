"""In-memory rate limits for the free public checker (the paid API is rate-limited by RapidAPI).

LESSON: a sliding window per client keeps timestamps of recent requests and drops the ones older
than the window. It lives in process memory, so it resets on restart and isn't shared between
instances: fine for one small server whose only goal is stopping scripts from using the free
page as an unpaid API.
"""
import threading
import time
from collections import defaultdict, deque

from app.errors import ApiError


class RateLimiter:
    def __init__(self, per_client: int, window_s: float, daily_cap: int):
        self.per_client, self.window_s, self.daily_cap = per_client, window_s, daily_cap
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._day = (0, 0)  # (day number, requests that day)
        self._lock = threading.Lock()

    def check(self, client: str) -> None:
        now = time.time()
        with self._lock:
            day = int(now // 86400)
            count = self._day[1] if self._day[0] == day else 0
            if count >= self.daily_cap:
                raise ApiError(429, "daily_limit", "The free checker has reached today's limit. "
                                                   "Try again tomorrow, or use the MarkLayer API.")
            hits = self._hits[client]
            while hits and hits[0] <= now - self.window_s:
                hits.popleft()
            if len(hits) >= self.per_client:
                wait_min = int((hits[0] + self.window_s - now) // 60) + 1
                raise ApiError(429, "rate_limited",
                               f"Free checks are limited to {self.per_client} per hour. Try again in {wait_min} min.")
            hits.append(now)
            self._day = (day, count + 1)
            if len(self._hits) > 50_000:  # forget idle clients so memory stays bounded
                for k in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window_s]:
                    del self._hits[k]
