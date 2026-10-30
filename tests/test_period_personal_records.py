import os
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DB_CONNECT_STRING", "postgresql://postgres:password@localhost/projects")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import checkin_submission as submission
import medal_log
import medals
import personal_records as records
from medal_constants import NON_STEALABLE_MEDALS, PERSONAL_TIER_MEDALS, SILENT_MEDALS
from medal_roundup import build_opening_medal_roundup_message
from slash_commands.medal_case import build_medal_case
from slash_commands import testpodium
import test_personal_tier_medal as fixtures


class PeriodAnnouncementTests(unittest.IsolatedAsyncioTestCase):
    def row(self, name, **kwargs):
        return NS(checkin_id=42, discord_id="123", medal_name=name, medal_emoji="🏆",
                  checkin_tier="T12", personal_previous_tier="T9",
                  personal_previous_date=date(2026, 6, 2),
                  personal_period_label="Summer 2026" if name.endswith("season") else "2026",
                  **kwargs)

    async def feedback(self, rows, suppressed):
        message = NS(author=NS(id=999), add_reaction=AsyncMock(), reply=AsyncMock())
        saved = submission.SavedCheckin(42, NS(id=2, challenge_id=2, start=date(2026, 6, 1)))
        with patch.object(medals, "update_medal_table"), patch.object(
            medal_log, "get_medal_log", return_value=rows
        ), patch.object(submission, "should_suppress_medal_announcements", return_value=suppressed):
            await submission.send_checkin_feedback(message, "T12", saved)
        return message

    async def test_scoped_records_follow_silence_but_all_time_does_not(self):
        scoped = [self.row("highest_tier_personal_season"), self.row("highest_tier_personal_year")]
        message = await self.feedback(scoped, True)
        message.reply.assert_not_awaited()
        message.add_reaction.assert_any_await("🏆")
        message = await self.feedback([*scoped, self.row("highest_tier_personal")], True)
        reply = message.reply.call_args.args[0]
        self.assertIn("Highest Ever Personal Tier", reply)
        self.assertNotIn("Seasonal", reply)
        self.assertNotIn("Yearly", reply)

    async def test_scoped_records_announce_owner_tier_period_and_previous_date(self):
        message = await self.feedback([
            self.row("highest_tier_personal_season"), self.row("highest_tier_personal_year")
        ], False)
        reply = message.reply.call_args.args[0]
        self.assertIn("Highest Seasonal Personal Tier**__ (Summer 2026)", reply)
        self.assertIn("Highest Yearly Personal Tier**__ (2026)", reply)
        self.assertEqual(reply.count("<@123>"), 2)
        self.assertEqual(reply.count("exceeding their T9 check-in on June 2, 2026!"), 2)
        self.assertNotIn("999", reply)
        self.assertNotIn("stole", reply)

    async def test_all_four_time_medals_are_silent_with_or_without_suppression(self):
        for suppressed in (True, False):
            with self.subTest(suppressed=suppressed):
                message = await self.feedback([self.row(name) for name in SILENT_MEDALS], suppressed)
                message.reply.assert_not_awaited()
                self.assertEqual([call.args[0] for call in message.add_reaction.await_args_list], ["✅", "🔥"])

    async def test_time_medal_steals_and_self_improvements_never_announce_or_react(self):
        for name in SILENT_MEDALS:
            for previous_owner in ("123", "456"):
                with self.subTest(name=name, previous_owner=previous_owner):
                    row = self.row(name, stolen_checkin_challenger_name="Previous",
                                   stolen_discord_id=previous_owner)
                    message = await self.feedback([row], False)
                    message.reply.assert_not_awaited()
                    self.assertEqual([call.args[0] for call in message.add_reaction.await_args_list], ["✅", "🔥"])

    async def test_time_medal_does_not_hide_a_record_announcement(self):
        message = await self.feedback([
            self.row("earliest_for_week"), self.row("highest_tier_personal_season")
        ], False)
        self.assertIn("Seasonal", message.reply.call_args.args[0])
        self.assertNotIn("Earliest", message.reply.call_args.args[0])

    def test_roundup_excludes_time_medals_and_includes_scoped_records_as_earned(self):
        rows = [self.row(name) for name in SILENT_MEDALS]
        self.assertIsNone(build_opening_medal_roundup_message(rows))
        message = build_opening_medal_roundup_message(rows + [self.row("highest_tier_personal_year")])
        self.assertIn("earned 🏆 __**Highest Yearly Personal Tier**__", message)
        self.assertNotIn("Earliest", message)
        self.assertNotIn("Latest", message)
        self.assertTrue(PERSONAL_TIER_MEDALS <= NON_STEALABLE_MEDALS)

    def test_challenge_summary_excludes_time_medals(self):
        counts = testpodium.collect_all_achievement_tags([
            *[self.row(name) for name in SILENT_MEDALS], self.row("highest_tier_personal_year")
        ])
        self.assertEqual(counts, {"highest_tier_personal_year": {"123": 1}})

    def test_medal_case_period_titles_tiers_dates_and_empty_record(self):
        periods = [NS(scope="season", label="Summer 2026", tier="T12", record_date=date(2026, 6, 2)),
                   NS(scope="year", label="2026", tier=None, record_date=None)]
        content = build_medal_case([], NS(tier="T20", record_date=date(2025, 1, 1)), period_records=periods)
        self.assertIn("**Your Personal Tier Record**\n- 🏆 T20 (January 1, 2025)", content)
        self.assertIn("**Your Seasonal Tier Record (Summer 2026)**\n- 🏆 T12 (June 2, 2026)", content)
        self.assertIn("**Your Yearly Tier Record (2026)**\nNo personal tier record yet", content)


