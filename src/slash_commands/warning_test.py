from auto_knockout import (
    AutoKnockoutEvent,
    build_auto_knockout_daily_message,
)


# Synthetic IDs for grouping demos. They are not real Discord users, so they
# will not ping anyone; the invoker is always included so the tester is notified.
_MOCK_USER_IDS = ("1000000000000000001", "1000000000000000002")


def _event(action, discord_id, challenger_id=0, **kwargs):
    return AutoKnockoutEvent(
        action=action,
        challenge_id=0,
        challenger_id=challenger_id,
        name="Test User",
        challenge_week_id=0,
        discord_id=discord_id,
        **kwargs,
    )


def build_warning_test_message(discord_id: str) -> str:
    """
    Build a mock auto-knockout daily message using the real formatters.

    Includes multiple users with matching conditions so natural-language
    grouping can be verified. The invoking user is always one of the mentions;
    other IDs are synthetic and will not ping real members.
    """
    mock_a, mock_b = _MOCK_USER_IDS

    action_events = [
        _event(
            "knockout",
            discord_id,
            required_checkins=5,
            checkin_count=3,
        ),
        _event(
            "knockout",
            mock_a,
            challenger_id=1,
            required_checkins=5,
            checkin_count=2,
        ),
        _event(
            "mulligan",
            discord_id,
            challenger_id=2,
            required_checkins=2,
            checkin_count=1,
            mulligan_checkin_id=1,
            mulligan_day="Tuesday",
        ),
        _event(
            "mulligan",
            mock_b,
            challenger_id=3,
            required_checkins=2,
            checkin_count=1,
            mulligan_checkin_id=2,
            mulligan_day="Wednesday",
        ),
    ]
    warning_events = [
        # Knockout-risk group (identical remaining days + no mulligan)
        _event(
            "warning",
            discord_id,
            challenger_id=4,
            required_checkins=2,
            checkin_count=1,
            remaining_checkin_days=("Sunday",),
            has_mulligan_available=False,
        ),
        _event(
            "warning",
            mock_a,
            challenger_id=5,
            required_checkins=2,
            checkin_count=1,
            remaining_checkin_days=("Sunday",),
            has_mulligan_available=False,
        ),
        # Mulligan-risk group (identical remaining days + mulligan available)
        _event(
            "warning",
            discord_id,
            challenger_id=6,
            required_checkins=2,
            checkin_count=0,
            remaining_checkin_days=("Saturday", "Sunday"),
            has_mulligan_available=True,
        ),
        _event(
            "warning",
            mock_a,
            challenger_id=7,
            required_checkins=2,
            checkin_count=0,
            remaining_checkin_days=("Saturday", "Sunday"),
            has_mulligan_available=True,
        ),
        _event(
            "warning",
            mock_b,
            challenger_id=8,
            required_checkins=2,
            checkin_count=0,
            remaining_checkin_days=("Saturday", "Sunday"),
            has_mulligan_available=True,
        ),
    ]

    message = build_auto_knockout_daily_message(action_events, warning_events)
    return f"_Mock auto-knockout message for formatting_\n{message}"
