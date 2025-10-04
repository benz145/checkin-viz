from helpers import *
import logging

# all medal queries return
# name, tier, checkin_id, challenge_week_id, time, medal_name, medal_emoji
# they can be composed with the medals function


def wrap_with_selector(sql):
    return f"""
Select name, challenger_id, tier, checkin_id, challenge_week_id, time, medal_name, medal_emoji from ({sql})
    """


def get_medals_now(challenge_id, challenge_week_id):
    new = all_medals(challenge_id, challenge_week_id)
    current = current_medals(challenge_id)
    return reconcile_medals(new, current)


def update_medal_table(challenge_id, challenge_week_id):
    medals = get_medals_now(challenge_id, challenge_week_id)
    logging.info("inserting medals %s", medals)
    insert_medals(medals, challenge_id)


def all_medals(challenge_id, challenge_week_id):
    return medals(
        highest_tier_week(challenge_week_id),
        earliest_for_week(challenge_week_id),
        latest_for_week(challenge_week_id),
        gold(challenge_week_id),
        green(challenge_week_id),
        first_to_green(challenge_week_id),
        highest_tier_challenge(challenge_id),
        earliest_for_challenge(challenge_id),
        latest_for_challenge(challenge_id),
    )


def medals(*args):
    statements = [wrap_with_selector(arg[0]) for arg in args]
    parameters = {
        key: value for d in [arg[1] for arg in args] for key, value in d.items()
    }
    sql = "\nUNION ALL\n".join(statements)
    print(sql)
    return fetchall(sql, parameters)


def current_medals(challenge_id):
    sql = """
WITH ranked_medals AS (
     SELECT
         m.*,
         ROW_NUMBER() OVER (
             PARTITION BY m.medal
             ORDER BY m.created_at DESC
         ) as rn
     FROM medals m
     WHERE m.challenge_id = %(challenge_id)s
 )
 SELECT
     rm.id,
     rm.medal as medal_name,
     rm.emoji as medal_emoji,
     rm.steal,
     rm.checkin_id,
     rm.challenge_id,
     rm.challenge_week_id,
     rm.challenger_id,
     rm.created_at,
     ch.name as challenger_name
 FROM ranked_medals rm
 LEFT JOIN challengers ch ON rm.challenger_id = ch.id
 WHERE
     -- For medals with steals, only get the most recent (rn = 1)
     -- For medals without steals (steal IS NULL), get all of them
     (rm.steal IS NOT NULL AND rm.rn = 1)
     OR rm.steal IS NULL
 ORDER BY rm.created_at DESC;
"""
    return fetchall(
        sql, {"challenge_id": challenge_id}
    )  # , "challenge_week_id": challenge_week_id})


def insert_medals(medals, challenge_id):
    sql = """
insert into medals
    (challenger_id, medal, challenge_id, challenge_week_id, checkin_id, steal, emoji)
    values
    (%(challenger_id)s, %(medal)s, %(challenge_id)s, %(challenge_week_id)s, %(checkin_id)s, %(steal)s, %(emoji)s) ON CONFLICT DO NOTHING
"""

    def insert_all_medals(conn, curr):
        curr.executemany(
            sql,
            [
                {
                    "challenge_week_id": m["challenge_week_id"],
                    "challenger_id": m["challenger_id"],
                    "challenge_id": challenge_id,
                    "checkin_id": m["checkin_id"],
                    "steal": m["steal"] if "steal" in m else None,
                    "medal": m["medal_name"],
                    "emoji": m["medal_emoji"],
                }
                for m in medals
            ],
        )

    with_psycopg(insert_all_medals)


