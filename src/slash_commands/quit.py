import discord
from base_queries import challenger_by_discord_id, get_current_challenge
from helpers import with_psycopg


class Button(discord.ui.View):
    @discord.ui.button(label="Yes, I am a quitter.", style=discord.ButtonStyle.primary)
    async def button_callback(self, button, interaction):
        id = interaction.user.id
        challenger = challenger_by_discord_id(str(id))
        current_challenge = get_current_challenge()
        print(challenger)
        await interaction.message.delete()

        def remove_challenger(conn, cur):
            print(f"Removing {challenger.id} from {current_challenge.id}")
            sql = """
                delete from challenger_challenges
                where challenger_id = %s
                and challenge_id = %s
                returning *
            """
            res = cur.execute(sql, [challenger.id, current_challenge.id])
            print(res)

        await interaction.response.send_message(
            f"You have disappointed us all {challenger.name}"
        )
        with_psycopg(remove_challenger)
