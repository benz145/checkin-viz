"""Shared record periods, based on original local dates and named challenges."""
from helpers import fetchall


# Challenge names, not check-in months, define a season. In particular, both
# parts of "Winter 2026" belong together even if they cross New Year's Day.
# Unlabelled challenges remain eligible for yearly/all-time records only.
PERSONAL_HISTORY_CTE = """
personal_checkin_history AS (
    SELECT ci.*,
           (ci.time AT TIME ZONE COALESCE(ci.tz, 'America/New_York'))::date AS record_date,
           EXTRACT(YEAR FROM ci.time AT TIME ZONE COALESCE(ci.tz, 'America/New_York'))::int AS record_year,
           INITCAP(SUBSTRING(LOWER(ch.name) FROM '\\m(summer|fall|autumn|winter|spring)\\M')) AS season,
           SUBSTRING(ch.name FROM '\\m([12][0-9]{3})\\M') AS season_year
    FROM checkins ci
    LEFT JOIN challenge_weeks cw ON cw.id = ci.challenge_week_id
    LEFT JOIN challenges ch ON ch.id = cw.challenge_id
    WHERE ci.tier ~ '^T[0-9]+$'
      AND NOT EXISTS (SELECT 1 FROM challenger_challenges cc WHERE cc.mulligan = ci.id)
), personal_period_history AS (
    SELECT *,
           CASE WHEN season IS NOT NULL AND season_year IS NOT NULL
                THEN REPLACE(season, 'Autumn', 'Fall') || ' ' || season_year END AS record_season
    FROM personal_checkin_history
)
"""


def get_period_personal_records(challenger_id, challenge_id, year):
    """Current named season and local calendar year, with historical baselines.

    Include empty records so the medal case distinguishes an unset record from
    an unrecognized season. Earliest original check-in wins equal-tier ties.
    """
    return fetchall(
        f"""WITH {PERSONAL_HISTORY_CTE}, contexts AS (
            SELECT 'season' AS scope,
                   REPLACE(INITCAP(SUBSTRING(LOWER(name) FROM '\\m(summer|fall|autumn|winter|spring)\\M')), 'Autumn', 'Fall')
                   || ' ' || SUBSTRING(name FROM '\\m([12][0-9]{{3}})\\M') AS label
            FROM challenges WHERE id = %s
            UNION ALL SELECT 'year', %s::text
        )
        SELECT context.scope, context.label, best.tier, best.record_date
        FROM contexts context
        LEFT JOIN LATERAL (
            SELECT tier, record_date FROM personal_period_history h
            WHERE h.challenger = %s AND (
                (context.scope = 'season' AND h.record_season = context.label)
                OR (context.scope = 'year' AND h.record_year::text = context.label)
            )
            ORDER BY SUBSTRING(tier FROM 2)::int DESC, time, id LIMIT 1
        ) best ON TRUE
        WHERE context.label IS NOT NULL
        ORDER BY context.scope
        """, [challenge_id, year, challenger_id],
    )


def period_record_medal(challenge_week_id, scope, execute=False):
    if scope not in {'season', 'year'}:
        raise ValueError('Unknown personal-record scope')
    column = 'record_season' if scope == 'season' else 'record_year'
    sql = f"""WITH {PERSONAL_HISTORY_CTE}, ranked_history AS (
        SELECT *, MAX(SUBSTRING(tier FROM 2)::int) OVER (
            PARTITION BY challenger, {column} ORDER BY time, id
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS previous_tier
        FROM personal_period_history WHERE {column} IS NOT NULL
    )
    SELECT c.name, c.id AS challenger_id, h.tier, h.id AS checkin_id,
           h.challenge_week_id,
           h.time AT TIME ZONE COALESCE(h.tz, 'America/New_York') AS time,
           'highest_tier_personal_{scope}' AS medal_name, '🏆' AS medal_emoji
    FROM ranked_history h JOIN challengers c ON c.id = h.challenger
    WHERE h.challenge_week_id = %(challenge_week_id)s
      AND (h.previous_tier IS NULL OR SUBSTRING(h.tier FROM 2)::int > h.previous_tier)
    ORDER BY h.time, h.id
    """
    parameters = {'challenge_week_id': challenge_week_id}
    return fetchall(sql, parameters) if execute else (sql, parameters)
