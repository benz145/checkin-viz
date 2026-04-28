from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import logging


AUTO_KNOCKOUT_RUNS_TABLE = """
create table if not exists auto_knockout_runs (
    id serial primary key,
    challenge_id integer not null,
    challenge_week_id integer not null,
    run_date date not null,
    created_at timestamptz not null default current_timestamp,
    unique (challenge_id, challenge_week_id, run_date)
);
"""

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
class AutoKnockoutDecision:
    action: str
    required_checkins: int
    checkin_count: int
    remaining_possible_days: int


@dataclass(frozen=True)
class AutoKnockoutEvent:
    action: str
    challenge_id: int
    challenger_id: int
    name: str
    discord_id: str
    required_checkins: int
    checkin_count: int
    challenge_week_id: int
    mulligan_checkin_id: int | None = None
    mulligan_day: str | None = None
    remaining_checkin_days: tuple[str, ...] = ()


def required_checkins_for_week(is_green_week):
    return 5 if is_green_week else 2


def remaining_possible_days(run_date, week_end):
    return len(remaining_week_days(run_date, week_end))


def remaining_week_days(run_date, week_end):
    days_remaining = min(max((week_end - run_date).days + 1, 0), 7)
    return tuple(
        (run_date + timedelta(days=day_offset)).strftime("%A")
        for day_offset in range(days_remaining)
    )


def elapsed_week_days(week_start, run_date):
    days_elapsed = min(max((run_date - week_start).days, 0), 7)
    return [
        (week_start + timedelta(days=day_offset)).strftime("%A")
        for day_offset in range(days_elapsed)
    ]


def run_day_for_week(run_date, challenge_week):
    if challenge_week.start <= run_date <= challenge_week.end:
        return run_date.strftime("%A")
    return None


def effective_checkin_count(elapsed_checkin_count, current_day_checked_in):
    return elapsed_checkin_count + int(current_day_checked_in)


def effective_remaining_week_days(remaining_checkin_days, run_day, current_day_checked_in):
    return tuple(
        day
        for day in remaining_checkin_days
        if not (current_day_checked_in and day == run_day)
    )


def decide_auto_knockout(
    checkin_count,
    required_checkins,
    remaining_days,
    has_mulligan,
):
    if checkin_count + remaining_days >= required_checkins:
        action = "none"
    elif checkin_count + remaining_days + int(has_mulligan) >= required_checkins:
        action = "mulligan"
    else:
        action = "knockout"

    return AutoKnockoutDecision(
        action=action,
        required_checkins=required_checkins,
        checkin_count=checkin_count,
        remaining_possible_days=remaining_days,
    )


def missing_mulligan_day(week_start, run_date, checked_in_days):
    checked_in_days = set(checked_in_days)
    days_elapsed = min(max((run_date - week_start).days, 0), 7)
    for day_offset in range(days_elapsed - 1, -1, -1):
        candidate = week_start + timedelta(days=day_offset)
        day_name = candidate.strftime("%A")
        if day_name not in checked_in_days:
            return day_name, candidate
    return None, None


def mulligan_time_for(challenger_tz, missing_date):
    import pytz

    tz = pytz.timezone(challenger_tz)
    return tz.localize(datetime.combine(missing_date, time(hour=12)))


def get_current_challenge_context(cur):
    contexts = get_challenge_contexts(cur)
    return contexts[0] if contexts else None


def get_challenge_contexts(cur):
    cur.execute(
        """
        with run_context as (
            select (current_timestamp at time zone 'America/New_York')::date as run_date
        ),
        selected_weeks as (
            select
                c.id as challenge_id,
                c.name as challenge_name,
                cw.id as challenge_week_id,
                cw.start,
                cw."end",
                cw.green,
                cw.bye_week,
                1 as sort_order
            from challenges c
            join challenge_weeks cw on cw.challenge_id = c.id
            cross join run_context rc
            where
                rc.run_date >= c.start
                and rc.run_date <= c."end"
                and rc.run_date >= cw.start
                and rc.run_date <= cw."end"

            union

            select
                c.id as challenge_id,
                c.name as challenge_name,
                cw.id as challenge_week_id,
                cw.start,
                cw."end",
                cw.green,
                cw.bye_week,
                0 as sort_order
            from challenges c
            join challenge_weeks cw on cw.challenge_id = c.id
            cross join run_context rc
            where
                extract(isodow from rc.run_date) = 1
                and rc.run_date - interval '1 day' >= c.start
                and rc.run_date - interval '1 day' <= c."end"
                and rc.run_date - interval '1 day' >= cw.start
                and rc.run_date - interval '1 day' <= cw."end"
        )
        select
            c.challenge_id,
            c.challenge_name,
            c.challenge_week_id,
            c.start,
            c."end",
            c.green,
            c.bye_week
        from selected_weeks c
        order by c.sort_order, c.start;
        """
    )
    return cur.fetchall()


