import discord
import re
import logging
from discord.ext import commands
from core import checks
from core.models import PermissionLevel

# Configure Logger
logger = logging.getLogger("ModmailEmbedder")

class AdvancedEmbedPlugin(commands.Cog):
    """
    A professional-grade Embed creation system for Modmail.
    """

    def __init__(self, bot):
        self.bot = bot

    def _parse_hex(self, hex_val: str) -> discord.Color:
        """Converts hex strings to discord.Color."""
        try:
            return discord.Color(int(hex_val.lstrip('#'), 16))
        except ValueError:
            return discord.Color.default()

    @commands.command(name="embed", aliases=["ce", "createembed"])
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def create_embed(self, ctx, *, args: str):
        """
        Builds complex embeds using flags.
        Syntax: .embed <channel_id> <#color> <description> [--title "Title"] [--image "url"] [--footer "text"] [--role <id>] [--url "link"]
        """
        # Regex to capture flags
        title = re.search(r'--title "(.*?)"', args)
        image = re.search(r'--image "(.*?)"', args)
        footer = re.search(r'--footer "(.*?)"', args)
        role = re.search(r'--role (\d+)', args)
        url = re.search(r'--url "(.*?)"', args)

        # Basic stripping of flags for the main content
        raw_args = args.split(' ')[0:3]
        if len(raw_args) < 3:
            return await ctx.send("❌ Format: `.embed <channel_id> <color> <description>`")
        
        channel_id = int(raw_args[0])
        color = self._parse_hex(raw_args[1])
        description = " ".join(args.split(' ')[2:]).split('--')[0].strip()

        # Channel Lookup
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return await ctx.send("❌ Channel not found.")

        # Embed Construction
        embed = discord.Embed(description=description.replace("\\n", "\n"), color=color)
        if title: embed.title = title.group(1)
        if image: embed.set_image(url=image.group(1))
        if footer: embed.set_footer(text=footer.group(1))
        if url: embed.url = url.group(1)
        
        # Send Preview
        view = EmbedActionView(channel, embed, role.group(1) if role else None)
        await ctx.send("👀 **Embed Preview:** ", embed=embed, view=view)

class EmbedActionView(discord.ui.View):
    def __init__(self, channel, embed, role_id):
        super().__init__(timeout=120)
        self.channel = channel
        self.embed = embed
        self.role_id = role_id

    @discord.ui.button(label="Publish", style=discord.ButtonStyle.green)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        content = f"<@&{self.role_id}>" if self.role_id else None
        try:
            await self.channel.send(content=content, embed=self.embed)
            await interaction.response.edit_message(content="✅ Successfully published to channel.", embed=None, view=None)
        except Exception as e:
            await interaction.response.edit_message(content=f"❌ Error: {e}", embed=None, view=None)

    @discord.ui.button(label="Abort", style=discord.ButtonStyle.danger)
    async def abort(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="⛔ Operation cancelled.", embed=None, view=None)

async def setup(bot):
    await bot.add_cog(AdvancedEmbedPlugin(bot))
    logger.info("AdvancedEmbedPlugin loaded.")
