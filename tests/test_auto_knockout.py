import asyncio
import importlib
import json
import os
import subprocess
import sys
import unittest
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock


os.environ.setdefault("DB_CONNECT_STRING", "postgresql://postgres:password@localhost/projects")
REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DISCORD_CHANNEL_ID = "1421955269759336490"
sys.path.insert(0, str(REPO_ROOT / "src"))

from auto_knockout import (
    AutoKnockoutEvent,
    build_auto_knockout_message,
    build_auto_knockout_warning_message,
    effective_checkin_count,
    effective_remaining_week_days,
    elapsed_week_days,
    evaluate_auto_knockout_participants,
    format_day_list,
    get_challenge_contexts,
    get_participants_for_week,
    missing_mulligan_day,
    remaining_week_days,
    run_auto_knockout,
    run_day_for_week,
)


WEEK_START = date(2026, 4, 27)
WEEK_END = date(2026, 5, 3)


def challenge_week(green=False, week_id=10):
    return SimpleNamespace(
        challenge_id=1,
        challenge_week_id=week_id,
        start=WEEK_START,
        end=WEEK_END,
        green=green,
        bye_week=False,
    )


def participant(
    elapsed_checkin_count=0,
    elapsed_checked_in_days=None,
    current_day_checked_in=False,
    mulligan=None,
    challenger_id=1,
    name="Test User",
):
    return SimpleNamespace(
        id=challenger_id,
        name=name,
        discord_id=str(1000 + challenger_id),
        tz="America/New_York",
        mulligan=mulligan,
        elapsed_checkin_count=elapsed_checkin_count,
        elapsed_checked_in_days=elapsed_checked_in_days or [],
        current_day_checked_in=current_day_checked_in,
    )


def evaluate(
    run_date,
    *,
    green=False,
    elapsed_checkin_count=0,
    elapsed_checked_in_days=None,
    current_day_checked_in=False,
    mulligan=None,
):
    return evaluate_auto_knockout_participants(
        challenge_week(green=green),
        run_date,
        [
            participant(
                elapsed_checkin_count=elapsed_checkin_count,
                elapsed_checked_in_days=elapsed_checked_in_days,
                current_day_checked_in=current_day_checked_in,
                mulligan=mulligan,
            )
        ],
        green,
        dry_run=True,
    )


def actions(events):
    return [event.action for event in events]


def fake_module(name, **attrs):
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def discord_test_config_from_orbstack():
    compose_file = REPO_ROOT / "docker-compose-local.yml"
    if not compose_file.exists():
        return None, None

    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(compose_file),
                "exec",
                "-T",
                "rq-worker",
                "sh",
                "-lc",
                'printf "%s\\n%s\\n" "$DISCORD_TOKEN" "$ALLOWED_MESSAGE_CHANNEL_ID"',
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None, None

    lines = result.stdout.splitlines()
    if len(lines) < 2:
        return None, None
    return lines[0] or None, lines[1] or None


def discord_test_config():
    token = os.environ.get("DISCORD_TOKEN")
    channel_id = os.environ.get("ALLOWED_MESSAGE_CHANNEL_ID")

    if token is None:
        token, orbstack_channel_id = discord_test_config_from_orbstack()
        channel_id = channel_id or orbstack_channel_id

    return token, channel_id or LOCAL_DISCORD_CHANNEL_ID


def send_discord_message(token, channel_id, content):
    request = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        data=json.dumps({"content": content}).encode("utf-8"),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "checkin-viz-auto-knockout-tests",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"Discord API returned status {response.status}")


class AutoKnockoutNormalWeekTests(unittest.TestCase):
    def test_no_mulligan_remaining_warning_progression(self):
        cases = [
            (date(2026, 4, 27), 0, []),
            (date(2026, 5, 1), 0, []),
            (date(2026, 5, 2), 0, ["warning"]),
            (date(2026, 5, 3), 0, ["knockout"]),
        ]

        for run_date, checkins, expected_actions in cases:
            with self.subTest(run_date=run_date):
                events = evaluate(
                    run_date,
                    elapsed_checkin_count=checkins,
                    mulligan=99,
                )
                self.assertEqual(actions(events), expected_actions)

    def test_normal_week_warning_days_without_mulligan(self):
        saturday_events = evaluate(date(2026, 5, 2), mulligan=99)

        self.assertEqual(
            saturday_events[0].remaining_checkin_days,
            ("Saturday", "Sunday"),
        )

    def test_normal_week_mulligan_available_warnings(self):
        saturday_events = evaluate(date(2026, 5, 2), mulligan=None)
        sunday_events = evaluate(date(2026, 5, 3), mulligan=None)

        self.assertEqual(actions(saturday_events), [])

        self.assertEqual(actions(sunday_events), ["mulligan", "warning"])
        self.assertEqual(sunday_events[0].mulligan_day, "Saturday")
        self.assertEqual(sunday_events[1].remaining_checkin_days, ("Sunday",))


