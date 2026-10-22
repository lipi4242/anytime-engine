"""Review-window logic of State (a mixin, so state.py stays one responsibility).

Windows come from config.review_windows() so review_due() and review_type()
derive from ONE source and can never drift (the pre-window bug: review_type
used broad hour-bands while review_due keyed off exact open-times, so a review
sent early in a band did not "service" the window and review_due flipped True
again, risking a duplicate).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import config, receipts


class ReviewWindowsMixin:
    reviews_serviced: dict
    last_review_at: str | None
    last_review_type: str | None
    last_trigger: str | None

    def now(self) -> datetime:  # provided by State
        raise NotImplementedError

    @staticmethod
    def _current_window(when: datetime) -> tuple[str, str] | None:
        """The latest window whose open time is <= `when`; None before the first."""
        cur = when.strftime("%H:%M")
        active: tuple[str, str] | None = None
        for name, open_time in config.review_windows():
            if cur >= open_time:
                active = (name, open_time)
        return active

    def _serviced_today(self, today: str) -> set[str]:
        """Window names serviced today. Falls back to last_review_at for state
        written before reviews_serviced existed (smooth migration)."""
        serviced = set(self.reviews_serviced.get(today, []))
        if not serviced and self.last_review_at:
            try:
                last = datetime.fromisoformat(self.last_review_at)
            except (ValueError, TypeError):
                return serviced
            if last.strftime("%Y-%m-%d") == today:
                w = self._current_window(last)
                if w:
                    serviced.add(w[0])
                elif self.last_review_type:
                    serviced.add(self.last_review_type)
        return serviced

    def review_due(self, now: datetime | None = None) -> bool:
        """True if the CURRENT window has opened and isn't serviced today. Keyed
        off the window, not a timestamp: an early send counts, no duplicate."""
        now = now or self.now()
        if not config.review_windows():
            config.warn_once(
                "no_review_windows",
                "review_due() asked, but no review windows are configured — set "
                "ANYTIME_REVIEW_TIMES (e.g. 08:30,17:30) or ANYTIME_REVIEW_WINDOWS. "
                "Until then no review is ever due.")
            return False
        w = self._current_window(now)
        if not w:
            return False
        return w[0] not in self._serviced_today(now.strftime("%Y-%m-%d"))

    def review_type(self, now: datetime | None = None) -> str:
        """The current window's name; before the first window, the first's name."""
        w = self._current_window(now or self.now())
        if w:
            return w[0]
        windows = config.review_windows()
        return windows[0][0] if windows else "review"

    def missed_review_windows(self, now: datetime | None = None) -> list[str]:
        """Earlier windows that opened today but were never serviced."""
        now = now or self.now()
        cur = now.strftime("%H:%M")
        serviced = self._serviced_today(now.strftime("%Y-%m-%d"))
        current = self._current_window(now)
        current_name = current[0] if current else None
        return [name for name, open_time in config.review_windows()
                if open_time <= cur and name != current_name and name not in serviced]

    def mark_review_serviced(self, window_name: str | None = None,
                             when: datetime | None = None, *, durable: bool = True) -> str:
        """Record the given (or current) window as serviced — in the state AND as
        a durable receipt, so losing the state cannot re-send the review."""
        when = when or self.now()
        today = when.strftime("%Y-%m-%d")
        if window_name is None:
            w = self._current_window(when)
            window_name = w[0] if w else self.review_type(when)
        self.reviews_serviced.setdefault(today, [])
        if window_name not in self.reviews_serviced[today]:
            self.reviews_serviced[today].append(window_name)
        cutoff = (when - timedelta(days=2)).strftime("%Y-%m-%d")
        for d in [d for d in self.reviews_serviced if d < cutoff]:
            del self.reviews_serviced[d]
        self.last_review_at = when.isoformat()
        self.last_review_type = window_name
        if durable:
            receipts.append(receipts.REVIEW_PREFIX + window_name,
                            trigger=self.last_trigger, result="ok", at=when)
        return window_name
