import os
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace


os.environ.setdefault("DB_CONNECT_STRING", "postgresql://postgres:password@localhost/projects")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from medal_roundup import (
    ROUNDUP_TZ,
    build_opening_medal_roundup_message,
    is_challenge_day_one,
    is_opening_roundup_day,
    should_suppress_medal_announcements,
)


def standing(discord_id, medal_name, medal_emoji=""):
    return SimpleNamespace(
        discord_id=discord_id,
        medal_name=medal_name,
        medal_emoji=medal_emoji,
    )


def utc_dt(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def ny_dt(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=ROUNDUP_TZ)


class TestIsChallengeDayOne(unittest.TestCase):
    def test_first_day(self):
        self.assertTrue(is_challenge_day_one(date(2026, 4, 27), date(2026, 4, 27)))

    def test_second_day(self):
        self.assertFalse(is_challenge_day_one(date(2026, 4, 27), date(2026, 4, 28)))


class TestIsOpeningRoundupDay(unittest.TestCase):
    def test_day_two_monday_start(self):
        self.assertTrue(is_opening_roundup_day(date(2026, 4, 27), date(2026, 4, 28)))

    def test_day_one_not_roundup_day(self):
        self.assertFalse(is_opening_roundup_day(date(2026, 4, 27), date(2026, 4, 27)))

    def test_day_three_not_roundup_day(self):
        self.assertFalse(is_opening_roundup_day(date(2026, 4, 27), date(2026, 4, 29)))

    def test_non_monday_week_start(self):
        # Challenge week starts Wednesday; roundup day is Thursday.
        self.assertTrue(is_opening_roundup_day(date(2026, 4, 29), date(2026, 4, 30)))
        self.assertFalse(is_opening_roundup_day(date(2026, 4, 29), date(2026, 4, 28)))


class TestShouldSuppressMedalAnnouncements(unittest.TestCase):
    week_start = date(2026, 4, 27)  # Monday

    def test_suppress_on_day_zero_any_utc_time(self):
        self.assertTrue(
            should_suppress_medal_announcements(
                self.week_start, utc_dt(2026, 4, 27, 13, 0)
            )
        )
        self.assertTrue(
            should_suppress_medal_announcements(
                self.week_start, utc_dt(2026, 4, 27, 15, 0)
            )
        )

    def test_suppress_on_day_one_before_utc_cutoff(self):
        self.assertTrue(
            should_suppress_medal_announcements(
                self.week_start, utc_dt(2026, 4, 28, 13, 59)
            )
        )
        self.assertTrue(
            should_suppress_medal_announcements(
                self.week_start, utc_dt(2026, 4, 28, 14, 0)
            )
        )

    def test_do_not_suppress_on_day_one_at_utc_cutoff(self):
        self.assertFalse(
            should_suppress_medal_announcements(
                self.week_start, utc_dt(2026, 4, 28, 14, 1)
            )
        )

    def test_do_not_suppress_on_day_one_after_utc_cutoff(self):
        self.assertFalse(
            should_suppress_medal_announcements(
                self.week_start, utc_dt(2026, 4, 28, 14, 30)
            )
        )

    def test_do_not_suppress_on_day_two_plus(self):
        self.assertFalse(
            should_suppress_medal_announcements(
                self.week_start, utc_dt(2026, 4, 29, 8, 0)
            )
        )

    def test_day_index_uses_ny_calendar_with_utc_cutoff(self):
        # 2026-04-28 03:00 UTC is still 2026-04-27 23:00 EDT (day 0).
        self.assertTrue(
            should_suppress_medal_announcements(
                self.week_start, utc_dt(2026, 4, 28, 3, 0)
            )
        )
        # Same absolute time expressed in NY should agree.
        self.assertTrue(
            should_suppress_medal_announcements(
                self.week_start, ny_dt(2026, 4, 27, 23, 0)
            )
        )


class TestOpeningMedalRoundupMessage(unittest.TestCase):
    def test_empty_standings_returns_none(self):
        self.assertIsNone(build_opening_medal_roundup_message([]))
        self.assertIsNone(build_opening_medal_roundup_message(None))

    def test_earned_only(self):
        message = build_opening_medal_roundup_message(
            [
                standing("1001", "green", "🟩"),
                standing("1001", "first_to_green", "✳️"),
            ]
        )
        self.assertEqual(
            message,
            "## Opening Medal Roundup\n"
            "- <@1001> earned 🟩 __**Green Week**__ and ✳️ __**First to Green**__.",
        )

    def test_holds_only(self):
        message = build_opening_medal_roundup_message(
            [
                standing("1002", "earliest_for_week", "☀️"),
                standing("1002", "highest_tier_week", "💪"),
            ]
        )
        self.assertEqual(
            message,
            "## Opening Medal Roundup\n"
            "- <@1002> currently holds 💪 __**Highest Weekly Tier**__.",
        )

    def test_challenge_scoped_holds_alongside_week_medal(self):
        message = build_opening_medal_roundup_message(
            [
                standing("1001", "green", "🟩"),
                standing("1001", "highest_tier_challenge", "👑"),
            ]
        )
        self.assertEqual(
            message,
            "## Opening Medal Roundup\n"
            "- <@1001> earned 🟩 __**Green Week**__, "
            "and currently holds 👑 __**Highest Overall Tier**__.",
        )

    def test_earned_before_currently_holds(self):
        message = build_opening_medal_roundup_message(
            [
                standing("1001", "earliest_for_week", "☀️"),
                standing("1001", "green", "🟩"),
                standing("1001", "gold", "🏅"),
                standing("1001", "highest_tier_week", "💪"),
            ]
        )
        self.assertEqual(
            message,
            "## Opening Medal Roundup\n"
            "- <@1001> earned 🟩 __**Green Week**__ and 🏅 __**Gold Week**__, "
            "and currently holds 💪 __**Highest Weekly Tier**__.",
        )

    def test_multi_user_preserves_first_appearance_order(self):
        message = build_opening_medal_roundup_message(
            [
                standing("1002", "latest_for_week", "🌙"),
                standing("1001", "green", "🟩"),
                standing("1003", "diamond", "💎"),
            ]
        )
        self.assertEqual(
            message,
            "## Opening Medal Roundup\n"
            "- <@1001> earned 🟩 __**Green Week**__.\n"
            "- <@1003> earned 💎 __**Diamond Week**__.",
        )

    def test_three_earned_medals_use_oxford_comma(self):
        message = build_opening_medal_roundup_message(
            [
                standing("1001", "green", "🟩"),
                standing("1001", "gold", "🏅"),
                standing("1001", "first_to_green", "✳️"),
            ]
        )
        self.assertIn(
            "earned 🟩 __**Green Week**__, 🏅 __**Gold Week**__, and ✳️ __**First to Green**__.",
            message,
        )


if __name__ == "__main__":
    unittest.main()
