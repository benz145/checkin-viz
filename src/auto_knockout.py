from dataclasses import dataclass
from datetime import datetime, time, timedelta
import logging
from zoneinfo import ZoneInfo


WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


@dataclass(frozen=True)
class AutoKnockoutEvent:
    action: str
    challenge_id: int
    challenger_id: int
    name: str
    required_checkins: int
    checkin_count: int
    challenge_week_id: int
    discord_id: str | None = None
    mulligan_checkin_id: int | None = None
    mulligan_day: str | None = None
    remaining_checkin_days: tuple[str, ...] = ()
    has_mulligan_available: bool = False


def required_checkins_for_week(is_green_week):
    return 5 if is_green_week else 2


def remaining_week_days(run_date, week_end):
    days_remaining = min(max((week_end - run_date).days + 1, 0), 7)
    return tuple(
        (run_date + timedelta(days=day_offset)).strftime("%A")
        for day_offset in range(days_remaining)
    )


def effective_remaining_week_days(remaining_checkin_days, run_day, current_day_checked_in):
    return tuple(
        day
        for day in remaining_checkin_days
        if not (current_day_checked_in and day == run_day)
    )


def should_send_first_no_slack_warning(challenge_week, run_date, required_checkins, checked_in_days):
    allowed_missed_days = 7 - required_checkins
    checked_in_days = set(checked_in_days or [])
    prior_days = []
    days_elapsed = min(max((run_date - challenge_week.start).days, 0), 7)

    for day_offset in range(days_elapsed):
        prior_days.append((challenge_week.start + timedelta(days=day_offset)).strftime("%A"))

    missed_prior_days = [day for day in prior_days if day not in checked_in_days]
    if len(missed_prior_days) != allowed_missed_days:
        return False

    return len(missed_prior_days) > 0 and missed_prior_days[-1] == prior_days[-1]


def mulligan_used_on_latest_elapsed_day(challenge_week, run_date, participant):
    """
    True when a this-week mulligan should trigger a consequence-update warning.

    The mulligan check-in may sit on an earlier missed day (first_missed_day),
    so we treat the latest elapsed day as uncovered by a *real* check-in when
    it is absent from checked_in_days excluding the mulligan day itself.
    """
    if (
        participant.mulligan is None
        or getattr(participant, "mulligan_challenge_week_id", None)
        != challenge_week.challenge_week_id
    ):
        return False

    days_elapsed = min(max((run_date - challenge_week.start).days, 0), 7)
    if days_elapsed == 0:
        return False

    latest_elapsed_day = (
        challenge_week.start + timedelta(days=days_elapsed - 1)
    ).strftime("%A")
    mulligan_day = getattr(participant, "mulligan_day", None)
    real_checked_in_days = set(participant.checked_in_days or []) - {mulligan_day}
    return latest_elapsed_day not in real_checked_in_days


def format_natural_language_list(items):
    items = list(items)
    if len(items) == 0:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def format_day_list(days):
    return format_natural_language_list(days)


def first_missed_day(week_start, checked_in_days):
    checked_in_days = set(checked_in_days or [])
    for day_offset in range(7):
        candidate = week_start + timedelta(days=day_offset)
        day_name = candidate.strftime("%A")
        if day_name not in checked_in_days:
            return day_name, candidate
    return None, None


def mulligan_time_for(challenger_tz, missing_date):
    return datetime.combine(missing_date, time(hour=12), tzinfo=ZoneInfo(challenger_tz))


def get_previous_challenge_week(cur):
    cur.execute(
        """
        select
            c.id as challenge_id,
            cw.id as challenge_week_id,
            cw.start,
            cw."end",
            cw.green,
            cw.bye_week
        from challenge_weeks cw
        join challenges c on c.id = cw.challenge_id
        where cw."end" = (
            (current_timestamp at time zone 'America/New_York')::date - interval '1 day'
        )::date
        order by cw."end" desc
        limit 1;
        """
    )
    return cur.fetchone()


