from helpers import *
import logging
from personal_records import period_record_medal
from medal_constants import (
    CHALLENGE_SCOPED_MEDALS,
    NON_STEALABLE_MEDALS,
    nice_medal_names,
)

# Podium emoji constants
PODIUM_EMOJIS = {
    "first_place": "🥇",
    "second_place": "🥈",
    "third_place": "🥉",
}

# Medal metadata: group (A-D) and difficulty (1-4) for organizing and ordering medals
medal_metadata = {
    "all_gold": {"group": "A", "difficulty": 1},
    "all_green": {"group": "A", "difficulty": 2},
    "highest_tier_challenge": {"group": "B", "difficulty": 1},
    "highest_tier_week": {"group": "B", "difficulty": 2},
    "highest_tier_personal": {"group": "B", "difficulty": 3},
    "highest_tier_personal_season": {"group": "B", "difficulty": 3},
    "highest_tier_personal_year": {"group": "B", "difficulty": 3},
    "gold": {"group": "C", "difficulty": 3},
    "green": {"group": "C", "difficulty": 4},
    "red": {"group": "C", "difficulty": 2},
    "diamond": {"group": "C", "difficulty": 1},
    "first_to_green": {"group": "C", "difficulty": 3},
    "earliest_for_challenge": {"group": "D", "difficulty": 1},
    "latest_for_challenge": {"group": "D", "difficulty": 1},
    "earliest_for_week": {"group": "D", "difficulty": 2},
    "latest_for_week": {"group": "D", "difficulty": 2},
}

# Re-export for existing imports: from medals import nice_medal_names, NON_STEALABLE_MEDALS


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
        highest_tier_personal(challenge_week_id),
        period_record_medal(challenge_week_id, "season"),
        period_record_medal(challenge_week_id, "year"),
        earliest_for_week(challenge_week_id),
        latest_for_week(challenge_week_id),
        gold(challenge_week_id),
        green(challenge_week_id),
        red(challenge_week_id),
        diamond(challenge_week_id),
        first_to_green(challenge_week_id),
        highest_tier_challenge(challenge_id),
        earliest_for_challenge(challenge_id),
        latest_for_challenge(challenge_id),
        all_gold_challenge(challenge_id),
        all_green_challenge(challenge_id),
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


def get_current_week_medal_standings(challenge_id, challenge_week_id):
    """
    Current medal holders for the opening roundup and medal case.

    Week-scoped medals: rows for this challenge week.
    Challenge-scoped medals: current holders across the whole challenge
    (so prior-week awards still appear as currently held).

    Non-stealable medals: every recipient.
    Stealable medals: only the latest holder per medal name.
    """
    non_stealable_list = ", ".join(f"'{m}'" for m in sorted(NON_STEALABLE_MEDALS))
    challenge_scoped_list = ", ".join(
        f"'{m}'" for m in sorted(CHALLENGE_SCOPED_MEDALS)
    )
    sql = f"""
    WITH ranked_medals AS (
        SELECT
            m.medal AS medal_name,
            m.emoji AS medal_emoji,
            c.discord_id,
            c.name AS challenger_name,
            ci.tier AS checkin_tier,
            ci.time AT TIME ZONE COALESCE(ci.tz, 'America/New_York') AS checkin_time,
            m.created_at,
            ROW_NUMBER() OVER (
                PARTITION BY
                    m.medal,
                    CASE
                        WHEN m.medal IN ({non_stealable_list})
                        THEN m.challenger_id
                    END
                ORDER BY m.created_at DESC, m.id DESC
            ) AS rn
        FROM medals m
        JOIN challengers c ON c.id = m.challenger_id
        LEFT JOIN checkins ci ON ci.id = m.checkin_id
        WHERE
            (
                m.medal IN ({challenge_scoped_list})
                AND m.challenge_id = %s
            )
            OR (
                m.medal NOT IN ({challenge_scoped_list})
                AND m.challenge_week_id = %s
            )
    )
    SELECT
        medal_name,
        medal_emoji,
        discord_id,
        challenger_name,
        checkin_tier,
        checkin_time
    FROM ranked_medals
    WHERE rn = 1
    ORDER BY created_at, discord_id, medal_name;
    """
    return fetchall(sql, [challenge_id, challenge_week_id])


