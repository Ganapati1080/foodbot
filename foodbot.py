# foodbot.py

import functools
from typing import Any, Callable

def track_food_requests(func: Callable) -> Callable:
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        # optional: inspect args to log or increment stats
        try:
            # call the original command/callback
            return await func(*args, **kwargs)
        finally:
            # optional: post-call tracking (safe to run even if func raises)
            pass
    return wrapper

import os
import random
import logging
import sqlite3
import atexit
import datetime
import threading
from typing import List, Tuple, Optional

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# --- Keep-alive server for Replit ---
app = Flask('')

@app.route('/')
def home():
    return "FoodBot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

Thread(target=run, daemon=True).start()
# ------------------------------------

load_dotenv()
logging.basicConfig(level=logging.INFO)

# --- Database helper (thread-safe) ---
DB_PATH = "foodbot.db"

class DB:
    def __init__(self, path: str):
        # allow access from multiple threads/tasks
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self._ensure_tables()

    def _ensure_tables(self):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS food_stats (
                    category TEXT PRIMARY KEY,
                    count INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS food_data (
                    category TEXT PRIMARY KEY,
                    images TEXT,
                    facts TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_food_stats (
                    user_id TEXT,
                    category TEXT,
                    count INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, category)
                )
            """)
            self.conn.commit()

    def add_food(self, category: str, images: List[str], facts: List[str]):
        images_s = self._join(images)
        facts_s = self._join(facts)
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("INSERT OR REPLACE INTO food_data (category, images, facts) VALUES (?, ?, ?)",
                        (category, images_s, facts_s))
            # ensure stats row exists
            cur.execute("INSERT OR IGNORE INTO food_stats (category, count) VALUES (?, 0)", (category,))
            self.conn.commit()

    def get_food(self, category: str) -> Tuple[List[str], List[str]]:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT images, facts FROM food_data WHERE category = ?", (category,))
            row = cur.fetchone()
            if not row:
                return [], []
            images = self._split(row["images"])
            facts = self._split(row["facts"])
            return images, facts

    def list_categories(self) -> List[str]:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT category FROM food_data ORDER BY category")
            return [r["category"] for r in cur.fetchall()]

    def increment_food(self, category: str):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("INSERT OR IGNORE INTO food_stats (category, count) VALUES (?, 0)", (category,))
            cur.execute("UPDATE food_stats SET count = count + 1 WHERE category = ?", (category,))
            self.conn.commit()

    def increment_user_food(self, user_id: str, category: str):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("INSERT OR IGNORE INTO user_food_stats (user_id, category, count) VALUES (?, ?, 0)",
                        (user_id, category))
            cur.execute("UPDATE user_food_stats SET count = count + 1 WHERE user_id = ? AND category = ?",
                        (user_id, category))
            self.conn.commit()

    def top_foods(self, limit: int = 3) -> List[Tuple[str, int]]:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT category, count FROM food_stats ORDER BY count DESC LIMIT ?", (limit,))
            return [(r["category"], r["count"]) for r in cur.fetchall()]

    def all_stats(self) -> List[Tuple[str, int]]:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT category, count FROM food_stats ORDER BY count DESC")
            return [(r["category"], r["count"]) for r in cur.fetchall()]

    def user_stats(self, user_id: str) -> List[Tuple[str, int]]:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT category, count FROM user_food_stats WHERE user_id = ? ORDER BY count DESC", (user_id,))
            return [(r["category"], r["count"]) for r in cur.fetchall()]

    def close(self):
        with self.lock:
            try:
                self.conn.commit()
            except Exception:
                pass
            self.conn.close()

    @staticmethod
    def _join(items: List[str]) -> str:
        # escape commas by replacing with special token
        return "|;|".join(item.replace("|;|", "||;||") for item in items)

    @staticmethod
    def _split(s: Optional[str]) -> List[str]:
        if not s:
            return []
        parts = s.split("|;|")
        return [p.replace("||;||", "|;|") for p in parts]

db = DB(DB_PATH)
atexit.register(db.close)

# --- Default in-memory data (used if DB is empty) ---
DEFAULT_FOOD = {
    "burger": {
        "images": [
            "https://cdn.discordapp.com/attachments/1517278740290212031/1517279900506128555/Z.png"
        ],
        "facts": [
            "Burgers became popular in the U.S. in the early 1900s."
        ]
    },
    "pizza": {
        "images": [
            "https://cdn.discordapp.com/attachments/1517278740290212031/1517294247022166156/2Q.png"
        ],
        "facts": [
            "Pizza originated in Naples, Italy, as a street food."
        ]
    },
    "taco": {
        "images": [
            "https://cdn.discordapp.com/attachments/1517278740290212031/1517294129770659981/9k.png"
        ],
        "facts": [
            "Tacos date back to the 18th century in Mexico."
        ]
    },
    "sushi": {
        "images": [
            "https://cdn.discordapp.com/attachments/1517278740290212031/1517314398027513907/Z.png"
        ],
        "facts": [
            "Sushi began as a way to preserve fish in fermented rice."
        ]
    }
}

# Populate DB with defaults if empty
if not db.list_categories():
    for cat, data in DEFAULT_FOOD.items():
        db.add_food(cat, data["images"], data["facts"])
    logging.info("Inserted default food categories into DB")

# --- Bot setup ---
intents = discord.Intents.default()
intents.message_content = True

class FoodView(discord.ui.View):
    def __init__(self, category: str):
        super().__init__(timeout=None)
        self.category = category

    @discord.ui.button(label="Another!", style=discord.ButtonStyle.primary, emoji="🍽️")
    async def another(self, interaction: discord.Interaction, button: discord.ui.Button):
        # pick a new image and fact from DB
        images, facts = db.get_food(self.category)
        if not images:
            await interaction.response.send_message("No images available for this category.", ephemeral=True)
            return
        url = random.choice(images)
        fact = random.choice(facts) if facts else ""
        embed = make_food_embed(self.category, f"Here’s another {self.category} 🍽️", fact, url, discord.Color.blue())
        # update stats for the user who clicked
        try:
            db.increment_food(self.category)
            db.increment_user_food(str(interaction.user.id), self.category)
        except Exception as e:
            logging.exception("Failed to increment stats on button press: %s", e)
        await interaction.response.edit_message(embed=embed, view=FoodView(self.category))

def make_food_embed(category: str, title: str, fact: str, url: str, color: discord.Color) -> discord.Embed:
    desc = f"Fun fact: {fact}" if fact else ""
    embed = discord.Embed(title=title, description=desc, color=color)
    if url:
        embed.set_image(url=url)
    embed.set_footer(text="Bon appétit!")
    return embed

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

# --- Helper: seasonal specials ---
def seasonal_food() -> Optional[str]:
    month = datetime.datetime.now().month
    if month == 10:
        return "pumpkin pie"
    if month == 12:
        return "gingerbread"
    return None

# --- Autocomplete for /food ---
async def category_autocomplete(interaction: discord.Interaction, current: str):
    cats = db.list_categories()
    suggestions = [app_commands.Choice(name=c, value=c) for c in cats if current.lower() in c.lower()]
    # limit to 25 choices
    return suggestions[:25]

# --- Commands ---
@bot.tree.command(name="food", description="Sends a random image of the chosen food")
@app_commands.describe(item="Choose a food type (autocomplete)")
@app_commands.autocomplete(item=category_autocomplete)
async def food(interaction: discord.Interaction, item: str):
    try:
        images, facts = db.get_food(item)
        if not images:
            await interaction.response.send_message(f"No data found for category '{item}'.", ephemeral=True)
            return
        url = random.choice(images)
        fact = random.choice(facts) if facts else ""
        embed = make_food_embed(item, f"Here's a {item} for you 🍽️", fact, url, discord.Color.green())
        await interaction.response.send_message(embed=embed, view=FoodView(item))
        # Track request
        try:
            db.increment_food(item)
            db.increment_user_food(str(interaction.user.id), item)
        except Exception:
            logging.exception("Failed to increment stats for /food")
    except Exception as e:
        logging.exception("Error in /food command")
        await interaction.response.send_message(f"⚠️ Something went wrong serving {item}. Error: {e}", ephemeral=True)

@bot.tree.command(name="randomfood", description="Sends a random food image and fun fact")
async def randomfood(interaction: discord.Interaction):
    try:
        # check seasonal first
        seasonal = seasonal_food()
        categories = db.list_categories()
        if seasonal and seasonal in categories:
            category = seasonal
        else:
            category = random.choice(categories) if categories else None

        if not category:
            await interaction.response.send_message("No food categories available.", ephemeral=True)
            return

        images, facts = db.get_food(category)
        url = random.choice(images) if images else ""
        fact = random.choice(facts) if facts else ""
        embed = make_food_embed(category, "Here’s a surprise dish 🍽️", f"You didn’t choose, so I picked {category}!\n\n{fact}", url, discord.Color.orange())
        await interaction.response.send_message(embed=embed)
        db.increment_food(category)
        db.increment_user_food(str(interaction.user.id), category)
    except Exception as e:
        logging.exception("Error in /randomfood")
        await interaction.response.send_message(f"⚠️ Error serving random food: {e}", ephemeral=True)

@bot.tree.command(name="foodfact", description="Get a random fun fact about food")
async def foodfact(interaction: discord.Interaction):
    try:
        categories = db.list_categories()
        if not categories:
            await interaction.response.send_message("No food facts available.", ephemeral=True)
            return
        category = random.choice(categories)
        _, facts = db.get_food(category)
        fact = random.choice(facts) if facts else "No fact available."
        await interaction.response.send_message(f"🍴 Fun fact about {category}: {fact}")
        db.increment_food(category)
        db.increment_user_food(str(interaction.user.id), category)
    except Exception as e:
        logging.exception("Error in /foodfact")
        await interaction.response.send_message(f"⚠️ Error serving food fact: {e}", ephemeral=True)

@bot.tree.command(name="topfoods", description="Shows the top 3 most requested foods")
async def topfoods(interaction: discord.Interaction):
    try:
        results = db.top_foods(3)
        if results:
            description = "\n".join([f"🍴 **{cat}**: {cnt} requests" for cat, cnt in results])
            embed = discord.Embed(title="Top 3 Most Requested Foods", description=description, color=discord.Color.gold())
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("No food requests yet!")
    except Exception as e:
        logging.exception("Error in /topfoods")
        await interaction.response.send_message(f"⚠️ Error retrieving top foods: {e}", ephemeral=True)

@bot.tree.command(name="foodstats", description="Shows all food request counts")
async def foodstats(interaction: discord.Interaction):
    try:
        results = db.all_stats()
        if results:
            description = "\n".join([f"🍴 **{cat}**: {cnt} requests" for cat, cnt in results])
            embed = discord.Embed(title="Food Request Stats", description=description, color=discord.Color.purple())
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("No food requests yet!")
    except Exception as e:
        logging.exception("Error in /foodstats")
        await interaction.response.send_message(f"⚠️ Error retrieving stats: {e}", ephemeral=True)

@bot.tree.command(name="myfoods", description="Shows your personal food request stats")
async def myfoods(interaction: discord.Interaction):
    try:
        results = db.user_stats(str(interaction.user.id))
        if results:
            description = "\n".join([f"🍴 **{cat}**: {cnt} requests" for cat, cnt in results])
            embed = discord.Embed(title=f"{interaction.user.display_name}'s Food Stats", description=description, color=discord.Color.teal())
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("You haven’t requested any foods yet!", ephemeral=True)
    except Exception as e:
        logging.exception("Error in /myfoods")
        await interaction.response.send_message(f"⚠️ Error retrieving your stats: {e}", ephemeral=True)

# Admin command to add or update a food category
@bot.tree.command(name="addfood", description="Add or update a food category (admin only)")
@app_commands.describe(category="Category name", images="Comma-separated image URLs", facts="Comma-separated facts")
async def addfood(interaction: discord.Interaction, category: str, images: str, facts: str):
    # permission check
    if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You need Manage Guild permission to use this command.", ephemeral=True)
        return
    try:
        # split by comma and strip whitespace
        images_list = [i.strip() for i in images.split(",") if i.strip()]
        facts_list = [f.strip() for f in facts.split(",") if f.strip()]
        if not images_list or not facts_list:
            await interaction.response.send_message("Please provide at least one image URL and one fact.", ephemeral=True)
            return
        db.add_food(category.lower(), images_list, facts_list)
        await interaction.response.send_message(f"Category '{category}' added/updated with {len(images_list)} images and {len(facts_list)} facts.")
    except Exception as e:
        logging.exception("Error in /addfood")
        await interaction.response.send_message(f"⚠️ Error adding/updating category: {e}", ephemeral=True)

# --- Run the bot ---
token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN environment variable not set")

try:
    bot.run(token)
finally:
    # ensure DB closed on exit
    try:
        db.close()
    except Exception:
        pass