def get_run_date(cur):
    cur.execute("select (current_timestamp at time zone 'America/New_York')::date")
    return cur.fetchone()[0]


def claim_daily_run(cur, challenge_id, challenge_week_id, run_date):
    cur.execute(AUTO_KNOCKOUT_RUNS_TABLE)
    cur.execute(
        """
        insert into auto_knockout_runs (challenge_id, challenge_week_id, run_date)
        values (%s, %s, %s)
        on conflict (challenge_id, challenge_week_id, run_date) do nothing
        returning id;
        """,
        (challenge_id, challenge_week_id, run_date),
    )
    return cur.fetchone() is not None


def get_participants_for_week(cur, challenge_id, challenge_week_id, elapsed_days, run_day):
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
                and c.day_of_week = any(%s::text[])
            ) as elapsed_checkin_count,
            array_remove(
                array_agg(distinct c.day_of_week) filter (
                    where c.tier != 'T0'
                    and c.day_of_week = any(%s::text[])
                ),
                null
            ) as elapsed_checked_in_days,
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
            and cc.tier != 'T0'
        group by ch.id, ch.name, ch.discord_id, ch.tz, cc.mulligan
        order by ch.name;
        """,
        (elapsed_days, elapsed_days, run_day, challenge_week_id, challenge_id),
    )
    return cur.fetchall()


def insert_mulligan(cur, participant, challenge_week, run_date, checked_in_days):
    day_name, missing_date = missing_mulligan_day(
        challenge_week.start,
        run_date,
        checked_in_days,
    )
    if missing_date is None:
        logging.warning("No missing mulligan day found for %s", participant.name)
        return None

    mulligan_time = mulligan_time_for(participant.tz, missing_date)
    cur.execute(
        """
        insert into checkins (
            name,
            time,
            tier,
            day_of_week,
            text,
            challenge_week_id,
            challenger,
            tz
        )
        values (%s, %s, 'T1', %s, 'MULLIGAN T1 checkin', %s, %s, %s)
        on conflict do nothing
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
    row = cur.fetchone()
    if row is None:
        logging.warning("Mulligan check-in insert returned no id for %s", participant.name)
        return None

    mulligan_id = row.id
    cur.execute(
        """
        update challenger_challenges
        set mulligan = %s
        where challenger_id = %s
        and challenge_id = %s;
        """,
        (mulligan_id, participant.id, challenge_week.challenge_id),
    )
    return mulligan_id, day_name


def knock_out(cur, participant, challenge_id):
    cur.execute(
        """
        update challenger_challenges
        set knocked_out = true
        where challenger_id = %s
        and challenge_id = %s;
        """,
        (participant.id, challenge_id),
    )


