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


def decide_auto_knockout(
    checkin_count,
    required_checkins,
    remaining_days,
    mulligan_available,
):
    if checkin_count + remaining_days >= required_checkins:
        return "none"
    if mulligan_available and checkin_count + remaining_days + 1 >= required_checkins:
        return "mulligan"
    return "knockout"


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


def format_day_list(days):
    days = list(days)
    if len(days) == 0:
        return ""
    if len(days) == 1:
        return days[0]
    if len(days) == 2:
        return f"{days[0]} and {days[1]}"
    return f"{', '.join(days[:-1])}, and {days[-1]}"


def latest_missed_elapsed_day(week_start, run_date, checked_in_days):
    checked_in_days = set(checked_in_days or [])
    days_elapsed = min(max((run_date - week_start).days, 0), 7)
    for day_offset in range(days_elapsed - 1, -1, -1):
        candidate = week_start + timedelta(days=day_offset)
        day_name = candidate.strftime("%A")
        if day_name not in checked_in_days:
            return day_name, candidate
    return None, None


def mulligan_time_for(challenger_tz, missing_date):
    return datetime.combine(missing_date, time(hour=12), tzinfo=ZoneInfo(challenger_tz))


def get_challenge_weeks_for_run(cur, run_date):
    cur.execute(
        """
        with run_context as (
            select %s::date as run_date
        ),
        selected_weeks as (
            select
                c.id as challenge_id,
                cw.id as challenge_week_id,
                cw.start,
                cw."end",
                coalesce(cw.green, false) as green,
                cw.bye_week,
                1 as sort_order
            from challenge_weeks cw
            join challenges c on c.id = cw.challenge_id
            cross join run_context rc
            where
                rc.run_date between cw.start and cw."end"
                and rc.run_date between c.start and c."end"

            union all

            select
                c.id as challenge_id,
                cw.id as challenge_week_id,
                cw.start,
                cw."end",
                coalesce(cw.green, false) as green,
                cw.bye_week,
                0 as sort_order
            from challenge_weeks cw
            join challenges c on c.id = cw.challenge_id
            cross join run_context rc
            where
                cw."end" < rc.run_date
                and coalesce(cw.bye_week, false) = false
                and cw.auto_knockout_reconciled_at is null
        )
        select
            challenge_id,
            challenge_week_id,
            start,
            "end",
            green,
            bye_week
        from selected_weeks
        order by sort_order, start;
        """,
        (run_date,),
    )
    return cur.fetchall()


def get_participants_for_week(cur, challenge_id, challenge_week_id, run_day):
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


def insert_mulligan(cur, participant, challenge_week, run_date):
    day_name, missing_date = latest_missed_elapsed_day(
        challenge_week.start,
        run_date,
        participant.checked_in_days,
    )
    if day_name is None:
        logging.error(
            "Cannot apply mulligan for %s in challenge week %s: "
            "check-in count indicates a shortfall but no elapsed day is missing",
            participant.name,
            challenge_week.challenge_week_id,
        )
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


def mark_challenge_week_reconciled(cur, challenge_week_id):
    cur.execute(
        """
        update challenge_weeks
        set auto_knockout_reconciled_at = current_timestamp
        where
            id = %s
            and auto_knockout_reconciled_at is null;
        """,
        (challenge_week_id,),
    )


