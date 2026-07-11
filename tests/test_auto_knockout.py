import os
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


os.environ.setdefault("DB_CONNECT_STRING", "postgresql://postgres:password@localhost/projects")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from auto_knockout import (
    AutoKnockoutEvent,
    apply_auto_knockout_for_week,
    build_auto_knockout_alert_message,
    build_auto_knockout_alerts_for_week,
    build_auto_knockout_reconciliation_message,
    first_missed_day,
    get_alert_participants_for_week,
    get_participants_for_week,
    get_previous_challenge_week,
    run_auto_knockout,
    should_send_first_no_slack_warning,
)


def challenge_week(green=False, bye_week=False):
    return SimpleNamespace(
        challenge_id=1,
        challenge_week_id=10,
        start=date(2026, 4, 27),
        end=date(2026, 5, 3),
        green=green,
        bye_week=bye_week,
    )


def participant(
    *,
    checkin_count,
    checked_in_days=None,
    mulligan=None,
    challenger_id=1,
    name="Test User",
    current_day_checked_in=False,
    mulligan_challenge_week_id=None,
):
    return SimpleNamespace(
        id=challenger_id,
        name=name,
        discord_id=str(1000 + challenger_id),
        tz="America/New_York",
        mulligan=mulligan,
        checkin_count=checkin_count,
        checked_in_days=checked_in_days or [],
        current_day_checked_in=current_day_checked_in,
        mulligan_challenge_week_id=mulligan_challenge_week_id,
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


class FakeRunCursor:
    def __init__(self, challenge_week_result):
        self.queries = []
        self.challenge_week_result = challenge_week_result

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchone(self):
        return self.challenge_week_result

    def fetchall(self):
        raise AssertionError("participants should not be fetched")


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
        self.assertEqual(events[0].discord_id, "1001")
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
        self.assertEqual(events[0].discord_id, "1001")
        self.assertIn("set knocked_out = true", query_texts(cur)[0])

    def test_rerun_skips_challenger_with_mulligan_from_same_week(self):
        cur = FakeCursor()

        events = apply_auto_knockout_for_week(
            cur,
            challenge_week(),
            [
                participant(
                    checkin_count=1,
                    checked_in_days=["Monday"],
                    mulligan=123,
                    mulligan_challenge_week_id=10,
                )
            ],
        )

        self.assertEqual(events, [])
        self.assertEqual(cur.queries, [])

    def test_prior_week_mulligan_still_allows_knockout(self):
        cur = FakeCursor()

        events = apply_auto_knockout_for_week(
            cur,
            challenge_week(),
            [
                participant(
                    checkin_count=1,
                    checked_in_days=["Monday"],
                    mulligan=123,
                    mulligan_challenge_week_id=9,
                )
            ],
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

        self.assertIn("ch.discord_id", query_texts(cur)[0])
        self.assertIn("cc.knocked_out = false", query_texts(cur)[0])

    def test_participant_query_exposes_mulligan_challenge_week(self):
        cur = FakeCursor()

        get_participants_for_week(cur, challenge_id=1, challenge_week_id=10)

        self.assertIn(
            "mulligan_checkin.challenge_week_id as mulligan_challenge_week_id",
            query_texts(cur)[0],
        )
        self.assertIn("left join checkins mulligan_checkin", query_texts(cur)[0])

    def test_previous_challenge_week_only_targets_week_ending_yesterday(self):
        cur = FakeCursor()

        get_previous_challenge_week(cur)

        self.assertIn('cw."end" = (', query_texts(cur)[0])
        self.assertIn("interval '1 day'", query_texts(cur)[0])

    def test_auto_knockout_skips_bye_week(self):
        captured = {}

        def fake_with_psycopg(fn):
            cur = FakeRunCursor(challenge_week(bye_week=True))
            captured["cur"] = cur
            return fn(None, cur)

        with patch.dict(
            sys.modules,
            {"helpers": SimpleNamespace(with_psycopg=fake_with_psycopg)},
        ):
            events = run_auto_knockout()

        self.assertEqual(events, [])
        self.assertEqual(len(captured["cur"].queries), 1)

    def test_normal_week_alert_when_no_mulligan_challenger_has_no_slack(self):
        events = build_auto_knockout_alerts_for_week(
            challenge_week(),
            date(2026, 5, 2),
            [participant(checkin_count=0, mulligan=99)],
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "warning")
        self.assertEqual(events[0].remaining_checkin_days, ("Saturday", "Sunday"))
        self.assertFalse(events[0].has_mulligan_available)

    def test_green_week_alert_uses_five_checkin_requirement(self):
        events = build_auto_knockout_alerts_for_week(
            challenge_week(green=True),
            date(2026, 5, 2),
            [
                participant(
                    checkin_count=3,
                    checked_in_days=["Monday", "Tuesday", "Wednesday"],
                    mulligan=99,
                )
            ],
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].required_checkins, 5)
        self.assertEqual(events[0].remaining_checkin_days, ("Saturday", "Sunday"))

    def test_alert_skipped_when_challenger_still_has_slack(self):
        events = build_auto_knockout_alerts_for_week(
            challenge_week(green=True),
            date(2026, 4, 29),
            [participant(checkin_count=1, checked_in_days=["Monday"])],
        )

        self.assertEqual(events, [])

    def test_alert_skipped_after_user_responds_to_first_warning(self):
        events = build_auto_knockout_alerts_for_week(
            challenge_week(green=True),
            date(2026, 4, 30),
            [participant(checkin_count=1, checked_in_days=["Wednesday"], mulligan=99)],
        )

        self.assertEqual(events, [])

    def test_normal_week_alert_skipped_after_user_responds_to_first_warning(self):
        events = build_auto_knockout_alerts_for_week(
            challenge_week(),
            date(2026, 5, 3),
            [participant(checkin_count=1, checked_in_days=["Saturday"], mulligan=99)],
        )

        self.assertEqual(events, [])

    def test_first_no_slack_warning_requires_latest_miss_to_create_no_slack(self):
        week = challenge_week(green=True)

        self.assertTrue(
            should_send_first_no_slack_warning(
                week,
                date(2026, 4, 29),
                required_checkins=5,
                checked_in_days=[],
            )
        )
        self.assertFalse(
            should_send_first_no_slack_warning(
                week,
                date(2026, 4, 30),
                required_checkins=5,
                checked_in_days=["Wednesday"],
            )
        )

    def test_alert_query_skips_knocked_out_and_t0_challengers(self):
        cur = FakeCursor()

        get_alert_participants_for_week(
            cur,
            challenge_id=1,
            challenge_week_id=10,
            run_day="Saturday",
        )

        self.assertIn("cc.knocked_out = false", query_texts(cur)[0])
        self.assertIn("coalesce(cc.tier, '') != 'T0'", query_texts(cur)[0])
        self.assertIn("checked_in_days", query_texts(cur)[0])

    def test_alert_message_mentions_discord_ids_and_remaining_days(self):
        events = build_auto_knockout_alerts_for_week(
            challenge_week(),
            date(2026, 5, 2),
            [participant(checkin_count=0, mulligan=99)],
        )

        message = build_auto_knockout_alert_message(events)

        self.assertIn("<@1001>", message)
        self.assertIn("Saturday and Sunday", message)
        self.assertIn("to avoid knockout", message)

    def test_alert_message_mentions_mulligan_risk_when_mulligan_available(self):
        events = build_auto_knockout_alerts_for_week(
            challenge_week(),
            date(2026, 5, 2),
            [participant(checkin_count=0, mulligan=None)],
        )

        message = build_auto_knockout_alert_message(events)

        self.assertIn("to avoid using a mulligan or being knocked out", message)

    def test_reconciliation_message_mentions_mulligan_used(self):
        message = build_auto_knockout_reconciliation_message(
            [
                AutoKnockoutEvent(
                    action="mulligan",
                    challenge_id=1,
                    challenger_id=1,
                    name="Test User",
                    required_checkins=2,
                    checkin_count=1,
                    challenge_week_id=10,
                    discord_id="123",
                    mulligan_checkin_id=456,
                    mulligan_day="Tuesday",
                )
            ]
        )

        self.assertIn("## Mulligans used", message)
        self.assertIn(
            "<@123> was saved from knockout by their mulligan on Tuesday.",
            message,
        )

    def test_reconciliation_message_mentions_knockout(self):
        message = build_auto_knockout_reconciliation_message(
            [
                AutoKnockoutEvent(
                    action="knockout",
                    challenge_id=1,
                    challenger_id=1,
                    name="Test User",
                    required_checkins=5,
                    checkin_count=3,
                    challenge_week_id=10,
                    discord_id="123",
                )
            ]
        )

        self.assertIn("## Knockouts", message)
        self.assertIn(
            "<@123> has been knocked out with 3/5 T1+ check-ins this week.",
            message,
        )


if __name__ == "__main__":
    unittest.main()