def evaluate_auto_knockout_participants(
    challenge_week,
    run_date,
    participants,
    is_green_week,
    dry_run=False,
    insert_mulligan_fn=None,
    knock_out_fn=None,
):
    required_checkins = required_checkins_for_week(is_green_week)
    remaining_checkin_days = remaining_week_days(run_date, challenge_week.end)
    run_day = run_date.strftime("%A")
    events = []

    for participant in participants:
        elapsed_checkin_count = participant.elapsed_checkin_count or 0
        checked_in_days = participant.elapsed_checked_in_days or []
        current_day_checked_in = participant.current_day_checked_in
        checkin_count = effective_checkin_count(
            elapsed_checkin_count,
            current_day_checked_in,
        )
        effective_remaining_checkin_days = tuple(
            effective_remaining_week_days(
                remaining_checkin_days,
                run_day,
                current_day_checked_in,
            )
        )
        effective_remaining_days = len(effective_remaining_checkin_days)
        decision = decide_auto_knockout(
            checkin_count,
            required_checkins,
            effective_remaining_days,
            participant.mulligan is None,
        )

        if decision.action == "none":
            has_no_mulligan = participant.mulligan is not None
            has_no_slack = checkin_count + effective_remaining_days == required_checkins
            if has_no_mulligan and has_no_slack and effective_remaining_checkin_days:
                events.append(
                    AutoKnockoutEvent(
                        action="warning",
                        challenge_id=challenge_week.challenge_id,
                        challenger_id=participant.id,
                        name=participant.name,
                        discord_id=participant.discord_id,
                        required_checkins=required_checkins,
                        checkin_count=checkin_count,
                        challenge_week_id=challenge_week.challenge_week_id,
                        remaining_checkin_days=effective_remaining_checkin_days,
                    )
                )
            continue

        if decision.action == "mulligan":
            mulligan_id = None
            mulligan_day = None
            if dry_run:
                mulligan_day, _ = missing_mulligan_day(
                    challenge_week.start,
                    run_date,
                    checked_in_days,
                )
            else:
                mulligan = insert_mulligan_fn(participant, checked_in_days)
                if mulligan is None:
                    logging.warning(
                        "Auto-knockout could not apply mulligan for %s",
                        participant.name,
                    )
                    continue
                mulligan_id, mulligan_day = mulligan

            events.append(
                AutoKnockoutEvent(
                    action="mulligan",
                    challenge_id=challenge_week.challenge_id,
                    challenger_id=participant.id,
                    name=participant.name,
                    discord_id=participant.discord_id,
                    required_checkins=required_checkins,
                    checkin_count=checkin_count,
                    challenge_week_id=challenge_week.challenge_week_id,
                    mulligan_checkin_id=mulligan_id,
                    mulligan_day=mulligan_day,
                )
            )
            if effective_remaining_checkin_days:
                events.append(
                    AutoKnockoutEvent(
                        action="warning",
                        challenge_id=challenge_week.challenge_id,
                        challenger_id=participant.id,
                        name=participant.name,
                        discord_id=participant.discord_id,
                        required_checkins=required_checkins,
                        checkin_count=checkin_count + 1,
                        challenge_week_id=challenge_week.challenge_week_id,
                        mulligan_checkin_id=mulligan_id,
                        mulligan_day=mulligan_day,
                        remaining_checkin_days=effective_remaining_checkin_days,
                    )
                )
            continue

        if not dry_run:
            knock_out_fn(participant)

        events.append(
            AutoKnockoutEvent(
                action="knockout",
                challenge_id=challenge_week.challenge_id,
                challenger_id=participant.id,
                name=participant.name,
                discord_id=participant.discord_id,
                required_checkins=required_checkins,
                checkin_count=checkin_count,
                challenge_week_id=challenge_week.challenge_week_id,
            )
        )

    return events


def run_auto_knockout(dry_run=False):
    from green import determine_if_green_for_week
    from helpers import with_psycopg

    def run(conn, cur):
        challenge_weeks = get_challenge_contexts(cur)
        if len(challenge_weeks) == 0:
            logging.info("Auto-knockout skipped: no challenge weeks to evaluate")
            return []

        run_date = get_run_date(cur)
        events = []

        for challenge_week in challenge_weeks:
            if challenge_week.bye_week:
                logging.info(
                    "Auto-knockout skipped: challenge week %s is a bye week",
                    challenge_week.challenge_week_id,
                )
                continue

            if not dry_run and not claim_daily_run(
                cur,
                challenge_week.challenge_id,
                challenge_week.challenge_week_id,
                run_date,
            ):
                logging.info(
                    "Auto-knockout skipped: challenge week %s already ran today",
                    challenge_week.challenge_week_id,
                )
                continue

            if challenge_week.green is None and dry_run:
                logging.warning("Auto-knockout dry-run treating undecided green week as false")
                is_green_week = False
            elif challenge_week.green is None:
                is_green_week = determine_if_green_for_week(challenge_week)
            else:
                is_green_week = challenge_week.green

            run_day = run_day_for_week(run_date, challenge_week)
            elapsed_days = elapsed_week_days(challenge_week.start, run_date)
            participants = get_participants_for_week(
                cur,
                challenge_week.challenge_id,
                challenge_week.challenge_week_id,
                elapsed_days,
                run_day,
            )

            events.extend(
                evaluate_auto_knockout_participants(
                    challenge_week,
                    run_date,
                    participants,
                    is_green_week,
                    dry_run=dry_run,
                    insert_mulligan_fn=lambda participant, checked_in_days: insert_mulligan(
                        cur,
                        participant,
                        challenge_week,
                        run_date,
                        checked_in_days,
                    ),
                    knock_out_fn=lambda participant: knock_out(
                        cur,
                        participant,
                        challenge_week.challenge_id,
                    ),
                )
            )

        return events

    return with_psycopg(run)


def build_auto_knockout_message(events):
    if len(events) == 0:
        return None

    mulligans = [event for event in events if event.action == "mulligan"]
    warnings_by_mulligan = {
        (event.challenger_id, event.mulligan_checkin_id): event
        for event in events
        if event.action == "warning" and event.mulligan_day is not None
    }
    knockouts = [event for event in events if event.action == "knockout"]
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


