import discord
import os
import random
import logging
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True


logging.basicConfig(level=logging.INFO)

class FoodView(discord.ui.View):
    def __init__(self, category: str):
        super().__init__(timeout=None)  # persistent view
        self.category = category

    @discord.ui.button(label="Another!", style=discord.ButtonStyle.primary, emoji="🍽️")
    async def another(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Serve another random image/fact from the same category
        url = random.choice(FOOD_IMAGES[self.category])
        fact = random.choice(FUN_FACTS[self.category])
        embed = discord.Embed(
            title=f"Here’s another {self.category} 🍽️",
            description=f"Fun fact: {fact}",
            color=discord.Color.blue()
        )
        embed.set_image(url=url)
        embed.set_footer(text="Bon appétit again!")
        await interaction.response.edit_message(embed=embed, view=FoodView(self.category))

class FoodBot(commands.Bot):
    async def setup_hook(self):
        dev_mode = os.getenv("DEV_MODE", "false").lower() == "true"
        if dev_mode:
            guild_id = os.getenv("GUILD_ID")
            if guild_id:
                guild = discord.Object(id=int(guild_id))
                await self.tree.sync(guild=guild)
                logging.info(f"✅ Synced commands to guild {guild_id} (DEV_MODE)")
        else:
            priority_guild_id = os.getenv("PRIORITY_GUILD_ID")
            if priority_guild_id:
                guild = discord.Object(id=int(priority_guild_id))
                await self.tree.sync(guild=guild)
                logging.info(f"🏠 Synced commands to priority guild {priority_guild_id} (PROD_MODE)")
            else:
                await self.tree.sync()
                logging.info("🌍 Synced commands globally (PROD_MODE)")


bot = FoodBot(command_prefix="!", intents=intents)

FOOD_IMAGES = {
    "burger": [
        "https://cdn.discordapp.com/attachments/1517278740290212031/1517279900506128555/Z.png",
        "https://cdn.discordapp.com/attachments/1517278740290212031/1517279613963735151/2Q.png",
        "https://cdn.discordapp.com/attachments/1517278740290212031/1517279822613713079/Z.png",
        "https://cdn.discordapp.com/attachments/1517278740290212031/1517279955887718602/9k.png"
    ],
    "pizza": [
        "https://cdn.discordapp.com/attachments/1517278740290212031/1517294247022166156/2Q.png",
        "https://cdn.discordapp.com/attachments/1517278740290212031/1517319668988252342/2Q.png",
        "https://cdn.discordapp.com/attachments/1517278740290212031/1517319782519799969/9k.png",
        "https://cdn.discordapp.com/attachments/1517278740290212031/1517319890548162570/images.png"
    ],
    "taco": [
        "https://cdn.discordapp.com/attachments/1517278740290212031/1517294129770659981/9k.png",
        "https://cdn.discordapp.com/attachments/1517278740290212031/1517319353887096882/images.png",
        "https://cdn.discordapp.com/attachments/1517278740290212031/1517319514730008626/images.png",
        "https://cdn.discordapp.com/attachments/1517278740290212031/1517319216649343048/2Q.png"
    ],
    "sushi": [
        "https://cdn.discordapp.com/attachments/1517278740290212031/1517314398027513907/Z.png",
        "https://cdn.discordapp.com/attachments/1517278740290212031/1517318518851375195/images.png",
        "https://cdn.discordapp.com/attachments/1517278740290212031/1517318628213526700/images.png",
        "https://cdn.discordapp.com/attachments/1517278740290212031/1517318807910355014/images.png"
        
    ]
}

FUN_FACTS = {\
    "burger": [
        "Burgers became popular in the U.S. in the early 1900s.",
        "The world’s largest burger weighed over 2,000 pounds!",
        "Cheeseburgers were first invented in the 1920s.",
        "McDonald’s sells over 75 burgers every second worldwide."
    ],
    "pizza": [
        "Pizza originated in Naples, Italy, as a street food.",
        "The world’s largest pizza was over 13,000 square feet!",
        "October is National Pizza Month in the U.S.",
        "The Margherita pizza was named after Queen Margherita of Savoy."
    ],
    "taco": [
        "Tacos date back to the 18th century in Mexico.",
        "The word 'taco' means 'plug' or 'wad' in Spanish.",
        "There’s a Taco Festival held annually in Mexico City.",
        "Hard-shell tacos were popularized in the U.S. in the 1940s."
    ],
    "sushi": [
        "Sushi began as a way to preserve fish in fermented rice.",
        "The word 'sushi' refers to the rice, not the fish.",
        "Japan has conveyor belt sushi restaurants called 'kaitenzushi'.",
        "The world’s most expensive sushi roll costs over $1,900!"
    ]
}

# /food command
@bot.tree.command(name="food", description="Sends a random image of the chosen food")
@app_commands.describe(item="Choose a food type")
@app_commands.choices(item=[
    app_commands.Choice(name="Burger", value="burger"),
    app_commands.Choice(name="Pizza", value="pizza"),
    app_commands.Choice(name="Taco", value="taco"),
    app_commands.Choice(name="Sushi", value="sushi")
])
async def food(interaction: discord.Interaction, item: app_commands.Choice[str]):
    try:
        url = random.choice(FOOD_IMAGES[item.value])
        fact = random.choice(FUN_FACTS[item.value])
        embed = discord.Embed(
            title=f"Here's a {item.name} for you 🍽️",
            description=f"Fun fact: {fact}",
            color=discord.Color.green()
        )
        embed.set_image(url=url)
        embed.set_footer(text="Bon appétit!")
        await interaction.response.send_message(embed=embed, view=FoodView(item.value))
    except Exception as e:
        await interaction.response.send_message(
            f"⚠️ Something went wrong serving {item.name}. Error: {e}"
        )


# /randomfood command
@bot.tree.command(name="randomfood", description="Sends a random food image and fun fact")
async def randomfood(interaction: discord.Interaction):
    try:
        category = random.choice(list(FOOD_IMAGES.keys()))
        url = random.choice(FOOD_IMAGES[category])
        fact = random.choice(FUN_FACTS[category])
        embed = discord.Embed(
            title="Here’s a surprise dish 🍽️",
            description=f"You didn’t choose, so I picked {category}!\n\nFun fact: {fact}",
            color=discord.Color.orange()
        )
        embed.set_image(url=url)
        embed.set_footer(text="Bon appétit!")
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"⚠️ Error serving random food: {e}")

# /foodfact command
@bot.tree.command(name="foodfact", description="Get a random fun fact about food")
async def foodfact(interaction: discord.Interaction):
    try:
        category = random.choice(list(FUN_FACTS.keys()))
        fact = random.choice(FUN_FACTS[category])
        await interaction.response.send_message(
            f"🍴 Fun fact about {category}: {fact}"
        )
    except Exception as e:
        await interaction.response.send_message(f"⚠️ Error serving food fact: {e}")

# Run the bot
token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN environment variable not set")
bot.run(token)

#python C:\Users\onehu\foodbot\foodbot.py -- use if you want to run the bot locally
