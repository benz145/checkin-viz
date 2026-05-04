from base_queries import get_current_challenge_week
from helpers import fetchone, with_psycopg
import logging
import random


def number_of_non_green_weeks_before_this_one(challenge_id):
    sql = """
  select count(*) from challenge_weeks
       where
       challenge_id = %s
       /* the end is after the last green week or the first week */
       and "end" > coalesce(
           (select "end" from challenge_weeks where green = true and challenge_id = %s order by "end" desc limit 1),
           (select "end" from challenge_weeks where challenge_id = %s order by "end" asc limit 1)
        )
       /* the end is before now */
       and "end" < current_date
  """
    return fetchone(sql, [challenge_id, challenge_id, challenge_id]).count


def determine_if_green():
    challenge_week = get_current_challenge_week()

    # If this is a bye week, set green to false and return
    if challenge_week.bye_week:
        def set_green(conn, cur):
            cur.execute(
                "update challenge_weeks set green = false where id = %s",
                [challenge_week.id],
            )
        with_psycopg(set_green)
        return False

    if challenge_week.green is None:
        
        num_non_green = number_of_non_green_weeks_before_this_one(
            challenge_week.challenge_id
        )
        logging.info(
            "there were %s weeks before this one that werent green", num_non_green
        )
        green = random.randint(0, 100) < 20 * num_non_green
        logging.debug("is is green %s", green)

        def set_green(conn, cur):
            cur.execute(
                "update challenge_weeks set green = %s where id = %s",
                [green, challenge_week.id],
            )

        with_psycopg(set_green)

        return green

    return challenge_week.green
