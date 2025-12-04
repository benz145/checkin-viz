import logging
from datetime import datetime

from helpers import fetchone, fetchall
from base_queries import get_challenges
from medals import PODIUM_EMOJIS
from rule_sets import calculate_total_score


def get_most_recently_ended_challenge():
    """
    Returns the most recently ended challenge, or None if none.
    """
    return fetchone(
        'SELECT * FROM challenges WHERE "end" < current_date ORDER BY "end" DESC LIMIT 1',
        []
    )


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


def collect_all_achievement_tags(medal_records):
    """Collect achievement tags with counts for all medal types at once.
    Only counts final holders (medals still held at end of week/challenge).
    Returns a dict mapping medal_name to {discord_id: count}.
    """
    result = {}
    for m in medal_records:
        if m.discord_id:
            if m.medal_name not in result:
                result[m.medal_name] = {}
            result[m.medal_name][m.discord_id] = result[m.medal_name].get(m.discord_id, 0) + 1
    return result


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
    
    # Build medal maps once for all medal types
    week_achievements = collect_all_achievement_tags(final_week_medals)
    
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
    
    highest_tier_week = week_achievements.get("highest_tier_week", {})
    if highest_tier_week:
        lines.append(render_achievement_line(":muscle:", "Highest Weekly Tier", highest_tier_week))
    
    # Group 2: Medal achievements
    gold_week = week_achievements.get("gold", {})
    first_to_green = week_achievements.get("first_to_green", {})
    green_week = week_achievements.get("green", {})
    
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
    earliest = week_achievements.get("earliest_for_week", {})
    latest = week_achievements.get("latest_for_week", {})
    
    # Add blank line between groups if both exist
    if (gold_week or first_to_green or green_week) and (earliest or latest):
        lines.append(None)  # Marker for blank line
    
    if earliest:
        lines.append(render_achievement_line(":sun_with_face:", "Earliest Check-in", earliest))
    
    if latest:
        lines.append(render_achievement_line(":new_moon_with_face:", "Latest Check-in", latest))
    
    return lines