def get_current_challenge_week(cur):
    cur.execute(
        """
        select
            c.id as challenge_id,
            cw.id as challenge_week_id,
            cw.start,
            cw."end",
            coalesce(cw.green, false) as green,
            cw.bye_week
        from challenge_weeks cw
        join challenges c on c.id = cw.challenge_id
        where
            (current_timestamp at time zone 'America/New_York')::date >= cw.start
            and (current_timestamp at time zone 'America/New_York')::date <= cw."end"
            and (current_timestamp at time zone 'America/New_York')::date >= c.start
            and (current_timestamp at time zone 'America/New_York')::date <= c."end"
        order by cw.start desc
        limit 1;
        """
    )
    return cur.fetchone()


def get_participants_for_week(cur, challenge_id, challenge_week_id, run_day):
    cur.execute(
        """
        select
            ch.id,
            ch.name,
            ch.discord_id,
            ch.tz,
            cc.mulligan,
            count(distinct c.day_of_week) filter (
                where c.tier != 'T0'
            ) as checkin_count,
            array_remove(
                array_agg(distinct c.day_of_week) filter (
                    where c.tier != 'T0'
                ),
                null
            ) as checked_in_days,
            coalesce(
                bool_or(c.tier != 'T0' and c.day_of_week = %s),
                false
            ) as current_day_checked_in
        from challenger_challenges cc
        join challengers ch on ch.id = cc.challenger_id
        left join checkins c on
            c.challenger = ch.id
            and c.challenge_week_id = %s
        where
            cc.challenge_id = %s
            and cc.knocked_out = false
            and coalesce(cc.tier, '') != 'T0'
        group by
            ch.id,
            ch.name,
            ch.discord_id,
            ch.tz,
            cc.mulligan
        order by ch.name;
        """,
        (run_day, challenge_week_id, challenge_id),
    )
    return cur.fetchall()


def get_alert_participants_for_week(cur, challenge_id, challenge_week_id, run_day):
    cur.execute(
        """
        select
            ch.id,
            ch.name,
            ch.discord_id,
            ch.tz,
            cc.mulligan,
            mulligan_checkin.challenge_week_id as mulligan_challenge_week_id,
            mulligan_checkin.day_of_week as mulligan_day,
            count(distinct c.day_of_week) filter (
                where c.tier != 'T0'
            ) as checkin_count,
            array_remove(
                array_agg(distinct c.day_of_week) filter (
                    where c.tier != 'T0'
                ),
                null
            ) as checked_in_days,
            coalesce(
                bool_or(c.tier != 'T0' and c.day_of_week = %s),
                false
            ) as current_day_checked_in
        from challenger_challenges cc
        join challengers ch on ch.id = cc.challenger_id
        left join checkins mulligan_checkin on mulligan_checkin.id = cc.mulligan
        left join checkins c on
            c.challenger = ch.id
            and c.challenge_week_id = %s
        where
            cc.challenge_id = %s
            and cc.knocked_out = false
            and coalesce(cc.tier, '') != 'T0'
        group by
            ch.id,
            ch.name,
            ch.discord_id,
            ch.tz,
            cc.mulligan,
            mulligan_checkin.challenge_week_id,
            mulligan_checkin.day_of_week
        order by ch.name;
        """,
        (run_day, challenge_week_id, challenge_id),
    )
    return cur.fetchall()


def insert_mulligan(cur, participant, challenge_week):
    day_name, missing_date = first_missed_day(
        challenge_week.start,
        participant.checked_in_days,
    )
    if day_name is None:
        logging.warning("No missing mulligan day found for %s", participant.name)
        return None, None

    mulligan_time = mulligan_time_for(participant.tz, missing_date)
    cur.execute(
        """
        insert into checkins
            (name, time, tier, day_of_week, text, challenge_week_id, challenger, tz)
        values
            (%s, %s, 'T1', %s, 'MULLIGAN T1 checkin', %s, %s, %s)
        returning id;
        """,
        (
            participant.name,
            mulligan_time,
            day_name,
            challenge_week.challenge_week_id,
            participant.id,
            participant.tz,
        ),
    )
    mulligan_id = cur.fetchone().id
    cur.execute(
        """
        update challenger_challenges
        set mulligan = %s
        where challenger_id = %s and challenge_id = %s;
        """,
        (mulligan_id, participant.id, challenge_week.challenge_id),
    )
    return mulligan_id, day_name


