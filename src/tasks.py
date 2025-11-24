from huey import crontab, SqliteHuey
from green import determine_if_green
from mulligan import check_last_week_for_mulligan_necessity, insert_mulligan_for
import logging

# --- Existing tasks config ---
logging.basicConfig(level="DEBUG")
huey = SqliteHuey()

@huey.task()
def example_task(n):
    print("-- RUNNING EXAMPLE TASK: CALLED WITH n=%s --" % n)
    return n

@huey.periodic_task(crontab(hour="8", day="1"))
def is_green_week():
    print("Determining if green")
    determine_if_green()

@huey.periodic_task(crontab(hour="8", day="1"))
def check_mulligans():
    logging.info("checking for mulligans")
    last_week_checkins = check_last_week_for_mulligan_necessity()
    logging.info("last week: %s" % last_week_checkins)

    is_green_week = last_week_checkins[0].green

    needing_of_mulligan = [
        (x.name, x.cwid)
        for x in last_week_checkins
        if x.count < 5 and is_green_week or x.count < 2
    ]
    logging.info("needs a mulligan: %s" % needing_of_mulligan)
    for name, cwid in needing_of_mulligan:
        insert_mulligan_for(name, cwid)

# --- New Discord Results Broadcast Task Begins Here ---

import os
from datetime import datetime, timedelta
import pytz
import requests

from base_queries import get_challenges, challenge_data, points_so_far
from medals import *
import medal_log
from helpers import fetchone, fetchall
from rule_sets import calculate_total_score

def get_challenge_that_ended_yesterday():
    """
    Returns the challenge (dict-like row) that ended yesterday in America/New_York, or None if none.
    Accounts for bye weeks - if a challenge's last week is a bye week,
    considers the challenge ended at the end of the last non-bye week.
    """
    tz = pytz.timezone("America/New_York")
    now = datetime.now(tz)
    yesterday = now - timedelta(days=1)
    for challenge in get_challenges():
        # Get effective end date (excluding bye weeks)
        effective_end = get_effective_challenge_end_date(challenge)
        if effective_end == yesterday.date():
            return challenge
    return None

def get_effective_challenge_end_date(challenge):
    """
    Get the effective end date of a challenge, excluding bye weeks.
    If the last week is a bye week, returns the end date of the last non-bye week.
    Otherwise, returns the challenge's end date.
    """
    # Get the last challenge week for this challenge
    last_week = fetchone(
        'SELECT * FROM challenge_weeks WHERE challenge_id = %s ORDER BY "end" DESC LIMIT 1',
        [challenge.id]
    )
    
    if not last_week:
        # No weeks found, use challenge end date
        end_date = challenge.end if hasattr(challenge, "end") else challenge["end"]
        return end_date.date() if isinstance(end_date, datetime) else end_date
    
    # If the last week is a bye week, get the last non-bye week
    if last_week.bye_week:
        last_non_bye_week = fetchone(
            'SELECT * FROM challenge_weeks WHERE challenge_id = %s AND (bye_week != true OR bye_week IS NULL) ORDER BY "end" DESC LIMIT 1',
            [challenge.id]
        )
        if last_non_bye_week:
            end_date = last_non_bye_week.end if hasattr(last_non_bye_week, "end") else last_non_bye_week["end"]
            return end_date.date() if isinstance(end_date, datetime) else end_date
        else:
            # All weeks are bye weeks? Use challenge end date
            end_date = challenge.end if hasattr(challenge, "end") else challenge["end"]
            return end_date.date() if isinstance(end_date, datetime) else end_date
    else:
        # Last week is not a bye week, use challenge end date
        end_date = challenge.end if hasattr(challenge, "end") else challenge["end"]
        return end_date.date() if isinstance(end_date, datetime) else end_date

def get_most_recently_ended_challenge():
    """
    Returns the most recently ended challenge, or None if none.
    Accounts for bye weeks - if a challenge's last week is a bye week,
    considers the challenge ended at the end of the last non-bye week.
    """
    tz = pytz.timezone("America/New_York")
    now = datetime.now(tz)
    most_recent = None
    most_recent_end = None
    
    for challenge in get_challenges():
        # Get effective end date (excluding bye weeks)
        effective_end = get_effective_challenge_end_date(challenge)
        
        # Only consider challenges that have ended
        if effective_end < now.date():
            if most_recent_end is None or effective_end > most_recent_end:
                most_recent = challenge
                most_recent_end = effective_end
    
    return most_recent

def generate_challenge_results_message(challenge):
    """
    Generate the results message for a given challenge.
    Returns the message string, or None if challenge is invalid or has no podium.
    """
    if not challenge:
        return None
    
    podium = get_podium(challenge.id)
    if not podium:
        logging.warning(f"No podium found for challenge {challenge.name}")
        return None
    
    ach_lines = gather_achievements(challenge.id)
    msg = compose_results_message(challenge, podium, ach_lines)
    return msg

