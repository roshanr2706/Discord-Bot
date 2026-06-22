"""Mirror an upcoming Google Calendar window into a Discord channel."""

import asyncio
import json
import logging
import os
import urllib.parse
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks
from google.oauth2 import service_account
from googleapiclient.discovery import build

log = logging.getLogger("events")

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
POSTED_PATH = os.path.join(CONFIG_DIR, "posted_events.json")

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
ACTIVE_COLOR = 0x5865F2
CANCELLED_COLOR = 0x808080
POLL_MINUTES = 15
WINDOW_DAYS = 30
# Google Calendar product logo, used for the embed author/footer icon.
CAL_ICON = (
    "https://fonts.gstatic.com/s/i/productlogos/calendar_2020q4/v8/"
    "web-64dp/logo_calendar_2020q4_color_2x_web_64dp.png"
)


class Events(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channel_id = int(os.getenv("EVENTS_CHANNEL_ID", "0"))
        self.calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "")
        self.credentials_path = os.getenv(
            "GOOGLE_CREDENTIALS_PATH", "./config/credentials.json"
        )
        self._service = None
        self._lock = asyncio.Lock()
        self.posted = self._load_posted()

    # ----- persistence -------------------------------------------------

    def _load_posted(self) -> dict:
        try:
            with open(POSTED_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_posted(self) -> None:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(POSTED_PATH, "w", encoding="utf-8") as f:
            json.dump(self.posted, f, indent=2, ensure_ascii=False)

    # ----- google calendar ---------------------------------------------

    def _get_service(self):
        if self._service is None:
            creds = service_account.Credentials.from_service_account_file(
                self.credentials_path, scopes=SCOPES
            )
            self._service = build("calendar", "v3", credentials=creds)
        return self._service

    async def _fetch_events(self) -> list[dict]:
        service = self._get_service()
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=WINDOW_DAYS)).isoformat()

        def _call():
            return (
                service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

        result = await asyncio.to_thread(_call)
        return result.get("items", [])

    # ----- embed building ----------------------------------------------

    @staticmethod
    def _ts(node: dict, style: str) -> str | None:
        """A Discord dynamic timestamp (auto-localizes to each viewer)."""
        if not node:
            return None
        if "dateTime" in node:
            dt = datetime.fromisoformat(node["dateTime"])
            return f"<t:{int(dt.timestamp())}:{style}>"
        if "date" in node:  # all-day event — date only
            dt = datetime.fromisoformat(node["date"]).replace(tzinfo=timezone.utc)
            return f"<t:{int(dt.timestamp())}:D>"
        return None

    def _format_when(self, event: dict) -> str | None:
        start = event.get("start", {})
        end = event.get("end", {})
        if "date" in start:  # all-day
            day = self._ts(start, "D")
            rel = self._ts(start, "R")
            return f"{day} · All day\n{rel}" if rel else f"{day} · All day"
        start_full = self._ts(start, "F")
        if not start_full:
            return None
        line = start_full
        end_time = self._ts(end, "t")
        if end_time:
            line += f" → {end_time}"
        rel = self._ts(start, "R")
        if rel:
            line += f"\n{rel}"
        return line

    def _build_embed(self, event: dict, cancelled: bool = False) -> discord.Embed:
        summary = event.get("summary", "(no title)")
        title = f"❌ CANCELLED — {summary}" if cancelled else summary

        description = (event.get("description") or "").strip()
        if len(description) > 2000:
            description = description[:1997] + "..."

        embed = discord.Embed(
            title=title,
            url=event.get("htmlLink"),
            description=description or None,
            color=CANCELLED_COLOR if cancelled else ACTIVE_COLOR,
        )
        embed.set_author(
            name="Cancelled Event" if cancelled else "Upcoming Event",
            icon_url=CAL_ICON,
        )

        when = self._format_when(event)
        if when:
            embed.add_field(name="🗓️ When", value=when, inline=False)

        location = event.get("location")
        if location:
            query = urllib.parse.quote(location)
            maps_url = f"https://www.google.com/maps/search/?api=1&query={query}"
            embed.add_field(
                name="📍 Where", value=f"[{location}]({maps_url})", inline=False
            )

        embed.set_footer(text="Google Calendar", icon_url=CAL_ICON)
        return embed

    # ----- sync core ---------------------------------------------------

    @staticmethod
    def _start_value(event: dict) -> str | None:
        """The event's start as a storable ISO string (dateTime or all-day date)."""
        node = event.get("start", {})
        return node.get("dateTime") or node.get("date")

    @staticmethod
    def _parse_start(value: str | None) -> datetime | None:
        if not value:
            return None
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:  # all-day "YYYY-MM-DD" — treat as UTC midnight
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    async def _sync(self) -> None:
        channel = self.bot.get_channel(self.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(self.channel_id)
            except discord.HTTPException:
                log.warning("events channel %s not reachable", self.channel_id)
                return

        async with self._lock:
            events = await self._fetch_events()
            seen_ids = set()

            for event in events:
                event_id = event["id"]
                seen_ids.add(event_id)
                record = self.posted.get(event_id)
                embed = self._build_embed(event)

                if record is None:
                    msg = await channel.send(embed=embed)
                    self.posted[event_id] = {
                        "message_id": msg.id,
                        "updated": event.get("updated"),
                        "cancelled": False,
                        "start": self._start_value(event),
                    }
                    continue

                # Keep the stored start fresh (and backfill older records).
                record["start"] = self._start_value(event)

                # Already posted — only edit if GCal says it changed.
                if record.get("updated") == event.get("updated") and not record.get(
                    "cancelled"
                ):
                    continue

                await self._edit_or_repost(channel, event_id, embed, event)

            # Anything we posted before but didn't see this round is gone from the
            # API. That happens both when an event is deleted AND when it simply
            # passed (it falls out of the now→+30d window). Only treat it as a
            # cancellation if it vanished while still upcoming.
            now = datetime.now(timezone.utc)
            for event_id, record in list(self.posted.items()):
                if event_id in seen_ids or record.get("cancelled"):
                    continue
                start = self._parse_start(record.get("start"))
                if start is None or start < now:
                    continue  # already happened (or unknown) — leave it alone
                await self._mark_cancelled(channel, event_id, record)

            self._save_posted()

    async def _edit_or_repost(self, channel, event_id, embed, event) -> None:
        record = self.posted[event_id]
        try:
            msg = await channel.fetch_message(record["message_id"])
            await msg.edit(embed=embed)
        except discord.NotFound:
            # Someone deleted the Discord message — re-post it.
            msg = await channel.send(embed=embed)
            record["message_id"] = msg.id
        record["updated"] = event.get("updated")
        record["cancelled"] = False
        record["start"] = self._start_value(event)

    async def _mark_cancelled(self, channel, event_id, record) -> None:
        try:
            msg = await channel.fetch_message(record["message_id"])
        except discord.NotFound:
            # Message is gone and event is gone too — just forget it.
            record["cancelled"] = True
            return

        if msg.embeds:
            embed = msg.embeds[0]
            if not embed.title or not embed.title.startswith("❌ CANCELLED —"):
                embed.title = f"❌ CANCELLED — {embed.title or '(no title)'}"
            embed.color = discord.Color(CANCELLED_COLOR)
            embed.set_author(name="Cancelled Event", icon_url=CAL_ICON)
            await msg.edit(embed=embed)
        record["cancelled"] = True

    # ----- task + command ----------------------------------------------

    @tasks.loop(minutes=POLL_MINUTES)
    async def poll(self):
        try:
            await self._sync()
        except Exception:
            log.exception("calendar sync failed")

    @poll.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    async def cog_load(self):
        self.poll.start()

    async def cog_unload(self):
        self.poll.cancel()

    @commands.command(name="events")
    async def events_cmd(self, ctx: commands.Context):
        """Force an immediate calendar sync."""
        await ctx.message.add_reaction("⏳")
        try:
            await self._sync()
        except Exception:
            log.exception("manual sync failed")
            await ctx.message.add_reaction("❌")
            return
        await ctx.message.add_reaction("✅")


async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))
