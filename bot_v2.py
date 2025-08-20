import os, re, csv, asyncio, discord
from pathlib import Path
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# ===== Load env (Railway Variables) =====
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
REGISTER_POST_CHANNEL_ID = int(os.getenv("REGISTER_POST_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))

# Small startup print to verify env read
print("CFG => GUILD_ID=", GUILD_ID,
      " REGISTER_POST_CHANNEL_ID=", REGISTER_POST_CHANNEL_ID,
      " LOG_CHANNEL_ID=", LOG_CHANNEL_ID)

# ===== Rules =====
EXACT_DIGITS = 9
EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I)

# ===== Texts (EN only to users) =====
BRAND = "Raid Rush"
COLOR_OK = 0x57F287

BTN_LABEL = "REGISTER"
POST_TITLE = "Special Reward Registration"
POST_DESC = (
    "Click the button below to start a private registration.\n"
    "You will receive a DM from the bot.\n\n"
    "In the DM, please send your **email and Player ID** in **one message** separated by space.\n"
    "Example: `email@example.com 123456789`"
)

DM_GREETING = (
    "Hi! Let's complete your registration.\n\n"
    "Please send your **email and Player ID** in one message separated by space.\n"
    "Example: `email@example.com 123456789`"
)
DM_HINT = (
    "Please use the correct format in **one message**:\n"
    "`email@example.com 123456789`"
)
DM_INVALID_EMAIL = "Invalid email format. Please try again.\n" + DM_HINT
DM_INVALID_DIGITS = "Player ID must contain only digits. Please try again.\n" + DM_HINT
DM_INVALID_LENGTH = f"Player ID must be exactly {EXACT_DIGITS} digits. Please try again.\n" + DM_HINT
DM_TIMEOUT = "Timed out waiting for your reply. You can press the REGISTER button again to restart."
DM_SUCCESS = "✅ Your information has been saved. Your code will be sent by email."

EPHEM_OPEN_DM = (
    "I couldn’t DM you. Please enable **Direct Messages** from server members (User Settings → Privacy) "
    "and click **REGISTER** again."
)
EPHEM_ALREADY = "You have already submitted your information. Updates are disabled."

# ===== Persistence (CSV) =====
SAVE_PATH = Path("submissions.csv")

def load_submitted_user_ids() -> set[int]:
    ids = set()
    if SAVE_PATH.exists():
        try:
            with SAVE_PATH.open("r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    uid_str = row.get("discord_user_id")
                    if uid_str and uid_str.isdigit():
                        id
