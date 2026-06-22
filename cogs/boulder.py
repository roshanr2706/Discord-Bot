"""Randomly chime into climbing-related chatter with a spoilered one-liner."""

import logging
import os
import random
import re

import discord
from discord.ext import commands

log = logging.getLogger("boulder")

TRIGGER_WORDS = [
    "boulder", "bouldering",
    "v0", "v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9", "v10",
    "send", "flash", "project", "dyno", "crimp", "sloper", "pinch", "jug",
    "heel hook", "toe hook", "mantle", "campus", "overhang", "slab", "crux",
    "beta", "smear", "flag", "drop knee",
]

CHIMES = [
    "||skill issue||",
    "||that's a beta spray if I've ever seen one||",
    "||just dyno it||",
    "||touch the wall more||",
    "||have you tried... not falling?||",
    "||more core bro||",
    "||the beta is to be taller||",
    "||look up Magnus Midtbø's video on that||",
    "||open hand grip supremacy||",
    "||that problem goes at V-one-more-than-you-think||",
    "||trust the feet||",
    "||did you try it in climbing shoes?||",
    "||your hips need to be closer to the wall||",
    "||just campus it||",
    "||have you tried being stronger?||",
    "||lock it off and reach||",
    "||that's a project for a reason||",
]

# Match trigger words on word boundaries so "sendoff" or "betamax" don't fire.
_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in TRIGGER_WORDS) + r")\b",
    re.IGNORECASE,
)


class Boulder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channel_id = int(os.getenv("BOULDER_CHANNEL_ID", "0"))
        try:
            self.chance = float(os.getenv("BOULDER_CHIME_CHANCE", "0.25"))
        except ValueError:
            self.chance = 0.25

    def _has_trigger(self, content: str) -> bool:
        return bool(_PATTERN.search(content))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        # Don't react to our own command invocations.
        if message.content.startswith("!"):
            return
        if self.channel_id and message.channel.id != self.channel_id:
            return

        mentioned = self.bot.user in message.mentions
        has_trigger = self._has_trigger(message.content)

        if mentioned:
            should_chime = True  # direct @mention: always respond
        elif has_trigger:
            should_chime = random.random() < self.chance
        else:
            should_chime = False

        if should_chime:
            await message.reply(random.choice(CHIMES))

    @commands.command(name="boulder")
    async def boulder_cmd(self, ctx: commands.Context):
        """Force a random chime (for testing)."""
        await ctx.reply(random.choice(CHIMES))


async def setup(bot: commands.Bot):
    await bot.add_cog(Boulder(bot))
