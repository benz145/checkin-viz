from base_queries import get_current_challenge_week
from helpers import fetchone, with_psycopg
import logging
import random


def number_of_non_green_weeks_before_this_one(challenge_id):
    sql = """
    select count(*) from challenge_weeks
      where 
      challenge_id = %s
      and "end" >= (
          select "end" from challenge_weeks where "end" <= current_date - 7 and green = true order by "end" desc limit 1
      )
      and "end" <= current_date - 7;
  """
    return fetchone(sql, [challenge_id]).count


def determine_if_green():
    challenge_week = get_current_challenge_week()
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
