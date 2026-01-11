import discord
intents = discord.Intents.default()
intents.message_content = True

bot = discord.Bot(intents=intents)
