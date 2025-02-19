import discord
import asyncio

def make_embed(msg: str) -> discord.Embed:
    return discord.Embed(description=msg, color=discord.Color.purple())

async def send_temp(interaction: discord.Interaction, embed: discord.Embed, delay: int = 10):
    msg = await interaction.followup.send(embed=embed, wait=True)
    await asyncio.sleep(delay)
    await msg.delete()