from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from auto_knockout import format_natural_language_list
from medal_constants import NON_STEALABLE_MEDALS, SILENT_MEDALS, nice_medal_names

ROUNDUP_TZ = ZoneInfo("America/New_York")
# Matches tasks.py cron "0 14 * * *". Silence until one minute later so the
# Opening Medal Roundup usually posts before live replies resume.
ROUNDUP_CRON_UTC_HOUR = 14
ROUNDUP_SILENCE_UNTIL_UTC = time(ROUNDUP_CRON_UTC_HOUR, 1)


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    return value


def challenge_day_index(week_start, today=None):
    """0-based day index within the challenge week (NY calendar dates)."""
    week_start = _as_date(week_start)
    if today is None:
        today = datetime.now(ROUNDUP_TZ).date()
    else:
        today = _as_date(today)
    return (today - week_start).days


def is_challenge_day_one(week_start, today=None):
    """True when today is the first calendar day of the challenge week."""
    return challenge_day_index(week_start, today) == 0


def is_opening_roundup_day(week_start, today=None):
    """True on challenge day 2 (the day the Opening Medal Roundup fires)."""
    return challenge_day_index(week_start, today) == 1


def should_suppress_medal_announcements(week_start, now=None):
    """
    Suppress live medal replies on challenge day 1, and on challenge day 2
    before 14:01 UTC (one minute after the Opening Medal Roundup cron at 14:00 UTC).
    Day index uses America/New_York calendar dates; the cutoff uses UTC to match cron.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    now_utc = now.astimezone(timezone.utc)
    day = challenge_day_index(week_start, now.astimezone(ROUNDUP_TZ).date())
    if day == 0:
        return True
    if day == 1 and now_utc.time() < ROUNDUP_SILENCE_UNTIL_UTC:
        return True
    return False


def describe_medal(medal_name):
    fallback = medal_name.replace("_", " ").replace("  ", " ").title()
    return nice_medal_names.get(medal_name, fallback)


def format_medal_display(medal_name, medal_emoji):
    emoji = medal_emoji or ""
    return f"{emoji} __**{describe_medal(medal_name)}**__".strip()


def build_opening_medal_roundup_message(standings):
    """
    Build the Opening Medal Roundup Discord message.

    Returns None when there are no medals to report.
    Non-stealable medals use "earned"; stealable use "currently holds".
    Earned always comes before currently holds for a given user.
    """
    if not standings:
        return None

    by_user = {}
    user_order = []

    for row in standings:
        if row.medal_name in SILENT_MEDALS:
            continue
        discord_id = str(row.discord_id)
        if discord_id not in by_user:
            by_user[discord_id] = {"earned": [], "holds": []}
            user_order.append(discord_id)

        display = format_medal_display(row.medal_name, row.medal_emoji)
        if row.medal_name in NON_STEALABLE_MEDALS:
            by_user[discord_id]["earned"].append(display)
        else:
            by_user[discord_id]["holds"].append(display)

    lines = []
    for discord_id in user_order:
        earned = by_user[discord_id]["earned"]
        holds = by_user[discord_id]["holds"]
        parts = []
        if earned:
            parts.append(f"earned {format_natural_language_list(earned)}")
        if holds:
            parts.append(f"currently holds {format_natural_language_list(holds)}")
        if not parts:
            continue
        lines.append(f"- <@{discord_id}> {', and '.join(parts)}.")

    if not lines:
        return None

    return "## Opening Medal Roundup\n" + "\n".join(lines)