def reconcile_medals(new_medals, current_medals):
    # green, gold, and first to green cannot be stolen
    medals = [
        {**m._asdict(), "steal": None}
        for m in new_medals
        if m.medal_name == "green"
        or m.medal_name == "gold"
        or m.medal_name == "first_to_green"
    ]

    latest_for_week_new = next(
        (m for m in new_medals if m.medal_name == "latest_for_week"), None
    )
    latest_for_week_old = next(
        (m for m in current_medals if m.medal_name == "latest_for_week"), None
    )
    medals.append(
        {
            **latest_for_week_new._asdict(),
            "steal": (
                latest_for_week_old.checkin_id
                if latest_for_week_old is not None
                and latest_for_week_new.checkin_id != latest_for_week_old.checkin_id
                and latest_for_week_new.challenge_week_id
                == latest_for_week_old.challenge_week_id
                else None
            ),
        }
    )

    earliest_for_week_new = next(
        (m for m in new_medals if m.medal_name == "earliest_for_week"), None
    )
    earliest_for_week_old = next(
        (m for m in current_medals if m.medal_name == "earliest_for_week"), None
    )
    medals.append(
        {
            **earliest_for_week_new._asdict(),
            "steal": (
                earliest_for_week_old.checkin_id
                if earliest_for_week_old is not None
                and earliest_for_week_new.checkin_id != earliest_for_week_old.checkin_id
                and earliest_for_week_new.challenge_week_id
                == earliest_for_week_old.challenge_week_id
                else None
            ),
        }
    )

    latest_for_challenge_new = next(
        (m for m in new_medals if m.medal_name == "latest_for_challenge"), None
    )
    latest_for_challenge_old = next(
        (m for m in current_medals if m.medal_name == "latest_for_challenge"), None
    )
    medals.append(
        {
            **latest_for_week_new._asdict(),
            "steal": (
                latest_for_challenge_old.checkin_id
                if latest_for_challenge_old is not None
                and latest_for_challenge_new.checkin_id
                != latest_for_challenge_old.checkin_id
                else None
            ),
        }
    )

    earliest_for_challenge_new = next(
        (m for m in new_medals if m.medal_name == "earliest_for_challenge"), None
    )
    earliest_for_challenge_old = next(
        (m for m in current_medals if m.medal_name == "earliest_for_challenge"), None
    )
    medals.append(
        {
            **earliest_for_week_new._asdict(),
            "steal": (
                earliest_for_challenge_old.checkin_id
                if earliest_for_challenge_old is not None
                and earliest_for_challenge_new.checkin_id
                != earliest_for_challenge_old.checkin_id
                else None
            ),
        }
    )

    highest_tier_for_week_new = next(
        (m for m in new_medals if m.medal_name == "highest_tier_week"), None
    )
    highest_tier_for_week_old = next(
        (m for m in current_medals if m.medal_name == "highest_tier_week"), None
    )
    medals.append(
        {
            **highest_tier_for_week_new._asdict(),
            "steal": (
                highest_tier_for_week_old.checkin_id
                if highest_tier_for_week_old is not None
                and highest_tier_for_week_new.checkin_id
                != highest_tier_for_week_old.checkin_id
                and highest_tier_for_week_new.challenge_week_id
                == highest_tier_for_week_old.challenge_week_id
                else None
            ),
        }
    )

    highest_tier_for_challenge_new = next(
        (m for m in new_medals if m.medal_name == "highest_tier_challenge"), None
    )
    highest_tier_for_challenge_old = next(
        (m for m in current_medals if m.medal_name == "highest_tier_challenge"), None
    )
    medals.append(
        {
            **highest_tier_for_challenge_new._asdict(),
            "steal": (
                highest_tier_for_challenge_old.checkin_id
                if highest_tier_for_challenge_old is not None
                and highest_tier_for_challenge_new.checkin_id
                != highest_tier_for_challenge_old.checkin_id
                else None
            ),
        }
    )

    return medals


def highest_tier_week(challenge_week_id, execute=False):
    sql = """
SELECT challengers.name as name,
       challengers.id as challenger_id,
       tier,
       checkins.id AS checkin_id,
       %(challenge_week_id)s as challenge_week_id,
       time AT TIME ZONE checkins.tz as time,
       'highest_tier_week' as medal_name,
       '💪' as medal_emoji
FROM checkins
join challengers on challengers.id = checkins.challenger
WHERE challenge_week_id = %(challenge_week_id)s
ORDER BY ltrim(checkins.tier, 'T')::INT DESC
LIMIT 1
"""
    if execute:
        return fetchall(sql, {"challenge_week_id": challenge_week_id})
    return (sql, {"challenge_week_id": challenge_week_id})


