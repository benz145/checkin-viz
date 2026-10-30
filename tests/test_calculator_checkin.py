import asyncio
import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DB_CONNECT_STRING", "postgresql://postgres:password@localhost/projects")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import checkin_submission as submission
from slash_commands import calc


class CalculatorSubmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.channel = NS(guild=NS(id=10), send=AsyncMock())
        self.interaction = NS(
            user=NS(id=123), guild_id=10,
            client=NS(get_channel=MagicMock(return_value=self.channel)),
            response=NS(defer=AsyncMock(), send_message=AsyncMock()),
            followup=NS(send=AsyncMock()), edit_original_response=AsyncMock(),
        )
        self.view = calc.SubmitCheckinView(123, "T5", "America/New_York")
        self.button = self.view.children[0]
        self.env = patch.dict(os.environ, {"ALLOWED_MESSAGE_CHANNEL_ID": "789"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.view.stop)

    async def test_save_owner_then_public_confirmation_and_feedback(self):
        with patch.object(calc, "save_checkin", return_value="saved") as save, patch.object(calc, "send_checkin_feedback", new_callable=AsyncMock) as feedback:
            await self.button.callback(self.interaction)
        save.assert_called_once_with("T5 check-in", "T5", 123, require_active_member=True)
        self.assertEqual(self.channel.send.call_args.args[0], "<@123> T5 check-in")
        feedback.assert_awaited_once_with(self.channel.send.return_value, "T5", "saved")
        self.assertTrue(self.button.disabled)
        self.assertEqual(self.button.label, "Submitted")

    async def test_concurrent_clicks_insert_once(self):
        with patch.object(calc, "save_checkin", return_value="saved") as save, patch.object(calc, "send_checkin_feedback", new_callable=AsyncMock):
            await asyncio.gather(self.button.callback(self.interaction), self.button.callback(self.interaction))
        save.assert_called_once()
        self.channel.send.assert_awaited_once()

    async def test_other_user_cannot_submit(self):
        self.interaction.user.id = 999
        with patch.object(calc, "save_checkin") as save:
            await self.button.callback(self.interaction)
        save.assert_not_called()
        self.interaction.response.send_message.assert_awaited_once()

    async def test_timeout_updates_private_result_and_disables_button(self):
        self.view.result_interaction = self.interaction
        with patch.object(calc, "save_checkin") as save:
            await self.view.on_timeout()
        save.assert_not_called()
        self.assertTrue(self.button.disabled)
        self.interaction.edit_original_response.assert_awaited_once_with(
            content=self.view.expired_message, view=self.view
        )

    async def test_timeout_does_not_overwrite_submission_status(self):
        self.view.result_interaction = self.interaction
        self.view.attempted = True
        await self.view.on_timeout()
        self.interaction.edit_original_response.assert_not_awaited()

    async def test_expired_and_previous_day_results_do_not_save(self):
        for expired in (True, False):
            with self.subTest(expired=expired):
                if expired:
                    self.view.expires_at = 0
                else:
                    self.view.expires_at = float("inf")
                    self.view.created_date -= timedelta(days=1)
                with patch.object(calc, "save_checkin") as save:
                    await self.button.callback(self.interaction)
                save.assert_not_called()

                self.assertEqual(
                    self.interaction.edit_original_response.call_args.kwargs["content"],
                    self.view.expired_message,
                )

    async def test_database_error_does_not_publish_or_repeat_insert(self):
        with patch.object(calc, "save_checkin", side_effect=RuntimeError("DB unavailable")) as save:
            await self.button.callback(self.interaction)
            await self.button.callback(self.interaction)
        save.assert_called_once()
        self.channel.send.assert_not_awaited()
        self.assertIn("Could not confirm", self.interaction.edit_original_response.call_args.kwargs["content"])

    async def test_validation_error_does_not_publish(self):
        with patch.object(calc, "save_checkin", side_effect=ValueError("Join first")):
            await self.button.callback(self.interaction)
        self.channel.send.assert_not_awaited()
        self.assertFalse(self.view.attempted)

    async def test_public_send_failure_never_reinserts(self):
        self.channel.send.side_effect = RuntimeError("Discord unavailable")
        with patch.object(calc, "save_checkin", return_value="saved") as save:
            await self.button.callback(self.interaction)
            await self.button.callback(self.interaction)
        save.assert_called_once()
        self.assertIn("was saved, but public confirmation failed", self.interaction.edit_original_response.call_args.kwargs["content"])

    async def test_medal_failure_reports_saved_state(self):
        with patch.object(calc, "save_checkin", return_value="saved"), patch.object(calc, "send_checkin_feedback", new_callable=AsyncMock, side_effect=RuntimeError("Medals failed")):
            await self.button.callback(self.interaction)
        self.assertIn("was saved and posted", self.interaction.edit_original_response.call_args.kwargs["content"])
        self.assertTrue(self.button.disabled)

    async def test_calculator_selects_higher_tier(self):
        for calories, minutes, expected in (("800", "30", "T6"), ("100", "120", "T7"), ("0", "0", "T0"), ("200", "15", "T0")):
            with self.subTest(expected=expected):
                modal = calc.Modal(title="Calculate")
                modal.children[0].value = calories
                modal.children[1].value = minutes
                with patch.object(calc, "challenger_by_discord_id", return_value=NS(bmr=2000, tz="America/New_York")):
                    await modal.callback(self.interaction)
                result = self.interaction.response.send_message.call_args.kwargs
                self.assertTrue(result["ephemeral"])
                self.assertEqual(result["view"].tier, expected)
                self.assertEqual(result["view"].children[0].label, f"Submit {expected} Check-in")
                result["view"].stop()

    async def test_invalid_calculator_input_has_no_submit_button(self):
        modal = calc.Modal(title="Calculate")
        modal.children[0].value = "-10"
        modal.children[1].value = "30"
        with patch.object(calc, "challenger_by_discord_id", return_value=NS(bmr=2000, tz="America/New_York")):
            await modal.callback(self.interaction)
        self.assertNotIn("view", self.interaction.response.send_message.call_args.kwargs)

    async def test_cross_server_submission_is_rejected(self):
        self.interaction.guild_id = 11
        with patch.object(calc, "save_checkin") as save:
            await self.button.callback(self.interaction)
        save.assert_not_called()
        self.channel.send.assert_not_awaited()


class PersistenceTests(unittest.TestCase):
    def test_owner_timezone_week_and_id_are_used_for_insert(self):
        challenger = NS(id=4, tz="America/Los_Angeles")
        week = NS(id=7, challenge_id=2)
        with patch.object(submission, "challenger_by_discord_id", return_value=challenger) as lookup, patch.object(submission, "get_current_challenge_week", return_value=week) as current, patch.object(submission, "fetchone", return_value=NS(challenger_id=4)), patch.object(submission, "insert_checkin", return_value="insert") as insert, patch.object(submission, "with_psycopg", return_value=42):
            saved = submission.save_checkin("T5 check-in", "T5", 123, require_active_member=True)
        lookup.assert_called_once_with("123")
        current.assert_called_once_with("America/Los_Angeles")
        insert.assert_called_once_with("T5 check-in", "T5", challenger, 7)
        self.assertEqual(saved.checkin_id, 42)
        self.assertEqual(saved.week, week)

    def test_missing_user_week_or_membership_never_inserts(self):
        for challenger, week, membership in ((None, None, None), (NS(tz="UTC", id=4), None, None), (NS(tz="UTC", id=4), NS(challenge_id=2), None)):
            with patch.object(submission, "challenger_by_discord_id", return_value=challenger), patch.object(submission, "get_current_challenge_week", return_value=week), patch.object(submission, "fetchone", return_value=membership), patch.object(submission, "with_psycopg") as insert:
                with self.assertRaises(ValueError):
                    submission.save_checkin("T5 check-in", "T5", 123, require_active_member=True)
                insert.assert_not_called()


class MedalOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_typed_checkins_share_feedback_and_bot_messages_are_ignored(self):
        import bot as handler
        client = NS(user=NS(id=999))
        message = NS(author=NS(id=123), channel=NS(id=789), content="T5 check-in")
        with patch.object(handler, "bot", client), patch.object(handler, "ALLOWED_MESSAGE_CHANNEL_ID", "789"), patch.object(handler, "save_checkin", return_value="saved") as save, patch.object(handler, "send_checkin_feedback", new_callable=AsyncMock) as feedback:
            await handler.on_message(message)
            save.assert_called_once_with("T5 check-in", "T5", 123)
            feedback.assert_awaited_once_with(message, "T5", "saved")
            message.author = client.user
            message.content = "<@123> T5 check-in"
            await handler.on_message(message)
            save.assert_called_once()

    async def test_bot_authored_confirmation_mentions_database_owners(self):
        message = NS(author=NS(id=999), add_reaction=AsyncMock(), reply=AsyncMock())
        saved = submission.SavedCheckin(42, NS(id=7, challenge_id=2, start=date(2026, 9, 7)))
        def medal(owner, previous=None, checkin_id=42):
            return NS(checkin_id=checkin_id, discord_id=owner, medal_name="highest_tier_week", medal_emoji="💪", stolen_discord_id=previous, stolen_checkin_challenger_name="Previous" if previous else None)
        for row, phrase in ((medal("123"), "<@123> earned"), (medal("123", "456"), "from <@456>!"), (medal("123", "123"), "<@123> still holds")):
            with self.subTest(phrase=phrase), patch.object(submission.medals, "update_medal_table"), patch.object(submission.medal_log, "get_medal_log", return_value=[row, medal("888", checkin_id=99)]), patch.object(submission, "should_suppress_medal_announcements", return_value=False):
                await submission.send_checkin_feedback(message, "T12", saved)
                reply = message.reply.call_args.args[0]
                self.assertIn(phrase, reply)
                self.assertIn("<@123>", reply)
                self.assertNotIn("<@999>", reply)
                self.assertNotIn("<@888>", reply)
                message.add_reaction.assert_any_await("✅")
                message.add_reaction.assert_any_await("🔥")
                message.add_reaction.assert_any_await("💪")

    async def test_roundup_suppression_keeps_medal_reactions(self):
        message = NS(add_reaction=AsyncMock(), reply=AsyncMock())
        saved = submission.SavedCheckin(42, NS(id=7, challenge_id=2, start=date(2026, 9, 7)))
        with patch.object(submission.medals, "update_medal_table"), patch.object(submission.medal_log, "get_medal_log", return_value=[NS(checkin_id=42, medal_name="highest_tier_week", medal_emoji="💪")]), patch.object(submission, "should_suppress_medal_announcements", return_value=True):
            await submission.send_checkin_feedback(message, "T5", saved)
        message.add_reaction.assert_any_await("💪")
        message.reply.assert_not_awaited()
