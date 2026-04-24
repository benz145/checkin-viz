import discord
from discord.ui import Modal, Select, InputText, Button
import re
import logging
from collections import defaultdict
from helpers import fetchall, fetchone, with_psycopg
from base_queries import *
from green import determine_if_green
import os
from utils import get_tier
import medals
import slash_commands.quit as quit_slash
import slash_commands.join as join_slash
import slash_commands.calc
import slash_commands.bmr
from chart import checkin_chart, diamond_week_holders, red_week_holders, week_heat_map_from_checkins, write_og_image
from rule_sets import calculate_total_score
import medal_log
from discord_bot import bot

LOGLEVEL = os.environ.get("LOGLEVEL", "DEBUG").upper()
logging.basicConfig(level=LOGLEVEL)
ALLOWED_MESSAGE_CHANNEL_ID = str(os.environ.get("ALLOWED_MESSAGE_CHANNEL_ID"))

# Import medal metadata and names from medals module
from medals import medal_metadata, nice_medal_names


def describe_medal(medal_name):
    fallback = medal_name.replace("_", " ").replace("  ", " ").title()
    return nice_medal_names.get(medal_name, fallback)


def get_medal_group(medal_name):
    """Get the group (A-D) for a medal"""
    metadata = medal_metadata.get(medal_name)
    return metadata["group"] if metadata else None


def get_medal_difficulty(medal_name):
    """Get the difficulty (1-4) for a medal"""
    metadata = medal_metadata.get(medal_name)
    return metadata["difficulty"] if metadata else None


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
        total_possible_checkins_so_far(
            current_challenge.id, selected_challenge_week.id
        ),
        red_week_names=red_week_holders(selected_challenge_week.id),
        diamond_week_names=diamond_week_holders(selected_challenge_week.id),
    )
    write_og_image(chart, selected_challenge_week.id)
    await send_current_chart(ctx)


@bot.slash_command(name="green", description="Check if it's a green week")
async def green(ctx: discord.ApplicationContext):
    green_week = determine_if_green()
    if green_week == True:
        await ctx.send_response("It's a green week!")
    else:
        await ctx.send_response("It's not a green week")
    print(green_week)


@bot.slash_command(name="quit", description="I can't handle the challenge.")
async def quit_command(ctx: discord.ApplicationContext):
    await ctx.respond("You sure?", view=quit_slash.Button())


@bot.slash_command(name="join", description="I'm ready to win.")
async def join_command(ctx: discord.ApplicationContext):
    await ctx.respond("You ready to win?", view=join_slash.Button())


@bot.slash_command(
    name="calculate_tier", description="Calculate the tier for your checkin"
)
async def calc_command(ctx: discord.ApplicationContext):
    await ctx.send_modal(slash_commands.calc.Modal(title="Enter Checkin Details"))


@bot.slash_command(
    name="bmr", description="Calculate and update your BMR"
)
async def bmr_command(ctx: discord.ApplicationContext):
    await slash_commands.bmr.launch_bmr_modal(ctx)


@bot.slash_command(
    name="bmr_reset",
    description="Reset your BMR profile and restart first-time BMR setup",
)
async def bmr_reset_command(ctx: discord.ApplicationContext):
    await slash_commands.bmr.reset_bmr_profile(ctx)


@bot.slash_command(
    name="testpodium",
    description="Test the podium results message for the most recently ended challenge",
)
async def testpodium_command(ctx: discord.ApplicationContext):
    """Send the results message for the most recently ended challenge."""
    from slash_commands.testpodium import (
        get_most_recently_ended_challenge,
        generate_challenge_results_message,
    )

    await ctx.defer()  # Acknowledge the command since this might take a moment

    challenge = get_most_recently_ended_challenge()
    if not challenge:
        await ctx.followup.send("No ended challenge found.")
        return

    msg = generate_challenge_results_message(challenge)
    if not msg:
        await ctx.followup.send(
            f"Could not generate results for challenge: {challenge.name}"
        )
        return

    try:
        await ctx.followup.send(msg)
    except Exception as e:
        logging.exception(f"Error sending testpodium message: {e}")
        await ctx.followup.send(f"Error sending message: {str(e)}")