def highest_tier_challenge(challenge_id, execute=False):
    sql = """
SELECT challengers.name as name,
       challengers.id as challenger_id,
       tier,
       checkins.id AS checkin_id,
       challenge_weeks.id AS challenge_week_id,
       time AT TIME ZONE checkins.tz as time,
       'highest_tier_challenge' as medal_name,
       '🏋' as medal_emoji
FROM checkins
JOIN challenge_weeks ON checkins.challenge_week_id = challenge_weeks.id
join challengers on challengers.id = checkins.challenger
WHERE challenge_weeks.challenge_id = %(challenge_id)s
ORDER BY ltrim(checkins.tier, 'T')::INT DESC
LIMIT 1
"""
    if execute:
        return fetchall(sql, {"challenge_id": challenge_id})
    return (sql, {"challenge_id": challenge_id})


def earliest_for_challenge(challenge_id, execute=False):
    sql = """
SELECT challengers.name,
       challengers.id as challenger_id,
       tier,
       checkins.id AS checkin_id,
       challenge_weeks.id AS challenge_week_id,
       time AT TIME ZONE checkins.tz AS time,
       'earliest_for_challenge' as medal_name,
       '🌞' as medal_emoji
FROM checkins
JOIN challenge_weeks ON checkins.challenge_week_id = challenge_weeks.id
join challengers on challengers.id = checkins.challenger
WHERE challenge_weeks.challenge_id = %(challenge_id)s
ORDER BY to_char(time AT TIME ZONE checkins.tz, 'HH24:MI:SS') ASC
LIMIT 1
"""
    if execute:
        return fetchall(sql, {"challenge_id": challenge_id})
    return (sql, {"challenge_id": challenge_id})


def earliest_for_week(challenge_week_id, execute=False):
    sql = """
SELECT challengers.name,
       challengers.id as challenger_id,
       tier,
       checkins.id AS checkin_id,
       checkins.challenge_week_id as challenge_week_id,
       time AT TIME ZONE checkins.tz AS time,
       'earliest_for_week' as medal_name,
       '🌞' as medal_emoji
FROM checkins
join challengers on checkins.challenger = challengers.id
WHERE checkins.challenge_week_id = %(challenge_week_id)s
ORDER BY to_char(time AT TIME ZONE checkins.tz, 'HH24:MI:SS') ASC
LIMIT 1
"""
    if execute:
        return fetchall(sql, {"challenge_week_id": challenge_week_id})
    return (sql, {"challenge_week_id": challenge_week_id})


def latest_for_challenge(challenge_id, execute=False):
    sql = """
SELECT challengers.name,
       challengers.id as challenger_id,
       tier,
       checkins.id AS checkin_id,
       challenge_weeks.id AS challenge_week_id,
       time AT TIME ZONE checkins.tz AS time,
       'latest_for_challenge' as medal_name,
       '🌚' as medal_emoji
FROM checkins
JOIN challenge_weeks ON checkins.challenge_week_id = challenge_weeks.id
join challengers on challengers.id = checkins.challenger
WHERE challenge_weeks.challenge_id = %(challenge_id)s
ORDER BY to_char(time AT TIME ZONE checkins.tz, 'HH24:MI:SS') DESC
LIMIT 1
"""
    if execute:
        return fetchall(sql, {"challenge_id": challenge_id})
    return (sql, {"challenge_id": challenge_id})


def latest_for_week(challenge_week_id, execute=False):
    sql = """
SELECT challengers.name,
       challengers.id as challenger_id,
       tier,
       checkins.id AS checkin_id,
       checkins.challenge_week_id as challenge_week_id,
       time AT TIME ZONE checkins.tz AS time,
       'latest_for_week' as medal_name,
       '🌚' as medal_emoji
FROM checkins
join challengers on checkins.challenger = challengers.id
WHERE checkins.challenge_week_id = %(challenge_week_id)s
ORDER BY to_char(time at TIME ZONE checkins.tz, 'HH24:MI:SS') DESC
LIMIT 1
"""
    if execute:
        return fetchall(sql, {"challenge_week_id": challenge_week_id})
    return (sql, {"challenge_week_id": challenge_week_id})


