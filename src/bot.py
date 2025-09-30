import discord
import re
import logging
from helpers import fetchall, fetchone, with_psycopg
from base_queries import *
import os
from utils import get_tier

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

LOGLEVEL = os.environ.get("LOGLEVEL", "WARNING").upper()
logging.basicConfig(level=LOGLEVEL)
BOT_ID = os.environ.get("CHALLENGEBOT_ID")

@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    print(message)
    print(message.mentions)
    mentioned = bot_mentioned(message.mentions)
    if mentioned:
        print(mentioned)
        await handle_mention_messages(message)


    tier = get_tier(message.content)

    if tier == "unknown":
        return

    print(tier)

    if int(tier[1:]) > 10:
        await message.add_reaction('🔥')

    save_checkin(message.content, tier, message.author.id)

def bot_mentioned(mentions):
    return BOT_ID in [str(mention.id) for mention in mentions]

async def handle_mention_messages(message):
    challenge = get_current_challenge()
    challenge_week = get_current_challenge_week()
    if "this week's chart" in message.content:
        await message.reply(file=discord.File(open(f'/src/static/preview-{challenge_week.id}.png', 'rb')))
        

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



client.run(os.environ.get("DISCORD_TOKEN"))
