import os
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


os.environ.setdefault("DB_CONNECT_STRING", "postgresql://postgres:password@localhost/projects")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from auto_knockout import (
    AutoKnockoutEvent,
    build_auto_knockout_alert_message,
    build_auto_knockout_reconciliation_message,
    decide_auto_knockout,
    evaluate_auto_knockout_for_week,
    get_challenge_weeks_for_run,
    get_participants_for_week,
    latest_missed_elapsed_day,
    run_auto_knockout,
)


def challenge_week(green=False, bye_week=False, challenge_week_id=10):
    return SimpleNamespace(
        challenge_id=1,
        challenge_week_id=challenge_week_id,
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
    mulligan_day=None,
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
        mulligan_day=mulligan_day,
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


class SequencedCursor(FakeCursor):
    def __init__(self, results):
        super().__init__()
        self.results = list(results)

    def fetchall(self):
        return self.results.pop(0)


def query_texts(cur):
    return [sql for sql, _ in cur.queries]


def actions(events):
    return [event.action for event in events]


def reconciled_week_ids(cur):
    return [
        params[0]
        for sql, params in cur.queries
        if "set auto_knockout_reconciled_at = current_timestamp" in sql
    ]


class DecisionTests(unittest.TestCase):
    def test_decision_uses_remaining_days_and_one_available_mulligan(self):
        cases = [
            (0, 2, 2, False, "none"),
            (0, 2, 1, True, "mulligan"),
            (0, 2, 1, False, "knockout"),
            (3, 5, 1, True, "mulligan"),
            (3, 5, 1, False, "knockout"),
            (5, 5, 0, False, "none"),
        ]

        for checkins, required, remaining, mulligan_available, expected in cases:
            with self.subTest(
                checkins=checkins,
                required=required,
                remaining=remaining,
                mulligan_available=mulligan_available,
            ):
                self.assertEqual(
                    decide_auto_knockout(
                        checkins,
                        required,
                        remaining,
                        mulligan_available,
                    ),
                    expected,
                )

    def test_latest_missed_elapsed_day_excludes_current_day(self):
        day_name, missing_date = latest_missed_elapsed_day(
            date(2026, 4, 27),
            date(2026, 5, 3),
            ["Monday", "Wednesday", "Friday"],
        )

        self.assertEqual(day_name, "Saturday")
        self.assertEqual(missing_date, date(2026, 5, 2))


class NormalWeekDailyTests(unittest.TestCase):
    def test_saturday_warning_when_both_days_are_required(self):
        for mulligan, has_mulligan_available in ((None, True), (99, False)):
            with self.subTest(mulligan=mulligan):
                cur = FakeCursor()
                events = evaluate_auto_knockout_for_week(
                    cur,
                    challenge_week(),
                    date(2026, 5, 2),
                    [participant(checkin_count=0, mulligan=mulligan)],
                )

                self.assertEqual(actions(events), ["warning"])
                self.assertEqual(
                    events[0].remaining_checkin_days,
                    ("Saturday", "Sunday"),
                )
                self.assertEqual(
                    events[0].has_mulligan_available,
                    has_mulligan_available,
                )
                self.assertEqual(cur.queries, [])

    def test_sunday_applies_mulligan_for_saturday_and_warns_for_sunday(self):
        cur = FakeCursor()

        events = evaluate_auto_knockout_for_week(
            cur,
            challenge_week(),
            date(2026, 5, 3),
            [participant(checkin_count=0)],
        )

        self.assertEqual(actions(events), ["mulligan", "warning"])
        self.assertEqual(events[0].mulligan_day, "Saturday")
        self.assertEqual(events[1].remaining_checkin_days, ("Sunday",))
        self.assertEqual(events[1].checkin_count, 1)
        self.assertIn("insert into checkins", query_texts(cur)[0])
        self.assertIn("set mulligan", query_texts(cur)[1])

    def test_sunday_knocks_out_when_recovery_is_impossible(self):
        cur = FakeCursor()

        events = evaluate_auto_knockout_for_week(
            cur,
            challenge_week(),
            date(2026, 5, 3),
            [participant(checkin_count=0, mulligan=99)],
        )

        self.assertEqual(actions(events), ["knockout"])
        self.assertIn("set knocked_out = true", query_texts(cur)[0])

    def test_current_day_checkin_is_counted_and_not_left_as_an_opportunity(self):
        cur = FakeCursor()

        events = evaluate_auto_knockout_for_week(
            cur,
            challenge_week(),
            date(2026, 5, 3),
            [
                participant(
                    checkin_count=2,
                    checked_in_days=["Saturday", "Sunday"],
                    mulligan=99,
                    current_day_checked_in=True,
                )
            ],
        )

        self.assertEqual(events, [])
        self.assertEqual(cur.queries, [])

    def test_monday_finalization_knocks_out_after_mulligan_and_sunday_miss(self):
        cur = FakeCursor()

        events = evaluate_auto_knockout_for_week(
            cur,
            challenge_week(),
            date(2026, 5, 4),
            [
                participant(
                    checkin_count=1,
                    checked_in_days=["Saturday"],
                    mulligan=123,
                    mulligan_challenge_week_id=10,
                )
            ],
        )

        self.assertEqual(actions(events), ["knockout"])

    def test_monday_finalization_applies_mulligan_for_one_checkin_shortfall(self):
        cur = FakeCursor()

        events = evaluate_auto_knockout_for_week(
            cur,
            challenge_week(),
            date(2026, 5, 4),
            [participant(checkin_count=1, checked_in_days=["Monday"])],
        )

        self.assertEqual(actions(events), ["mulligan"])
        self.assertEqual(events[0].mulligan_day, "Sunday")
        self.assertNotIn("set knocked_out = true", " ".join(query_texts(cur)))

    def test_monday_finalization_knocks_out_at_zero_of_two(self):
        cur = FakeCursor()

        events = evaluate_auto_knockout_for_week(
            cur,
            challenge_week(),
            date(2026, 5, 4),
            [participant(checkin_count=0)],
        )

        self.assertEqual(actions(events), ["knockout"])
        self.assertIn("set knocked_out = true", query_texts(cur)[0])
        self.assertNotIn("insert into checkins", " ".join(query_texts(cur)))

    def test_invalid_mulligan_candidate_aborts_reconciliation(self):
        cur = FakeCursor()

        with self.assertLogs(level="ERROR") as logs:
            with self.assertRaisesRegex(RuntimeError, "Failed to apply mulligan"):
                evaluate_auto_knockout_for_week(
                    cur,
                    challenge_week(),
                    date(2026, 5, 4),
                    [
                        participant(
                            challenger_id=1,
                            checkin_count=1,
                            checked_in_days=[
                                "Monday",
                                "Tuesday",
                                "Wednesday",
                                "Thursday",
                                "Friday",
                                "Saturday",
                                "Sunday",
                            ],
                        ),
                        participant(
                            challenger_id=2,
                            checkin_count=0,
                            mulligan=99,
                        ),
                    ],
                )

        self.assertIn("no elapsed day is missing", logs.output[0])
        self.assertEqual(cur.queries, [])

    def test_sunday_does_not_repeat_saturday_no_slack_warning(self):
        events = evaluate_auto_knockout_for_week(
            FakeCursor(),
            challenge_week(),
            date(2026, 5, 3),
            [
                participant(
                    checkin_count=1,
                    checked_in_days=["Saturday"],
                    mulligan=99,
                )
            ],
        )

        self.assertEqual(events, [])

    def test_rerun_after_mulligan_is_a_noop(self):
        first_cur = FakeCursor()
        first_events = evaluate_auto_knockout_for_week(
            first_cur,
            challenge_week(),
            date(2026, 5, 3),
            [participant(checkin_count=0)],
        )
        rerun_cur = FakeCursor()
        rerun_events = evaluate_auto_knockout_for_week(
            rerun_cur,
            challenge_week(),
            date(2026, 5, 3),
            [
                participant(
                    checkin_count=1,
                    checked_in_days=["Saturday"],
                    mulligan=123,
                    mulligan_challenge_week_id=10,
                    mulligan_day="Saturday",
                )
            ],
        )

        self.assertEqual(actions(first_events), ["mulligan", "warning"])
        self.assertEqual(rerun_events, [])
        self.assertEqual(rerun_cur.queries, [])


class GreenWeekDailyTests(unittest.TestCase):
    def test_wednesday_warns_when_every_remaining_day_is_required(self):
        events = evaluate_auto_knockout_for_week(
            FakeCursor(),
            challenge_week(green=True),
            date(2026, 4, 29),
            [participant(checkin_count=0)],
        )

        self.assertEqual(actions(events), ["warning"])
        self.assertEqual(
            events[0].remaining_checkin_days,
            ("Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
        )

    def test_thursday_uses_mulligan_then_warns_for_remaining_days(self):
        events = evaluate_auto_knockout_for_week(
            FakeCursor(),
            challenge_week(green=True),
            date(2026, 4, 30),
            [participant(checkin_count=0)],
        )

        self.assertEqual(actions(events), ["mulligan", "warning"])
        self.assertEqual(events[0].mulligan_day, "Wednesday")
        self.assertEqual(
            events[1].remaining_checkin_days,
            ("Thursday", "Friday", "Saturday", "Sunday"),
        )

    def test_thursday_knocks_out_without_mulligan(self):
        events = evaluate_auto_knockout_for_week(
            FakeCursor(),
            challenge_week(green=True),
            date(2026, 4, 30),
            [participant(checkin_count=0, mulligan=99)],
        )

        self.assertEqual(actions(events), ["knockout"])

    def test_response_to_first_warning_is_not_warned_again(self):
        events = evaluate_auto_knockout_for_week(
            FakeCursor(),
            challenge_week(green=True),
            date(2026, 4, 30),
            [
                participant(
                    checkin_count=1,
                    checked_in_days=["Wednesday"],
                    mulligan=99,
                )
            ],
        )

        self.assertEqual(events, [])

    def test_green_week_requirement_met_has_no_action(self):
        events = evaluate_auto_knockout_for_week(
            FakeCursor(),
            challenge_week(green=True),
            date(2026, 5, 3),
            [
                participant(
                    checkin_count=5,
                    checked_in_days=[
                        "Monday",
                        "Tuesday",
                        "Wednesday",
                        "Saturday",
                        "Sunday",
                    ],
                    current_day_checked_in=True,
                )
            ],
        )

        self.assertEqual(events, [])


class QueryAndOrchestrationTests(unittest.TestCase):
    def test_challenge_query_includes_current_and_unreconciled_ended_weeks(self):
        cur = FakeCursor()
        run_date = date(2026, 5, 4)

        get_challenge_weeks_for_run(cur, run_date)

        sql = query_texts(cur)[0]
        self.assertIn("select %s::date as run_date", sql)
        self.assertIn("rc.run_date between cw.start and cw.\"end\"", sql)
        self.assertIn('cw."end" < rc.run_date', sql)
        self.assertIn("cw.auto_knockout_reconciled_at is null", sql)
        self.assertNotIn("and exists (", sql)
        self.assertNotIn("interval '7 days'", sql)
        self.assertIn("order by sort_order, start", sql)
        self.assertNotIn("extract(isodow from rc.run_date)", sql)
        self.assertEqual(cur.queries[0][1], (run_date,))

    def test_participant_query_exposes_daily_decision_fields(self):
        cur = FakeCursor()

        get_participants_for_week(cur, 1, 10, "Sunday")

        sql = query_texts(cur)[0]
        self.assertIn("cc.knocked_out = false", sql)
        self.assertIn("coalesce(cc.tier, '') != 'T0'", sql)
        self.assertIn("where c.tier != 'T0'", sql)
        self.assertIn("current_day_checked_in", sql)
        self.assertIn("mulligan_checkin.day_of_week as mulligan_day", sql)
        self.assertEqual(cur.queries[0][1], ("Sunday", 10, 1))

    def test_daily_runner_processes_previous_then_current_week_on_monday(self):
        previous = challenge_week(challenge_week_id=10)
        current = SimpleNamespace(
            challenge_id=1,
            challenge_week_id=11,
            start=date(2026, 5, 4),
            end=date(2026, 5, 10),
            green=False,
            bye_week=False,
        )
        captured = {}

        def fake_with_psycopg(fn):
            cur = SequencedCursor([[previous, current], [], []])
            captured["cur"] = cur
            return fn(None, cur)

        class MondayDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 5, 4, 14, 5, tzinfo=tz)

        with patch.dict(
            sys.modules,
            {"helpers": SimpleNamespace(with_psycopg=fake_with_psycopg)},
        ), patch("auto_knockout.datetime", MondayDatetime):
            events = run_auto_knockout()

        self.assertEqual(events, [])
        participant_params = [
            params
            for sql, params in captured["cur"].queries
            if "from challenger_challenges cc" in sql and "ch.discord_id" in sql
        ]
        self.assertEqual(participant_params, [(None, 10, 1), ("Monday", 11, 1)])
        self.assertEqual(reconciled_week_ids(captured["cur"]), [10])
        marker_sql = next(
            sql
            for sql, _ in captured["cur"].queries
            if "set auto_knockout_reconciled_at = current_timestamp" in sql
        )
        self.assertIn("and auto_knockout_reconciled_at is null", marker_sql)

    def test_daily_runner_does_not_mark_current_week_reconciled(self):
        current = SimpleNamespace(
            challenge_id=1,
            challenge_week_id=11,
            start=date(2026, 5, 4),
            end=date(2026, 5, 10),
            green=False,
            bye_week=False,
        )
        captured = {}

        def fake_with_psycopg(fn):
            cur = SequencedCursor([[current], []])
            captured["cur"] = cur
            return fn(None, cur)

        class TuesdayDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 5, 5, 14, 5, tzinfo=tz)

        with patch.dict(
            sys.modules,
            {"helpers": SimpleNamespace(with_psycopg=fake_with_psycopg)},
        ), patch("auto_knockout.datetime", TuesdayDatetime):
            events = run_auto_knockout()

        self.assertEqual(events, [])
        self.assertEqual(reconciled_week_ids(captured["cur"]), [])

    def test_daily_runner_catches_up_unresolved_week_on_tuesday(self):
        previous = challenge_week(challenge_week_id=10)
        current = SimpleNamespace(
            challenge_id=1,
            challenge_week_id=11,
            start=date(2026, 5, 4),
            end=date(2026, 5, 10),
            green=False,
            bye_week=False,
        )

        captured = {}

        def fake_with_psycopg(fn):
            cur = SequencedCursor(
                [
                    [previous, current],
                    [
                        participant(
                            checkin_count=1,
                            checked_in_days=["Saturday"],
                            mulligan=123,
                            mulligan_challenge_week_id=10,
                        )
                    ],
                    [],
                ]
            )
            captured["cur"] = cur
            return fn(None, cur)

        class TuesdayDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 5, 5, 14, 5, tzinfo=tz)

        with patch.dict(
            sys.modules,
            {"helpers": SimpleNamespace(with_psycopg=fake_with_psycopg)},
        ), patch("auto_knockout.datetime", TuesdayDatetime):
            events = run_auto_knockout()

        self.assertEqual(actions(events), ["knockout"])
        self.assertEqual(events[0].challenge_week_id, 10)
        self.assertEqual(reconciled_week_ids(captured["cur"]), [10])

    def test_daily_runner_processes_multiple_ended_weeks_oldest_first(self):
        oldest = challenge_week(challenge_week_id=9)
        oldest.start = date(2026, 4, 20)
        oldest.end = date(2026, 4, 26)
        recent = challenge_week(challenge_week_id=10)
        current = SimpleNamespace(
            challenge_id=1,
            challenge_week_id=11,
            start=date(2026, 5, 4),
            end=date(2026, 5, 10),
            green=False,
            bye_week=False,
        )
        captured = {}

        def fake_with_psycopg(fn):
            cur = SequencedCursor(
                [
                    [oldest, recent, current],
                    [participant(checkin_count=2)],
                    [participant(checkin_count=0, mulligan=99)],
                    [],
                ]
            )
            captured["cur"] = cur
            return fn(None, cur)

        class TuesdayDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 5, 5, 14, 5, tzinfo=tz)

        with patch.dict(
            sys.modules,
            {"helpers": SimpleNamespace(with_psycopg=fake_with_psycopg)},
        ), patch("auto_knockout.datetime", TuesdayDatetime):
            events = run_auto_knockout()

        self.assertEqual(actions(events), ["knockout"])
        self.assertEqual(events[0].challenge_week_id, 10)
        participant_params = [
            params
            for sql, params in captured["cur"].queries
            if "from challenger_challenges cc" in sql and "ch.discord_id" in sql
        ]
        self.assertEqual(
            participant_params,
            [(None, 9, 1), (None, 10, 1), ("Tuesday", 11, 1)],
        )
        self.assertEqual(reconciled_week_ids(captured["cur"]), [9, 10])

    def test_failed_ended_week_is_not_marked_reconciled(self):
        previous = challenge_week(challenge_week_id=10)
        captured = {}

        def fake_with_psycopg(fn):
            cur = SequencedCursor(
                [
                    [previous],
                    [
                        participant(
                            checkin_count=1,
                            checked_in_days=[
                                "Monday",
                                "Tuesday",
                                "Wednesday",
                                "Thursday",
                                "Friday",
                                "Saturday",
                                "Sunday",
                            ],
                        )
                    ],
                ]
            )
            captured["cur"] = cur
            return fn(None, cur)

        class MondayDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 5, 4, 14, 5, tzinfo=tz)

        with patch.dict(
            sys.modules,
            {"helpers": SimpleNamespace(with_psycopg=fake_with_psycopg)},
        ), patch("auto_knockout.datetime", MondayDatetime):
            with self.assertLogs(level="ERROR"):
                with self.assertRaisesRegex(RuntimeError, "Failed to apply mulligan"):
                    run_auto_knockout()

        self.assertEqual(reconciled_week_ids(captured["cur"]), [])

    def test_daily_runner_skips_bye_weeks(self):
        captured = {}

        def fake_with_psycopg(fn):
            cur = SequencedCursor([[challenge_week(bye_week=True)]])
            captured["cur"] = cur
            return fn(None, cur)

        with patch.dict(
            sys.modules,
            {"helpers": SimpleNamespace(with_psycopg=fake_with_psycopg)},
        ):
            events = run_auto_knockout()

        self.assertEqual(events, [])
        self.assertEqual(len(captured["cur"].queries), 1)