def knock_out_challenger(cur, participant, challenge_week):
    cur.execute(
        """
        update challenger_challenges
        set knocked_out = true
        where challenger_id = %s and challenge_id = %s;
        """,
        (participant.id, challenge_week.challenge_id),
    )


def apply_auto_knockout_for_week(cur, challenge_week, participants, run_date):
    required_checkins = required_checkins_for_week(challenge_week.green)
    remaining_days = remaining_week_days(run_date, challenge_week.end)
    run_day = run_date.strftime("%A")
    events = []

    for participant in participants:
        checkin_count = participant.checkin_count or 0
        needed_checkins = required_checkins - checkin_count
        effective_remaining_days = effective_remaining_week_days(
            remaining_days,
            run_day,
            participant.current_day_checked_in,
        )

        # Still mathematically able to meet the requirement by checking in
        # every remaining day: no action.
        if needed_checkins <= len(effective_remaining_days):
            continue

        # A mulligan is worth exactly one check-in, so it only helps if it
        # brings the week back within reach.
        mulligan_can_save = needed_checkins - 1 <= len(effective_remaining_days)

        if participant.mulligan is None and mulligan_can_save:
            mulligan_id, mulligan_day = insert_mulligan(cur, participant, challenge_week)
            events.append(
                AutoKnockoutEvent(
                    action="mulligan",
                    challenge_id=challenge_week.challenge_id,
                    challenger_id=participant.id,
                    name=participant.name,
                    required_checkins=required_checkins,
                    checkin_count=checkin_count,
                    challenge_week_id=challenge_week.challenge_week_id,
                    discord_id=participant.discord_id,
                    mulligan_checkin_id=mulligan_id,
                    mulligan_day=mulligan_day,
                )
            )
        else:
            knock_out_challenger(cur, participant, challenge_week)
            events.append(
                AutoKnockoutEvent(
                    action="knockout",
                    challenge_id=challenge_week.challenge_id,
                    challenger_id=participant.id,
                    name=participant.name,
                    required_checkins=required_checkins,
                    checkin_count=checkin_count,
                    challenge_week_id=challenge_week.challenge_week_id,
                    discord_id=participant.discord_id,
                )
            )

    return events


def build_auto_knockout_alerts_for_week(challenge_week, run_date, participants):
    if challenge_week.bye_week:
        return []

    required_checkins = required_checkins_for_week(challenge_week.green)
    remaining_days = remaining_week_days(run_date, challenge_week.end)
    run_day = run_date.strftime("%A")
    events = []

    for participant in participants:
        checkin_count = participant.checkin_count or 0
        if checkin_count >= required_checkins:
            continue

        effective_remaining_days = effective_remaining_week_days(
            remaining_days,
            run_day,
            participant.current_day_checked_in,
        )
        if len(effective_remaining_days) == 0:
            continue

        # Exactly-doomed-unless-perfect is warning territory; anything worse
        # (needed > remaining) is handled by the knockout path instead.
        needed_checkins = required_checkins - checkin_count
        if needed_checkins != len(effective_remaining_days):
            continue

        is_first_no_slack_warning = should_send_first_no_slack_warning(
            challenge_week,
            run_date,
            required_checkins,
            participant.checked_in_days,
        )
        consequence_changed_after_mulligan = mulligan_used_on_latest_elapsed_day(
            challenge_week,
            run_date,
            participant,
        )
        if not is_first_no_slack_warning and not consequence_changed_after_mulligan:
            continue

        events.append(
            AutoKnockoutEvent(
                action="warning",
                challenge_id=challenge_week.challenge_id,
                challenger_id=participant.id,
                name=participant.name,
                required_checkins=required_checkins,
                checkin_count=checkin_count,
                challenge_week_id=challenge_week.challenge_week_id,
                discord_id=participant.discord_id,
                remaining_checkin_days=effective_remaining_days,
                has_mulligan_available=participant.mulligan is None,
            )
        )

    return events