def get_all_challenge_week_ids(challenge_id):
    """Get all challenge week IDs for a challenge."""
    cw = fetchall(
        'SELECT id FROM challenge_weeks WHERE challenge_id = %s ORDER BY "end" ASC',
        [challenge_id],
    )
    return [row.id for row in cw]

def format_discord_mention(discord_id):
    return f"<@{discord_id}>"

def get_podium(challenge_id):
    """Get top 3 participants with their discord_id and points.
    Uses calculate_total_score() to match the web interface calculation,
    which properly excludes bye weeks and uses rule_set scoring.
    """
    # Use calculate_total_score to match web interface (excludes bye weeks, uses rule_set)
    total_points = calculate_total_score(challenge_id)
    
    if not total_points:
        return []
    
    # Get all discord_ids in one query
    unique_names = set(total_points.keys())
    placeholders = ','.join(['%s'] * len(unique_names))
    challengers = fetchall(
        f"SELECT name, discord_id FROM challengers WHERE name IN ({placeholders})",
        list(unique_names)
    )
    name_to_discord_id = {c.name: c.discord_id for c in challengers if c.discord_id}
    
    # Sort by points and get top 3
    sorted_names = sorted(total_points.items(), key=lambda x: -x[1])[:3]
    podium = []
    for name, points in sorted_names:
        if name in name_to_discord_id:
            podium.append({
                'name': name,
                'discord_id': name_to_discord_id[name],
                'points': float(points)
            })
    return podium

def get_final_medal_holders_per_week(challenge_id):
    """
    Get final medal holders for each week in the challenge.
    For week-based medals, returns only the person who held the medal at the end of each week.
    This excludes bye weeks and only counts medals that were still held at week end.
    
    For non-stealable medals (green, gold, first_to_green), multiple people can earn them
    in the same week, so we partition by medal+week+challenger to get all recipients.
    For stealable medals, we partition by medal+week to get only the final holder.
    """
    sql = """
    WITH ranked_medals AS (
        SELECT
            m.*,
            ROW_NUMBER() OVER (
                PARTITION BY 
                    m.medal, 
                    m.challenge_week_id,
                    -- For non-stealable medals, partition by challenger too (multiple people can earn)
                    -- For stealable medals, only partition by medal+week (one final holder)
                    CASE 
                        WHEN m.medal IN ('green', 'gold', 'first_to_green') 
                        THEN m.challenger_id 
                    END
                ORDER BY m.created_at DESC
            ) as rn
        FROM medals m
        JOIN challenge_weeks cw ON m.challenge_week_id = cw.id
        WHERE cw.challenge_id = %s
        AND (cw.bye_week != true OR cw.bye_week IS NULL)
    ),
    numbered_weeks AS (
        SELECT 
            id,
            challenge_id,
            ROW_NUMBER() OVER (
                PARTITION BY challenge_id 
                ORDER BY start
            ) AS week_number
        FROM challenge_weeks
        WHERE challenge_id = %s
        AND (bye_week != true OR bye_week IS NULL)
    )
    SELECT
        rm.medal AS medal_name,
        rm.emoji AS medal_emoji,
        c.name AS challenger_name,
        c.discord_id as discord_id,
        rm.challenge_week_id,
        rm.checkin_id,
        ci.tier AS checkin_tier,
        nw.week_number
    FROM ranked_medals rm
    JOIN challengers c ON c.id = rm.challenger_id
    LEFT JOIN checkins ci ON ci.id = rm.checkin_id
    JOIN numbered_weeks nw ON nw.id = rm.challenge_week_id
    WHERE rm.rn = 1
    ORDER BY rm.challenge_week_id, rm.medal;
    """
    return fetchall(sql, [challenge_id, challenge_id])

