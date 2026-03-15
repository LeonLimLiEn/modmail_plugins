import discord
from discord.ext import commands

class TicketButtons(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        view = TicketView()
        await thread.channel.send(view=view)


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.send("Ticket closed.")
        await interaction.channel.delete()

    @discord.ui.button(label="Close With Reason", style=discord.ButtonStyle.secondary)
    async def close_reason(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Type the reason in chat.", ephemeral=True)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.send(f"{interaction.user.mention} claimed this ticket.")


async def setup(bot):
    await bot.add_cog(TicketButtons(bot))
