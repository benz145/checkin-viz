from huey import crontab, SqliteHuey
from green import determine_if_green
from mulligan import check_last_week_for_mulligan_necessity, insert_mulligan_for
import logging

# --- Existing tasks config ---
logging.basicConfig(level="DEBUG")
huey = SqliteHuey()


@huey.task()
def example_task(n):
    print("-- RUNNING EXAMPLE TASK: CALLED WITH n=%s --" % n)
    return n


@huey.periodic_task(crontab(hour="8", day="1"))
def is_green_week():
    print("Determining if green")
    determine_if_green()


@huey.periodic_task(crontab(hour="8", day="1"))
def check_mulligans():
    logging.info("checking for mulligans")
    last_week_checkins = check_last_week_for_mulligan_necessity()
    logging.info("last week: %s" % last_week_checkins)

    is_green_week = last_week_checkins[0].green

    needing_of_mulligan = [
        (x.name, x.cwid)
        for x in last_week_checkins
        if x.count < 5 and is_green_week or x.count < 2
    ]
    logging.info("needs a mulligan: %s" % needing_of_mulligan)
    for name, cwid in needing_of_mulligan:
        insert_mulligan_for(name, cwid)
