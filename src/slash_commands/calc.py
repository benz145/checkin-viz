import discord
import math
from base_queries import challenger_by_discord_id, get_current_challenge
from simpleeval import simple_eval
from helpers import with_psycopg


class Modal(discord.ui.Modal):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.add_item(discord.ui.InputText(label="Calories Burnt"))
        self.add_item(discord.ui.InputText(label="Time Spent"))

    async def callback(self, interaction: discord.Interaction):
        id = interaction.user.id
        challenger = challenger_by_discord_id(str(id))

        calories = simple_eval(self.children[0].value)
        time = simple_eval(self.children[1].value)
        calTier = self.tier_for_calories(challenger.bmr, calories)
        timeTier = self.tier_for_time(time)
        calToNextTier = self.calories_for_next_tier(challenger.bmr, calTier) - calories
        timeToNextTier = self.time_for_next_tier(timeTier) - time

        embed = discord.Embed(title="Tier Results")
        embed.add_field(name="Calories tier:", value=f"T{calTier}", inline=False)
        embed.add_field(name="Time tier:", value=f"T{timeTier}", inline=False)
        embed.add_field(
            name="Calories to next tier:",
            value=f"{calToNextTier} calories",
            inline=False,
        )
        embed.add_field(
            name="Time to next tier:", value=f"{timeToNextTier} minutes", inline=False
        )

        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    def calories_for_next_tier(self, bmr, currentTier):
        nextTier = currentTier + 1
        return math.floor((((5 * (nextTier - 1)) / 100) + 0.15) * bmr)

    def time_for_next_tier(self, currentTier):
        nextTier = currentTier + 1
        return math.floor(15 * (nextTier + 1))

    def tier_for_calories(self, bmr, calories):
        return max(0, math.floor((20 * (calories + 1)) / bmr - 2))

    def tier_for_time(self, time):
        return max(0, math.floor(time / 15 - 1))
