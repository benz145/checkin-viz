"""Private view of current medal holders and the participant's personal best."""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from base_queries import challenger_by_discord_id, get_current_challenge_week
from medal_constants import NON_STEALABLE_MEDALS, SILENT_MEDALS
from medal_roundup import describe_medal
import medals
from personal_records import get_period_personal_records


def build_medal_case(held_medals, record, active_week=True, viewer_discord_id=None, period_records=()):
    held_medals = [row for row in held_medals if row.medal_name not in SILENT_MEDALS]
    lines = ["## Medal Case", "", "**Currently Held**"]
    if not active_week:
        lines.append("There is no active challenge week right now.")
    elif held_medals:
        for medal in sorted(held_medals, key=lambda row: (
            str(row.discord_id) != str(viewer_discord_id), describe_medal(row.medal_name)
        )):
            owner = f"<@{medal.discord_id}>" if medal.discord_id else medal.challenger_name
            if medal.medal_name.startswith("highest_tier_"):
                condition = medal.checkin_tier
            else:
                # Time medals compare the check-in's original local clock time.
                condition = medal.checkin_time.strftime("%I:%M%p").lstrip("0") if medal.checkin_time else None
            detail = f" ({condition})" if condition else ""
            lines.append(f"- {medal.medal_emoji or ''} **{describe_medal(medal.medal_name)}**")
            lines.append(f"  - {owner}{detail}")
    else:
        lines.append("No stealable medals are currently held.")

    lines.extend(["", "**Personal Tier Records**"])
    periods = {period.scope: period for period in period_records}
    for title, best in (
        ("Highest Ever", record),
        ("Highest This Year", periods.get("year")),
        ("Highest This Challenge Season", periods.get("season")),
    ):
        lines.append(f"- {title}")
        if best is None or best.tier is None:
            if title == "Highest This Challenge Season" and best is None:
                lines.append("  - No challenge season available.")
            else:
                lines.append("  - No personal tier record yet.")
        else:
            day = best.record_date
            lines.append(f"  - {best.tier} ({day:%B} {day.day}, {day:%Y})")
    return "\n".join(lines)


async def send_medal_case(ctx):
    await ctx.defer(ephemeral=True)
    try:
        challenger = challenger_by_discord_id(str(ctx.author.id))
        if challenger is None:
            await ctx.followup.send(
                "You aren't registered as a challenger yet, so you don't have a medal case.",
                ephemeral=True,
            )
            return

        week = get_current_challenge_week(challenger.tz)
        held = []
        if week is not None:
            # Rank awards across all participants so stolen medals show only
            # their current owner, including holders from earlier weeks.
            standings = medals.get_current_week_medal_standings(week.challenge_id, week.id)
            held = [
                row for row in standings
                if row.medal_name not in NON_STEALABLE_MEDALS
            ]
        record = medals.get_personal_tier_record(challenger.id)
        period_records = get_period_personal_records(
            challenger.id, week.challenge_id if week else None,
            datetime.now(ZoneInfo(challenger.tz or "America/New_York")).year,
        )
        await ctx.followup.send(
            build_medal_case(held, record, active_week=week is not None,
                             viewer_discord_id=ctx.author.id, period_records=period_records),
            ephemeral=True,
        )
    except Exception:
        logging.exception("Failed to load medal case")
        await ctx.followup.send(
            "I couldn't load your medal case. Please try /medal-case again in a moment.",
            ephemeral=True,
        )
