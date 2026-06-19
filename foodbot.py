import functools
from typing import Any, Callable

def track_food_requests(func: Callable) -> Callable:
    import functools
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        finally:
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

    def remove_food(self, category: str) -> bool:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM food_data WHERE category = ?", (category,))
            cur.execute("DELETE FROM food_stats WHERE category = ?", (category,))
            cur.execute("DELETE FROM user_food_stats WHERE category = ?", (category,))
            self.conn.commit()
            return cur.rowcount > 0

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
        return "|;|".join(item.replace("|;|", "||;||") for item in items)

    @staticmethod
    def _split(s: Optional[str]) -> List[str]:
        if not s:
            return []
        parts = s.split("|;|")
        return [p.replace("||;||", "|;|") for p in parts]

db = DB(DB_PATH)
atexit.register(db.close)

# --- Default data ---
DEFAULT_FOOD = {
    "burger": {"images": ["https://..."], "facts": ["Burgers became popular in the U.S. in the early 1900s."]},
    "pizza": {"images": ["https://..."], "facts": ["Pizza originated in Naples, Italy, as a street food."]},
    "taco": {"images": ["https://..."], "facts": ["Tacos date back to the 18th century in Mexico."]},
    "sushi": {"images": ["https://..."], "facts": ["Sushi began as a way to preserve fish in fermented rice."]}
}
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
        images, facts = db.get_food(self.category)
        if not images:
            await interaction.response.send_message("No images available for this category.", ephemeral=True)
            return
        url = random.choice(images)
        fact = random.choice(facts) if facts else ""
        embed = make_food_embed(self.category, f"Here’s another {self.category} 🍽️", fact, url, discord.Color.blue())
        db.increment_food(self.category)
        db.increment_user_food(str(interaction.user.id), self.category)
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
        else:
            priority_guild_id = os.getenv("PRIORITY_GUILD_ID")
            if priority_guild_id:
                guild = discord.Object(id=int(priority_guild_id))
                await self.tree.sync(guild=guild)
            else:
                await self.tree.sync()

bot = FoodBot(command_prefix="!", intents=intents)

# --- Seasonal specials ---
def seasonal_food() -> Optional[str]:
    month = datetime.datetime.now().month
    if month == 10:
        return "pumpkin pie"
    if month == 12:
        return "gingerbread"
    return None

# --- Autocomplete ---
async def category_autocomplete(interaction: discord.Interaction,
                                 current: str) -> List[app_commands.Choice[str]]:
    categories = db.list_categories()
    return [
        app_commands.Choice(name=cat, value=cat)
        for cat in categories if current.lower() in cat.lower()
    ]

# --- Commands ---
@bot.tree.command(name="food", description="Get a random food image and fact")
@app_commands.autocomplete(category=category_autocomplete)
async def food(interaction: discord.Interaction, category: str):
    await interaction.response.defer()
    images, facts = db.get_food(category)
    if not images:
        await interaction.followup.send(f"Category '{category}' not found. Try `/food_list`")
        return
    url = random.choice(images)
    fact = random.choice(facts) if facts else ""
    embed = make_food_embed(category, f"Here's a {category} 🍽️", fact, url, discord.Color.green())
    db.increment_food(category)
    db.increment_user_food(str(interaction.user.id), category)
    await interaction.followup.send(embed=embed, view=FoodView(category))

@bot.tree.command(name="food_list", description="List all food categories")
async def food_list(interaction: discord.Interaction):
    categories = db.list_categories()
    if not categories:
        await interaction.response.send_message("No food categories available.")
        return
    embed = discord.Embed(title="Available Foods", description="\n".join(categories), color=discord.Color.orange())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="stats", description="View global food statistics")
async def stats(interaction: discord.Interaction):
    top = db.top_foods(10)
    if not top:
        await interaction.response.send_message("No statistics yet.")
        return
    desc = "\n".join(f"{i+1}. {cat}: {count}" for i, (cat, count) in enumerate(top))
    embed = discord.Embed(title="Top Foods", description=desc, color=discord.Color.purple())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="my_stats", description="View your personal food statistics")
async def my_stats(interaction: discord.Interaction):
    user_stats = db.user_stats(str(interaction.user.id))
    if not user_stats:
        await interaction.response.send_message("You haven't requested any foods yet!")
        return
    desc = "\n".join(f"{i+1}. {cat}: {count}" for i, (cat, count) in enumerate(user_stats))
    embed = discord.Embed(title="Your Food Stats", description=desc, color=discord.Color.blue())
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_ready():
    logging.info(f"FoodBot is ready! Logged in as {bot.user}")
    try:
        await bot.tree.sync()  # force global sync
        logging.info("Slash commands synced successfully.")
    except Exception as e:
        logging.error(f"Failed to sync commands: {e}")


# --- Run bot ---
TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    logging.error("DISCORD_TOKEN not found in environment")

# python C:\Users\onehu\foodbot\foodbot.py -- use if you want to run the bot locally
