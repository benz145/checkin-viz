from auto_knockout import (
    AutoKnockoutEvent,
    build_auto_knockout_daily_message,
)


def build_warning_test_message(discord_id: str) -> str:
    """
    Build a mock auto-knockout daily message using the real formatters.
    All sample events mention the invoking user so formatting can be checked
    without pinging other challengers.
    """
    action_events = [
        AutoKnockoutEvent(
            action="mulligan",
            challenge_id=0,
            challenger_id=0,
            name="Test User",
            required_checkins=2,
            checkin_count=0,
            challenge_week_id=0,
            discord_id=discord_id,
            mulligan_checkin_id=1,
            mulligan_day="Tuesday",
        ),
        AutoKnockoutEvent(
            action="knockout",
            challenge_id=0,
            challenger_id=0,
            name="Test User",
            required_checkins=5,
            checkin_count=3,
            challenge_week_id=0,
            discord_id=discord_id,
        ),
    ]
    warning_events = [
        AutoKnockoutEvent(
            action="warning",
            challenge_id=0,
            challenger_id=0,
            name="Test User",
            required_checkins=2,
            checkin_count=0,
            challenge_week_id=0,
            discord_id=discord_id,
            remaining_checkin_days=("Saturday", "Sunday"),
            has_mulligan_available=True,
        ),
        AutoKnockoutEvent(
            action="warning",
            challenge_id=0,
            challenger_id=0,
            name="Test User",
            required_checkins=5,
            checkin_count=3,
            challenge_week_id=0,
            discord_id=discord_id,
            remaining_checkin_days=("Sunday",),
            has_mulligan_available=False,
        ),
    ]

    message = build_auto_knockout_daily_message(action_events, warning_events)
    return f"_Mock auto-knockout message for formatting_\n\n{message}"
