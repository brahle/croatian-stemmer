"""In-process token buckets per annotator (one replica; state resets on restart).

The daily cap is enforced in the database (routes), so a restart cannot reset it.
"""

import math
import time
from dataclasses import dataclass

from fastapi import HTTPException


@dataclass(frozen=True)
class Rate:
    capacity: float  # burst
    per_second: float  # sustained refill


# Section 3.3 of the design: answers 30/min sustained with a burst of 15;
# queue reads 120/min; consent, export and erasure 10/hour.
RATES = {
    "answer": Rate(15, 30 / 60),
    "read": Rate(120, 120 / 60),
    "account": Rate(10, 10 / 3600),
}


class Limiter:
    def __init__(self, rates=RATES, clock=time.monotonic):
        self.rates, self.clock = rates, clock
        self.buckets = {}

    def take(self, name: str, key) -> None:
        """Spend one token or raise 429 rate_limited with Retry-After."""
        rate = self.rates[name]
        now = self.clock()
        tokens, then = self.buckets.get((name, key), (rate.capacity, now))
        tokens = min(rate.capacity, tokens + (now - then) * rate.per_second)
        if tokens < 1:
            self.buckets[(name, key)] = (tokens, now)
            wait = max(1, math.ceil((1 - tokens) / rate.per_second))
            raise HTTPException(429, detail={"code": "rate_limited", "retry_after": wait},
                                headers={"Retry-After": str(wait)})
        self.buckets[(name, key)] = (tokens - 1, now)
        if len(self.buckets) > 50000:
            self.prune(now)

    def prune(self, now):
        """Forget buckets that have refilled completely; they carry no state."""
        for (name, key), (tokens, then) in list(self.buckets.items()):
            rate = self.rates[name]
            if tokens + (now - then) * rate.per_second >= rate.capacity:
                del self.buckets[(name, key)]