def get_final_medal_holders_challenge_wide(challenge_id):
    """
    Get final medal holders for challenge-wide medals.
    Returns only the person who held the medal at the end of the challenge.
    Includes tier and week information for highest_tier_challenge.
    """
    sql = """
    WITH ranked_medals AS (
        SELECT
            m.*,
            ROW_NUMBER() OVER (
                PARTITION BY m.medal
                ORDER BY m.created_at DESC
            ) as rn
        FROM medals m
        JOIN challenge_weeks cw ON m.challenge_week_id = cw.id
        WHERE cw.challenge_id = %s
        AND (cw.bye_week != true OR cw.bye_week IS NULL)
        AND m.medal IN ('highest_tier_challenge', 'earliest_for_challenge', 'latest_for_challenge')
    ),
    numbered_weeks AS (
        SELECT 
            id,
            challenge_id,
            ROW_NUMBER() OVER (
                PARTITION BY challenge_id 
                ORDER BY start
            ) AS week_number
        FROM challenge_weeks
        WHERE challenge_id = %s
        AND (bye_week != true OR bye_week IS NULL)
    )
    SELECT
        rm.medal AS medal_name,
        rm.emoji AS medal_emoji,
        c.name AS challenger_name,
        c.discord_id as discord_id,
        rm.challenge_week_id,
        rm.checkin_id,
        ci.tier AS checkin_tier,
        nw.week_number
    FROM ranked_medals rm
    JOIN challengers c ON c.id = rm.challenger_id
    LEFT JOIN checkins ci ON ci.id = rm.checkin_id
    LEFT JOIN numbered_weeks nw ON nw.id = rm.challenge_week_id
    WHERE rm.rn = 1;
    """
    return fetchall(sql, [challenge_id, challenge_id])

def collect_achievement_tags_multiple(medal_records, kind):
    """Collect achievement tags with counts for medals that can be earned multiple times.
    Only counts final holders (medals still held at end of week/challenge).
    """
    d = {}
    for m in medal_records:
        if m.medal_name == kind and m.discord_id:
            d[m.discord_id] = d.get(m.discord_id, 0) + 1
    return d

def collect_highest_tier_challenge_with_details(medal_records):
    """Collect highest_tier_challenge medals with tier and week information.
    Returns a dict mapping discord_id to (tier, week_number) tuple.
    """
    d = {}
    for m in medal_records:
        if m.medal_name == "highest_tier_challenge" and m.discord_id:
            tier = getattr(m, 'checkin_tier', None)
            week_num = getattr(m, 'week_number', None)
            if tier and week_num:
                d[m.discord_id] = (tier, week_num)
    return d

def render_achievement_line(emote, label, discord_dict):
    """Render an achievement line with mentions and counts.
    Users with higher counts are listed first.
    Format: blockquote with h3 header.
    """
    if not discord_dict:
        return ""
    tags = []
    # Sort by count in descending order (highest count first)
    for discord_id, count in sorted(discord_dict.items(), key=lambda x: -x[1]):
        tag = format_discord_mention(discord_id)
        if count > 1:
            tag += f" (x{count})"
        tags.append(tag)
    return f"> ### {emote} **{label}:** \n> {', '.join(tags)}"

def render_highest_tier_challenge_line(emote, label, tier_week_dict):
    """Render highest tier challenge line with tier and week information.
    Format: blockquote with h3 header.
    """
    if not tier_week_dict:
        return ""
    tags = []
    for discord_id, (tier, week_num) in sorted(tier_week_dict.items()):
        tag = format_discord_mention(discord_id)
        tag += f" ({tier}, week {week_num})"
        tags.append(tag)
    return f"> ### {emote} **{label}:** \n> {', '.join(tags)}"

def compose_results_message(challenge, podium, achievements):
    """Compose the final results message."""
    msg = f"# {challenge.name} Results! :checkered_flag:\n\n"
    
    # Podium places - using emojis from medals module
    places_config = [
        (PODIUM_EMOJIS["first_place"], "1st Place:", 0),
        (PODIUM_EMOJIS["second_place"], "2nd Place:", 1),
        (PODIUM_EMOJIS["third_place"], "3rd Place:", 2),
    ]
    
    for emoji, label, idx in places_config:
        if idx < len(podium):
            person = podium[idx]
            points_str = f"{person['points']:.1f}" if person['points'] % 1 != 0 else f"{int(person['points'])}"
            msg += f"## {emoji} **{label}** {format_discord_mention(person['discord_id'])} with {points_str} points\n"
    
    msg += "\n\n## Achievements\n\n"
    for line in achievements:
        if line is None:
            # Blank line between groups - add a newline
            msg += "\n"
        elif line:
            # Achievement line (already has header and content with newline between them)
            # Add a newline after the achievement to separate from next item
            msg += f"{line}\n"
    msg += "\n@everyone"
    return msg

