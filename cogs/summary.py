"""!Summary command plus a background rolling-memory updater."""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

from utils import ai, memory

log = logging.getLogger("summary")

DEFAULT_COUNT = 50
MEMORY_INTERVAL_HOURS = 3
SUMMARY_COLOR = 0x57F287


def _format_message(msg: discord.Message) -> str:
    stamp = msg.created_at.astimezone(timezone.utc).strftime("%H:%M")
    return f"[{stamp}] {msg.author.display_name}: {msg.content}"


class Summary(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.summary_channel_id = int(os.getenv("SUMMARY_CHANNEL_ID", "0"))
        self._lock = asyncio.Lock()

    # ----- background memory task --------------------------------------

    @tasks.loop(hours=MEMORY_INTERVAL_HOURS)
    async def memory_task(self):
        channel = self.bot.get_channel(self.summary_channel_id)
        if channel is None:
            return

        after = datetime.now(timezone.utc) - timedelta(hours=MEMORY_INTERVAL_HOURS)
        lines = []
        async for msg in channel.history(limit=None, after=after, oldest_first=True):
            if msg.author.bot or not msg.content:
                continue
            lines.append(_format_message(msg))

        if not lines:
            return  # nothing happened, skip silently

        transcript = "\n".join(lines)
        try:
            snapshot = await ai.condense(transcript)
        except Exception:
            log.exception("memory condense failed")
            return

        memory.save_memory(snapshot)
        log.info("updated chat memory from %d messages", len(lines))

    @memory_task.before_loop
    async def before_memory(self):
        await self.bot.wait_until_ready()

    async def cog_load(self):
        self.memory_task.start()

    async def cog_unload(self):
        self.memory_task.cancel()

    # ----- !Summary ----------------------------------------------------

    @commands.command(name="Summary", aliases=["summarize", "summary"])
    async def summary_cmd(self, ctx: commands.Context, count: int = DEFAULT_COUNT):
        """Summarize the last <count> messages (default 50)."""
        if self._lock.locked():
            await ctx.reply("⏳ A summary is already running — give it a sec.")
            return

        async with self._lock:
            # Show we're working — this can take a while on the AI call.
            await ctx.message.add_reaction("⏳")
            try:
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

                context = memory.get_context_block()
                try:
                    text = await ai.summarize(transcript, context=context)
                except Exception:
                    log.exception("summarize failed")
                    await ctx.reply("Something went wrong generating the summary.")
                    return

                footer_ctx = "with chat context" if context else "no context yet"
                embed = discord.Embed(
                    title=f"📝 Summary — last {len(messages)} messages",
                    description=text,
                    color=SUMMARY_COLOR,
                )
                embed.set_footer(
                    text=f"Requested by {ctx.author.display_name} · {footer_ctx}"
                )
                await ctx.reply(embed=embed)
                await ctx.message.add_reaction("✅")
            finally:
                # Clear our hourglass (a bot can always remove its own reaction).
                try:
                    await ctx.message.remove_reaction("⏳", ctx.me)
                except discord.HTTPException:
                    pass

    # ----- !memory (debug, mod only) -----------------------------------

    @commands.command(name="memory")
    @commands.has_permissions(manage_messages=True)
    async def memory_cmd(self, ctx: commands.Context):
        """Show the current rolling chat memory (mods only)."""
        data = memory.load_memory()
        if not data.get("summary"):
            await ctx.reply("No memory stored yet.")
            return

        embed = discord.Embed(
            title="🧠 Current chat memory",
            description=data["summary"],
            color=SUMMARY_COLOR,
        )
        embed.set_footer(text=f"Last updated {data.get('updated_at')}")
        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Summary(bot))
