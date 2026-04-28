from base_queries import get_current_challenge_week
from helpers import fetchone, with_psycopg
import logging
import random


def number_of_non_green_weeks_before_week(challenge_id, week_start):
    sql = """
  select count(*) from challenge_weeks
       where
       challenge_id = %s
       /* the end is after the last green week or the first week */
       and "end" > coalesce(
           (select "end" from challenge_weeks where green = true and challenge_id = %s order by "end" desc limit 1),
           (select "end" from challenge_weeks where challenge_id = %s order by "end" asc limit 1)
        )
       /* the end is before the evaluated week */
       and "end" < %s
  """
    return fetchone(sql, [challenge_id, challenge_id, challenge_id, week_start]).count


def number_of_non_green_weeks_before_this_one(challenge_id):
    challenge_week = get_current_challenge_week()
    return number_of_non_green_weeks_before_week(challenge_id, challenge_week.start)


def challenge_week_id(challenge_week):
    if hasattr(challenge_week, "id"):
        return challenge_week.id
    return challenge_week.challenge_week_id


def determine_if_green_for_week(challenge_week):
    # If this is a bye week, set green to false and return
    if challenge_week.bye_week:
        def set_green(conn, cur):
            cur.execute(
                "update challenge_weeks set green = false where id = %s",
                [challenge_week_id(challenge_week)],
            )
        with_psycopg(set_green)
        return False

    if challenge_week.green is None:
        num_non_green = number_of_non_green_weeks_before_week(
            challenge_week.challenge_id,
            challenge_week.start,
        )
        logging.info(
            "there were %s weeks before this one that werent green", num_non_green
        )
        green = random.randint(0, 100) < 20 * num_non_green
        logging.debug("is is green %s", green)

        def set_green(conn, cur):
            cur.execute(
                "update challenge_weeks set green = %s where id = %s",
                [green, challenge_week_id(challenge_week)],
            )

        with_psycopg(set_green)

        return green

    return challenge_week.green


def determine_if_green():
    challenge_week = get_current_challenge_week()
    return determine_if_green_for_week(challenge_week)
