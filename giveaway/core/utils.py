from __future__ import annotations

import math

from typing import Optional, TYPE_CHECKING

from core.time import UserFriendlyTime


if TYPE_CHECKING:
    from datetime import datetime
    from discord.ext import commands


duration_syntax = (
    "`30m` or `30 minutes` = 30 minutes\n"
    "`2d` or `2days` or `2day` = 2 days\n"
    "`1mo` or `1 month` = 1 month\n"
    "`7 days 12 hours` or `7days12hours` (with/without spaces)\n"
    "`6d12h` (this syntax must be without spaces)\n"
)


def format_time_remaining(seconds: float) -> str:
    """
    Human-friendly remaining-time string. Used only for log lines and the
    "ended at" rendering — the live countdown in the embed uses Discord's
    native relative timestamp (`<t:...:R>`), which updates in the client
    itself with no edits needed.
    """
    seconds = int(seconds)
    if seconds <= 0:
        return "0 seconds"

    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if not parts and secs:
        parts.append(f"{secs} second{'s' if secs != 1 else ''}")
    return " ".join(parts) if parts else "less than 1 minute"


async def time_converter(
    ctx: "commands.Context", argument: str, *, now: Optional["datetime"] = None
) -> UserFriendlyTime:
    return await UserFriendlyTime().convert(ctx, argument, now=now)


def progress_bar(current: float, total: float, width: int = 20) -> str:
    """
    Render a unicode progress bar showing how much of the giveaway has elapsed.
    """
    if total <= 0:
        return "▰" * width
    pct = max(0.0, min(1.0, current / total))
    filled = int(round(pct * width))
    return "▰" * filled + "▱" * (width - filled)
  
