# foodbot.py (patched)
import functools
from typing import Any, Callable, List, Tuple, Optional
import os
import random
import logging
import sqlite3
import atexit
import datetime
import threading
from urllib.parse import urlparse

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
        """
        Return True if the category existed and was removed, False otherwise.
        """
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT 1 FROM food_data WHERE category = ?", (category,))
            exists = cur.fetchone() is not None
            if not exists:
                return False
            cur.execute("DELETE FROM food_data WHERE category = ?", (category,))
            cur.execute("DELETE FROM food_stats WHERE category = ?", (category,))
            cur.execute("DELETE FROM user_food_stats WHERE category = ?", (category,))
            self.conn.commit()
            return True

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
    "burger": {
        "images": [
            "https://i.imgur.com/5ZQ0rQh.png",
            "https://i.imgur.com/7nYwXjP.jpg",
            "https://i.imgur.com/3kXzYwL.png"
        ],
        "facts": ["Burgers became popular in the U.S. in the early 1900s."]
    },
    "pizza": {
        "images": [
            "https://i.imgur.com/8kYzLhQ.png",
            "https://i.imgur.com/2mXzYwP.jpg",
            "https://i.imgur.com/4hT2VbQ.png"
        ],
        "facts": ["Pizza originated in Naples, Italy, as a street food."]
    },
    "taco": {
        "images": [
            "https://i.imgur.com/0qPuNix_d.webp?maxwidth=760&fidelity=grand",
            "https://i.pinimg.com/736x/6c/d2/27/6cd2275d20911f429bce82ce22ba554c.jpg",
            "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSMNh-lEEWwzf0a0qZ7kffbuMPTetRlabhMO3-cX4sEytFMOhbNcwOhLg4&s=10",
            "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcR4tBO3Z_SUcVqYOMA-rMForY2haTsXCrrcnYZlOKukQg&s"
        ],
        "facts": ["Tacos date back to the 18th century in Mexico."]
    },
    "sushi": {
        "images": [
            "https://cdn.foodfaithfitness.com/uploads/2025/02/a-crunchy_roll_sushi-feature-2.jpeg",
            "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTdmqTi9O8hHWc21FLY7UNZYWGGrC9fS7oZVf3232nHAA&s=10",
            "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcR6blZr2aiza7_VtZNxIw8qMyPc7WzJplEh_8q0E8uCCg&s=10"
        ],
        "facts": ["Sushi began as a way to preserve fish in fermented rice."]
    }
}

if not db.list_categories():
    for cat, data in DEFAULT_FOOD.items():
        db.add_food(cat, data["images"], data["facts"])
    logging.info("Inserted default food categories into DB")

# --- Bot setup ---
intents = discord.Intents.default()
intents.message_content = True

