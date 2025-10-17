import discord
from base_queries import challenger_by_discord_id, get_current_challenge
from helpers import with_psycopg


class Button(discord.ui.View):
    @discord.ui.button(label="Yes, I will win.", style=discord.ButtonStyle.primary)
    async def button_callback(self, button, interaction):
        id = interaction.user.id
        challenger = challenger_by_discord_id(str(id))
        current_challenge = get_current_challenge()
        print(challenger)
        await interaction.message.delete()

        def add_challenger(conn, cur):
            print(f"Adding {challenger.id} to {current_challenge.id}")
            sql = """
                insert into challenger_challenges
                    (challenger_id, challenge_id, tier, ante, knocked_out, bi_checkins)
                values (%s, %s, 'floating', 0, false, 0);
            """
            res = cur.execute(sql, [challenger.id, current_challenge.id])

        await interaction.response.send_message(f"Good luck {challenger.name}")
        with_psycopg(add_challenger)
