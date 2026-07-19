import os
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo


os.environ.setdefault("DB_CONNECT_STRING", "postgresql://postgres:password@localhost/projects")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from auto_knockout import (
    AutoKnockoutEvent,
    apply_auto_knockout_for_week,
    build_auto_knockout_alert_message,
    build_auto_knockout_alerts_for_week,
    build_auto_knockout_daily_message,
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


# The morning after the test week (Mon Apr 27 - Sun May 3) has ended.
WEEK_END_RUN_DATE = date(2026, 5, 4)


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
            WEEK_END_RUN_DATE,
        )

        self.assertEqual(events, [])
        self.assertEqual(cur.queries, [])

    def test_mulligan_inserted_when_one_short_at_week_end_without_mulligan(self):
        cur = FakeCursor()

        events = apply_auto_knockout_for_week(
            cur,
            challenge_week(),
            [participant(checkin_count=1, checked_in_days=["Monday"])],
            WEEK_END_RUN_DATE,
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
            WEEK_END_RUN_DATE,
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "knockout")
        self.assertEqual(events[0].discord_id, "1001")
        self.assertIn("set knocked_out = true", query_texts(cur)[0])

    def test_challenger_doomed_again_after_same_week_mulligan_is_knocked_out(self):
        cur = FakeCursor()

        # Mulligan already applied this week counted as one check-in; the
        # challenger still failed the requirement, so they are knocked out.
        events = apply_auto_knockout_for_week(
            cur,
            challenge_week(),
            [
                participant(
                    checkin_count=1,
                    checked_in_days=["Monday"],
                    mulligan=123,
                )
            ],
            WEEK_END_RUN_DATE,
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "knockout")
        self.assertIn("set knocked_out = true", query_texts(cur)[0])

    def test_zero_checkin_challenger_knocked_out_when_mulligan_cannot_save(self):
        cur = FakeCursor()

        # 0/2 at week end: a single mulligan check-in cannot save the week,
        # so the challenger is knocked out without spending the mulligan.
        events = apply_auto_knockout_for_week(
            cur,
            challenge_week(),
            [participant(checkin_count=0)],
            WEEK_END_RUN_DATE,
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "knockout")
        self.assertEqual(len(cur.queries), 1)
        self.assertIn("set knocked_out = true", query_texts(cur)[0])

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
            WEEK_END_RUN_DATE,
        )

        self.assertEqual(events[0].action, "knockout")
        self.assertEqual(events[0].required_checkins, 5)

    def test_midweek_no_action_when_still_savable(self):
        cur = FakeCursor()

        # Saturday with 0/2: checking in Saturday and Sunday still works.
        events = apply_auto_knockout_for_week(
            cur,
            challenge_week(),
            [participant(checkin_count=0)],
            date(2026, 5, 2),
        )

        self.assertEqual(events, [])
        self.assertEqual(cur.queries, [])

    def test_midweek_mulligan_applied_when_doomed_but_savable_by_mulligan(self):
        cur = FakeCursor()

        # Sunday with 0/2: only one day remains, so the challenger is doomed,
        # but the mulligan (one check-in) puts the week back within reach.
        events = apply_auto_knockout_for_week(
            cur,
            challenge_week(),
            [participant(checkin_count=0)],
            date(2026, 5, 3),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "mulligan")
        self.assertEqual(events[0].mulligan_day, "Monday")
        self.assertEqual(events[0].remaining_checkin_days, ("Sunday",))
        self.assertIn("insert into checkins", query_texts(cur)[0])

    def test_midweek_knockout_when_doomed_with_mulligan_spent(self):
        cur = FakeCursor()

        # Green week Friday with 1/5: four needed, three days remain.
        events = apply_auto_knockout_for_week(
            cur,
            challenge_week(green=True),
            [participant(checkin_count=1, checked_in_days=["Monday"], mulligan=99)],
            date(2026, 5, 1),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "knockout")
        self.assertIn("set knocked_out = true", query_texts(cur)[0])

    def test_midweek_knockout_when_mulligan_cannot_save_week(self):
        cur = FakeCursor()

        # Green week Friday with 0/5: five needed, three days remain, and a
        # mulligan only covers one, so knock out without inserting a mulligan.
        events = apply_auto_knockout_for_week(
            cur,
            challenge_week(green=True),
            [participant(checkin_count=0)],
            date(2026, 5, 1),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "knockout")
        self.assertEqual(len(cur.queries), 1)
        self.assertIn("set knocked_out = true", query_texts(cur)[0])

    def test_midweek_current_day_checkin_counts_toward_remaining(self):
        cur = FakeCursor()

        # Green week Saturday with 3/5 and no check-in yet today: Saturday and
        # Sunday remain, so the week is still savable.
        events = apply_auto_knockout_for_week(
            cur,
            challenge_week(green=True),
            [
                participant(
                    checkin_count=3,
                    checked_in_days=["Monday", "Tuesday", "Wednesday"],
                    mulligan=99,
                )
            ],
            date(2026, 5, 2),
        )

        self.assertEqual(events, [])

        # Same Saturday, but today's check-in is already in the count: only
        # Sunday remains for the two still needed, so the challenger is doomed.
        events = apply_auto_knockout_for_week(
            cur,
            challenge_week(green=True),
            [
                participant(
                    checkin_count=3,
                    checked_in_days=["Monday", "Tuesday", "Saturday"],
                    mulligan=99,
                    current_day_checked_in=True,
                )
            ],
            date(2026, 5, 2),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "knockout")

    def test_midweek_mulligan_counts_as_single_checkin_then_knockout(self):
        cur = FakeCursor()

        # Green week: mulligan already applied this week brought the count to
        # 2/5. On Saturday only two days remain for the three still needed,
        # so the challenger is knocked out despite the same-week mulligan.
        events = apply_auto_knockout_for_week(
            cur,
            challenge_week(green=True),
            [
                participant(
                    checkin_count=2,
                    checked_in_days=["Monday", "Tuesday"],
                    mulligan=50,
                )
            ],
            date(2026, 5, 2),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "knockout")
        self.assertIn("set knocked_out = true", query_texts(cur)[0])

    def test_first_missed_day_skips_checked_in_days(self):
        day_name, missing_date = first_missed_day(
            date(2026, 4, 27),
            ["Monday", "Wednesday"],
        )

        self.assertEqual(day_name, "Tuesday")
        self.assertEqual(missing_date, date(2026, 4, 28))

    def test_participant_query_skips_knocked_out_challengers(self):
        cur = FakeCursor()

        get_participants_for_week(
            cur, challenge_id=1, challenge_week_id=10, run_day="Saturday"
        )

        self.assertIn("ch.discord_id", query_texts(cur)[0])
        self.assertIn("cc.knocked_out = false", query_texts(cur)[0])

    def test_participant_query_exposes_current_day_checkin(self):
        cur = FakeCursor()

        get_participants_for_week(
            cur, challenge_id=1, challenge_week_id=10, run_day="Saturday"
        )

        self.assertIn("current_day_checked_in", query_texts(cur)[0])
        self.assertEqual(cur.queries[0][1][0], "Saturday")

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
        # Only the two week-lookup queries run; participants are never fetched.
        self.assertEqual(len(captured["cur"].queries), 2)

    def test_run_auto_knockout_processes_previous_and_current_week(self):
        today = datetime.now(tz=ZoneInfo("America/New_York")).date()
        previous_week = SimpleNamespace(
            challenge_id=1,
            challenge_week_id=9,
            start=today - timedelta(days=7),
            end=today - timedelta(days=1),
            green=False,
            bye_week=False,
        )
        current_week = SimpleNamespace(
            challenge_id=1,
            challenge_week_id=10,
            start=today,
            end=today + timedelta(days=6),
            green=False,
            bye_week=False,
        )

        # Previous week ended one check-in short: mulligan applies.
        # Current week just started: nobody is doomed yet.
        previous_participants = [participant(checkin_count=1, checked_in_days=[])]
        current_participants = [participant(checkin_count=0)]

        cur = FakeCursor()

        def fake_with_psycopg(fn):
            return fn(None, cur)

        with patch.dict(
            sys.modules,
            {"helpers": SimpleNamespace(with_psycopg=fake_with_psycopg)},
        ), patch(
            "auto_knockout.get_previous_challenge_week", return_value=previous_week
        ), patch(
            "auto_knockout.get_current_challenge_week", return_value=current_week
        ), patch(
            "auto_knockout.get_participants_for_week",
            side_effect=[previous_participants, current_participants],
        ) as participants_mock:
            events = run_auto_knockout()

        self.assertEqual(participants_mock.call_count, 2)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "mulligan")
        self.assertEqual(events[0].challenge_week_id, 9)

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

    def test_sunday_alert_after_saturday_mulligan_warns_of_knockout(self):
        saturday_events = build_auto_knockout_alerts_for_week(
            challenge_week(),
            date(2026, 5, 2),
            [participant(checkin_count=0, mulligan=None)],
        )

        self.assertEqual(len(saturday_events), 1)
        self.assertTrue(saturday_events[0].has_mulligan_available)
        self.assertIn(
            "to avoid using a mulligan",
            build_auto_knockout_alert_message(saturday_events),
        )

        # Daily auto-mulligan places on first_missed_day (Monday), not Saturday.
        # Latest elapsed day (Saturday) is still uncovered by a real check-in,
        # so the consequence-update warning still fires.
        sunday_events = build_auto_knockout_alerts_for_week(
            challenge_week(),
            date(2026, 5, 3),
            [
                participant(
                    checkin_count=1,
                    checked_in_days=["Monday"],
                    mulligan=99,
                    mulligan_challenge_week_id=10,
                    mulligan_day="Monday",
                )
            ],
        )

        self.assertEqual(len(sunday_events), 1)
        self.assertFalse(sunday_events[0].has_mulligan_available)
        self.assertEqual(sunday_events[0].remaining_checkin_days, ("Sunday",))
        self.assertIn(
            "to avoid being knocked out",
            build_auto_knockout_alert_message(sunday_events),
        )

    def test_post_mulligan_warning_when_mulligan_fills_latest_elapsed_day(self):
        # first_no_slack is false because Saturday (latest elapsed) is checked
        # in via the mulligan; the adapted helper still fires because Saturday
        # is not covered by a real check-in.
        events = build_auto_knockout_alerts_for_week(
            challenge_week(),
            date(2026, 5, 3),
            [
                participant(
                    checkin_count=1,
                    checked_in_days=["Saturday"],
                    mulligan=99,
                    mulligan_challenge_week_id=10,
                    mulligan_day="Saturday",
                )
            ],
        )

        self.assertEqual(len(events), 1)
        self.assertFalse(events[0].has_mulligan_available)
        self.assertIn(
            "to avoid being knocked out",
            build_auto_knockout_alert_message(events),
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
        self.assertIn(
            "mulligan_checkin.challenge_week_id as mulligan_challenge_week_id",
            query_texts(cur)[0],
        )
        self.assertIn(
            "mulligan_checkin.day_of_week as mulligan_day",
            query_texts(cur)[0],
        )
        self.assertIn("left join checkins mulligan_checkin", query_texts(cur)[0])

    def test_alert_message_mentions_discord_ids_and_remaining_days(self):
        events = build_auto_knockout_alerts_for_week(
            challenge_week(),
            date(2026, 5, 2),
            [participant(checkin_count=0, mulligan=99)],
        )

        message = build_auto_knockout_alert_message(events)

        self.assertEqual(
            message,
            "## Warnings\n"
            "- 🚨 <@1001> must check in on Saturday and Sunday "
            "to avoid being knocked out.",
        )
        self.assertNotIn("mulligan", message)
        self.assertFalse(message.endswith("\n"))

    def test_alert_message_mentions_mulligan_risk_when_mulligan_available(self):
        events = build_auto_knockout_alerts_for_week(
            challenge_week(),
            date(2026, 5, 2),
            [participant(checkin_count=0, mulligan=None)],
        )

        message = build_auto_knockout_alert_message(events)

        self.assertEqual(
            message,
            "## Warnings\n"
            "- ⚠️ <@1001> must check in on Saturday and Sunday "
            "to avoid using a mulligan.",
        )
        self.assertNotIn("being knocked out", message)
        self.assertFalse(message.endswith("\n"))

    def test_alert_message_groups_users_with_identical_conditions(self):
        events = build_auto_knockout_alerts_for_week(
            challenge_week(),
            date(2026, 5, 2),
            [
                participant(checkin_count=0, mulligan=None),
                participant(checkin_count=0, mulligan=None, challenger_id=2),
                participant(checkin_count=0, mulligan=None, challenger_id=3),
                participant(checkin_count=0, mulligan=99, challenger_id=4),
                participant(checkin_count=0, mulligan=99, challenger_id=5),
            ],
        )

        message = build_auto_knockout_alert_message(events)

        self.assertEqual(
            message,
            "## Warnings\n"
            "- 🚨 <@1004> and <@1005> must check in on Saturday and Sunday "
            "to avoid being knocked out.\n"
            "- ⚠️ <@1001>, <@1002>, and <@1003> must check in on "
            "Saturday and Sunday to avoid using a mulligan.",
        )
        self.assertEqual(message.count("\n"), 2)
        self.assertNotIn("\n\n", message)
        self.assertFalse(message.endswith("\n"))

    def test_alert_message_keeps_different_checkin_days_separate(self):
        events = build_auto_knockout_alerts_for_week(
            challenge_week(),
            date(2026, 5, 2),
            [
                participant(checkin_count=0, mulligan=None),
                participant(
                    checkin_count=1,
                    checked_in_days=["Saturday"],
                    current_day_checked_in=True,
                    mulligan=None,
                    challenger_id=2,
                ),
            ],
        )

        message = build_auto_knockout_alert_message(events)

        self.assertEqual(
            message,
            "## Warnings\n"
            "- ⚠️ <@1001> must check in on Saturday and Sunday "
            "to avoid using a mulligan.\n"
            "- ⚠️ <@1002> must check in on Sunday to avoid using a mulligan.",
        )
        self.assertFalse(message.endswith("\n"))

    def test_alert_still_sent_after_same_week_mulligan(self):
        # A same-week mulligan no longer forgives the week: with 1/2 (the
        # mulligan check-in) and only Sunday left, the challenger is warned.
        events = build_auto_knockout_alerts_for_week(
            challenge_week(),
            date(2026, 5, 3),
            [
                participant(
                    checkin_count=1,
                    checked_in_days=["Monday"],
                    mulligan=50,
                    mulligan_challenge_week_id=10,
                    mulligan_day="Monday",
                )
            ],
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "warning")
        self.assertEqual(events[0].remaining_checkin_days, ("Sunday",))
        self.assertFalse(events[0].has_mulligan_available)

    def test_daily_message_combines_actions_and_warnings(self):
        action_events = [
            AutoKnockoutEvent(
                action="knockout",
                challenge_id=1,
                challenger_id=1,
                name="Knocked Out User",
                required_checkins=2,
                checkin_count=0,
                challenge_week_id=10,
                discord_id="111",
            )
        ]
        warning_events = build_auto_knockout_alerts_for_week(
            challenge_week(),
            date(2026, 5, 2),
            [participant(checkin_count=0, challenger_id=2, mulligan=99)],
        )

        message = build_auto_knockout_daily_message(action_events, warning_events)

        self.assertEqual(
            message,
            "## Knockouts\n"
            "- <@111> has been knocked out with 0/2 T1+ check-ins this week.\n"
            "## Warnings\n"
            "- 🚨 <@1002> must check in on Saturday and Sunday "
            "to avoid being knocked out.",
        )
        self.assertNotIn("\n\n", message)

    def test_daily_message_with_only_warnings(self):
        warning_events = build_auto_knockout_alerts_for_week(
            challenge_week(),
            date(2026, 5, 2),
            [participant(checkin_count=0, mulligan=99)],
        )

        message = build_auto_knockout_daily_message([], warning_events)

        self.assertIn("## Warnings", message)
        self.assertNotIn("## Knockouts\n", message)

    def test_daily_message_none_when_no_events(self):
        self.assertIsNone(build_auto_knockout_daily_message([], []))

    def test_reconciliation_message_omits_mulligans(self):
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
                    remaining_checkin_days=("Sunday",),
                )
            ]
        )

        self.assertIsNone(message)

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

        self.assertEqual(
            message,
            "## Knockouts\n"
            "- <@123> has been knocked out with 3/5 T1+ check-ins this week.",
        )
        self.assertFalse(message.endswith("\n"))

    def test_warning_message_includes_mulligan_save(self):
        message = build_auto_knockout_alert_message(
            [
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
                    remaining_checkin_days=("Sunday",),
                )
            ]
        )

        self.assertEqual(
            message,
            "## Warnings\n"
            "- <@123> was saved by a mulligan on Saturday and must check in "
            "on Sunday to avoid knockout.",
        )

    def test_warning_message_groups_matching_mulligan_saves(self):
        message = build_auto_knockout_alert_message(
            [
                AutoKnockoutEvent(
                    action="mulligan",
                    challenge_id=1,
                    challenger_id=1,
                    name="Ben",
                    required_checkins=2,
                    checkin_count=0,
                    challenge_week_id=10,
                    discord_id="111",
                    mulligan_checkin_id=1,
                    mulligan_day="Saturday",
                    remaining_checkin_days=("Sunday",),
                ),
                AutoKnockoutEvent(
                    action="mulligan",
                    challenge_id=1,
                    challenger_id=2,
                    name="Austin",
                    required_checkins=2,
                    checkin_count=0,
                    challenge_week_id=10,
                    discord_id="222",
                    mulligan_checkin_id=2,
                    mulligan_day="Saturday",
                    remaining_checkin_days=("Sunday",),
                ),
                AutoKnockoutEvent(
                    action="mulligan",
                    challenge_id=1,
                    challenger_id=3,
                    name="Mark",
                    required_checkins=2,
                    checkin_count=0,
                    challenge_week_id=10,
                    discord_id="333",
                    mulligan_checkin_id=3,
                    mulligan_day="Saturday",
                    remaining_checkin_days=("Sunday",),
                ),
            ]
        )

        self.assertEqual(
            message,
            "## Warnings\n"
            "- <@111>, <@222>, and <@333> were saved by a mulligan on Saturday "
            "and must check in on Sunday to avoid a knockout.",
        )

    def test_daily_message_puts_mulligan_saves_in_warnings(self):
        action_events = [
            AutoKnockoutEvent(
                action="knockout",
                challenge_id=1,
                challenger_id=1,
                name="Knocked Out User",
                required_checkins=2,
                checkin_count=0,
                challenge_week_id=10,
                discord_id="111",
            ),
            AutoKnockoutEvent(
                action="mulligan",
                challenge_id=1,
                challenger_id=2,
                name="Saved User",
                required_checkins=2,
                checkin_count=0,
                challenge_week_id=10,
                discord_id="222",
                mulligan_checkin_id=9,
                mulligan_day="Saturday",
                remaining_checkin_days=("Sunday",),
            ),
        ]
        # Same challenger also got a post-mulligan warning from the alert pass;
        # the daily builder should drop that duplicate.
        warning_events = [
            AutoKnockoutEvent(
                action="warning",
                challenge_id=1,
                challenger_id=2,
                name="Saved User",
                required_checkins=2,
                checkin_count=1,
                challenge_week_id=10,
                discord_id="222",
                remaining_checkin_days=("Sunday",),
                has_mulligan_available=False,
            ),
            AutoKnockoutEvent(
                action="warning",
                challenge_id=1,
                challenger_id=3,
                name="Warned User",
                required_checkins=2,
                checkin_count=0,
                challenge_week_id=10,
                discord_id="333",
                remaining_checkin_days=("Saturday", "Sunday"),
                has_mulligan_available=True,
            ),
        ]

        message = build_auto_knockout_daily_message(action_events, warning_events)

        self.assertEqual(
            message,
            "## Knockouts\n"
            "- <@111> has been knocked out with 0/2 T1+ check-ins this week.\n"
            "## Warnings\n"
            "- <@222> was saved by a mulligan on Saturday and must check in "
            "on Sunday to avoid knockout.\n"
            "- ⚠️ <@333> must check in on Saturday and Sunday "
            "to avoid using a mulligan.",
        )
        self.assertNotIn("## Saved", message)
        self.assertNotIn("🚨 <@222>", message)


if __name__ == "__main__":
    unittest.main()
