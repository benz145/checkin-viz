import os
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace


os.environ.setdefault("DB_CONNECT_STRING", "postgresql://postgres:password@localhost/projects")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from auto_knockout import (
    apply_auto_knockout_for_week,
    first_missed_day,
    get_participants_for_week,
)


def challenge_week(green=False):
    return SimpleNamespace(
        challenge_id=1,
        challenge_week_id=10,
        start=date(2026, 4, 27),
        green=green,
    )


def participant(
    *,
    checkin_count,
    checked_in_days=None,
    mulligan=None,
    challenger_id=1,
    name="Test User",
):
    return SimpleNamespace(
        id=challenger_id,
        name=name,
        tz="America/New_York",
        mulligan=mulligan,
        checkin_count=checkin_count,
        checked_in_days=checked_in_days or [],
    )


class FakeCursor:
    def __init__(self):
        self.queries = []
        self.next_checkin_id = 123

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchone(self):
        return SimpleNamespace(id=self.next_checkin_id)

    def fetchall(self):
        return []


def query_texts(cur):
    return [sql for sql, _ in cur.queries]


class AutoKnockoutTests(unittest.TestCase):
    def test_no_action_when_normal_week_requirement_is_met(self):
        cur = FakeCursor()

        events = apply_auto_knockout_for_week(
            cur,
            challenge_week(),
            [participant(checkin_count=2, checked_in_days=["Monday", "Tuesday"])],
        )

        self.assertEqual(events, [])
        self.assertEqual(cur.queries, [])

    def test_mulligan_inserted_when_below_requirement_without_mulligan(self):
        cur = FakeCursor()

        events = apply_auto_knockout_for_week(
            cur,
            challenge_week(),
            [participant(checkin_count=1, checked_in_days=["Monday"])],
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "mulligan")
        self.assertEqual(events[0].mulligan_checkin_id, 123)
        self.assertEqual(events[0].mulligan_day, "Tuesday")
        self.assertIn("insert into checkins", query_texts(cur)[0])
        self.assertIn("set mulligan", query_texts(cur)[1])

    def test_knockout_set_when_below_requirement_with_existing_mulligan(self):
        cur = FakeCursor()

        events = apply_auto_knockout_for_week(
            cur,
            challenge_week(),
            [participant(checkin_count=1, checked_in_days=["Monday"], mulligan=99)],
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "knockout")
        self.assertIn("set knocked_out = true", query_texts(cur)[0])

    def test_zero_checkin_challenger_gets_mulligan_on_first_day(self):
        cur = FakeCursor()

        events = apply_auto_knockout_for_week(
            cur,
            challenge_week(),
            [participant(checkin_count=0)],
        )

        self.assertEqual(events[0].action, "mulligan")
        self.assertEqual(events[0].mulligan_day, "Monday")

    def test_green_week_requires_five_checkins(self):
        cur = FakeCursor()

        events = apply_auto_knockout_for_week(
            cur,
            challenge_week(green=True),
            [
                participant(
                    checkin_count=4,
                    checked_in_days=["Monday", "Tuesday", "Wednesday", "Thursday"],
                    mulligan=99,
                )
            ],
        )

        self.assertEqual(events[0].action, "knockout")
        self.assertEqual(events[0].required_checkins, 5)

    def test_first_missed_day_skips_checked_in_days(self):
        day_name, missing_date = first_missed_day(
            date(2026, 4, 27),
            ["Monday", "Wednesday"],
        )

        self.assertEqual(day_name, "Tuesday")
        self.assertEqual(missing_date, date(2026, 4, 28))

    def test_participant_query_skips_knocked_out_challengers(self):
        cur = FakeCursor()

        get_participants_for_week(cur, challenge_id=1, challenge_week_id=10)

        self.assertIn("cc.knocked_out = false", query_texts(cur)[0])


if __name__ == "__main__":
    unittest.main()
