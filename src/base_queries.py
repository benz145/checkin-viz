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


def challenger_by_discord_id(discord_id):
    return fetchone("select * from challengers where discord_id = %s", [discord_id])


def latest_bmr_log_for_challenger(challenger_id):
    sql = """
        select *
        from bmr_logs
        where challenger_id = %s
        order by logged_at desc, id desc
        limit 1
    """
    return fetchone(sql, [challenger_id])


def insert_bmr_log_and_update_challenger_bmr(
    challenger_id, gender, birthday, height_feet, height_inches, weight_lbs, bmr
):
    def fn(conn, cur):
        cur.execute(
            """
            insert into bmr_logs
                (challenger_id, gender, birthday, height_feet, height_inches, weight_lbs, bmr)
            values
                (%s, %s, %s, %s, %s, %s, %s)
            returning *
            """,
            [challenger_id, gender, birthday, height_feet, height_inches, weight_lbs, bmr],
        )
        inserted = cur.fetchone()
        cur.execute(
            "update challengers set bmr = %s where id = %s",
            [bmr, challenger_id],
        )
        return inserted

    return fn


def clear_bmr_profile_for_challenger(challenger_id):
    def fn(conn, cur):
        cur.execute("delete from bmr_logs where challenger_id = %s", [challenger_id])
        cur.execute("update challengers set bmr = null where id = %s", [challenger_id])
        return cur.rowcount

    return fn


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
        """
        select * from challenges where 
        (current_timestamp at time zone 'America/New_York')::date >= start and (current_timestamp at time zone 'America/New_York')::date <= "end";
    """
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


def clear_today_checkins_for_challenger(challenger, challenge_week):
    """
    Delete the latest check-in from today for the given challenger in the given
    challenge week, using the challenger's timezone to determine \"today\".

    Returns a function suitable for use with with_psycopg that, when executed
    in a transaction, deletes any related medals and then the check-in, and
    returns the number of deleted check-ins (0 or 1).
    """

    def fn(conn, cur):
        # First, find today's latest check-in for this challenger and challenge week.
        select_sql = """
            select id
            from checkins
            where
                challenger = %s
                and challenge_week_id = %s
                and (time at time zone %s)::date = (current_timestamp at time zone %s)::date
            order by time at time zone %s desc
            limit 1;
        """
        cur.execute(
            select_sql,
            (challenger.id, challenge_week.id, challenger.tz, challenger.tz, challenger.tz),
        )
        row = cur.fetchone()
        if not row:
            return 0

        checkin_id = row.id

        # Delete any medals that reference this check-in to satisfy FK constraints.
        delete_medals_sql = """
            delete from medals
            where checkin_id = %s;
        """
        cur.execute(delete_medals_sql, (checkin_id,))

        # Now delete the check-in itself.
        delete_checkins_sql = """
            delete from checkins
            where id = %s;
        """
        cur.execute(delete_checkins_sql, (checkin_id,))

        return 1

    return fn
