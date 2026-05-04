import discord
from base_queries import challenger_by_discord_id, update_challenger_bmr
from helpers import with_psycopg

INVALID_INPUT_MESSAGE = "Invalid input, please try again."


def calculate_bmr(sex, weight_lbs, height_feet, height_inches, age_years):
    weight_kg = float(weight_lbs) * 0.45359237
    height_cm = ((height_feet * 12) + height_inches) * 2.54

    if sex == "female":
        return int((10 * weight_kg) + (6.25 * height_cm) - (5 * age_years) - 161)
    return int((10 * weight_kg) + (6.25 * height_cm) - (5 * age_years) + 5)


def parse_positive_weight(weight_value):
    weight_lbs = float(weight_value)
    if weight_lbs <= 0:
        raise ValueError("Weight must be greater than 0.")
    if weight_lbs > 500:
        raise ValueError("Weight must be 500 lbs or less.")
    return weight_lbs


def parse_age(age_value):
    age_years = int(age_value)
    if age_years <= 0:
        raise ValueError("Age must be greater than 0.")
    if age_years > 120:
        raise ValueError("Age must be 120 or less.")
    return age_years


def parse_height(height_feet_value, height_inches_value):
    height_feet = int(height_feet_value)
    height_inches = int(height_inches_value)
    if height_feet < 0:
        raise ValueError("Height feet must be 0 or greater.")
    if height_feet > 7:
        raise ValueError("Height feet must be 7 or less.")
    if height_inches < 0 or height_inches > 12:
        raise ValueError("Height inches must be between 0 and 12.")
    if height_feet == 0 and height_inches == 0:
        raise ValueError("Height must be greater than 0.")
    return height_feet, height_inches


def bmr_response_text(current_bmr, previous_bmr):
    current_bmr_text = f"{current_bmr:,}"
    if previous_bmr is None:
        return f"Your BMR is now set to **{current_bmr_text}**."

    delta = current_bmr - int(float(previous_bmr))
    delta_text = f"{delta:+,d}"
    return (
        f"Your BMR is now set to **{current_bmr_text}**, a difference of "
        f"**{delta_text}** compared to your previous BMR."
    )


class BmrModal(discord.ui.DesignerModal):
    def __init__(self, challenger):
        super().__init__(title="Update BMR")
        self.challenger = challenger
        self.sex = discord.ui.RadioGroup()
        self.sex.add_option(label="Male", value="male")
        self.sex.add_option(label="Female", value="female")
        self.age = discord.ui.TextInput()
        self.height_feet = discord.ui.TextInput()
        self.height_inches = discord.ui.TextInput()
        self.weight = discord.ui.TextInput()
        self.add_item(discord.ui.Label("Sex", self.sex))
        self.add_item(discord.ui.Label("Age", self.age))
        self.add_item(discord.ui.Label("Height (feet)", self.height_feet))
        self.add_item(discord.ui.Label("Height (inches)", self.height_inches))
        self.add_item(discord.ui.Label("Current Weight (lbs)", self.weight))

    async def callback(self, interaction: discord.Interaction):
        try:
            sex = self.sex.value
            if sex is None:
                raise ValueError("Sex is required.")
            age_years = parse_age(self.age.value)
            height_feet, height_inches = parse_height(
                self.height_feet.value, self.height_inches.value
            )
            weight_lbs = parse_positive_weight(self.weight.value)
        except (TypeError, ValueError):
            await interaction.response.send_message(
                INVALID_INPUT_MESSAGE, ephemeral=True
            )
            return

        previous_bmr = self.challenger.bmr
        current_bmr = calculate_bmr(
            sex, weight_lbs, height_feet, height_inches, age_years
        )
        with_psycopg(update_challenger_bmr(self.challenger.id, current_bmr))
        await interaction.response.send_message(
            bmr_response_text(current_bmr, previous_bmr), ephemeral=True
        )


async def launch_bmr_modal(ctx: discord.ApplicationContext):
    user = getattr(ctx, "author", None) or getattr(ctx, "user", None)
    if user is None:
        await ctx.respond(
            "Could not determine which user invoked this command.",
            ephemeral=True,
        )
        return

    challenger = challenger_by_discord_id(str(user.id))
    if challenger is None:
        await ctx.respond(
            "You are not registered as a challenger yet.",
            ephemeral=True,
        )
        return

    await ctx.send_modal(BmrModal(challenger))
