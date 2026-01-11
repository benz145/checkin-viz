from rq import cron
from green import determine_if_green
import discord
from discord_bot import bot
import os
#from mulligan import check_last_week_for_mulligan_necessity, insert_mulligan_for
import logging
import random

logging.basicConfig(level="DEBUG")
from rq import cron

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = os.environ.get("ALLOWED_MESSAGE_CHANNEL_ID")

async def get_channel():
    if bot.user is None:
        await bot.login(DISCORD_TOKEN)
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if channel is None:
        channel = await bot.fetch_channel(DISCORD_CHANNEL_ID)
        if channel is None:
            logging.info("Cannot find channel %s", DISCORD_CHANNEL_ID)
    return channel

async def example_task():
    print("-- RUNNING EXAMPLE TASK --")
    await send_bot_message("test")
    print("-- RUNNING EXAMPLE TASK --")


#cron.register(
    #example_task,
    #queue_name='cron',
    #cron='* * * * *'
#)

no_gifs = [
    "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExcnp1eHN2MGZ4OWI2ZnV2eGdlNno4MzU3cTJmdGFpZTZrNHY1Ym9jaCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/JYZ397GsFrFtu/giphy.gif",
    "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExdGI2am52cDl1MTJ1dmliM2N1emVzZDdwbDAzMHF4d3MwdXB5Zml3cyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/AL10PPC3eZhxC/giphy.gif",
    "https://media2.giphy.com/media/v1.Y2lkPTc5MGI3NjExcjFic3owOHBwbmR2NzY0MTB6ajF1cGNvamsyZ3FqY3B1N2plNmYwYyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/ctDn1gKAGSW27BPleZ/giphy.gif",
]
yes_gifs = [
    "https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExbjF6MzM5NGh6ZHFxcGs1dDh2eGpvenR3ZjJ2azVna2d3Z2NzbDQ1cyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/HUkOv6BNWc1HO/giphy.gif",
    "https://media3.giphy.com/media/v1.Y2lkPTc5MGI3NjExeWF0M2lqZHY3bTd6dHNpcWtpb2VkeWd1NXFlcXZ5cjdrbWxkaHFuaiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/MZocLC5dJprPTcrm65/giphy.gif",
]
async def is_green_week():
    logging.info("Determining if green")
    green_week = determine_if_green()
    channel = await get_channel()
    if channel is None:
        logging.warning("Cannot send message channel not found")
    if green_week == True:
        await channel.send(
            embed=discord.Embed(
                image=random.choice(yes_gifs), description="It's a green week!!!!"
            )
        )
    else:
        await channel.send(
            embed=discord.Embed(
                image=random.choice(no_gifs), description="Not this week!"
            )
        )

cron.register(
    is_green_week,
    queue_name='cron',
    cron='0 14 * * 1'
)


#def check_mulligans():
#    logging.info("checking for mulligans")
#    last_week_checkins = check_last_week_for_mulligan_necessity()
#    logging.info("last week: %s" % last_week_checkins)
#
#    is_green_week = last_week_checkins[0].green
#
#    needing_of_mulligan = [
#        (x.name, x.cwid)
#        for x in last_week_checkins
#        if x.count < 5 and is_green_week or x.count < 2
#    ]
#    logging.info("needs a mulligan: %s" % needing_of_mulligan)
#    for name, cwid in needing_of_mulligan:
#        insert_mulligan_for(name, cwid)
