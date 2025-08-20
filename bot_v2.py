import os, re, csv, asyncio, discord
from pathlib import Path
from discord.ext import commands
from dotenv import load_dotenv

# === load secrets from .env ===
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
REGISTER_POST_CHANNEL_ID = int(os.getenv("REGISTER_POST_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))

# === rules ===
EXACT_DIGITS = 9
EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I)

# === texts (English only for users) ===
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

# === persistence (CSV) ===
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
                        ids.add(int(uid_str))
        except Exception:
            pass
    return ids

def append_submission(discord_user_id: int, email: str, player_id: str):
    new_file = not SAVE_PATH.exists()
    with SAVE_PATH.open("a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["discord_user_id", "email", "player_id"])
        w.writerow([discord_user_id, email, player_id])

# === bot ===
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

submitted_users: set[int] = set()  # loaded from CSV on_ready

class RegisterView(discord.ui.View):
    def __init__(self, timeout=None):
        super().__init__(timeout=timeout)

    @discord.ui.button(label=BTN_LABEL, style=discord.ButtonStyle.primary, custom_id="rr_register_btn")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user

        # one-time only
        if user.id in submitted_users:
            await interaction.response.send_message(EPHEM_ALREADY, ephemeral=True)
            return

        # open DM
        try:
            dm = await user.create_dm()
            await dm.send(DM_GREETING)
        except Exception:
            await interaction.response.send_message(EPHEM_OPEN_DM, ephemeral=True)
            return

        # acknowledge
        await interaction.response.send_message("I've sent you a DM. Please check your inbox.", ephemeral=True)

        # wait for DM reply
        def check(m: discord.Message):
            return m.author.id == user.id and isinstance(m.channel, discord.DMChannel)

        attempts = 3
        while attempts > 0:
            try:
                msg: discord.Message = await bot.wait_for("message", check=check, timeout=120)
            except asyncio.TimeoutError:
                try:
                    await dm.send(DM_TIMEOUT)
                except Exception:
                    pass
                return

            content = msg.content.strip().replace("\n", " ")
            parts = content.split()
            if len(parts) != 2:
                try:
                    await dm.send(DM_HINT)
                except:
                    pass
                attempts -= 1
                continue

            email, player_id = parts[0].strip(), parts[1].strip()

            if not EMAIL_RE.fullmatch(email):
                try:
                    await dm.send(DM_INVALID_EMAIL)
                except:
                    pass
                attempts -= 1
                continue

            if not player_id.isdigit():
                try:
                    await dm.send(DM_INVALID_DIGITS)
                except:
                    pass
                attempts -= 1
                continue

            if len(player_id) != EXACT_DIGITS:
                try:
                    await dm.send(DM_INVALID_LENGTH)
                except:
                    pass
                attempts -= 1
                continue

            # valid
            submitted_users.add(user.id)
            try:
                append_submission(user.id, email, player_id)
            except Exception:
                pass

            # log to private channel
            guild = bot.get_guild(GUILD_ID) if GUILD_ID else None
            if guild:
                log_ch = guild.get_channel(LOG_CHANNEL_ID)
                if log_ch:
                    try:
                        emb = discord.Embed(title="New Submission", color=0x3498DB)
                        emb.add_field(name="Discord", value=f"{user} (`{user.id}`)", inline=False)
                        emb.add_field(name="Email", value=email, inline=True)
                        emb.add_field(name="Player ID", value=player_id, inline=True)
                        await log_ch.send(embed=emb)
                    except:
                        await log_ch.send(f"<@{user.id}> email `{email}` | player id `{player_id}`")

            try:
                emb_ok = discord.Embed(description=DM_SUCCESS, color=COLOR_OK)
                emb_ok.set_author(name=f"{BRAND} Verify")
                emb_ok.add_field(name="Email", value=email, inline=True)
                emb_ok.add_field(name="Player ID", value=f"`{player_id}`", inline=True)
                await dm.send(embed=emb_ok)
            except:
                pass
            return

        # attempts exhausted
        try:
            await dm.send("Too many invalid attempts. Please click REGISTER again to restart.")
        except:
            pass

@bot.command(name="setup_register")
@commands.has_permissions(administrator=True)
async def setup_register(ctx: commands.Context):
    if ctx.guild is None or ctx.guild.id != GUILD_ID:
        return
    ch = ctx.guild.get_channel(REGISTER_POST_CHANNEL_ID)
    if not ch:
        await ctx.reply("REGISTER_POST_CHANNEL_ID not found.")
        return

    emb = discord.Embed(title=POST_TITLE, description=POST_DESC, color=0x5865F2)
    view = RegisterView()
    await ch.send(embed=emb, view=view)
    await ctx.reply("Register post sent.", delete_after=5)

@bot.event
async def on_ready():
    global submitted_users
    submitted_users = load_submitted_user_ids()
    print(f"✅ Logged in as {bot.user} | Loaded {len(submitted_users)} submissions from CSV")
    # keep the button alive after restarts
    bot.add_view(RegisterView())

bot.run(TOKEN)
