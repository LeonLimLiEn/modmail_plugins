from discord.ext import commands
import discord
from core import checks
from core.models import PermissionLevel
import re
from datetime import datetime
import typing

class EmbedPlugin(commands.Cog):
    """
    Advanced embed creator with multiple formatting options and role ping support.
    Requires ADMINISTRATOR permissions.
    """
    
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(name="embed", aliases=["emb"])
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def create_embed(self, ctx, *, args: str = None):
        """
        Create and send a custom embed to any channel.
        
        **Usage:**         `.embed <message> <channel_id> <hex_color> [Role Ping]`
        
        **Advanced Formatting:**         - Use `\\n` for line breaks
        - Use ` **text** ` for bold
        - Use `*text*` for italic
        - Use `__text__` for underline
        - Use `~~text~~` for strikethrough
        - Use `[text](url)` for hyperlinks
        
        **Examples:**         `.embed Hello everyone! 123456789 #FF5733 @Admin`
        `.embed Welcome to the server!\\n\\nEnjoy your stay! 123456789 #00FF00`
        `.embed **Important** \\nPlease read the rules! 123456789 #FF0000 @Members`
        """
        
        if not args:
            return await self.send_usage_guide(ctx)
        
        # Parse the arguments
        parsed = await self.parse_arguments(ctx, args)
        if not parsed:
            return
        
        message_content, channel_id, hex_color, role_ping = parsed
        
        # Get the target channel
        channel = self.bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except:
                embed = discord.Embed(
                    title="❌ Error",
                    description=f"Channel with ID `{channel_id}` not found.",
                    color=discord.Color.red()
                )
                return await ctx.send(embed=embed)
        
        # Check if bot has permissions in target channel
        if not channel.permissions_for(channel.guild.me).send_messages:
            embed = discord.Embed(
                title="❌ Error",
                description=f"I don't have permission to send messages in {channel.mention}.",
                color=discord.Color.red()
            )
            return await ctx.send(embed=embed)
        
        # Create the embed
        embed = discord.Embed(
            description=message_content,
            color=hex_color,
            timestamp=datetime.utcnow()
        )
        
        # Add footer with sender info
        embed.set_footer(
            text=f"Sent by {ctx.author}",
            icon_url=ctx.author.display_avatar.url
        )
        
        # Send the embed with optional role ping
        try:
            if role_ping:
                # Check if bot can mention the role
                if role_ping.mentionable or channel.permissions_for(channel.guild.me).mention_everyone:
                    await channel.send(content=role_ping.mention, embed=embed)
                else:
                    # Temporarily make role mentionable if bot has manage roles permission
                    if channel.permissions_for(channel.guild.me).manage_roles:
                        try:
                            await role_ping.edit(mentionable=True)
                            await channel.send(content=role_ping.mention, embed=embed)
                            await role_ping.edit(mentionable=False)
                        except:
                            await channel.send(embed=embed)
                            embed_warn = discord.Embed(
                                title="⚠️ Warning",
                                description=f"Role {role_ping.mention} couldn't be pinged. Embed sent without ping.",
                                color=discord.Color.orange()
                            )
                            await ctx.send(embed=embed_warn)
                    else:
                        await channel.send(embed=embed)
                        embed_warn = discord.Embed(
                            title="⚠️ Warning",
                            description=f"Role {role_ping.mention} is not mentionable. Embed sent without ping.",
                            color=discord.Color.orange()
                            )
                        await ctx.send(embed=embed_warn)
            else:
                await channel.send(embed=embed)
            
            # Confirmation message
            confirm_embed = discord.Embed(
                title="✅ Embed Sent Successfully",
                description=f"Embed sent to {channel.mention}",
                color=discord.Color.green()
            )
            confirm_embed.add_field(name="Message Preview", value=message_content[:1024], inline=False)
            if role_ping:
                confirm_embed.add_field(name="Role Pinged", value=role_ping.mention, inline=False)
            
            await ctx.send(embed=confirm_embed)
            
        except discord.Forbidden:
            embed = discord.Embed(
                title="❌ Error",
                description="I don't have permission to send embeds in that channel.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"An error occurred: {str(e)}",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
    
    async def parse_arguments(self, ctx, args: str):
        """
        Parse the command arguments with advanced regex patterns.
        Returns: (message, channel_id, hex_color, role_ping) or None
        """
        
        # Pattern to extract channel ID (supports both raw ID and mention)
        channel_pattern = r'(?:<#)?(\d{17,19})(?:>)?'
        
        # Pattern to extract hex color (supports #RRGGBB format)
        hex_pattern = r'#?([0-9A-Fa-f]{6})'
        
        # Pattern to extract role mention or ID
        role_pattern = r'(?:<@&)?(\d{17,19})(?:>)?'
        
        # Find channel ID
        channel_match = re.search(channel_pattern, args)
        if not channel_match:
            embed = discord.Embed(
                title="❌ Invalid Format",
                description="Please provide a valid channel ID or mention.\n\n **Example:** `.embed Hello! 123456789 #FF5733`",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return None
        
        channel_id = int(channel_match.group(1))
        
        # Find hex color
        hex_match = re.search(hex_pattern, args)
        if not hex_match:
            embed = discord.Embed(
                title="❌ Invalid Format",
                description="Please provide a valid hex color code.\n\n **Example:** `.embed Hello! 123456789 #FF5733`",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return None
        
        hex_value = hex_match.group(1)
        try:
            hex_color = discord.Color(int(hex_value, 16))
        except ValueError:
            embed = discord.Embed(
                title="❌ Invalid Color",
                description="Please provide a valid hex color code (e.g., #FF5733).",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return None
        
        # Find role mention (optional)
        role_ping = None
        role_match = re.search(role_pattern, args)
        if role_match:
            role_id = int(role_match.group(1))
            role_ping = ctx.guild.get_role(role_id)
            if not role_ping:
                embed = discord.Embed(
                    title="⚠️ Warning",
                    description=f"Role with ID `{role_id}` not found. Continuing without role ping.",
                    color=discord.Color.orange()
                )
                await ctx.send(embed=embed)
        
        # Extract the message content by removing channel, color, and role from args
        message = args
        message = re.sub(channel_pattern, '', message, count=1).strip()
        message = re.sub(hex_pattern, '', message, count=1).strip()
        if role_match:
            message = re.sub(role_pattern, '', message, count=1).strip()
        
        # Replace \\n with actual newlines
        message = message.replace('\\n', '\n')
        
        if not message:
            embed = discord.Embed(
                title="❌ Invalid Format",
                description="Please provide a message to send in the embed.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return None
        
        # Limit message length
        if len(message) > 4096:
            embed = discord.Embed(
                title="❌ Message Too Long",
                description="Embed descriptions must be 4096 characters or less.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return None
        
        return message, channel_id, hex_color, role_ping
    
    async def send_usage_guide(self, ctx):
        """Send a detailed usage guide embed."""
        embed = discord.Embed(
            title="📝 Embed Command Usage",
            description="Create beautiful embeds and send them to any channel!",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name=" **Basic Format** ",
            value="`.embed <message> <channel_id> <hex_color> [Role Ping]`",
            inline=False
        )
        
        embed.add_field(
            name=" **Parameters** ",
            value=(
                "• `<message>` - The text to display in the embed\n"
                "• `<channel_id>` - Channel ID or mention (e.g., 123456789 or <#123456789>)\n"
                "• `<hex_color>` - Hex color code (e.g., #FF5733)\n"
                "• `[Role Ping]` - Optional role to ping (e.g., <@&123456789>)"
            ),
            inline=False
        )
        
        embed.add_field(
            name=" **Text Formatting** ",
            value=(
                "• `\\n` - New line\n"
                "• ` **bold** ` - **Bold text** \n"
                "• `*italic*` - *Italic text*\n"
                "• `__underline__` - __Underlined text__\n"
                "• `~~strikethrough~~` - ~~Strikethrough~~\n"
                "• `[link text](url)` - [Clickable links](https://discord.com)"
            ),
            inline=False
        )
        
        embed.add_field(
            name=" **Examples** ",
            value=(
                "```\n"
                ".embed Hello everyone! 123456789 #FF5733\n\n"
                ".embed **Welcome!** \\n\\nEnjoy your stay! 123456789 #00FF00\n\n"
                ".embed Important announcement! 123456789 #FF0000 @Members\n"
                "```"
            ),
            inline=False
        )
        
        embed.add_field(
            name=" **Color Examples** ",
            value=(
                "🔴 Red: `#FF0000`\n"
                "🟢 Green: `#00FF00`\n"
                "🔵 Blue: `#0000FF`\n"
                "🟣 Purple: `#9B59B6`\n"
                "🟡 Gold: `#FFD700`\n"
                "⚫ Black: `#000000`"
            ),
            inline=False
        )
        
        embed.set_footer(text="Requires ADMINISTRATOR permissions")
        
        await ctx.send(embed=embed)

def setup(bot):
    bot.add_cog(EmbedPlugin(bot))
