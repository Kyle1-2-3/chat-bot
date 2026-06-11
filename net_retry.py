"""Retry helper for the cron-driven sync scripts.

A sync runs once a day, so a single transient network failure means a
day-long data gap — retry a couple of times with a short backoff first.
"""
import logging
import time

logger = logging.getLogger("sync")


def with_retry(fn, attempts: int = 3, delays: tuple = (2, 5)):
    """Call fn(); on failure wait delays[i] seconds and retry. Re-raises the
    last error once attempts are exhausted."""
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
            delay = delays[min(i, len(delays) - 1)]
            logger.warning("attempt %d/%d failed; retrying in %ss",
                           i + 1, attempts, delay, exc_info=True)
            time.sleep(delay)