@unittest.skipUnless(os.environ.get("TEST_DB_CONNECT_STRING"), "Requires local PostgreSQL")
class PeriodPostgresTests(unittest.TestCase):
    setUp = fixtures.PersonalTierPostgresTests.setUp
    checkin = fixtures.PersonalTierPostgresTests.checkin

    def seasons(self, first="Summer 2026 Part 1", second="Summer 2026 Part 2"):
        self.conn.execute("UPDATE challenges SET name = %s WHERE id = 1", [first])
        self.conn.execute("UPDATE challenges SET name = %s WHERE id = 2", [second])

    def ids(self, scope, week=2):
        return [row.checkin_id for row in records.period_record_medal(week, scope, execute=True)]

    def test_season_combines_parts_and_compares_numeric_tiers_against_history(self):
        self.seasons()
        self.checkin(1, "T9", "2026-06-01T12:00Z", week=1)
        self.checkin(2, "T9", "2026-07-01T12:00Z")
        self.checkin(3, "T8", "2026-07-02T12:00Z")
        self.checkin(4, "T10", "2026-07-03T12:00Z")
        self.assertEqual(self.ids("season"), [4])
        self.assertEqual(self.ids("year"), [4])

    def test_every_season_groups_both_parts(self):
        for season in ("Summer", "Fall", "Winter", "Spring"):
            with self.subTest(season=season):
                self.seasons(f"{season} 2026 Part 1", f"{season.upper()} 2026 part 2")
                self.conn.execute("DELETE FROM checkins")
                self.checkin(1, "T10", "2026-01-01T12:00Z", week=1)
                self.checkin(2, "T9", "2026-02-01T12:00Z")
                self.assertEqual(self.ids("season"), [])

    def test_new_season_and_season_year_reset_independently(self):
        self.checkin(1, "T20", "2025-06-01T12:00Z", week=1)
        self.checkin(2, "T1", "2026-06-01T12:00Z")
        for first, second in (("Summer 2025 Part 1", "Summer 2026 Part 2"),
                              ("Spring 2026 Part 1", "Summer 2026 Part 2")):
            self.seasons(first, second)
            self.assertEqual(self.ids("season"), [2])

    def test_winter_uses_named_year_across_calendar_rollover(self):
        self.seasons("Winter 2026 Part 1", "Winter 2026 Part 2")
        self.checkin(1, "T10", "2025-12-10T12:00Z", week=1)
        self.checkin(2, "T9", "2026-01-10T12:00Z")
        self.assertEqual(self.ids("season"), [])
        self.assertEqual(self.ids("year"), [2])

    def test_year_boundary_uses_original_checkin_timezone_and_resets(self):
        self.checkin(1, "T15", "2026-01-01T01:00Z", week=1, tz="America/Los_Angeles")
        self.checkin(2, "T1", "2026-01-01T10:00Z", tz="Asia/Tokyo")
        self.assertEqual(self.ids("year"), [2])
        by_year = records.get_period_personal_records(1, None, 2025)
        self.assertEqual((by_year[0].tier, by_year[0].record_date), ("T15", date(2025, 12, 31)))
        self.assertEqual(records.get_period_personal_records(1, None, 2026)[0].tier, "T1")

    def test_records_are_per_user_ignore_mulligans_and_accept_zero(self):
        self.seasons()
        self.checkin(1, "T99", "2026-06-01T12:00Z", week=1)
        self.conn.execute("INSERT INTO challenger_challenges VALUES (1, 1, 1)")
        self.checkin(2, "T20", "2026-06-02T12:00Z", week=1, challenger=2)
        self.checkin(3, "T0", "2026-07-01T12:00Z")
        self.checkin(4, "T19", "2026-07-02T12:00Z", challenger=2)
        for scope in ("season", "year"):
            self.assertEqual(self.ids(scope), [3])

    def test_unknown_season_is_not_guessed_but_yearly_medal_still_works(self):
        self.checkin(1, "T3", "2026-01-02T12:00Z")
        self.assertEqual(self.ids("season"), [])
        self.assertEqual(self.ids("year"), [1])
        contexts = records.get_period_personal_records(1, 2, 2026)
        self.assertEqual([row.scope for row in contexts], ["year"])

    def test_year_without_valid_checkins_is_explicitly_unset(self):
        periods = records.get_period_personal_records(2, None, 2026)
        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0].label, "2026")
        self.assertIsNone(periods[0].tier)

    def test_invalid_tiers_do_not_poison_scoped_baselines(self):
        self.seasons()
        self.checkin(1, "invalid", "2026-06-01T12:00Z", week=1)
        self.checkin(2, "T-1", "2026-06-02T12:00Z", week=1)
        self.checkin(3, "T0", "2026-07-01T12:00Z")
        for scope in ("season", "year"):
            self.assertEqual(self.ids(scope), [3])

    def test_deleted_record_restores_scoped_baseline(self):
        self.seasons()
        self.checkin(1, "T9", "2026-06-01T12:00Z", week=1)
        self.checkin(2, "T15", "2026-07-01T12:00Z")
        self.conn.execute("DELETE FROM checkins WHERE id = 2")
        self.checkin(3, "T10", "2026-07-02T12:00Z")
        for scope in ("season", "year"):
            self.assertEqual(self.ids(scope), [3])
        self.assertTrue(all(row.tier == "T10" for row in records.get_period_personal_records(1, 2, 2026)))

    def test_autumn_alias_and_case_match_fall(self):
        self.seasons("Autumn 2026 part 1", "FALL 2026 PART 2")
        self.checkin(1, "T10", "2026-09-01T12:00Z", week=1)
        self.checkin(2, "T9", "2026-10-01T12:00Z")
        self.assertEqual(self.ids("season"), [])
        self.assertEqual(records.get_period_personal_records(1, 2, 2026)[0].label, "Fall 2026")

    def test_multiple_records_same_timestamp_are_deterministic_and_idempotent(self):
        self.seasons()
        for checkin_id, tier in enumerate(("T9", "T10", "T10"), 1):
            self.checkin(checkin_id, tier, "2026-06-01T12:00Z")
        for scope in ("season", "year"):
            rows = records.period_record_medal(2, scope, execute=True)
            self.assertEqual([row.checkin_id for row in rows], [1, 2])
            for _ in range(2):
                medals.insert_medals([row._asdict() for row in rows], 2)
        awards = self.conn.execute("SELECT * FROM medals").fetchall()
        self.assertEqual(len(awards), 4)
        self.assertTrue(all(row.steal is None for row in awards))
        counts = testpodium.collect_all_achievement_tags(testpodium.get_final_medal_holders_per_week(2))
        self.assertEqual(counts["highest_tier_personal_season"], {"123": 2})
        self.assertEqual(counts["highest_tier_personal_year"], {"123": 2})

    def test_scoped_previous_record_and_medal_case_use_first_achievement_date(self):
        self.seasons()
        self.checkin(1, "T9", "2026-06-02T01:00Z", week=1, tz="America/Los_Angeles")
        self.checkin(2, "T9", "2026-06-03T12:00Z", week=1)
        self.checkin(3, "T10", "2026-07-01T12:00Z")
        for scope in ("season", "year"):
            rows = records.period_record_medal(2, scope, execute=True)
            medals.insert_medals([row._asdict() for row in rows], 2)
        for row in medal_log.get_medal_log(2):
            self.assertEqual(row.personal_previous_tier, "T9")
            self.assertEqual(row.personal_previous_date, date(2026, 6, 1))
            self.assertIn(row.personal_period_label, ("Summer 2026", "2026"))
        periods = records.get_period_personal_records(1, 2, 2026)
        self.assertEqual([row.tier for row in periods], ["T10", "T10"])

    def test_other_periods_do_not_leak_into_previous_record(self):
        self.seasons("Spring 2025 part 2", "Summer 2026 part 1")
        self.checkin(1, "T20", "2025-04-01T12:00Z", week=1)
        self.checkin(2, "T0", "2026-06-01T12:00Z")
        for scope in ("season", "year"):
            rows = records.period_record_medal(2, scope, execute=True)
            medals.insert_medals([row._asdict() for row in rows], 2)
        self.assertTrue(all(row.personal_previous_tier is None for row in medal_log.get_medal_log(2)))

    def test_full_pipeline_tracks_time_medals_and_nonstealable_records(self):
        self.seasons()
        self.checkin(1, "T3", "2026-07-01T12:00Z")
        with patch("builtins.print"):
            medals.update_medal_table(2, 2)
        log = medal_log.get_medal_log(2)
        self.assertTrue(SILENT_MEDALS <= {row.medal_name for row in log})
        self.assertTrue(PERSONAL_TIER_MEDALS <= {row.medal_name for row in log})
        self.assertTrue(all(row.steal is None for row in self.conn.execute(
            "SELECT steal FROM medals WHERE medal LIKE 'highest_tier_personal%'").fetchall()))


if __name__ == "__main__":
    unittest.main()