def reconcile_medals(new_medals, current_medals):
    # Personal records and other earned achievements cannot be stolen.
    medals = [
        {**m._asdict(), "steal": None}
        for m in new_medals
        if m.medal_name in NON_STEALABLE_MEDALS
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
    if latest_for_challenge_new is not None:
        medals.append(
            {
                **latest_for_challenge_new._asdict(),
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
    if earliest_for_challenge_new is not None:
        medals.append(
            {
                **earliest_for_challenge_new._asdict(),
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


def get_personal_tier_record(challenger_id):
    """Highest real tier across all challenges and the date first achieved."""
    return fetchone(
        """
        SELECT ci.tier,
               (ci.time AT TIME ZONE COALESCE(ci.tz, 'America/New_York'))::date AS record_date
        FROM checkins ci
        WHERE ci.challenger = %s
          AND ci.tier ~ '^T[0-9]+$'
          AND NOT EXISTS (
              SELECT 1 FROM challenger_challenges cc WHERE cc.mulligan = ci.id
          )
        ORDER BY SUBSTRING(ci.tier FROM 2)::INT DESC, ci.time, ci.id
        LIMIT 1
        """,
        [challenger_id],
    )


def highest_tier_personal(challenge_week_id, execute=False):
    """Record-breaking check-ins this week, compared with all previous challenges.

    Compute history before filtering to the requested week. The check-in ID
    breaks timestamp ties deterministically; equal tiers never set a new record.
    Automatic mulligans are not personal achievements.
    """
    sql = """
WITH personal_history AS (
    SELECT ci.*,
           MAX(SUBSTRING(ci.tier FROM 2)::INT) OVER (
               PARTITION BY ci.challenger
               ORDER BY ci.time, ci.id
               ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
           ) AS previous_tier
    FROM checkins ci
    WHERE ci.tier ~ '^T[0-9]+$'
      AND ci.challenger IN (
          SELECT challenger FROM checkins
          WHERE challenge_week_id = %(challenge_week_id)s
      )
      AND NOT EXISTS (
          SELECT 1 FROM challenger_challenges cc WHERE cc.mulligan = ci.id
      )
)
SELECT c.name,
       c.id AS challenger_id,
       ci.tier,
       ci.id AS checkin_id,
       ci.challenge_week_id,
       ci.time AT TIME ZONE COALESCE(ci.tz, 'America/New_York') AS time,
       'highest_tier_personal' AS medal_name,
       '🏆' AS medal_emoji
FROM personal_history ci
JOIN challengers c ON c.id = ci.challenger
WHERE ci.challenge_week_id = %(challenge_week_id)s
  AND (ci.previous_tier IS NULL OR SUBSTRING(ci.tier FROM 2)::INT > ci.previous_tier)
ORDER BY ci.time, ci.id
"""
    parameters = {"challenge_week_id": challenge_week_id}
    if execute:
        return fetchall(sql, parameters)
    return sql, parameters


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
       '☀️' as medal_emoji
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
       '🌙' as medal_emoji
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


def red(challenge_week_id, execute=False):
    """Red Week: 5 check-ins for the week, each must be T3 or higher."""
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
       AND ltrim(tier, 'T')::INT >= 3
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
     'red' as medal_name,
     '🟥' as medal_emoji
 FROM totals
 JOIN challengers c ON totals.challenger = c.id
 WHERE checkin_count = 5
 ORDER BY time
"""
    if execute:
        return fetchall(sql, {"challenge_week_id": challenge_week_id})
    return (sql, {"challenge_week_id": challenge_week_id})


def diamond(challenge_week_id, execute=False):
    """Diamond Week: 7 check-ins for the week, each must be T3 or higher."""
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
       AND ltrim(tier, 'T')::INT >= 3
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
     'diamond' as medal_name,
     '💎' as medal_emoji
 FROM totals
 JOIN challengers c ON totals.challenger = c.id
 WHERE checkin_count = 7
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
    '✳️' AS medal_emoji
FROM totals
JOIN challengers c ON totals.challenger = c.id
WHERE checkin_count >= 5
ORDER BY time
LIMIT 1
    """

    if execute:
        return fetchall(sql, {"challenge_week_id": challenge_week_id})
    return (sql, {"challenge_week_id": challenge_week_id})


def all_gold_challenge(challenge_id, execute=False):
    sql = """
WITH non_bye_weeks AS (
    SELECT id
    FROM challenge_weeks
    WHERE challenge_id = %(challenge_id)s
      AND (bye_week != true OR bye_week IS NULL)
),
required_weeks AS (
    SELECT COUNT(*) AS total_weeks FROM non_bye_weeks
),
daily_checkins AS (
    SELECT
        cw.id AS challenge_week_id,
        ci.challenger,
        DATE(ci.time AT TIME ZONE ci.tz) AS checkin_date,
        MAX(ci.time AT TIME ZONE ci.tz) AS latest_checkin_time,
        (ARRAY_AGG(ci.id ORDER BY ci.time AT TIME ZONE ci.tz DESC))[1] AS latest_checkin_id,
        (ARRAY_AGG(ci.tier ORDER BY ci.time AT TIME ZONE ci.tz DESC))[1] AS latest_tier
    FROM checkins ci
    JOIN challenge_weeks cw ON ci.challenge_week_id = cw.id
    JOIN non_bye_weeks nbw ON nbw.id = cw.id
    GROUP BY cw.id, ci.challenger, DATE(ci.time AT TIME ZONE ci.tz)
),
totals AS (
    SELECT
        challenge_week_id,
        challenger,
        latest_checkin_time AS time,
        ROW_NUMBER() OVER (
            PARTITION BY challenge_week_id, challenger
            ORDER BY checkin_date
        ) AS checkin_count,
        latest_checkin_id AS checkin_id,
        latest_tier AS tier
    FROM daily_checkins
),
gold_weeks AS (
    SELECT *
    FROM totals
    WHERE checkin_count = 7
),
challenger_gold_counts AS (
    SELECT
        challenger,
        COUNT(DISTINCT challenge_week_id) AS weeks_with_gold
    FROM gold_weeks
    GROUP BY challenger
),
gold_with_counts AS (
    SELECT
        gw.*,
        cgc.weeks_with_gold,
        ROW_NUMBER() OVER (
            PARTITION BY gw.challenger
            ORDER BY gw.challenge_week_id DESC, gw.time DESC
        ) AS rn
    FROM gold_weeks gw
    JOIN challenger_gold_counts cgc ON gw.challenger = cgc.challenger
)
SELECT
    c.name,
    c.id AS challenger_id,
    gw.tier,
    gw.checkin_id,
    gw.challenge_week_id,
    gw.time,
    'all_gold' AS medal_name,
    '⭐' AS medal_emoji
FROM gold_with_counts gw
JOIN challengers c ON c.id = gw.challenger
JOIN required_weeks rw ON TRUE
WHERE rw.total_weeks > 0
  AND gw.weeks_with_gold = rw.total_weeks
  AND gw.rn = 1
"""
    if execute:
        return fetchall(sql, {"challenge_id": challenge_id})
    return (sql, {"challenge_id": challenge_id})


def all_green_challenge(challenge_id, execute=False):
    sql = """
WITH non_bye_weeks AS (
    SELECT id
    FROM challenge_weeks
    WHERE challenge_id = %(challenge_id)s
      AND (bye_week != true OR bye_week IS NULL)
),
required_weeks AS (
    SELECT COUNT(*) AS total_weeks FROM non_bye_weeks
),
daily_checkins AS (
    SELECT
        cw.id AS challenge_week_id,
        ci.challenger,
        DATE(ci.time AT TIME ZONE ci.tz) AS checkin_date,
        MAX(ci.time AT TIME ZONE ci.tz) AS latest_checkin_time,
        (ARRAY_AGG(ci.id ORDER BY ci.time AT TIME ZONE ci.tz DESC))[1] AS latest_checkin_id,
        (ARRAY_AGG(ci.tier ORDER BY ci.time AT TIME ZONE ci.tz DESC))[1] AS latest_tier
    FROM checkins ci
    JOIN challenge_weeks cw ON ci.challenge_week_id = cw.id
    JOIN non_bye_weeks nbw ON nbw.id = cw.id
    GROUP BY cw.id, ci.challenger, DATE(ci.time AT TIME ZONE ci.tz)
),
totals AS (
    SELECT
        challenge_week_id,
        challenger,
        latest_checkin_time AS time,
        ROW_NUMBER() OVER (
            PARTITION BY challenge_week_id, challenger
            ORDER BY checkin_date
        ) AS checkin_count,
        latest_checkin_id AS checkin_id,
        latest_tier AS tier
    FROM daily_checkins
),
green_weeks AS (
    SELECT *
    FROM totals
    WHERE checkin_count = 5
),
challenger_green_counts AS (
    SELECT
        challenger,
        COUNT(DISTINCT challenge_week_id) AS weeks_with_green
    FROM green_weeks
    GROUP BY challenger
),
green_with_counts AS (
    SELECT
        gw.*,
        cgc.weeks_with_green,
        ROW_NUMBER() OVER (
            PARTITION BY gw.challenger
            ORDER BY gw.challenge_week_id DESC, gw.time DESC
        ) AS rn
    FROM green_weeks gw
    JOIN challenger_green_counts cgc ON gw.challenger = cgc.challenger
)
SELECT
    c.name,
    c.id AS challenger_id,
    gw.tier,
    gw.checkin_id,
    gw.challenge_week_id,
    gw.time,
    'all_green' AS medal_name,
    '❇️' AS medal_emoji
FROM green_with_counts gw
JOIN challengers c ON c.id = gw.challenger
JOIN required_weeks rw ON TRUE
WHERE rw.total_weeks > 0
  AND gw.weeks_with_green = rw.total_weeks
  AND gw.rn = 1
"""
    if execute:
        return fetchall(sql, {"challenge_id": challenge_id})
    return (sql, {"challenge_id": challenge_id})
