from __future__ import annotations

import discord
from discord.ext import commands
from core import checks
from core.models import PermissionLevel


def parse_hex_color(hex_str: str) -> int | None:
    hex_str = hex_str.lstrip("#")
    if len(hex_str) != 6:
        return None
    try:
        return int(hex_str, 16)
    except ValueError:
        return None


async def resolve_role(guild: discord.Guild, value: str) -> discord.Role | None:
    value = value.strip("<@&>")
    if value.isdigit():
        return guild.get_role(int(value))
    return discord.utils.find(lambda r: r.name.lower() == value.lower(), guild.roles)


class EmbedSender(commands.Cog):
    """Plugin for sending custom embedded messages to any channel."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="embed")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def embed_send(self, ctx: commands.Context, *args) -> None:
        """Send a custom embed to a channel.

        Usage: .embed <channel_id> <#hex_color> <message> [role_ping]

        Examples:
          .embed 123456789 #ff0000 Hello everyone!
          .embed 123456789 #00ff99 Important update! @everyone
          .embed 123456789 #5865f2 Staff meeting tonight. 987654321
        """
        missing = []
        if len(args) < 1:
            missing += ["channel_id", "hex_color", "message"]
        elif len(args) < 2:
            missing += ["hex_color", "message"]
        elif len(args) < 3:
            missing += ["message"]

        if missing:
            embed = discord.Embed(
                title="❌ Missing Arguments",
                description=(
                    "You are missing the following required arguments:\n"
                    + "\n".join(f"• `{m}`" for m in missing)
                    + f"\n\n**Usage:** `.embed <channel_id> <#hex_color> <message> [role_ping]`"
                ),
                color=discord.Color.red(),
            )
            return await ctx.send(embed=embed)

        raw_channel = args[0]
        raw_color   = args[1]
        rest        = args[2:]

        # ── Resolve channel ──────────────────────────────────────────────
        channel_id = raw_channel.strip("<#>")
        if not channel_id.isdigit():
            embed = discord.Embed(
                description=(
                    f"❌ `{raw_channel}` is not a valid channel. "
                    "Provide a channel ID or #mention."
                ),
                color=discord.Color.red(),
            )
            return await ctx.send(embed=embed)

        channel = ctx.guild.get_channel(int(channel_id))
        if not channel:
            embed = discord.Embed(
                description=f"❌ Could not find a channel with ID `{channel_id}`.",
                color=discord.Color.red(),
            )
            return await ctx.send(embed=embed)

        # ── Resolve hex color ─────────────────────────────────────────────
        color_value = parse_hex_color(raw_color)
        if color_value is None:
            embed = discord.Embed(
                description=(
                    f"❌ `{raw_color}` is not a valid hex color. "
                    "Use a 6-digit hex code like `#ff0000` or `ff0000`."
                ),
                color=discord.Color.red(),
            )
            return await ctx.send(embed=embed)

        # ── Resolve optional role ping (last word if it looks like a role) ─
        role: discord.Role | None = None
        message_parts = list(rest)

        if message_parts:
            last_word = message_parts[-1]
            resolved = await resolve_role(ctx.guild, last_word)
            if resolved:
                role = resolved
                message_parts = message_parts[:-1]

        if not message_parts:
            embed = discord.Embed(
                description=(
                    "❌ Missing `message`. You must include a message to send.\n\n"
                    "**Usage:** `.embed <channel_id> <#hex_color> <message> [role_ping]`"
                ),
                color=discord.Color.red(),
            )
            return await ctx.send(embed=embed)

        message_text = " ".join(message_parts)

        # ── Build and send embed ──────────────────────────────────────────
        out_embed = discord.Embed(
            description=message_text,
            color=discord.Color(color_value),
        )

        ping_content = role.mention if role else None

        await channel.send(content=ping_content, embed=out_embed)

        confirm = discord.Embed(
            description=f"✅ Message sent to {channel.mention}" + (f" with a ping to {role.mention}" if role else "") + ".",
            color=discord.Color.green(),
        )
        await ctx.send(embed=confirm)

    async def cog_command_error(self, ctx: commands.Context, error: Exception) -> None:
        raise error


async def setup(bot):
    await bot.add_cog(EmbedSender(bot))
