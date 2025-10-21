from helpers import fetchall


def get_medal_log(challenge_week_id):
    sql = """
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
     m.checkin_id
 FROM
     medals m
 JOIN
     challengers c ON c.id = m.challenger_id
 JOIN
     checkins ci ON ci.id = m.checkin_id
 LEFT JOIN
     checkins stolen_ci ON stolen_ci.id = m.steal
 LEFT JOIN
     challengers stolen_c ON stolen_c.id = stolen_ci.challenger
 WHERE
     m.challenge_week_id = %s
 ORDER BY
     m.created_at;
"""
    return fetchall(sql, [challenge_week_id])