def evaluate_auto_knockout_for_week(
    cur,
    challenge_week,
    run_date,
    participants,
):
    required_checkins = required_checkins_for_week(challenge_week.green)
    remaining_days = remaining_week_days(run_date, challenge_week.end)
    run_day = (
        run_date.strftime("%A")
        if challenge_week.start <= run_date <= challenge_week.end
        else None
    )
    events = []

    for participant in participants:
        checkin_count = participant.checkin_count or 0
        effective_remaining_days = effective_remaining_week_days(
            remaining_days,
            run_day,
            participant.current_day_checked_in,
        )
        decision = decide_auto_knockout(
            checkin_count,
            required_checkins,
            len(effective_remaining_days),
            participant.mulligan is None,
        )

        if decision == "none":
            has_no_slack = (
                checkin_count + len(effective_remaining_days) == required_checkins
            )
            if (
                has_no_slack
                and effective_remaining_days
                and should_send_first_no_slack_warning(
                    challenge_week,
                    run_date,
                    required_checkins,
                    participant.checked_in_days,
                )
            ):
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
            continue

        if decision == "mulligan":
            mulligan_id, mulligan_day = insert_mulligan(
                cur,
                participant,
                challenge_week,
                run_date,
            )
            if mulligan_id is None:
                raise RuntimeError(
                    "Failed to apply mulligan for "
                    f"{participant.name} in challenge week "
                    f"{challenge_week.challenge_week_id}"
                )
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
            if effective_remaining_days:
                events.append(
                    AutoKnockoutEvent(
                        action="warning",
                        challenge_id=challenge_week.challenge_id,
                        challenger_id=participant.id,
                        name=participant.name,
                        required_checkins=required_checkins,
                        checkin_count=checkin_count + 1,
                        challenge_week_id=challenge_week.challenge_week_id,
                        discord_id=participant.discord_id,
                        mulligan_checkin_id=mulligan_id,
                        mulligan_day=mulligan_day,
                        remaining_checkin_days=effective_remaining_days,
                        has_mulligan_available=False,
                    )
                )
            continue

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


def build_auto_knockout_alert_message(events):
    warnings = [
        event
        for event in events
        if event.action == "warning" and event.mulligan_checkin_id is None
    ]
    if len(warnings) == 0:
        return None

    lines = []
    for event in warnings:
        days = format_day_list(event.remaining_checkin_days)
        consequence = (
            "to avoid using a mulligan or being knocked out"
            if event.has_mulligan_available
            else "to avoid knockout"
        )
        lines.append(
            f"<@{event.discord_id}> must check in on {days} {consequence}."
        )

    return "## Knockout warnings\n" + "\n".join(lines)


def build_auto_knockout_reconciliation_message(events):
    mulligans = [event for event in events if event.action == "mulligan"]
    knockouts = [event for event in events if event.action == "knockout"]
    warnings_by_mulligan = {
        (event.challenger_id, event.mulligan_checkin_id): event
        for event in events
        if event.action == "warning" and event.mulligan_checkin_id is not None
    }
    sections = []

    if mulligans:
        lines = []
        for event in mulligans:
            line = (
                f"<@{event.discord_id}> was saved from knockout by their mulligan "
                f"on {event.mulligan_day}."
            )
            warning = warnings_by_mulligan.get(
                (event.challenger_id, event.mulligan_checkin_id)
            )
            if warning is not None:
                line += (
                    f" They must check in on "
                    f"{format_day_list(warning.remaining_checkin_days)} "
                    f"to avoid knockout."
                )
            lines.append(line)
        sections.append("## Mulligans used\n" + "\n".join(lines))

    if knockouts:
        lines = [
            f"<@{event.discord_id}> has been knocked out with "
            f"{event.checkin_count}/{event.required_checkins} T1+ check-ins this week."
            for event in knockouts
        ]
        sections.append("## Knockouts\n" + "\n".join(lines))

    if len(sections) == 0:
        return None

    return "\n\n".join(sections)


def run_auto_knockout():
    from helpers import with_psycopg

    def fn(conn, cur):
        run_date = datetime.now(tz=ZoneInfo("America/New_York")).date()
        challenge_weeks = get_challenge_weeks_for_run(cur, run_date)
        if len(challenge_weeks) == 0:
            logging.info("Auto-knockout skipped: no challenge weeks to evaluate")
            return []

        events = []
        for challenge_week in challenge_weeks:
            if challenge_week.bye_week:
                logging.info(
                    "Auto-knockout skipped: challenge week %s is a bye week",
                    challenge_week.challenge_week_id,
                )
                continue

            run_day = (
                run_date.strftime("%A")
                if challenge_week.start <= run_date <= challenge_week.end
                else None
            )
            participants = get_participants_for_week(
                cur,
                challenge_week.challenge_id,
                challenge_week.challenge_week_id,
                run_day,
            )
            week_events = evaluate_auto_knockout_for_week(
                cur,
                challenge_week,
                run_date,
                participants,
            )
            events.extend(week_events)
            if run_date > challenge_week.end:
                mark_challenge_week_reconciled(
                    cur,
                    challenge_week.challenge_week_id,
                )
        return events

    return with_psycopg(fn)