class MessageTests(unittest.TestCase):
    def test_standalone_warning_message_uses_available_mulligan_copy(self):
        message = build_auto_knockout_alert_message(
            [
                AutoKnockoutEvent(
                    action="warning",
                    challenge_id=1,
                    challenger_id=1,
                    name="Test User",
                    required_checkins=2,
                    checkin_count=0,
                    challenge_week_id=10,
                    discord_id="123",
                    remaining_checkin_days=("Saturday", "Sunday"),
                    has_mulligan_available=True,
                )
            ]
        )

        self.assertIn("Saturday and Sunday", message)
        self.assertIn("to avoid using a mulligan or being knocked out", message)

    def test_mulligan_message_includes_followup_without_duplicate_alert(self):
        events = [
            AutoKnockoutEvent(
                action="mulligan",
                challenge_id=1,
                challenger_id=1,
                name="Test User",
                required_checkins=2,
                checkin_count=0,
                challenge_week_id=10,
                discord_id="123",
                mulligan_checkin_id=456,
                mulligan_day="Saturday",
            ),
            AutoKnockoutEvent(
                action="warning",
                challenge_id=1,
                challenger_id=1,
                name="Test User",
                required_checkins=2,
                checkin_count=1,
                challenge_week_id=10,
                discord_id="123",
                mulligan_checkin_id=456,
                mulligan_day="Saturday",
                remaining_checkin_days=("Sunday",),
            ),
        ]

        reconciliation = build_auto_knockout_reconciliation_message(events)

        self.assertIn("mulligan on Saturday", reconciliation)
        self.assertIn("must check in on Sunday to avoid knockout", reconciliation)
        self.assertIsNone(build_auto_knockout_alert_message(events))

    def test_knockout_message_reports_weekly_count(self):
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

        self.assertIn("3/5 T1+ check-ins this week", message)


if __name__ == "__main__":
    unittest.main()
