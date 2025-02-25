from helpers import fetchone, fetchall
from datetime import datetime, timedelta, date
import pytz
import logging
import itertools


def points_so_far(challenge_id):
    return fetchall("select * from get_challenge_score(%s, FALSE)", [challenge_id])


def get_challenges():
    return fetchall("select * from challenges")


def bi_checkins(challenge_id):
    sql = "select sum(bi_checkins) from challenger_challenges where challenge_id = %s"
    return fetchone(sql, [challenge_id]).sum


def points_knocked_out(challenge_id):
    return fetchall("select * from get_challenge_score(%s, TRUE)", [challenge_id])


def challenge_data(challenge_id):
    return fetchone("select * from challenges where id = %s;", [challenge_id])


def total_ante(challenge_id, tier):
    return fetchone(
        "select sum(ante) from challenger_challenges where challenge_id = %s and tier = %s",
        (challenge_id, tier),
    ).sum


def total_possible_checkins_so_far(challenge_id, week_id):
    sql = "select count(*) * 5 as total_possible from challenge_weeks where challenge_id = %s and id < %s;"
    checkins_possible_before_now = fetchone(sql, (challenge_id, week_id))[0]
    now = datetime.now()
    day_of_week = now.weekday()
    return checkins_possible_before_now + min(day_of_week + 1, 5)


def total_possible_checkins(challenge_id):
    sql = "select count(*) * 5 as total_possible from challenge_weeks where challenge_id = %s;"
    return fetchone(sql, [challenge_id])


def challenge_weeks():
    sql = """
        select c.name, cw.id, cw.start from challenge_weeks cw
        join challenges c on cw.challenge_id = c.id
        order by cw.start
        """
    challenges = fetchall(sql, [])
    return [
        list(value) for n, value in itertools.groupby(challenges, key=lambda x: x.name)
    ]


def get_current_challenge_week(tz="America/New_York"):
    sql = """
        select * from challenge_weeks 
        where 
            week_of_year = extract(week from current_timestamp at time zone %s) and
            (current_timestamp at time zone 'America/New_York')::date >= start and (current_timestamp at time zone 'America/New_York')::date <= "end";
        """
    return fetchone(sql, [tz])


def get_current_challenge():
    return fetchone(
        'select * from challenges where start <= CURRENT_DATE and "end" >= CURRENT_DATE'
    )


def checkins_this_week(challenge_week_id):
    sql = """
    select
      ch.name,
      c.day_of_week,
      c.tier,
      c.time at time zone ch.tz as time,
      cw.bye_week,
      CASE
        WHEN c.id = cch.mulligan
        THEN True
        ELSE False
      END AS isMulligan
    from
      (select max(time) as time, day_of_week, challenger
       from checkins
       where challenge_week_id = %s
       group by day_of_week, challenger) as max_time_per_day
    join checkins c on
      c.challenger = max_time_per_day.challenger 
      and
      c.time = max_time_per_day.time
      and
      c.day_of_week = max_time_per_day.day_of_week
    join
      challenge_weeks cw on cw.id = c.challenge_week_id
    join
      challengers ch on ch.id = max_time_per_day.challenger
    join
      challenger_challenges cch on ch.id = cch.challenger_id
    where cw.id = %s
    and cch.challenge_id = cw.challenge_id
    group by c.id, ch.name, c.day_of_week, c.tier, c.time, cw.bye_week, ch.tz, cch.mulligan
    order by time desc;
    """
    return fetchall(sql, (challenge_week_id, challenge_week_id))


def insert_checkin(message, tier, challenger, week_id, day_of_week=None, time=None):
    tz = pytz.timezone(challenger.tz)
    now = datetime.now(tz=tz)
    logging.info("now %s", now)

    def fn(conn, cur):
        cur.execute(
            "INSERT INTO checkins (name, time, tier, day_of_week, text, challenge_week_id, challenger, tz) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING returning id",
            (
                challenger.name,
                time or now,
                tier,
                day_of_week or now.strftime("%A"),
                message,
                week_id,
                challenger.id,
                challenger.tz,
            ),
        )
        return cur.fetchone().id

    return fn
