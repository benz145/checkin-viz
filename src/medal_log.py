from helpers import fetchall
from personal_records import PERSONAL_HISTORY_CTE


def get_medal_log(challenge_week_id):
    sql = f"""WITH {PERSONAL_HISTORY_CTE}
SELECT
     m.medal AS medal_name,
     m.emoji AS medal_emoji,
     c.name AS challenger_name,
     c.discord_id as discord_id,
     ci.tier AS checkin_tier,
     ci.time AS checkin_time,
     stolen_c.name AS stolen_checkin_challenger_name,
     stolen_c.discord_id as stolen_discord_id,
     stolen_ci.tier as stolen_checkin_tier,
     personal_previous.tier AS personal_previous_tier,
     personal_previous.record_date AS personal_previous_date,
     CASE m.medal
         WHEN 'highest_tier_personal_season' THEN current_history.record_season
         WHEN 'highest_tier_personal_year' THEN current_history.record_year::text
     END AS personal_period_label,
     m.checkin_id
 FROM
     medals m
 JOIN
     challengers c ON c.id = m.challenger_id
 JOIN
     checkins ci ON ci.id = m.checkin_id
 LEFT JOIN personal_period_history current_history ON current_history.id = ci.id
 LEFT JOIN
     checkins stolen_ci ON stolen_ci.id = m.steal
 LEFT JOIN
     challengers stolen_c ON stolen_c.id = stolen_ci.challenger
 LEFT JOIN LATERAL (
     SELECT previous.tier,
            previous.record_date
     FROM personal_period_history previous
     WHERE (
         m.medal = 'highest_tier_personal'
         OR (m.medal = 'highest_tier_personal_season' AND previous.record_season = current_history.record_season)
         OR (m.medal = 'highest_tier_personal_year' AND previous.record_year = current_history.record_year)
     )
       AND previous.challenger = ci.challenger
       AND (previous.time, previous.id) < (ci.time, ci.id)
       AND previous.tier ~ '^T[0-9]+$'
       AND NOT EXISTS (
           SELECT 1 FROM challenger_challenges cc WHERE cc.mulligan = previous.id
       )
     ORDER BY SUBSTRING(previous.tier FROM 2)::INT DESC, previous.time, previous.id
     LIMIT 1
 ) personal_previous ON TRUE
 WHERE
     m.challenge_week_id = %s
 ORDER BY
     m.created_at;
"""
    return fetchall(sql, [challenge_week_id])
