import discord
import re
import logging
from helpers import fetchall, fetchone, with_psycopg
from base_queries import *
import os
from utils import get_tier

LOGLEVEL = os.environ.get("LOGLEVEL", "WARNING").upper()
logging.basicConfig(level=LOGLEVEL)
BOT_ID = os.environ.get("CHALLENGEBOT_ID")

intents = discord.Intents.default()
intents.message_content = True

bot = discord.Bot(intents=intents)


@bot.event
async def on_ready():
    print(f"{bot.user} is ready and online!")


@bot.slash_command(name="chart", description="Display the current chart")
async def hello(ctx: discord.ApplicationContext):
    await send_current_chart(ctx)


@bot.event
async def on_message(message):
    logging.debug("DISCORD: %s", message)

    if message.author == bot.user:
        return

    tier = get_tier(message.content)

    if tier == "unknown":
        return

    logging.info("DISCORD: tier from message: %s", tier)

    if int(tier[1:]) > 10:
        await message.add_reaction("🔥")

    save_checkin(message.content, tier, message.author.id)


async def send_current_chart(message):
    challenge_week = get_current_challenge_week()
    await message.send_response(
        file=discord.File(open(f"/src/static/preview-{challenge_week.id}.png", "rb"))
    )


def save_checkin(message, tier, discord_id):
    challenger = fetchone(
        "select * from challengers where discord_id = %s",
        [str(discord_id)],
    )
    challenge_week = get_current_challenge_week(challenger.tz)

    logging.info("DISCORD: challenger %s", challenger)
    logging.info("DISCORD: challenge week %s", challenge_week.id)

    with_psycopg(insert_checkin(message, tier, challenger, challenge_week.id))

    logging.info("DISCORD: inserted checkin for %s", challenger)


bot.run(os.getenv("DISCORD_TOKEN"))
