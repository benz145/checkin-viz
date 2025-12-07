import itertools
import os
import logging
from helpers import fetchall

def score(tier, rule_set):
    if rule_set == 1:
        return version_1_score(tier)
    return version_2_score(tier)


def version_1_score(tier):
    match tier:
        case "T0":
            return 0
        case "T1":
            return 0
        case "T2":
            return 1
        case "T3":
            return 1.2
        case "T4":
            return 1.5
    return 1


def version_2_score(tier):
    if tier == "T0":
        return 0
    number = int(tier.lstrip("T")) if isinstance(tier, str) else tier
    points = 0.9 + 0.1 * number
    logging.info("Tier: %s Number: %s Points: %s", tier, number, points)
    return points


def calculate_total_score(challenge_id):
    query = """
        select 
            Max(ltrim(checkins.tier, 'T')::INT) as max,
            checkins.name,
            checkins.challenge_week_id,
            challenges.rule_set
        from checkins
        join challenge_weeks
            on checkins.challenge_week_id = challenge_weeks.id
        join challenges
            on challenge_weeks.challenge_id = challenges.id
        where 
           (
               challenge_weeks.bye_week != true
               or challenge_weeks.bye_week is null
           )
           and challenge_weeks.challenge_id = %s
           and challenges.id = %s
           and checkins.tier != 'T0'
        group by
            date(checkins.time at time zone 'America/New_York'),
            checkins.name,
            checkins.challenge_week_id,
            challenges.rule_set
        order by checkins.challenge_week_id
    """
    checkins_this_challenge = fetchall(query, (challenge_id, challenge_id))
    if len(checkins_this_challenge) == 0:
        return {}
    version = checkins_this_challenge[0].rule_set
    logging.info("Version: %s", version)
    nums = [
        {
            "name": n.name,
            "value": score(n.max, version),
            "week": n.challenge_week_id,
            "tier": n.max,
        }
        for n in checkins_this_challenge
    ]
    names = set(n["name"] for n in nums)
    weeks = [list(week) for w, week in itertools.groupby(nums, key=lambda x: x["week"])]
    num_weeks = len(list(weeks))
    result = {
        n: sum(
            round(
                sum(
                    sorted(
                        (name["value"] for name in week if name["name"] == n),
                        reverse=True,
                    )[:5]
                ),
                4,
            )
            for week in weeks
        )
        for n in names
    }
    logging.info("Total Points: %s", result)
    return result
