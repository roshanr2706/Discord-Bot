"""!Summary command — summarize recent channel messages."""

import asyncio
import logging
from datetime import timezone

import discord
from discord.ext import commands

from utils import ai

log = logging.getLogger("summary")

DEFAULT_COUNT = 50
SUMMARY_COLOR = 0x57F287


def _format_message(msg: discord.Message) -> str:
    stamp = msg.created_at.astimezone(timezone.utc).strftime("%H:%M")
    return f"[{stamp}] {msg.author.display_name}: {msg.content}"


class Summary(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._lock = asyncio.Lock()

    @commands.command(name="Summary")
    async def summary_cmd(self, ctx: commands.Context, count: int = DEFAULT_COUNT):
        """Summarize the last <count> messages (default 50)."""
        if self._lock.locked():
            await ctx.reply("⏳ A summary is already running — give it a sec.")
            return

        async with self._lock:
            messages = []
            async for msg in ctx.channel.history(limit=count, before=ctx.message):
                if msg.author.bot or not msg.content:
                    continue
                messages.append(msg)

            if not messages:
                await ctx.reply("Nothing to summarize here.")
                return

            messages.reverse()  # chronological order for the transcript
            transcript = "\n".join(_format_message(m) for m in messages)

            try:
                text = await ai.summarize(transcript)
            except Exception:
                log.exception("summarize failed")
                await ctx.reply("Something went wrong generating the summary.")
                return

            embed = discord.Embed(
                title=f"📝 Summary — last {len(messages)} messages",
                description=text,
                color=SUMMARY_COLOR,
            )
            embed.set_footer(text=f"Requested by {ctx.author.display_name}")
            await ctx.reply(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Summary(bot))