@bot.slash_command(
    name="uncheckin",
    description="Remove your last check-in from today",
)
async def uncheckin(ctx: discord.ApplicationContext):
    """
    Clear the invoking user's check-in for today (in their timezone) in the
    current challenge week, if one exists.
    """
    user = getattr(ctx, "author", None) or getattr(ctx, "user", None)
    if user is None:
        await ctx.respond(
            "Could not determine which user invoked this command.",
            ephemeral=True,
        )
        return

    challenger = challenger_by_discord_id(str(user.id))
    if challenger is None:
        await ctx.respond(
            "You’re not currently registered for the challenge, so there’s no check-in to clear.",
            ephemeral=True,
        )
        return

    challenge_week = get_current_challenge_week(challenger.tz)
    if challenge_week is None:
        await ctx.respond(
            "There is no active challenge week right now, so there’s no check-in for today to clear.",
            ephemeral=True,
        )
        return

    deleted_count = with_psycopg(
        clear_today_checkins_for_challenger(challenger, challenge_week)
    )

    if deleted_count == 0:
        await ctx.respond(
            "You don’t have a check-in for today to clear.",
            ephemeral=True,
        )
        return

    challenge = get_current_challenge()
    if challenge is not None:
        medals.update_medal_table(challenge.id, challenge_week.id)

    await ctx.respond(
        f"<@{user.id}>'s last check-in from today was removed.",
        ephemeral=False,
    )


@bot.event
async def on_message(message):
    logging.debug("Got a message: %s", message)

    if str(message.channel.id) != ALLOWED_MESSAGE_CHANNEL_ID:
        logging.info("Skipping message from disallowed channel: %s", message.channel.id)
        return None

    if message.author == bot.user:
        return

    tier = get_tier(message.content)

    if tier == "unknown":
        return

    logging.info("DISCORD: tier from message: %s", tier)

    # Mark all valid check-ins
    await message.add_reaction("✅")

    if int(tier[1:]) > 10:
        await message.add_reaction("🔥")

    checkin_id = save_checkin(message.content, tier, message.author.id)

    challenge_week = get_current_challenge_week()
    challenge = get_current_challenge()
    medals.update_medal_table(challenge.id, challenge_week.id)
    log = medal_log.get_medal_log(challenge_week.id)
    logging.info("DISCORD: medal log %s", log)

    relevant_medals = [medal for medal in log if medal.checkin_id == checkin_id]
    if relevant_medals:
        logging.info("DISCORD: medals for checkin %s", relevant_medals)
        
        # Add reactions for all medals
        for medal in relevant_medals:
            await message.add_reaction(medal.medal_emoji)
        
        # Group medals by user, action type, and (for steals) the person they stole from
        grouped_medals = defaultdict(list)
        
        for medal in relevant_medals:
            nice_name = describe_medal(medal.medal_name)
            emoji = medal.medal_emoji or ""
            medal_display = f"{emoji} __**{nice_name}**__".strip()
            
            # Check if this medal was stolen (has a previous holder)
            if medal.stolen_checkin_challenger_name and medal.stolen_discord_id is not None:
                if medal.discord_id == medal.stolen_discord_id:
                    # Special case: still holds and surpassed their own record
                    key = (medal.discord_id, "still_holds", None)
                else:
                    # Stolen from someone else
                    key = (medal.discord_id, "stole", medal.stolen_discord_id)
            else:
                # Earned (no previous holder or invalid steal data)
                key = (medal.discord_id, "earned", None)
            
            grouped_medals[key].append(medal_display)
        
        # Format grouped messages
        # Sort so earned messages come before stolen/still_holds messages
        def sort_key(item):
            (discord_id, action_type, stolen_discord_id), medal_list = item
            # Return 0 for "earned", 1 for others to ensure earned comes first
            return (0 if action_type == "earned" else 1, discord_id, action_type, stolen_discord_id or "")
        
        medal_message = ""
        for (discord_id, action_type, stolen_discord_id), medal_list in sorted(grouped_medals.items(), key=sort_key):
            # Format medal list with commas and "and"
            if len(medal_list) == 1:
                medals_text = medal_list[0]
            elif len(medal_list) == 2:
                medals_text = f"{medal_list[0]} and {medal_list[1]}"
            else:
                medals_text = ", ".join(medal_list[:-1]) + f", and {medal_list[-1]}"
            
            if action_type == "still_holds":
                pronoun = "them" if len(medal_list) > 1 else "it"
                medal_message += (
                    f"\n\n<@{discord_id}> still holds {medals_text}, and has now surpassed {pronoun}!"
                )
            elif action_type == "stole":
                # Validate stolen_discord_id to prevent invalid mentions
                if stolen_discord_id is not None:
                    medal_message += (
                        f"\n\n<@{discord_id}> stole {medals_text} from <@{stolen_discord_id}>!"
                    )
                else:
                    # Fallback if stolen_discord_id is None (shouldn't happen, but safety check)
                    logging.warning(f"stolen_discord_id is None for steal action by {discord_id}")
                    medal_message += (
                        f"\n\n<@{discord_id}> stole {medals_text}!"
                    )
            else:  # earned
                medal_message += (
                    f"\n\n<@{discord_id}> earned {medals_text}!"
                )
        
        logging.info("DISCORD: %s", medal_message)
        await message.reply(medal_message)


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

    id = with_psycopg(insert_checkin(message, tier, challenger, challenge_week.id))

    logging.info("DISCORD: inserted checkin id: %s for %s", id, challenger)

    return id


if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))
