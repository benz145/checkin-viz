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
    mulligan_checkin_id: int | None = None
    mulligan_day: str | None = None


def required_checkins_for_week(is_green_week):
    return 5 if is_green_week else 2


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
        where cw."end" < (current_timestamp at time zone 'America/New_York')::date
        order by cw."end" desc
        limit 1;
        """
    )
    return cur.fetchone()


def get_participants_for_week(cur, challenge_id, challenge_week_id):
    cur.execute(
        """
        select
            ch.id,
            ch.name,
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
            ) as checked_in_days
        from challenger_challenges cc
        join challengers ch on ch.id = cc.challenger_id
        left join checkins c on
            c.challenger = ch.id
            and c.challenge_week_id = %s
        where
            cc.challenge_id = %s
            and cc.knocked_out = false
            and coalesce(cc.tier, '') != 'T0'
        group by ch.id, ch.name, ch.tz, cc.mulligan
        order by ch.name;
        """,
        (challenge_week_id, challenge_id),
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


def apply_auto_knockout_for_week(cur, challenge_week, participants):
    required_checkins = required_checkins_for_week(challenge_week.green)
    events = []

    for participant in participants:
        checkin_count = participant.checkin_count or 0
        if checkin_count >= required_checkins:
            continue

        if participant.mulligan is None:
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
                )
            )

    return events


def run_auto_knockout():
    from helpers import with_psycopg

    def fn(conn, cur):
        challenge_week = get_previous_challenge_week(cur)
        if challenge_week is None:
            logging.info("Auto-knockout skipped: no completed challenge week")
            return []

        participants = get_participants_for_week(
            cur,
            challenge_week.challenge_id,
            challenge_week.challenge_week_id,
        )
        return apply_auto_knockout_for_week(cur, challenge_week, participants)

    return with_psycopg(fn)