# --- Helpers ---
def looks_like_image_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    path = parsed.path.lower()
    return any(path.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"))

def choose_image_url(images: List[str]) -> Optional[str]:
    # Prefer valid-looking image URLs; fall back to any URL if none look valid
    valid = [u for u in images if looks_like_image_url(u)]
    if valid:
        return random.choice(valid)
    if images:
        return random.choice(images)
    return None

def make_food_embed(category: str, title: str, fact: str, url: Optional[str], color: discord.Color) -> discord.Embed:
    desc = f"Fun fact: {fact}" if fact else ""
    embed = discord.Embed(title=title, description=desc, color=color)
    if url:
        embed.set_image(url=url)
    embed.set_footer(text="Bon appétit!")
    return embed

class FoodView(discord.ui.View):
    def __init__(self, category: str):
        super().__init__(timeout=None)
        self.category = category

    @discord.ui.button(label="Another!", style=discord.ButtonStyle.primary, emoji="🍽️")
    async def another(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            images, facts = db.get_food(self.category)
            if not images and not facts:
                await interaction.followup.send("No data available for this category.", ephemeral=True)
                return

            # --- Rotate to next image ---
            current_url = None
            if interaction.message and interaction.message.embeds:
                embed0 = interaction.message.embeds[0]
                if embed0.image and embed0.image.url:
                    current_url = embed0.image.url

            def next_item(items: List[str], current: Optional[str]) -> Optional[str]:
                if not items:
                    return None
                if current in items:
                    idx = items.index(current)
                    return items[(idx + 1) % len(items)]
                return items[0]

            url = next_item(images, current_url)

            # --- Rotate to next fact ---
            current_fact = None
            if interaction.message and interaction.message.embeds:
                desc = interaction.message.embeds[0].description or ""
                if desc.startswith("Fun fact: "):
                    current_fact = desc[len("Fun fact: "):]

            fact = next_item(facts, current_fact) or ""

            # --- Build new embed ---
            embed = make_food_embed(
                self.category,
                f"Here’s another {self.category} 🍽️",
                fact,
                url,
                discord.Color.blue()
            )

            # --- Update stats ---
            db.increment_food(self.category)
            db.increment_user_food(str(interaction.user.id), self.category)

            # ✅ Edit the existing message
            await interaction.edit_original_response(embed=embed, view=FoodView(self.category))

        except Exception as e:
            logging.exception("Error in Another! button")
            await interaction.followup.send(f"⚠️ Something went wrong: {e}", ephemeral=True)



# --- Simple tracking decorator (now logs) ---
def track_food_requests(func: Callable) -> Callable:
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        finally:
            try:
                logging.info(f"Tracked call to {func.__name__}")
            except Exception:
                pass
    return wrapper

class FoodBot(commands.Bot):
    async def setup_hook(self):
        # Sync application commands
        dev_mode = os.getenv("DEV_MODE", "false").lower() == "true"
        if dev_mode:
            guild_id = os.getenv("GUILD_ID")
            if guild_id:
                guild = discord.Object(id=int(guild_id))
                await self.tree.sync(guild=guild)
                logging.info(f"Synced commands for guild {guild_id}")
        else:
            priority_guild_id = os.getenv("PRIORITY_GUILD_ID")
            if priority_guild_id:
                guild = discord.Object(id=int(priority_guild_id))
                await self.tree.sync(guild=guild)
            else:
                await self.tree.sync()
                logging.info("Synced global commands")

        # ✅ Register persistent views for all categories
        categories = db.list_categories()
        for cat in categories:
            self.add_view(FoodView(cat))
        logging.info(f"Registered persistent views for categories: {categories}")

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
@track_food_requests
async def food(interaction: discord.Interaction, category: str):
    await interaction.response.defer()
    images, facts = db.get_food(category)
    if not images and not facts:
        await interaction.followup.send(f"Category '{category}' not found. Try `/food_list`")
        return

    url = choose_image_url(images)
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

@bot.tree.command(name="remove_food", description="Remove a food category")
async def remove_food(interaction: discord.Interaction, category: str):
    # Restrict to admins only
    if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You don’t have permission to remove foods.", ephemeral=True)
        return

    success = db.remove_food(category)
    if success:
        embed = discord.Embed(
            title=f"Removed {category} ❌",
            description=f"The category '{category}' has been deleted from the database.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(f"Category '{category}' not found.", ephemeral=True)

@bot.tree.command(name="update_food", description="Append new images and facts to an existing food category")
async def update_food(interaction: discord.Interaction, category: str, image_urls: str, facts: str):
    # Restrict to admins only
    if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You don’t have permission to update foods.", ephemeral=True)
        return

    # Split comma-separated values into lists
    new_images = [url.strip() for url in image_urls.split(",") if url.strip()]
    new_facts = [fact.strip() for fact in facts.split(",") if fact.strip()]

    if not new_images and not new_facts:
        await interaction.response.send_message("Please provide at least one new image URL or fact.", ephemeral=True)
        return

    # Fetch existing data
    existing_images, existing_facts = db.get_food(category)

    if not existing_images and not existing_facts:
        await interaction.response.send_message(f"Category '{category}' not found. Try `/food_list`.", ephemeral=True)
        return

    # Append new items (avoid exact duplicates)
    updated_images = existing_images[:]
    for img in new_images:
        if img not in updated_images:
            updated_images.append(img)

    updated_facts = existing_facts[:]
    for f in new_facts:
        if f not in updated_facts:
            updated_facts.append(f)

    # Save back to DB
    db.add_food(category, updated_images, updated_facts)

    # Confirmation embed
    embed = discord.Embed(
        title=f"Updated {category} 🍽️",
        description=f"**Images added:** {len([i for i in new_images if i not in existing_images])}\n"
                    f"**Facts added:** {len([f for f in new_facts if f not in existing_facts])}\n\n"
                    f"Now totals: {len(updated_images)} images, {len(updated_facts)} facts.",
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed)

# --- Run bot ---
TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    logging.error("DISCORD_TOKEN not found in environment")