def format_day_list(days):
    days = list(days)
    if len(days) == 0:
        return ""
    if len(days) == 1:
        return days[0]
    if len(days) == 2:
        return f"{days[0]} and {days[1]}"
    return f"{', '.join(days[:-1])}, and {days[-1]}"


def build_auto_knockout_warning_message(events):
    warnings = [
        event
        for event in events
        if event.action == "warning" and event.mulligan_day is None
    ]
    if len(warnings) == 0:
        return None

    lines = []
    for event in warnings:
        days = format_day_list(event.remaining_checkin_days)
        lines.append(
            f"<@{event.discord_id}> has no more mulligans and must check in on "
            f"{days} to avoid knockout."
        )

    return "## Knockout warnings\n" + "\n".join(lines)


def _assert_decision(checkins, required, remaining, has_mulligan, expected):
    actual = decide_auto_knockout(checkins, required, remaining, has_mulligan)
    assert actual.action == expected, (
        f"expected {expected} for checkins={checkins}, required={required}, "
        f"remaining={remaining}, has_mulligan={has_mulligan}; got {actual.action}"
    )


def _warning_event(
    remaining_checkin_days,
    mulligan_day=None,
    mulligan_checkin_id=None,
    checkin_count=0,
    required_checkins=2,
):
    return AutoKnockoutEvent(
        action="warning",
        challenge_id=1,
        challenger_id=1,
        name="Test",
        discord_id="123",
        required_checkins=required_checkins,
        checkin_count=checkin_count,
        challenge_week_id=1,
        mulligan_checkin_id=mulligan_checkin_id,
        mulligan_day=mulligan_day,
        remaining_checkin_days=tuple(remaining_checkin_days),
    )