def gold(challenge_week_id, execute=False):
    sql = """
WITH daily_checkins AS (
    SELECT
        challenger,
        DATE(time AT TIME ZONE checkins.tz) AS checkin_date,
        MAX(time AT TIME ZONE checkins.tz) AS latest_checkin_time,
        (ARRAY_AGG(id ORDER BY time AT TIME ZONE checkins.tz DESC))[1] AS latest_checkin_id,
        (ARRAY_AGG(tier ORDER BY time AT TIME ZONE checkins.tz DESC))[1] AS latest_tier
    FROM checkins
    WHERE challenge_week_id = %(challenge_week_id)s
    GROUP BY
        challenger,
        DATE(time AT TIME ZONE checkins.tz)
),
totals AS (
    SELECT
        challenger,
        latest_checkin_time AS time,
        ROW_NUMBER() OVER (PARTITION BY challenger ORDER BY checkin_date) AS checkin_count,
        latest_checkin_id AS checkin_id,
        latest_tier AS tier
    FROM daily_checkins
    ORDER BY challenger, checkin_date
)
SELECT
    c.name,
    c.id AS challenger_id,
    tier,
    checkin_id,
    %(challenge_week_id)s AS challenge_week_id,
    time,
    'gold' AS medal_name,
    '🏅' AS medal_emoji
FROM totals
JOIN challengers c ON totals.challenger = c.id
WHERE checkin_count = 7
ORDER BY time
"""
    if execute:
        return fetchall(sql, {"challenge_week_id": challenge_week_id})
    return (sql, {"challenge_week_id": challenge_week_id})


def green(challenge_week_id, execute=False):
    sql = """
WITH daily_checkins AS (
     SELECT
         challenger,
         DATE(time AT TIME ZONE checkins.tz) AS checkin_date,
         MAX(time AT TIME ZONE checkins.tz) AS latest_checkin_time,
         (ARRAY_AGG(id ORDER BY time AT TIME ZONE checkins.tz DESC))[1] AS latest_checkin_id,
         (ARRAY_AGG(tier ORDER BY time AT TIME ZONE checkins.tz DESC))[1] AS latest_tier
     FROM checkins
     WHERE challenge_week_id = %(challenge_week_id)s
     GROUP BY
         challenger,
         DATE(time AT TIME ZONE checkins.tz)
 ),
 totals AS (
     SELECT
         challenger,
         latest_checkin_time AS time,
         ROW_NUMBER() OVER (PARTITION BY challenger ORDER BY checkin_date) AS checkin_count,
         latest_checkin_id AS checkin_id,
         latest_tier AS tier
     FROM daily_checkins
 )
 SELECT
     c.name,
     c.id as challenger_id,
     tier,
     checkin_id,
     %(challenge_week_id)s as challenge_week_id,
     time,
     'green' as medal_name,
     '🟩' as medal_emoji
 FROM totals
 JOIN challengers c ON totals.challenger = c.id
 WHERE checkin_count = 5
 ORDER BY time
"""
    if execute:
        return fetchall(sql, {"challenge_week_id": challenge_week_id})
    return (sql, {"challenge_week_id": challenge_week_id})


def first_to_green(challenge_week_id, execute=False):
    sql = """
WITH daily_checkins AS (
    SELECT
        challenger,
        DATE(time AT TIME ZONE checkins.tz) AS checkin_date,
        MAX(time AT TIME ZONE checkins.tz) AS latest_checkin_time,
        (ARRAY_AGG(id ORDER BY time AT TIME ZONE checkins.tz DESC))[1] AS latest_checkin_id,
        (ARRAY_AGG(tier ORDER BY time AT TIME ZONE checkins.tz DESC))[1] AS latest_tier
    FROM checkins
    WHERE challenge_week_id = %(challenge_week_id)s
    GROUP BY
        challenger,
        DATE(time AT TIME ZONE checkins.tz)
),
totals AS (
    SELECT
        challenger,
        latest_checkin_time AS time,
        ROW_NUMBER() OVER (PARTITION BY challenger ORDER BY checkin_date) AS checkin_count,
        latest_checkin_id AS checkin_id,
        latest_tier AS tier
    FROM daily_checkins
    ORDER BY challenger, checkin_date
)
SELECT
    c.name AS name,
    c.id AS challenger_id,
    checkin_id,
    tier,
    %(challenge_week_id)s AS challenge_week_id,
    time AS time,
    'first_to_green' AS medal_name,
    '❇' AS medal_emoji
FROM totals
JOIN challengers c ON totals.challenger = c.id
WHERE checkin_count >= 5
ORDER BY time
LIMIT 1
    """

    if execute:
        return fetchall(sql, {"challenge_week_id": challenge_week_id})
    return (sql, {"challenge_week_id": challenge_week_id})