def build_auto_knockout_alert_message(events):
    warnings = [event for event in events if event.action == "warning"]
    if len(warnings) == 0:
        return None

    groups = {}
    for event in warnings:
        key = (event.remaining_checkin_days, event.has_mulligan_available)
        groups.setdefault(key, []).append(event)

    # Knockout-risk warnings (no mulligan left) before mulligan-use warnings.
    ordered_groups = sorted(
        groups.items(),
        key=lambda item: (item[0][1], item[0][0]),
    )

    lines = []
    for (remaining_checkin_days, has_mulligan_available), group in ordered_groups:
        mentions = format_natural_language_list(
            f"<@{event.discord_id}>" for event in group
        )
        days = format_day_list(remaining_checkin_days)
        emoji = "⚠️" if has_mulligan_available else "🚨"
        consequence = (
            "to avoid using a mulligan"
            if has_mulligan_available
            else "to avoid being knocked out"
        )
        lines.append(f"- {emoji} {mentions} must check in on {days} {consequence}.")

    return "## Warnings\n" + "\n".join(lines)


def build_auto_knockout_reconciliation_message(events):
    mulligans = [event for event in events if event.action == "mulligan"]
    knockouts = [event for event in events if event.action == "knockout"]
    sections = []

    if knockouts:
        lines = [
            f"- <@{event.discord_id}> has been knocked out with "
            f"{event.checkin_count}/{event.required_checkins} T1+ check-ins this week."
            for event in knockouts
        ]
        sections.append("## Knockouts\n" + "\n".join(lines))

    if mulligans:
        lines = [
            f"- <@{event.discord_id}> was saved from knockout by their mulligan "
            f"on {event.mulligan_day}."
            for event in mulligans
        ]
        sections.append("## Saved\n" + "\n".join(lines))

    if len(sections) == 0:
        return None

    return "\n".join(sections)


def build_auto_knockout_daily_message(action_events, warning_events):
    sections = []

    reconciliation_message = build_auto_knockout_reconciliation_message(action_events)
    if reconciliation_message is not None:
        sections.append(reconciliation_message)

    alert_message = build_auto_knockout_alert_message(warning_events)
    if alert_message is not None:
        sections.append(alert_message)

    if len(sections) == 0:
        return None

    return "\n".join(sections)


def run_auto_knockout():
    from helpers import with_psycopg

    def fn(conn, cur):
        run_date = datetime.now(tz=ZoneInfo("America/New_York")).date()
        events = []

        # The week that ended yesterday (if any) catches final-day failures
        # that were never mathematically doomed mid-week; the current week
        # catches challengers who can no longer meet the requirement.
        weeks = [
            ("previous", get_previous_challenge_week(cur)),
            ("current", get_current_challenge_week(cur)),
        ]

        for label, challenge_week in weeks:
            if challenge_week is None:
                logging.info("Auto-knockout skipped: no %s challenge week", label)
                continue

            if challenge_week.bye_week:
                logging.info(
                    "Auto-knockout skipped: challenge week %s is a bye week",
                    challenge_week.challenge_week_id,
                )
                continue

            participants = get_participants_for_week(
                cur,
                challenge_week.challenge_id,
                challenge_week.challenge_week_id,
                run_date.strftime("%A"),
            )
            events.extend(
                apply_auto_knockout_for_week(cur, challenge_week, participants, run_date)
            )

        return events

    return with_psycopg(fn)


def run_auto_knockout_alerts():
    from helpers import with_psycopg

    def fn(conn, cur):
        challenge_week = get_current_challenge_week(cur)
        if challenge_week is None:
            logging.info("Auto-knockout alerts skipped: no current challenge week")
            return []

        if challenge_week.bye_week:
            logging.info(
                "Auto-knockout alerts skipped: challenge week %s is a bye week",
                challenge_week.challenge_week_id,
            )
            return []

        run_date = datetime.now(tz=ZoneInfo("America/New_York")).date()
        participants = get_alert_participants_for_week(
            cur,
            challenge_week.challenge_id,
            challenge_week.challenge_week_id,
            run_date.strftime("%A"),
        )
        return build_auto_knockout_alerts_for_week(
            challenge_week,
            run_date,
            participants,
        )

    return with_psycopg(fn)