def run_rule_checks():
    _assert_decision(1, 2, 0, True, "mulligan")
    _assert_decision(0, 2, 0, True, "knockout")
    _assert_decision(4, 5, 0, True, "mulligan")
    _assert_decision(3, 5, 0, True, "knockout")
    _assert_decision(1, 5, 4, True, "none")
    _assert_decision(1, 5, 3, True, "mulligan")
    _assert_decision(1, 5, 3, False, "knockout")

    assert required_checkins_for_week(True) == 5
    assert required_checkins_for_week(False) == 2
    assert remaining_possible_days(date(2026, 4, 27), date(2026, 5, 3)) == 7
    assert remaining_possible_days(date(2026, 5, 3), date(2026, 5, 3)) == 1
    assert effective_checkin_count(1, True) == 2
    assert effective_checkin_count(1, False) == 1
    assert effective_remaining_week_days(("Sunday",), "Sunday", True) == ()
    assert effective_remaining_week_days(("Sunday",), "Sunday", False) == ("Sunday",)
    assert elapsed_week_days(date(2026, 4, 27), date(2026, 4, 27)) == []
    assert elapsed_week_days(date(2026, 4, 27), date(2026, 5, 1)) == [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
    ]

    day_name, missing_date = missing_mulligan_day(
        date(2026, 4, 27),
        date(2026, 5, 1),
        ["Monday", "Wednesday", "Thursday"],
    )
    assert (day_name, missing_date) == ("Tuesday", date(2026, 4, 28))

    day_name, missing_date = missing_mulligan_day(
        date(2026, 4, 27),
        date(2026, 5, 1),
        ["Monday", "Tuesday", "Wednesday", "Thursday"],
    )
    assert (day_name, missing_date) == (None, None)

    # Friday is the current day here, so it is still an available check-in day.
    _assert_decision(
        2,
        5,
        remaining_possible_days(date(2026, 5, 1), date(2026, 5, 3)),
        True,
        "none",
    )

    saturday_run = date(2026, 5, 2)
    sunday_run = date(2026, 5, 3)
    thursday_run = date(2026, 4, 30)
    week_end = date(2026, 5, 3)

    # Normal week, no mulligan: after Friday, Saturday and Sunday are both required.
    normal_no_mulligan_remaining = remaining_week_days(saturday_run, week_end)
    _assert_decision(0, 2, len(normal_no_mulligan_remaining), False, "none")
    assert len(normal_no_mulligan_remaining) == 2
    no_mulligan_message = build_auto_knockout_warning_message(
        [_warning_event(normal_no_mulligan_remaining)]
    )
    assert (
        "<@123> has no more mulligans and must check in on Saturday and Sunday "
        "to avoid knockout."
    ) in no_mulligan_message

    # Normal week, with mulligan: after Saturday, the mulligan covers Saturday.
    normal_mulligan_remaining = remaining_week_days(sunday_run, week_end)
    _assert_decision(0, 2, len(normal_mulligan_remaining), True, "mulligan")
    day_name, missing_date = missing_mulligan_day(
        date(2026, 4, 27),
        sunday_run,
        [],
    )
    assert (day_name, missing_date) == ("Saturday", date(2026, 5, 2))
    normal_mulligan_message = build_auto_knockout_message(
        [
            AutoKnockoutEvent(
                action="mulligan",
                challenge_id=1,
                challenger_id=1,
                name="Test",
                discord_id="123",
                required_checkins=2,
                checkin_count=0,
                challenge_week_id=1,
                mulligan_checkin_id=10,
                mulligan_day=day_name,
            ),
            _warning_event(
                normal_mulligan_remaining,
                mulligan_day=day_name,
                mulligan_checkin_id=10,
            ),
        ]
    )
    assert (
        "<@123> was saved from knockout by their mulligan on Saturday. "
        "They must check in on Sunday to avoid knockout."
    ) in normal_mulligan_message

    # Green week, with mulligan: after Wednesday, Thursday through Sunday are required.
    green_wednesday_remaining = remaining_week_days(thursday_run, week_end)
    _assert_decision(0, 5, len(green_wednesday_remaining), True, "mulligan")
    day_name, missing_date = missing_mulligan_day(
        date(2026, 4, 27),
        thursday_run,
        [],
    )
    assert (day_name, missing_date) == ("Wednesday", date(2026, 4, 29))
    green_wednesday_message = build_auto_knockout_message(
        [
            AutoKnockoutEvent(
                action="mulligan",
                challenge_id=1,
                challenger_id=1,
                name="Test",
                discord_id="123",
                required_checkins=5,
                checkin_count=0,
                challenge_week_id=1,
                mulligan_checkin_id=10,
                mulligan_day=day_name,
            ),
            _warning_event(
                green_wednesday_remaining,
                mulligan_day=day_name,
                mulligan_checkin_id=10,
                required_checkins=5,
            ),
        ]
    )
    assert (
        "They must check in on Thursday, Friday, Saturday, and Sunday to avoid "
        "knockout."
    ) in green_wednesday_message

    # Green week, three check-ins after Saturday: the mulligan covers a previous day.
    green_saturday_remaining = remaining_week_days(sunday_run, week_end)
    _assert_decision(3, 5, len(green_saturday_remaining), True, "mulligan")
    day_name, missing_date = missing_mulligan_day(
        date(2026, 4, 27),
        sunday_run,
        ["Monday", "Wednesday", "Saturday"],
    )
    assert (day_name, missing_date) == ("Friday", date(2026, 5, 1))
    green_saturday_message = build_auto_knockout_message(
        [
            AutoKnockoutEvent(
                action="mulligan",
                challenge_id=1,
                challenger_id=1,
                name="Test",
                discord_id="123",
                required_checkins=5,
                checkin_count=3,
                challenge_week_id=1,
                mulligan_checkin_id=10,
                mulligan_day=day_name,
            ),
            _warning_event(
                green_saturday_remaining,
                mulligan_day=day_name,
                mulligan_checkin_id=10,
                checkin_count=4,
                required_checkins=5,
            )
        ]
    )
    assert (
        "They must check in on Sunday to avoid knockout."
    ) in green_saturday_message

    # If Sunday is already checked in before the job runs, do not warn for Sunday.
    checked_in_sunday_remaining = effective_remaining_week_days(
        remaining_week_days(sunday_run, week_end),
        "Sunday",
        True,
    )
    assert checked_in_sunday_remaining == ()
    _assert_decision(
        effective_checkin_count(4, True),
        5,
        len(checked_in_sunday_remaining),
        False,
        "none",
    )

    # If Sunday has not been checked in yet, it remains required and warnable.
    missing_sunday_remaining = effective_remaining_week_days(
        remaining_week_days(sunday_run, week_end),
        "Sunday",
        False,
    )
    assert missing_sunday_remaining == ("Sunday",)
    _assert_decision(4, 5, len(missing_sunday_remaining), False, "none")
    missing_sunday_message = build_auto_knockout_warning_message(
        [_warning_event(missing_sunday_remaining)]
    )
    assert (
        "<@123> has no more mulligans and must check in on Sunday to avoid knockout."
    ) in missing_sunday_message

    # Today is never eligible for mulligan selection.
    day_name, missing_date = missing_mulligan_day(
        date(2026, 4, 27),
        sunday_run,
        ["Monday", "Wednesday", "Friday", "Saturday"],
    )
    assert (day_name, missing_date) == ("Thursday", date(2026, 4, 30))

    assert build_auto_knockout_message([_warning_event(["Sunday"])]) is None


if __name__ == "__main__":
    run_rule_checks()
