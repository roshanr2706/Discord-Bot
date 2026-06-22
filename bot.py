import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bot")

COGS = [
    "cogs.events",
    "cogs.summary",
    "cogs.boulder",
]


class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        for ext in COGS:
            try:
                await self.load_extension(ext)
                log.info("loaded extension %s", ext)
            except Exception:
                log.exception("failed to load extension %s", ext)

        # Sync slash commands once on startup. We don't register any app
        # commands yet, but doing this keeps things tidy for later.
        try:
            synced = await self.tree.sync()
            log.info("synced %d slash command(s)", len(synced))
        except Exception:
            log.exception("failed to sync slash commands")


bot = Bot()


@bot.event
async def on_ready():
    log.info("logged in as %s (id %s)", bot.user, bot.user.id if bot.user else "?")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return  # someone typed an unknown !command — not worth logging
    if isinstance(error, commands.CheckFailure):
        await ctx.reply("You don't have permission to use that.")
        return
    log.error("command error in %s", ctx.command, exc_info=error)


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN is not set (see .env.example)")
    bot.run(token)


if __name__ == "__main__":
    main()