def gather_achievements(challenge_id):
    """Gather all achievements for the entire challenge across all weeks.
    Only includes medals that were still held at the end of each week/challenge.
    """
    # Get final medal holders (only those who held medals at end of week/challenge)
    final_week_medals = get_final_medal_holders_per_week(challenge_id)
    final_challenge_medals = get_final_medal_holders_challenge_wide(challenge_id)
    
    lines = []
    
    # Club 60 and Club 50 - based on total points
    # Use calculate_total_score to match web interface (excludes bye weeks, uses rule_set)
    total_points = calculate_total_score(challenge_id)
    
    if not total_points:
        name_to_discord_id = {}
    else:
        # Get all discord_ids in one query
        unique_names = set(total_points.keys())
        placeholders = ','.join(['%s'] * len(unique_names))
        challengers = fetchall(
            f"SELECT name, discord_id FROM challengers WHERE name IN ({placeholders})",
            list(unique_names)
        )
        name_to_discord_id = {c.name: c.discord_id for c in challengers if c.discord_id}
    
    club_60_ids = [name_to_discord_id[name] for name, points in total_points.items() 
                   if points >= 60 and name in name_to_discord_id]
    club_50_ids = [name_to_discord_id[name] for name, points in total_points.items() 
                   if points >= 50 and name in name_to_discord_id]
    
    if club_60_ids:
        lines.append(f"> ### 🌟 **Club 60:** \n> {', '.join(format_discord_mention(i) for i in club_60_ids)}")
    if club_50_ids:
        lines.append(f"> ### ⭐ **Club 50:** \n> {', '.join(format_discord_mention(i) for i in club_50_ids)}")
    
    # Group 1: Tier achievements
    highest_tier_challenge_details = collect_highest_tier_challenge_with_details(final_challenge_medals)
    if highest_tier_challenge_details:
        lines.append(render_highest_tier_challenge_line(":person_lifting_weights:", "Highest Overall Tier", highest_tier_challenge_details))
    
    highest_tier_week = collect_achievement_tags_multiple(final_week_medals, "highest_tier_week")
    if highest_tier_week:
        lines.append(render_achievement_line(":muscle:", "Highest Weekly Tier", highest_tier_week))
    
    # Group 2: Medal achievements
    gold_week = collect_achievement_tags_multiple(final_week_medals, "gold")
    first_to_green = collect_achievement_tags_multiple(final_week_medals, "first_to_green")
    green_week = collect_achievement_tags_multiple(final_week_medals, "green")
    
    # Add blank line between groups if both exist
    if (highest_tier_challenge_details or highest_tier_week) and (gold_week or first_to_green or green_week):
        lines.append(None)  # Marker for blank line
    
    if gold_week:
        lines.append(render_achievement_line(":medal:", "Gold Week", gold_week))
    
    if first_to_green:
        lines.append(render_achievement_line(":eight_spoked_asterisk:", "First to Green", first_to_green))
    
    if green_week:
        lines.append(render_achievement_line(":green_square:", "Green Week", green_week))
    
    # Group 3: Check-in achievements
    earliest = collect_achievement_tags_multiple(final_week_medals, "earliest_for_week")
    latest = collect_achievement_tags_multiple(final_week_medals, "latest_for_week")
    
    # Add blank line between groups if both exist
    if (gold_week or first_to_green or green_week) and (earliest or latest):
        lines.append(None)  # Marker for blank line
    
    if earliest:
        lines.append(render_achievement_line(":sun_with_face:", "Earliest Check-in", earliest))
    
    if latest:
        lines.append(render_achievement_line(":new_moon_with_face:", "Latest Check-in", latest))
    
    return lines

def _post_discord_message(channel_id, msg):
    """Send a message to Discord channel using HTTP API."""
    try:
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            logging.error("DISCORD_TOKEN environment variable is not set")
            return
        
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        headers = {
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json"
        }
        data = {
            "content": msg
        }
        
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        logging.info(f"Successfully sent message to Discord channel {channel_id}")
    except Exception as e:
        logging.exception(f"Error sending results message to Discord: {e}")

@huey.periodic_task(crontab(minute="0", hour="13,14"))  # Check both 13 and 14 UTC to handle DST
def broadcast_discord_challenge_results():
    """Broadcast challenge results to Discord the day after a challenge ends."""
    # Verify it's approximately 9am ET (within 1 hour window)
    tz = pytz.timezone("America/New_York")
    now_et = datetime.now(tz)
    if not (8 <= now_et.hour <= 10):
        logging.debug(f"Not 9am ET (current ET time: {now_et.hour}:{now_et.minute:02d}), skipping")
        return
    
    chan_id = os.getenv("DISCORD_RESULTS_CHANNEL_ID")
    if not chan_id:
        logging.error("DISCORD_RESULTS_CHANNEL_ID environment variable is required for automated results broadcasts.")
        return
    
    challenge = get_challenge_that_ended_yesterday()
    if not challenge:
        logging.debug("No challenge ended yesterday, skipping results broadcast")
        return
    
    logging.info(f"Broadcasting results for challenge: {challenge.name}")
    
    msg = generate_challenge_results_message(challenge)
    if not msg:
        return
    
    # Send message to Discord
    try:
        _post_discord_message(int(chan_id), msg)
        logging.info(f"Successfully broadcasted results for challenge {challenge.name}")
    except Exception as e:
        logging.exception(f"Failed to broadcast results for challenge {challenge.name}: {e}")
