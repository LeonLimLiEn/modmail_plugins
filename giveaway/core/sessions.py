from __future__ import annotations

import asyncio
import random

from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

import discord

from core.models import getLogger

from .utils import format_time_remaining, progress_bar
from .views import disabled_entry_view, GIFT, LOCK, TADA


if TYPE_CHECKING:
    from bot import ModmailBot
    from ..giveaway import Giveaway


logger = getLogger(__name__)


# How long to wait between attempts when finalization fails for transient
# reasons (network blip, 5xx from Discord, ratelimit). Capped exponential.
_RETRY_DELAYS = (5, 15, 30, 60, 120, 300)


class GiveawaySession:
    """
    A single running giveaway.

    Reliability model
    -----------------
    - The list of entrants lives in `self.entrants` and is mirrored to the DB
      on every change. Reactions are NEVER consulted — they are unreliable.
    - The handler loop sleeps until the end time (no per-minute edits — the
      embed uses Discord's native relative timestamps).
    - When the end time arrives, `_finalize` is invoked. `_finalize` is
      idempotent and self-retrying: if any single step (fetch / edit /
      announce) fails, the whole step is retried with exponential backoff
      until it succeeds or the bot shuts down. The session is only marked
      "done" after the winners message has been sent.
    - On bot startup, sessions whose end time is already in the past are
      finalized immediately (catch-up).
    """

    def __init__(self, cog: "Giveaway", giveaway_data: Dict[str, Any]):
        self.cog: "Giveaway" = cog
        self.bot: "ModmailBot" = cog.bot
        self.data: Dict[str, Any] = giveaway_data

        self.channel_id: int = self.data.get("channel", 0)
        self.guild_id: int = self.data.get("guild", 0)
        self.id: int = self.data.get("message", 0)
        self.giveaway_item: str = self.data.get("item", "Unknown prize")
        self.winners_count: int = self.data.get("winners", 1)
        self.ends: float = self.data.get("time", 0.0)
        self.host_id: int = self.data.get("host", 0)
        self.required_role_id: Optional[int] = self.data.get("required_role")
        self.bonus_entries: Dict[int, int] = {
            int(k): int(v) for k, v in self.data.get("bonus_entries", {}).items()
        }
        self.dm_winners: bool = bool(self.data.get("dm_winners", True))
        self.entrants: Set[int] = set(int(uid) for uid in self.data.get("entrants", []))
        self.created_at: float = float(self.data.get("created_at", self.ends))
        self.paused: bool = bool(self.data.get("paused", False))
        self.pause_remaining: Optional[float] = self.data.get("pause_remaining")

        self.message: Optional[discord.Message] = None

        self._task: Optional[asyncio.Task] = None
        self._stopped: bool = False
        self._done: bool = False
        self._finalizing: bool = False

    # ------------------------------------------------------------------ start

    @classmethod
    def start(cls, cog: "Giveaway", giveaway_data: Dict[str, Any]) -> "GiveawaySession":
        session = cls(cog, giveaway_data)
        loop = session.bot.loop
        session._task = loop.create_task(session._run())
        session._task.add_done_callback(session._task_done)
        return session

    def _task_done(self, fut: asyncio.Future) -> None:
        try:
            fut.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(
                "Giveaway session %s crashed: %s: %s",
                self.id, type(exc).__name__, exc,
                exc_info=exc,
            )
            # Schedule a recovery attempt — we never give up on announcing
            # the winner. This is what makes the system reliable.
            if not self._done and not self._stopped:
                self._task = self.bot.loop.create_task(self._run())
                self._task.add_done_callback(self._task_done)

    # -------------------------------------------------------------- properties

    @property
    def channel(self) -> Optional[discord.TextChannel]:
        return self.bot.get_channel(self.channel_id)

    @property
    def guild(self) -> Optional[discord.Guild]:
        if self.message:
            return self.message.guild
        if self.channel:
            return self.channel.guild
        return self.bot.get_guild(self.guild_id)

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def done(self) -> bool:
        return self._done

    # -------------------------------------------------------- entrant tracking

    def total_entries_for(self, member: discord.Member) -> int:
        """How many raffle tickets a member has, including bonus entries."""
        if member.id not in self.entrants:
            return 0
        bonus = 0
        for role_id, extra in self.bonus_entries.items():
            if any(r.id == role_id for r in member.roles):
                bonus += extra
        return 1 + bonus

    def serializable(self) -> Dict[str, Any]:
        """Snapshot the session in a form safe to write to the DB."""
        return {
            "item": self.giveaway_item,
            "winners": self.winners_count,
            "time": self.ends,
            "guild": self.guild_id,
            "channel": self.channel_id,
            "message": self.id,
            "host": self.host_id,
            "required_role": self.required_role_id,
            "bonus_entries": {str(k): v for k, v in self.bonus_entries.items()},
            "dm_winners": self.dm_winners,
            "entrants": list(self.entrants),
            "created_at": self.created_at,
            "paused": self.paused,
            "pause_remaining": self.pause_remaining,
        }

    # ------------------------------------------------------------- lifecycle

    def suspend(self) -> None:
        self._stopped = True

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._done = True
        logger.debug(
            "Stopping giveaway %s (channel %s, guild %s)",
            self.id, self.channel_id, self.guild_id,
        )
        self.bot.dispatch("giveaway_end", self)

    def force_stop(self) -> None:
        self._stopped = True
        self._done = True
        if self._task and not self._task.done():
            self._task.cancel()
        logger.debug("Force stopping giveaway %s", self.id)

    async def pause(self) -> None:
        if self.paused or self._done:
            return
        self.paused = True
        now = discord.utils.utcnow().timestamp()
        self.pause_remaining = max(0.0, self.ends - now)
        if self._task and not self._task.done():
            self._task.cancel()
        await self.cog._update_db()

    async def resume(self) -> None:
        if not self.paused or self._done:
            return
        self.paused = False
        now = discord.utils.utcnow().timestamp()
        self.ends = now + (self.pause_remaining or 0.0)
        self.pause_remaining = None
        # Restart the run loop
        self._task = self.bot.loop.create_task(self._run())
        self._task.add_done_callback(self._task_done)
        await self.cog._update_db()

    # ----------------------------------------------------------- main loop

    async def _run(self) -> None:
        await self.bot.wait_for_connected()

        # If the giveaway was paused while the bot was offline, just stay parked.
        if self.paused:
            return

        # Make sure we have the message object. Failures here are retried —
        # we never silently give up.
        if self.message is None:
            self.message = await self._fetch_message_with_retry()
        if self.message is None:
            # Channel/message gone for good. Mark stopped without dispatching
            # a winner so the user can investigate.
            logger.warning("Giveaway %s: message permanently unavailable.", self.id)
            self.stop()
            return

        # Sleep until the end time (woken early via task cancel from edit/cancel).
        now = discord.utils.utcnow().timestamp()
        delay = self.ends - now
        if delay > 0:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                # Edit / pause / cancel asked us to bail. Don't finalize.
                return

        # Time to finalize.
        await self._finalize()

    async def _fetch_message_with_retry(self) -> Optional[discord.Message]:
        attempt = 0
        while not self._stopped:
            channel = self.channel
            if channel is None:
                # Wait a bit in case it's a transient cache miss after restart.
                await asyncio.sleep(_RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)])
                attempt += 1
                if attempt > len(_RETRY_DELAYS):
                    return None
                continue
            try:
                return await channel.fetch_message(self.id)
            except discord.NotFound:
                return None
            except discord.Forbidden:
                logger.warning("Giveaway %s: missing permission to fetch message.", self.id)
                return None
            except discord.HTTPException as exc:
                delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                logger.warning(
                    "Giveaway %s: fetch failed (%s); retrying in %ss",
                    self.id, exc, delay,
                )
                await asyncio.sleep(delay)
                attempt += 1

    # -------------------------------------------------------- finalization

    async def _finalize(self) -> None:
        """
        Draw winners and announce them. This method is the heart of the
        reliability story:

        - It loops until all critical operations succeed (or the message is
          confirmed gone). Transient Discord errors don't kill the announce.
        - Each step is wrapped individually so a failure in one (e.g.
          editing the embed) doesn't prevent the next (sending the
          congratulations message). The user's main complaint — winners not
          showing — is solved here.
        - It is safe to call multiple times. The catch-up path on bot
          startup relies on this.
        """
        if self._finalizing:
            return
        self._finalizing = True

        attempt = 0
        while not self._stopped and not self._done:
            try:
                # Refresh the message so we see the latest embed state.
                if self.message is None:
                    self.message = await self._fetch_message_with_retry()
                if self.message is None:
                    logger.warning("Giveaway %s: message gone, cannot announce winner.", self.id)
                    self.stop()
                    return

                winners = self._draw_winners()
                base_embed = self._build_final_embed(winners)

                # 1) Edit the original message (best-effort — we still
                #    announce even if this fails).
                edit_ok = await self._safe_edit(self.message, base_embed)

                # 2) Always send the congratulations / no-winner message in
                #    the channel, independent of whether the edit succeeded.
                announce_ok = await self._safe_announce(winners)

                if announce_ok:
                    # 3) Optionally DM the winners.
                    if self.dm_winners and winners:
                        await self._dm_winners(winners)

                    self.stop()
                    return

                # If we couldn't announce, retry from the top.
                raise RuntimeError(f"Announcement failed (edit_ok={edit_ok})")

            except asyncio.CancelledError:
                self._finalizing = False
                raise
            except Exception as exc:
                delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                logger.error(
                    "Giveaway %s: finalize attempt %s failed (%s: %s); retrying in %ss",
                    self.id, attempt + 1, type(exc).__name__, exc, delay,
                )
                attempt += 1
                await asyncio.sleep(delay)

    def _draw_winners(self) -> List[int]:
        """
        Pick winners from the entrant set, applying bonus entries.
        Returns a list of user IDs. Members who have left the guild,
        bots, or who lost the required role are skipped.
        """
        guild = self.guild
        if guild is None or not self.entrants:
            return []

        # Build a weighted ticket pool.
        pool: List[int] = []
        for uid in list(self.entrants):
            member = guild.get_member(uid)
            if member is None or member.bot:
                continue
            if self.required_role_id and not any(r.id == self.required_role_id for r in member.roles):
                continue
            tickets = self.total_entries_for(member)
            pool.extend([uid] * max(1, tickets))

        if not pool:
            return []

        winners: List[int] = []
        seen: Set[int] = set()
        # We sample without replacement at the user level.
        random.shuffle(pool)
        for uid in pool:
            if uid in seen:
                continue
            winners.append(uid)
            seen.add(uid)
            if len(winners) >= self.winners_count:
                break
        return winners

    def _build_final_embed(self, winners: List[int]) -> discord.Embed:
        embed = self.message.embeds[0] if self.message and self.message.embeds else discord.Embed(
            title=self.cog.giveaway_title, colour=0xE74C3C
        )
        embed.colour = 0xE74C3C if not winners else 0x9B59B6

        if winners:
            mentions = " ".join(f"<@{uid}>" for uid in winners)
            embed.description = (
                f"{TADA} **Giveaway has ended!**\n\n"
                f"**{'Winners' if len(winners) > 1 else 'Winner'}:** {mentions}"
            )
            footer = f"{len(winners)} winner{'s' if len(winners) > 1 else ''} • Ended"
        else:
            embed.description = (
                f"{TADA} **Giveaway has ended!**\n\n"
                "Sadly nobody eligible entered."
            )
            footer = (
                f"{self.winners_count} winner{'s' if self.winners_count > 1 else ''} • Ended"
            )

        embed.set_footer(text=footer)

        # Keep the prize and host fields, refresh the entries field, drop the
        # countdown field by rebuilding cleanly.
        prize = self.giveaway_item
        host_mention = f"<@{self.host_id}>" if self.host_id else "Unknown"
        embed.clear_fields()
        embed.add_field(name=f"{GIFT} Prize", value=prize, inline=False)
        embed.add_field(name="Hosted by", value=host_mention, inline=True)
        embed.add_field(name="Entries", value=f"**{len(self.entrants)}**", inline=True)
        if self.required_role_id:
            embed.add_field(
                name=f"{LOCK} Required role",
                value=f"<@&{self.required_role_id}>",
                inline=False,
            )
        return embed

    async def _safe_edit(self, message: discord.Message, embed: discord.Embed) -> bool:
        try:
            await message.edit(embed=embed, view=disabled_entry_view())
            return True
        except discord.NotFound:
            return False
        except discord.HTTPException as exc:
            logger.warning("Giveaway %s: edit failed: %s", self.id, exc)
            return False

    async def _safe_announce(self, winners: List[int]) -> bool:
        channel = self.channel
        if channel is None:
            return False

        jump_url = self.message.jump_url if self.message else ""
        prize = self.giveaway_item

        if winners:
            mentions = " ".join(f"<@{uid}>" for uid in winners)
            content = (
                f"{TADA} Congratulations {mentions}! You won **{prize}**!\n"
                f"{jump_url}"
            )
        else:
            content = (
                f"The giveaway for **{prize}** ended with no eligible entries.\n"
                f"{jump_url}"
            )

        try:
            await channel.send(
                content,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            return True
        except discord.Forbidden:
            logger.warning("Giveaway %s: missing permission to send announcement.", self.id)
            return False
        except discord.HTTPException as exc:
            logger.warning("Giveaway %s: announcement send failed: %s", self.id, exc)
            return False

    async def _dm_winners(self, winners: List[int]) -> None:
        guild = self.guild
        if guild is None:
            return
        jump_url = self.message.jump_url if self.message else ""
        for uid in winners:
            member = guild.get_member(uid)
            if member is None or member.bot:
                continue
            try:
                await member.send(
                    f"{TADA} You won the giveaway for **{self.giveaway_item}** "
                    f"in **{guild.name}**!\n{jump_url}"
                )
            except (discord.Forbidden, discord.HTTPException):
                # DMs closed — not a failure of the giveaway.
                continue

    # ------------------------------------------------------------ rendering

    def render_progress(self) -> str:
        now = discord.utils.utcnow().timestamp()
        total = max(1.0, self.ends - self.created_at)
        elapsed = max(0.0, min(total, now - self.created_at))
        return f"{progress_bar(elapsed, total)}  {format_time_remaining(self.ends - now)} left"
      
