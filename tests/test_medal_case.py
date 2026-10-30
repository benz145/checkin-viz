import os
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DB_CONNECT_STRING", "postgresql://postgres:password@localhost/projects")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from slash_commands import medal_case
import medals
import test_personal_tier_medal as fixtures


def standing(medal_name, owner="123", emoji="💪", tier="T15", when=None):
    return NS(medal_name=medal_name, discord_id=owner, medal_emoji=emoji,
              challenger_name="Participant", checkin_tier=tier,
              checkin_time=when or datetime(2026, 10, 25, 23, 46))


class MedalCaseCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        period_lookup = patch.object(medal_case, "get_period_personal_records", return_value=[])
        period_lookup.start()
        self.addCleanup(period_lookup.stop)
        self.ctx = NS(author=NS(id=123), defer=AsyncMock(), followup=NS(send=AsyncMock()))
        self.challenger = NS(id=42, tz="Asia/Tokyo")
        self.week = NS(id=7, challenge_id=2)

    async def test_private_case_shows_all_holders_with_own_medals_first(self):
        record = NS(tier="T15", record_date=date(2026, 10, 25))
        rows = [
            standing("highest_tier_week"), standing("highest_tier_challenge", "456"),
            standing("earliest_for_week", "456"), standing("latest_for_week"),
            standing("green", emoji="🟩"), standing("highest_tier_personal", emoji="🏆"),
        ]
        with patch.object(medal_case, "challenger_by_discord_id", return_value=self.challenger) as lookup, patch.object(
            medal_case, "get_current_challenge_week", return_value=self.week
        ) as week_lookup, patch.object(medals, "get_current_week_medal_standings", return_value=rows) as holders, patch.object(
            medals, "get_personal_tier_record", return_value=record
        ) as personal, patch.object(medals, "update_medal_table") as update:
            await medal_case.send_medal_case(self.ctx)
        self.ctx.defer.assert_awaited_once_with(ephemeral=True)
        lookup.assert_called_once_with("123")
        week_lookup.assert_called_once_with("Asia/Tokyo")
        holders.assert_called_once_with(2, 7)
        personal.assert_called_once_with(42)
        update.assert_not_called()
        self.ctx.followup.send.assert_awaited_once()
        content = self.ctx.followup.send.call_args.args[0]
        self.assertTrue(self.ctx.followup.send.call_args.kwargs["ephemeral"])
        self.assertIn("Highest Weekly Tier", content)
        self.assertIn("- 🏆 T15 (October 25, 2026)", content)
        self.assertIn("October 25, 2026", content)
        self.assertIn("**Highest Weekly Tier**\n  - <@123> (T15)", content)
        self.assertIn("**Highest Overall Tier**\n  - <@456> (T15)", content)
        self.assertLess(content.index("Highest Weekly Tier"), content.index("Highest Overall Tier"))
        self.assertNotIn("Earliest", content)
        self.assertNotIn("Latest", content)
        self.assertTrue(content.startswith("## Medal Case\n\n**Currently Held**"))
        self.assertIn("**Your Personal Tier Record**\n- 🏆 T15 (October 25, 2026)", content)
        self.assertNotIn("Green Week", content)
        self.assertNotIn("Highest Ever Personal Tier", content)

    async def test_record_is_shown_between_challenges(self):
        with patch.object(medal_case, "challenger_by_discord_id", return_value=self.challenger), patch.object(
            medal_case, "get_current_challenge_week", return_value=None
        ), patch.object(medals, "get_current_week_medal_standings") as holders, patch.object(
            medals, "get_personal_tier_record", return_value=NS(tier="T0", record_date=date(2025, 1, 2))
        ):
            await medal_case.send_medal_case(self.ctx)
        holders.assert_not_called()
        content = self.ctx.followup.send.call_args.args[0]
        self.assertIn("no active challenge week", content)
        self.assertIn("**Your Personal Tier Record**\n- 🏆 T0 (January 2, 2025)", content)
        self.assertTrue(self.ctx.followup.send.call_args.kwargs["ephemeral"])

    async def test_period_records_use_selected_challenge_and_viewers_local_year(self):
        year_boundary = datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc)
        periods = [NS(scope="year", label="2027", tier="T5", record_date=date(2027, 1, 1))]
        with patch.object(medal_case, "challenger_by_discord_id", return_value=self.challenger), patch.object(
            medal_case, "get_current_challenge_week", return_value=self.week
        ), patch.object(medals, "get_current_week_medal_standings", return_value=[]), patch.object(
            medals, "get_personal_tier_record", return_value=None
        ), patch.object(medal_case, "get_period_personal_records", return_value=periods) as lookup, patch.object(
            medal_case, "datetime", wraps=datetime
        ) as clock:
            clock.now.side_effect = lambda tz: year_boundary.astimezone(tz)
            await medal_case.send_medal_case(self.ctx)
        lookup.assert_called_once_with(42, 2, 2027)
        self.assertIn("**Your Yearly Tier Record (2027)**\n- 🏆 T5 (January 1, 2027)", self.ctx.followup.send.call_args.args[0])
        self.assertTrue(self.ctx.followup.send.call_args.kwargs["ephemeral"])

    async def test_unregistered_user_gets_private_explanation(self):
        with patch.object(medal_case, "challenger_by_discord_id", return_value=None), patch.object(
            medals, "get_personal_tier_record"
        ) as personal:
            await medal_case.send_medal_case(self.ctx)
        personal.assert_not_called()
        self.assertIn("aren't registered", self.ctx.followup.send.call_args.args[0])
        self.assertTrue(self.ctx.followup.send.call_args.kwargs["ephemeral"])

    async def test_database_failure_stays_private_and_does_not_expose_error(self):
        with patch.object(medal_case, "challenger_by_discord_id", side_effect=RuntimeError("private DB details")):
            with self.assertLogs(level="ERROR"):
                await medal_case.send_medal_case(self.ctx)
        self.assertIn("try /medal-case", self.ctx.followup.send.call_args.args[0])
        self.assertNotIn("private DB details", self.ctx.followup.send.call_args.args[0])
        self.assertTrue(self.ctx.followup.send.call_args.kwargs["ephemeral"])

    def test_empty_case_has_clear_messages(self):
        content = medal_case.build_medal_case([], None)
        self.assertIn("No stealable medals are currently held", content)
        self.assertIn("No personal tier record yet", content)

    def test_retired_time_medals_are_hidden_even_when_passed_to_formatter(self):
        rows = [
            standing("earliest_for_week", when=datetime(2026, 10, 25, 0, 5)),
            standing("latest_for_week", when=datetime(2026, 10, 25, 12, 0)),
            standing("earliest_for_challenge"), standing("latest_for_challenge"),
        ]
        content = medal_case.build_medal_case(rows, None, viewer_discord_id=123)
        self.assertNotIn("Earliest", content)
        self.assertNotIn("Latest", content)
        self.assertIn("No stealable medals are currently held", content)

    def test_holder_without_discord_account_uses_name(self):
        content = medal_case.build_medal_case([standing("highest_tier_week", owner=None)], None)
        self.assertIn("\n  - Participant (T15)", content)
        self.assertNotIn("<@None>", content)

    async def test_command_is_registered_with_requested_name(self):
        import bot
        self.assertEqual(bot.medal_case_command.name, "medal-case")
        with patch.object(medal_case, "send_medal_case", new_callable=AsyncMock) as send:
            await bot.medal_case_command.callback(self.ctx)
        send.assert_awaited_once_with(self.ctx)


