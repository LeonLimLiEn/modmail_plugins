import discord
from discord.ext import commands

from core import checks
from core.checks import PermissionLevel


def make_embed(title, description, color):
    return discord.Embed(
        title=title,
        description=description,
        color=color
    )


class ClaimThread(commands.Cog):
    """Allows supporters to claim thread by sending claim in the thread channel"""

    def __init__(self, bot):
        self.bot = bot
        self.db = self.bot.plugin_db.get_partition(self)
        check_reply.fail_msg = 'This thread has been claimed by another user.'
        self.bot.get_command('reply').add_check(check_reply)
        self.bot.get_command('areply').add_check(check_reply)
        self.bot.get_command('fareply').add_check(check_reply)
        self.bot.get_command('freply').add_check(check_reply)

    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @checks.thread_only()
    @commands.command()
    async def claim(self, ctx):
        thread = await self.db.find_one({'thread_id': str(ctx.thread.channel.id)})

        if thread is None:
            await self.db.insert_one({
                'thread_id': str(ctx.thread.channel.id),
                'claimers': [str(ctx.author.id)]
            })

            embed = make_embed(
                "Thread Claimed",
                f"{ctx.author.mention} has successfully claimed this thread.",
                discord.Color.green()
            )
        else:
            embed = make_embed(
                "Claim Unsuccessful",
                "This thread has already been claimed by another user.",
                discord.Color.red()
            )

        await ctx.send(embed=embed)

    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @checks.thread_only()
    @commands.command()
    async def unclaim(self, ctx):
        """Allows a claimer to remove their claim from the thread"""

        thread = await self.db.find_one({'thread_id': str(ctx.thread.channel.id)})

        if not thread:
            embed = make_embed(
                "Unclaim Unsuccessful",
                "This thread is not currently claimed.",
                discord.Color.red()
            )
            return await ctx.send(embed=embed)

        if str(ctx.author.id) not in thread['claimers']:
            embed = make_embed(
                "Unclaim Denied",
                "You are not listed as a claimer for this thread.",
                discord.Color.red()
            )
            return await ctx.send(embed=embed)

        await self.db.find_one_and_update(
            {'thread_id': str(ctx.thread.channel.id)},
            {'$pull': {'claimers': str(ctx.author.id)}}
        )

        updated_thread = await self.db.find_one({'thread_id': str(ctx.thread.channel.id)})

        if not updated_thread['claimers']:
            await self.db.delete_one({'thread_id': str(ctx.thread.channel.id)})

            embed = make_embed(
                "Thread Unclaimed",
                "You have removed your claim. This thread is now unclaimed.",
                discord.Color.orange()
            )
        else:
            embed = make_embed(
                "Claim Updated",
                "You have successfully removed your claim from this thread.",
                discord.Color.orange()
            )

        await ctx.send(embed=embed)

    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @checks.thread_only()
    @commands.command()
    async def addclaim(self, ctx, *, member: discord.Member):
        """Adds another user to the thread claimers"""
        thread = await self.db.find_one({'thread_id': str(ctx.thread.channel.id)})

        if thread and str(ctx.author.id) in thread['claimers']:
            await self.db.find_one_and_update(
                {'thread_id': str(ctx.thread.channel.id)},
                {'$addToSet': {'claimers': str(member.id)}}
            )

            embed = make_embed(
                "Claimer Added",
                f"{member.mention} has been added to the list of claimers.",
                discord.Color.green()
            )
            await ctx.send(embed=embed)

    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @checks.thread_only()
    @commands.command()
    async def removeclaim(self, ctx, *, member: discord.Member):
        """Removes a user from the thread claimers"""
        thread = await self.db.find_one({'thread_id': str(ctx.thread.channel.id)})

        if thread and str(ctx.author.id) in thread['claimers']:
            await self.db.find_one_and_update(
                {'thread_id': str(ctx.thread.channel.id)},
                {'$pull': {'claimers': str(member.id)}}
            )

            embed = make_embed(
                "Claimer Removed",
                f"{member.mention} has been removed from the list of claimers.",
                discord.Color.orange()
            )
            await ctx.send(embed=embed)

    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @checks.thread_only()
    @commands.command()
    async def transferclaim(self, ctx, *, member: discord.Member):
        """Transfers claim to another member"""
        thread = await self.db.find_one({'thread_id': str(ctx.thread.channel.id)})

        if thread and str(ctx.author.id) in thread['claimers']:
            await self.db.find_one_and_update(
                {'thread_id': str(ctx.thread.channel.id)},
                {'$set': {'claimers': [str(member.id)]}}
            )

            embed = make_embed(
                "Claim Transferred",
                f"Ownership of this thread has been transferred to {member.mention}.",
                discord.Color.blurple()
            )
            await ctx.send(embed=embed)

    @checks.has_permissions(PermissionLevel.MODERATOR)
    @checks.thread_only()
    @commands.command()
    async def overrideaddclaim(self, ctx, *, member: discord.Member):
        """Allow mods to bypass claim thread check in add"""
        thread = await self.db.find_one({'thread_id': str(ctx.thread.channel.id)})

        if thread:
            await self.db.find_one_and_update(
                {'thread_id': str(ctx.thread.channel.id)},
                {'$addToSet': {'claimers': str(member.id)}}
            )

            embed = make_embed(
                "Override Successful",
                f"{member.mention} has been added to the claimers by a moderator override.",
                discord.Color.gold()
            )
            await ctx.send(embed=embed)

    @checks.has_permissions(PermissionLevel.MODERATOR)
    @checks.thread_only()
    @commands.command()
    async def overridereply(self, ctx, *, msg: str = ""):
        """Allow mods to bypass claim thread check in reply"""
        await ctx.invoke(self.bot.get_command('reply'), msg=msg)


async def check_reply(ctx):
    thread = await ctx.bot.get_cog('ClaimThread').db.find_one(
        {'thread_id': str(ctx.thread.channel.id)}
    )

    if thread:
        return ctx.author.bot or str(ctx.author.id) in thread['claimers']

    return True


async def setup(bot):
    await bot.add_cog(ClaimThread(bot))