class AutoKnockoutGreenWeekTests(unittest.TestCase):
    def test_no_mulligan_remaining_green_week(self):
        wednesday_events = evaluate(date(2026, 4, 29), green=True, mulligan=99)
        thursday_events = evaluate(date(2026, 4, 30), green=True, mulligan=99)
        saturday_events = evaluate(
            date(2026, 5, 2),
            green=True,
            elapsed_checkin_count=3,
            elapsed_checked_in_days=["Monday", "Tuesday", "Wednesday"],
            mulligan=99,
        )
        sunday_events = evaluate(
            date(2026, 5, 3),
            green=True,
            elapsed_checkin_count=4,
            elapsed_checked_in_days=["Monday", "Tuesday", "Wednesday", "Thursday"],
            mulligan=99,
        )
        sunday_checked_in_events = evaluate(
            date(2026, 5, 3),
            green=True,
            elapsed_checkin_count=4,
            elapsed_checked_in_days=["Monday", "Tuesday", "Wednesday", "Thursday"],
            current_day_checked_in=True,
            mulligan=99,
        )

        self.assertEqual(actions(wednesday_events), ["warning"])
        self.assertEqual(
            wednesday_events[0].remaining_checkin_days,
            ("Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
        )
        self.assertEqual(actions(thursday_events), ["knockout"])
        self.assertEqual(actions(saturday_events), ["warning"])
        self.assertEqual(
            saturday_events[0].remaining_checkin_days,
            ("Saturday", "Sunday"),
        )
        self.assertEqual(actions(sunday_events), ["warning"])
        self.assertEqual(sunday_events[0].remaining_checkin_days, ("Sunday",))
        self.assertEqual(actions(sunday_checked_in_events), [])

    def test_mulligan_available_green_week(self):
        thursday_events = evaluate(date(2026, 4, 30), green=True, mulligan=None)
        sunday_events = evaluate(
            date(2026, 5, 3),
            green=True,
            elapsed_checkin_count=3,
            elapsed_checked_in_days=["Monday", "Wednesday", "Saturday"],
            mulligan=None,
        )

        self.assertEqual(actions(thursday_events), ["mulligan", "warning"])
        self.assertEqual(thursday_events[0].mulligan_day, "Wednesday")
        self.assertEqual(
            thursday_events[1].remaining_checkin_days,
            ("Thursday", "Friday", "Saturday", "Sunday"),
        )

        self.assertEqual(actions(sunday_events), ["mulligan", "warning"])
        self.assertEqual(sunday_events[0].mulligan_day, "Friday")
        self.assertEqual(sunday_events[1].remaining_checkin_days, ("Sunday",))


class AutoKnockoutSameDayAndMulliganTests(unittest.TestCase):
    def test_same_day_checkin_adjusts_count_and_remaining_days(self):
        self.assertEqual(effective_checkin_count(4, True), 5)
        self.assertEqual(
            effective_remaining_week_days(("Sunday",), "Sunday", True),
            (),
        )
        self.assertEqual(
            effective_remaining_week_days(("Sunday",), "Sunday", False),
            ("Sunday",),
        )

    def test_today_is_not_eligible_for_mulligan_selection(self):
        day_name, missing_date = missing_mulligan_day(
            WEEK_START,
            date(2026, 5, 3),
            ["Monday", "Wednesday", "Friday", "Saturday"],
        )

        self.assertEqual(day_name, "Thursday")
        self.assertEqual(missing_date, date(2026, 4, 30))

    def test_mulligan_can_apply_to_earlier_than_previous_day(self):
        day_name, missing_date = missing_mulligan_day(
            WEEK_START,
            date(2026, 5, 4),
            ["Monday", "Wednesday", "Saturday", "Sunday"],
        )

        self.assertEqual(day_name, "Friday")
        self.assertEqual(missing_date, date(2026, 5, 1))


class AutoKnockoutMondayFinalizationTests(unittest.TestCase):
    def test_monday_after_normal_week_finalizes_previous_week(self):
        monday_run = date(2026, 5, 4)

        self.assertEqual(remaining_week_days(monday_run, WEEK_END), ())
        self.assertEqual(
            elapsed_week_days(WEEK_START, monday_run),
            ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        )

        one_checkin_with_mulligan = evaluate(
            monday_run,
            elapsed_checkin_count=1,
            elapsed_checked_in_days=["Monday"],
            mulligan=None,
        )
        no_checkins_with_mulligan = evaluate(monday_run, mulligan=None)
        one_checkin_no_mulligan = evaluate(
            monday_run,
            elapsed_checkin_count=1,
            elapsed_checked_in_days=["Monday"],
            mulligan=99,
        )

        self.assertEqual(actions(one_checkin_with_mulligan), ["mulligan"])
        self.assertEqual(actions(no_checkins_with_mulligan), ["knockout"])
        self.assertEqual(actions(one_checkin_no_mulligan), ["knockout"])

    def test_monday_after_normal_week_does_not_double_count_monday_checkin(self):
        monday_run = date(2026, 5, 4)

        self.assertIsNone(run_day_for_week(monday_run, challenge_week()))

        events = evaluate(
            monday_run,
            elapsed_checkin_count=1,
            elapsed_checked_in_days=["Monday"],
            current_day_checked_in=False,
            mulligan=99,
        )

        self.assertEqual(actions(events), ["knockout"])

    def test_monday_after_green_week_finalizes_previous_week(self):
        monday_run = date(2026, 5, 4)

        four_checkins_with_mulligan = evaluate(
            monday_run,
            green=True,
            elapsed_checkin_count=4,
            elapsed_checked_in_days=["Monday", "Wednesday", "Saturday", "Sunday"],
            mulligan=None,
        )
        three_checkins_with_mulligan = evaluate(
            monday_run,
            green=True,
            elapsed_checkin_count=3,
            elapsed_checked_in_days=["Monday", "Wednesday", "Saturday"],
            mulligan=None,
        )
        four_checkins_no_mulligan = evaluate(
            monday_run,
            green=True,
            elapsed_checkin_count=4,
            elapsed_checked_in_days=["Monday", "Wednesday", "Saturday", "Sunday"],
            mulligan=99,
        )

        self.assertEqual(actions(four_checkins_with_mulligan), ["mulligan"])
        self.assertEqual(four_checkins_with_mulligan[0].mulligan_day, "Friday")
        self.assertEqual(actions(three_checkins_with_mulligan), ["knockout"])
        self.assertEqual(actions(four_checkins_no_mulligan), ["knockout"])

    def test_monday_after_green_week_does_not_double_count_monday_checkin(self):
        monday_run = date(2026, 5, 4)

        self.assertIsNone(run_day_for_week(monday_run, challenge_week(green=True)))

        events = evaluate(
            monday_run,
            green=True,
            elapsed_checkin_count=4,
            elapsed_checked_in_days=["Monday", "Wednesday", "Saturday", "Sunday"],
            current_day_checked_in=False,
            mulligan=99,
        )

        self.assertEqual(actions(events), ["knockout"])

    def test_context_query_includes_monday_previous_week_branch(self):
        class FakeCursor:
            def __init__(self):
                self.query = None

            def execute(self, query):
                self.query = query

            def fetchall(self):
                return []

        cur = FakeCursor()
        self.assertEqual(get_challenge_contexts(cur), [])
        self.assertIn("extract(isodow", cur.query)
        self.assertIn("rc.run_date - interval '1 day'", cur.query)

    def test_monday_previous_week_uses_week_scoped_green_resolution(self):
        previous_week = challenge_week(green=None, week_id=99)
        captured_weeks = []

        class FakeCursor:
            def __init__(self):
                self.fetchall_calls = 0

            def execute(self, *args):
                pass

            def fetchall(self):
                self.fetchall_calls += 1
                if self.fetchall_calls == 1:
                    return [previous_week]
                return []

            def fetchone(self):
                return SimpleNamespace(id=123)

        def fake_with_psycopg(fn):
            return fn(None, FakeCursor())

        def fake_determine_if_green_for_week(challenge_week):
            captured_weeks.append(challenge_week)
            return True

        fake_helpers = fake_module("helpers", with_psycopg=fake_with_psycopg)
        fake_green = fake_module(
            "green",
            determine_if_green_for_week=fake_determine_if_green_for_week,
        )

        with mock.patch.dict(
            sys.modules,
            {"helpers": fake_helpers, "green": fake_green},
        ), mock.patch("auto_knockout.get_run_date", return_value=date(2026, 5, 4)):
            self.assertEqual(run_auto_knockout(), [])

        self.assertEqual(captured_weeks, [previous_week])
        self.assertEqual(captured_weeks[0].challenge_week_id, 99)


class AutoKnockoutMessageTests(unittest.TestCase):
    def event(self, action, **kwargs):
        defaults = {
            "challenge_id": 1,
            "challenger_id": 1,
            "name": "Test User",
            "discord_id": "123",
            "required_checkins": 5,
            "checkin_count": 4,
            "challenge_week_id": 10,
        }
        defaults.update(kwargs)
        return AutoKnockoutEvent(action=action, **defaults)

    def test_state_change_message_sections(self):
        message = build_auto_knockout_message(
            [
                self.event("mulligan", mulligan_day="Friday", mulligan_checkin_id=10),
                self.event(
                    "warning",
                    mulligan_day="Friday",
                    mulligan_checkin_id=10,
                    remaining_checkin_days=("Sunday",),
                ),
                self.event("knockout", checkin_count=3),
            ]
        )

        self.assertIn("## Mulligans used", message)
        self.assertIn("## Knockouts", message)
        self.assertIn("<@123> was saved from knockout", message)
        self.assertIn("They must check in on Sunday to avoid knockout.", message)
        self.assertIn("<@123> has been knocked out", message)

    def test_mulligan_warning_is_not_repeated_as_standalone_warning(self):
        events = [
            self.event("mulligan", mulligan_day="Saturday", mulligan_checkin_id=10),
            self.event(
                "warning",
                mulligan_day="Saturday",
                mulligan_checkin_id=10,
                remaining_checkin_days=("Sunday",),
            ),
        ]

        state_message = build_auto_knockout_message(events)
        warning_message = build_auto_knockout_warning_message(events)

        self.assertIn("They must check in on Sunday to avoid knockout.", state_message)
        self.assertIsNone(warning_message)

    def test_warning_only_events_do_not_make_state_change_message(self):
        message = build_auto_knockout_message(
            [self.event("warning", remaining_checkin_days=("Sunday",))]
        )

        self.assertIsNone(message)

    def test_warning_message_formats_days_and_multiple_users(self):
        message = build_auto_knockout_warning_message(
            [
                self.event(
                    "warning",
                    discord_id="123",
                    remaining_checkin_days=("Sunday",),
                ),
                self.event(
                    "warning",
                    challenger_id=2,
                    discord_id="456",
                    remaining_checkin_days=("Thursday", "Friday", "Saturday", "Sunday"),
                ),
            ]
        )

        self.assertIn("## Knockout warnings", message)
        self.assertIn(
            "<@123> has no more mulligans and must check in on Sunday",
            message,
        )
        self.assertIn(
            "<@456> has no more mulligans and must check in on "
            "Thursday, Friday, Saturday, and Sunday",
            message,
        )
        self.assertEqual(format_day_list(["Saturday", "Sunday"]), "Saturday and Sunday")
        self.assertEqual(
            format_day_list(["Friday", "Saturday", "Sunday"]),
            "Friday, Saturday, and Sunday",
        )

    def test_participant_query_excludes_t0_checkins(self):
        class FakeCursor:
            def __init__(self):
                self.query = None
                self.args = None

            def execute(self, query, args):
                self.query = query
                self.args = args

            def fetchall(self):
                return []

        cur = FakeCursor()
        self.assertEqual(
            get_participants_for_week(cur, 1, 10, ["Monday"], "Tuesday"),
            [],
        )
        self.assertIn("c.tier != 'T0'", cur.query)
        self.assertEqual(cur.args, (["Monday"], ["Monday"], "Tuesday", 10, 1))


class AutoKnockoutTaskIntegrationTests(unittest.TestCase):
    def test_medal_failure_does_not_block_discord_notification(self):
        class FakeCron:
            def register(self, *args, **kwargs):
                pass

        fake_bot = SimpleNamespace(user=object(), get_channel=lambda channel_id: None)
        fake_modules = {
            "rq": fake_module("rq", cron=FakeCron()),
            "helpers": fake_module("helpers", fetchall=lambda *args, **kwargs: []),
            "green": fake_module("green", determine_if_green=lambda: False),
            "discord": fake_module("discord", Embed=lambda *args, **kwargs: None),
            "discord_bot": fake_module("discord_bot", bot=fake_bot),
            "medals": fake_module("medals", update_medal_table=lambda *args: None),
        }

        sys.modules.pop("tasks", None)
        with mock.patch.dict(sys.modules, fake_modules):
            tasks = importlib.import_module("tasks")

        sent_messages = []

        class FakeChannel:
            async def send(self, message):
                sent_messages.append(message)

        async def fake_get_channel():
            return FakeChannel()

        events = [
            AutoKnockoutEvent(
                action="knockout",
                challenge_id=1,
                challenger_id=1,
                name="Test User",
                discord_id="123",
                required_checkins=5,
                checkin_count=3,
                challenge_week_id=10,
            )
        ]

        with mock.patch.object(tasks, "run_auto_knockout", return_value=events), mock.patch.object(
            tasks,
            "get_channel",
            side_effect=fake_get_channel,
        ), mock.patch.object(
            tasks.medals,
            "update_medal_table",
            side_effect=RuntimeError("medal failure"),
        ) as update_medal_table, self.assertLogs(level="ERROR") as logs:
            asyncio.run(tasks.auto_knockout())

        self.assertEqual(len(sent_messages), 1)
        self.assertIn("<@123> has been knocked out", sent_messages[0])
        update_medal_table.assert_called_once_with(1, 10)
        self.assertIn("Auto-knockout medal update failed", "\n".join(logs.output))
        sys.modules.pop("tasks", None)


class AutoKnockoutDiscordIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("RUN_DISCORD_MESSAGE_TESTS") == "1",
        "Set RUN_DISCORD_MESSAGE_TESTS=1 to send messages to Discord",
    )
    def test_send_auto_knockout_messages_to_discord(self):
        token, channel_id = discord_test_config()
        if token is None:
            self.skipTest(
                "DISCORD_TOKEN is required or an OrbStack rq-worker with "
                "DISCORD_TOKEN must be running"
            )

        events = []
        scenarios = [
            (
                "Normal week, no mulligan remaining",
                date(2026, 5, 2),
                False,
                [
                    participant(
                        challenger_id=111,
                        name="Normal No Mulligan",
                        mulligan=9001,
                    )
                ],
            ),
            (
                "Normal week, mulligan available",
                date(2026, 5, 3),
                False,
                [
                    participant(
                        challenger_id=222,
                        name="Normal Mulligan",
                        mulligan=None,
                    )
                ],
            ),
            (
                "Green week, mulligan available",
                date(2026, 4, 30),
                True,
                [
                    participant(
                        challenger_id=333,
                        name="Green Mulligan",
                        mulligan=None,
                    )
                ],
            ),
            (
                "Monday finalization, mixed outcomes",
                date(2026, 5, 4),
                False,
                [
                    participant(
                        challenger_id=555,
                        name="One Checkin With Mulligan",
                        elapsed_checkin_count=1,
                        elapsed_checked_in_days=["Monday"],
                        mulligan=None,
                    ),
                    participant(
                        challenger_id=666,
                        name="No Checkins With Mulligan",
                        mulligan=None,
                    ),
                    participant(
                        challenger_id=777,
                        name="One Checkin No Mulligan",
                        elapsed_checkin_count=1,
                        elapsed_checked_in_days=["Monday"],
                        mulligan=9003,
                    ),
                ],
            ),
        ]

        for title, run_date, green, people in scenarios:
            scenario_events = evaluate_auto_knockout_participants(
                challenge_week(green=green),
                run_date,
                people,
                green,
                dry_run=True,
            )
            events.append((title, scenario_events))

        for title, scenario_events in events:
            state_message = build_auto_knockout_message(scenario_events)
            warning_message = build_auto_knockout_warning_message(scenario_events)
            try:
                if state_message is not None:
                    send_discord_message(
                        token,
                        channel_id,
                        f"**Auto-knockout test: {title}**\n\n{state_message}",
                    )
                if warning_message is not None:
                    send_discord_message(
                        token,
                        channel_id,
                        f"**Auto-knockout test: {title}**\n\n{warning_message}",
                    )
            except urllib.error.HTTPError as error:
                self.fail(f"Discord API returned status {error.code}: {error.reason}")


if __name__ == "__main__":
    unittest.main()
