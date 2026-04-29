from __future__ import annotations

from typing import TYPE_CHECKING

import discord


if TYPE_CHECKING:
    from discord.ext import commands


REQUIRED_PERMS = (
    "send_messages",
    "read_message_history",
    "embed_links",
    "view_channel",
)


def can_execute_giveaway(ctx: "commands.Context", channel: discord.TextChannel) -> bool:
    """
    Check that the bot has the permissions required to host a giveaway in `channel`
    (and in the invocation channel, if different).
    """
    me = channel.guild.me
    targets = {channel}
    if ctx.channel and ctx.channel != channel:
        targets.add(ctx.channel)

    for target in targets:
        perms = target.permissions_for(me)
        for name in REQUIRED_PERMS:
            if not getattr(perms, name, False):
                return False
    return True
  
