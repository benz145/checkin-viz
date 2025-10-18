import discord
from discord.ui import Modal, Select, InputText, Button
import re
import logging
from helpers import fetchall, fetchone, with_psycopg
from base_queries import *
from green import determine_if_green
import os
from utils import get_tier
import random
import medals
import slash_commands.quit as quit_slash
import slash_commands.join as join_slash
import slash_commands.calc
from chart import checkin_chart, week_heat_map_from_checkins, write_og_image
from rule_sets import calculate_total_score

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
async def get_chart(ctx: discord.ApplicationContext):
    current_challenge = get_current_challenge()
    selected_challenge_week = get_current_challenge_week()
    checkins = checkins_this_week(selected_challenge_week.id)
    total_points = calculate_total_score(current_challenge.id)
    week, latest, achievements = week_heat_map_from_checkins(
        checkins,
        current_challenge.id,
        current_challenge.rule_set,
    )
    week = sorted(
        week, key=lambda x: -total_points[x.name] if x.name in total_points else 0
    )
    total_checkins = {x[1]: x[0] for x in points_so_far(current_challenge.id)}
    logging.info("TOTAL CHECKINS %s", total_checkins)
    logging.debug("WEEK: %s, LATEST: %s", week, latest)
    chart = checkin_chart(
        week,
        1000,
        600,
        current_challenge.id,
        selected_challenge_week.green,
        selected_challenge_week.bye_week,
        total_points,
        achievements,
        total_checkins,
        total_possible_checkins(current_challenge.id)[0],
        total_possible_checkins_so_far(current_challenge.id, selected_challenge_week.id),
    )
    write_og_image(chart, selected_challenge_week.id)
    await send_current_chart(ctx)


no_gifs = [
    "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExcnp1eHN2MGZ4OWI2ZnV2eGdlNno4MzU3cTJmdGFpZTZrNHY1Ym9jaCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/JYZ397GsFrFtu/giphy.gif",
    "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExdGI2am52cDl1MTJ1dmliM2N1emVzZDdwbDAzMHF4d3MwdXB5Zml3cyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/AL10PPC3eZhxC/giphy.gif",
    "https://media2.giphy.com/media/v1.Y2lkPTc5MGI3NjExcjFic3owOHBwbmR2NzY0MTB6ajF1cGNvamsyZ3FqY3B1N2plNmYwYyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/ctDn1gKAGSW27BPleZ/giphy.gif",
]
yes_gifs = [
    "https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExbjF6MzM5NGh6ZHFxcGs1dDh2eGpvenR3ZjJ2azVna2d3Z2NzbDQ1cyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/HUkOv6BNWc1HO/giphy.gif",
    "https://media3.giphy.com/media/v1.Y2lkPTc5MGI3NjExeWF0M2lqZHY3bTd6dHNpcWtpb2VkeWd1NXFlcXZ5cjdrbWxkaHFuaiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/MZocLC5dJprPTcrm65/giphy.gif",
]


@bot.slash_command(name="green", description="Determine if it's a green week")
async def green(ctx: discord.ApplicationContext):
    green_week = determine_if_green()
    print(green_week)
    if green_week == True:
        await ctx.send_response(
            embed=discord.Embed(
                image=random.choice(yes_gifs), description="It's a green week!!!!"
            )
        )
    else:
        await ctx.send_response(
            embed=discord.Embed(
                image=random.choice(no_gifs), description="Not this week!"
            )
        )


@bot.slash_command(name="quit", description="I can't handle the challenge.")
async def quit_command(ctx: discord.ApplicationContext):
    await ctx.respond("You sure?", view=quit_slash.Button())


@bot.slash_command(name="join", description="I'm ready to win.")
async def join_command(ctx: discord.ApplicationContext):
    await ctx.respond("You ready to win?", view=join_slash.Button())

@bot.slash_command(name="calculate_tier", description="Calculate the tier for your checkin")
async def calc_command(ctx: discord.ApplicationContext):
    await ctx.send_modal(slash_commands.calc.Modal(title="Enter Checkin Details"))


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

    challenge_week = get_current_challenge_week()
    challenge = get_current_challenge()
    medals.update_medal_table(challenge.id, challenge_week.id)


async def send_current_chart(message):
    challenge_week = get_current_challenge_week()
    await message.send_response(
        file=discord.File(open(f"/src/static/preview-{challenge_week.id}.png", "rb")),
        ephemeral=True,
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
