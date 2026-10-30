# Shared medal display/constants with no DB dependencies.

PERSONAL_TIER_MEDALS = frozenset({
    "highest_tier_personal", "highest_tier_personal_season", "highest_tier_personal_year",
})

SILENT_MEDALS = frozenset({
    "earliest_for_week", "latest_for_week", "earliest_for_challenge", "latest_for_challenge",
})

NON_STEALABLE_MEDALS = frozenset(
    {"green", "red", "diamond", "gold", "first_to_green", "all_gold", "all_green"} | PERSONAL_TIER_MEDALS
)

CHALLENGE_SCOPED_MEDALS = frozenset(
    {
        "highest_tier_challenge",
        "earliest_for_challenge",
        "latest_for_challenge",
        "all_gold",
        "all_green",
    }
)

nice_medal_names = {
    "highest_tier_personal": "Highest Ever Personal Tier",
    "highest_tier_personal_season": "Highest Seasonal Personal Tier",
    "highest_tier_personal_year": "Highest Yearly Personal Tier",
    "highest_tier_challenge": "Highest Overall Tier",
    "highest_tier_week": "Highest Weekly Tier",
    "gold": "Gold Week",
    "all_gold": "All Gold",
    "first_to_green": "First to Green",
    "green": "Green Week",
    "red": "Red Week",
    "diamond": "Diamond Week",
    "all_green": "All Green",
    "earliest_for_week": "Earliest Weekly Check-in",
    "latest_for_week": "Latest Weekly Check-in",
    "earliest_for_challenge": "Earliest Overall Check-in",
    "latest_for_challenge": "Latest Overall Check-in",
}
