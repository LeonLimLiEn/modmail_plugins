import discord
from discord.ext import commands

class ClaimLock(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def claimpanel(self, ctx):
        view = discord.ui.View(timeout=None)

        async def claim_callback(interaction: discord.Interaction):

            channel = interaction.channel
            guild = interaction.guild
            claimer = interaction.user

            staff_role = discord.utils.get(guild.roles, name="Staff")

            for member in staff_role.members:
                if member != claimer:
                    await channel.set_permissions(member, view_channel=False)

            await channel.set_permissions(claimer, view_channel=True)

            await interaction.response.send_message(
                f"👨‍💼 {claimer.mention} has claimed this ticket. Other staff access removed."
            )

        button = discord.ui.Button(
            label="Claim",
            style=discord.ButtonStyle.green,
            emoji="👨‍💼"
        )

        button.callback = claim_callback
        view.add_item(button)

        await ctx.send("🎫 **Staff Controls**", view=view)


async def setup(bot):
    await bot.add_cog(ClaimLock(bot))
