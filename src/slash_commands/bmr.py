import discord
from datetime import date
from base_queries import (
    challenger_by_discord_id,
    latest_bmr_log_for_challenger,
    insert_bmr_log_and_update_challenger_bmr,
    clear_bmr_profile_for_challenger,
)
from helpers import with_psycopg

INVALID_INPUT_MESSAGE = "Invalid input, please try again."


def normalize_two_digit_year(two_digit_year):
    current_two_digit_year = date.today().year % 100
    century = 1900 if two_digit_year > current_two_digit_year else 2000
    return century + two_digit_year


def calculate_age_years(birthday):
    today = date.today()
    years = today.year - birthday.year
    if (today.month, today.day) < (birthday.month, birthday.day):
        years -= 1
    return years


def calculate_bmr(gender, weight_lbs, height_feet, height_inches, birthday):
    weight_kg = float(weight_lbs) * 0.45359237
    height_cm = ((height_feet * 12) + height_inches) * 2.54
    age_years = calculate_age_years(birthday)

    if gender == "female":
        return int((10 * weight_kg) + (6.25 * height_cm) - (5 * age_years) - 161)
    return int((10 * weight_kg) + (6.25 * height_cm) - (5 * age_years) + 5)


def parse_positive_weight(weight_value):
    weight_lbs = float(weight_value)
    if weight_lbs <= 0:
        raise ValueError("Weight must be greater than 0.")
    if weight_lbs > 500:
        raise ValueError("Weight must be 500 lbs or less.")
    return weight_lbs


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


def parse_gender(gender_value):
    gender = gender_value.strip().lower()
    gender_map = {
        "m": "male",
        "male": "male",
        "f": "female",
        "female": "female",
    }
    if gender not in gender_map:
        raise ValueError("Sex must be one of: m, f, male, or female.")
    return gender_map[gender]


def parse_birthday(birthday_value):
    raw = birthday_value.strip()
    parts = raw.split("-")
    if len(parts) != 3:
        raise ValueError("Birthday must use format MM-DD-YY or MM-DD-YYYY.")

    month_str, day_str, year_str = [x.strip() for x in parts]
    if not month_str.isdigit() or not day_str.isdigit() or not year_str.isdigit():
        raise ValueError("Birthday must contain numeric month, day, and year.")

    month = int(month_str)
    day = int(day_str)

    if len(year_str) == 2:
        year = normalize_two_digit_year(int(year_str))
    elif len(year_str) == 4:
        year = int(year_str)
    else:
        raise ValueError("Year must be 2 or 4 digits.")

    try:
        birthday = date(year, month, day)
    except ValueError:
        raise ValueError("Birthday is not a valid calendar date.")

    if birthday > date.today():
        raise ValueError("Birthday cannot be in the future.")
    return birthday


def bmr_response_text(current_bmr, previous_log):
    current_bmr_text = f"{current_bmr:,}"
    if previous_log is None:
        return f"Your BMR is now set to **{current_bmr_text}**."

    delta = current_bmr - int(float(previous_log.bmr))
    delta_text = f"{delta:+,d}"
    previous_date = previous_log.logged_at.strftime("%B %-d, %Y")
    return (
        f"Your BMR is now set to **{current_bmr_text}**, a difference of "
        f"**{delta_text}** compared to your last BMR logged on "
        f"**{previous_date}**."
    )


class FullBmrModal(discord.ui.Modal):
    def __init__(self, challenger):
        super().__init__(title="Update BMR")
        self.challenger = challenger
        self.add_item(discord.ui.InputText(label='Sex ("m" or "f")'))
        self.add_item(discord.ui.InputText(label="Birthday (MM-DD-YY)"))
        self.add_item(discord.ui.InputText(label="Height (feet)"))
        self.add_item(discord.ui.InputText(label="Height (inches)"))
        self.add_item(discord.ui.InputText(label="Current Weight (lbs)"))

    async def callback(self, interaction: discord.Interaction):
        try:
            gender = parse_gender(self.children[0].value)
            birthday = parse_birthday(self.children[1].value)
            height_feet, height_inches = parse_height(
                self.children[2].value, self.children[3].value
            )
            weight_lbs = parse_positive_weight(self.children[4].value)
        except (TypeError, ValueError):
            await interaction.response.send_message(
                INVALID_INPUT_MESSAGE, ephemeral=True
            )
            return

        previous_log = latest_bmr_log_for_challenger(self.challenger.id)
        current_bmr = calculate_bmr(
            gender, weight_lbs, height_feet, height_inches, birthday
        )
        with_psycopg(
            insert_bmr_log_and_update_challenger_bmr(
                self.challenger.id,
                gender,
                birthday,
                height_feet,
                height_inches,
                weight_lbs,
                current_bmr,
            )
        )
        await interaction.response.send_message(
            bmr_response_text(current_bmr, previous_log), ephemeral=True
        )


class WeightOnlyBmrModal(discord.ui.Modal):
    def __init__(self, challenger, profile):
        super().__init__(title="Update BMR")
        self.challenger = challenger
        self.profile = profile
        self.add_item(discord.ui.InputText(label="Current Weight (lbs)"))

    async def callback(self, interaction: discord.Interaction):
        try:
            weight_lbs = parse_positive_weight(self.children[0].value)
        except (TypeError, ValueError):
            await interaction.response.send_message(
                INVALID_INPUT_MESSAGE, ephemeral=True
            )
            return

        previous_log = latest_bmr_log_for_challenger(self.challenger.id)
        current_bmr = calculate_bmr(
            self.profile.gender,
            weight_lbs,
            self.profile.height_feet,
            self.profile.height_inches,
            self.profile.birthday,
        )
        with_psycopg(
            insert_bmr_log_and_update_challenger_bmr(
                self.challenger.id,
                self.profile.gender,
                self.profile.birthday,
                self.profile.height_feet,
                self.profile.height_inches,
                weight_lbs,
                current_bmr,
            )
        )
        await interaction.response.send_message(
            bmr_response_text(current_bmr, previous_log), ephemeral=True
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

    latest_log = latest_bmr_log_for_challenger(challenger.id)
    if latest_log is None:
        await ctx.send_modal(FullBmrModal(challenger))
        return

    await ctx.send_modal(WeightOnlyBmrModal(challenger, latest_log))


async def reset_bmr_profile(ctx: discord.ApplicationContext):
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

    with_psycopg(clear_bmr_profile_for_challenger(challenger.id))
    await ctx.respond(
        "Your BMR profile data has been reset. Use `/bmr` to complete first-time setup again.",
        ephemeral=True,
    )