@unittest.skipUnless(os.environ.get("TEST_DB_CONNECT_STRING"), "Set TEST_DB_CONNECT_STRING to run PostgreSQL tests")
class MedalCasePostgresTests(unittest.TestCase):
    setUp = fixtures.PersonalTierPostgresTests.setUp
    checkin = fixtures.PersonalTierPostgresTests.checkin

    def test_all_time_record_uses_numeric_tier_first_date_and_original_timezone(self):
        self.checkin(1, "T9", "2025-01-01T12:00Z", week=1)
        self.checkin(2, "T14", "2025-01-02T01:30Z", week=1, tz="America/Los_Angeles")
        self.checkin(3, "T14", "2026-01-02T12:00Z", tz="Asia/Tokyo")
        record = medals.get_personal_tier_record(1)
        self.assertEqual(record.tier, "T14")
        self.assertEqual(record.record_date, date(2025, 1, 1))
        self.assertIsNone(medals.get_personal_tier_record(2))

    def test_personal_record_excludes_invalid_tiers_and_automatic_mulligans(self):
        self.checkin(1, "T15", "2025-01-01T12:00Z", week=1)
        self.conn.execute("INSERT INTO challenger_challenges VALUES (1, 1, 1)")
        self.checkin(2, "invalid", "2026-01-01T12:00Z")
        self.checkin(3, "T0", "2026-01-02T12:00Z")
        self.assertEqual(medals.get_personal_tier_record(1).tier, "T0")

    def award(self, name, checkin_id, owner, week=2):
        self.conn.execute(
            "INSERT INTO medals (medal, checkin_id, challenger_id, challenge_id, challenge_week_id, emoji) "
            "VALUES (%s, %s, %s, 2, %s, '💪')", [name, checkin_id, owner, week],
        )

    def test_stolen_medal_only_shows_current_owner_even_with_tied_award_times(self):
        self.checkin(1, "T5", "2026-01-01T12:00Z")
        self.checkin(2, "T6", "2026-01-02T12:00Z", challenger=2)
        self.award("highest_tier_week", 1, 1)
        self.award("highest_tier_week", 2, 2)
        rows = medals.get_current_week_medal_standings(2, 2)
        self.assertEqual([(row.medal_name, row.discord_id) for row in rows], [("highest_tier_week", "456")])
        self.assertEqual(rows[0].checkin_tier, "T6")
        self.assertEqual(rows[0].challenger_name, "Second")
        self.assertEqual(rows[0].checkin_time, datetime(2026, 1, 2, 7, 0))

    def test_time_medal_uses_checkin_timezone_not_current_participant_timezone(self):
        self.checkin(1, "T5", "2026-01-02T07:46Z", tz="America/Los_Angeles")
        self.award("latest_for_week", 1, 1)
        rows = medals.get_current_week_medal_standings(2, 2)
        self.assertEqual(rows[0].checkin_time, datetime(2026, 1, 1, 23, 46))
        self.assertNotIn("Latest Weekly Check-in", medal_case.build_medal_case(rows, None))

    def test_old_weekly_medals_expire_but_challenge_medals_carry_between_weeks(self):
        self.checkin(1, "T5", "2026-01-01T12:00Z")
        self.checkin(2, "T6", "2026-01-08T12:00Z", week=3, challenger=2)
        self.award("highest_tier_week", 1, 1)
        self.award("highest_tier_challenge", 1, 1)
        self.award("highest_tier_week", 2, 2, week=3)
        rows = medals.get_current_week_medal_standings(2, 3)
        self.assertEqual(
            {(row.medal_name, row.discord_id) for row in rows},
            {("highest_tier_challenge", "123"), ("highest_tier_week", "456")},
        )


if __name__ == "__main__":
    unittest.main()
