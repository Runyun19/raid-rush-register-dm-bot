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
POST_TITLE = "Community Registration"
POST_DESC = (
    "Hello Defender!\n\n"
    "Please follow these steps to register for your reward:\n\n"
    "1️⃣ Click the **REGISTER** button below.\n"
    "2️⃣ The bot will send you a private message (DM).\n"
    "3️⃣ In that DM, send your **email address** and **Player ID** together in one message, separated by a space.\n\n"
    "✅ Example:\n"
    "`email@example.com 123456789`\n\n"
    "📌 Make sure the information is correct; otherwise, your reward cannot be added.\n\n"
    "🔵 Click the button below to start your registration:"
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
                        ids.add(int(uid_str))
        except Exception as e:
            print("CSV load error:", e)
    return ids

def append_submission(discord_user_id: int, email: str, player_id: str):
    new_file = not SAVE_PATH.exists()
    with SAVE_PATH.open("a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["discord_user_id", "email", "player_id"])
        w.writerow([discord_user_id, email, player_id])

# ===== Bot & Intents =====
intents = discord.Intents.default()
intents.members = True
intents.message_content = True  # prefix komutları için gerekli
bot = commands.Bot(command_prefix="!", intents=intents)
submitted_users: set[int] = set()

# Tek bir guild’e hızlı kayıt için Object
GOBJ = discord.Object(id=GUILD_ID)

# ===== View (REGISTER button) =====
class RegisterView(discord.ui.View):
    def __init__(self, timeout=None):
        super().__init__(timeout=timeout)

    @discord.ui.button(label=BTN_LABEL, style=discord.ButtonStyle.primary, custom_id="rr_register_btn")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        print("Button click from:", user, user.id)

        if user.id in submitted_users:
            await interaction.response.send_message(EPHEM_ALREADY, ephemeral=True)
            return

        try:
            dm = await user.create_dm()
            await dm.send(DM_GREETING)
        except Exception as e:
            print("DM open error:", e)
            await interaction.response.send_message(EPHEM_OPEN_DM, ephemeral=True)
            return

        await interaction.response.send_message("I've sent you a DM. Please check your inbox.", ephemeral=True)

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
                try: await dm.send(DM_HINT)
                except: pass
                attempts -= 1
                continue

            email, player_id = parts[0].strip(), parts[1].strip()

            if not EMAIL_RE.fullmatch(email):
                try: await dm.send(DM_INVALID_EMAIL)
                except: pass
                attempts -= 1; continue

            if not player_id.isdigit():
                try: await dm.send(DM_INVALID_DIGITS)
                except: pass
                attempts -= 1; continue

            if len(player_id) != EXACT_DIGITS:
                try: await dm.send(DM_INVALID_LENGTH)
                except: pass
                attempts -= 1; continue

            # valid
                       # valid
            submitted_users.add(user.id)
            try:
                append_submission(user.id, email, player_id)
            except Exception as e:
                print("CSV append error:", e)

            # --- Guild / Log / Role ---
            guild = bot.get_guild(GUILD_ID)
            if guild:
                # 1) Log channel
                log_ch = guild.get_channel(LOG_CHANNEL_ID)
                if log_ch:
                    try:
                        emb = discord.Embed(title="New Submission", color=0x3498DB)
                        emb.add_field(name="Discord", value=f"{user} (`{user.id}`)", inline=False)
                        emb.add_field(name="Email", value=email, inline=True)
                        emb.add_field(name="Player ID", value=player_id, inline=True)
                        await log_ch.send(embed=emb)
                    except Exception as e:
                        print("Log embed error:", e)
                        try:
                            await log_ch.send(f"<@{user.id}> email `{email}` | player id `{player_id}`")
                        except Exception as e2:
                            print("Log plaintext error:", e2)

                # 2) Role assignment (REGISTERED_ROLE_ID env)
                try:
                    if REGISTERED_ROLE_ID:
                        role = guild.get_role(REGISTERED_ROLE_ID)
                        if role:
                            await user.add_roles(role, reason="Successfully registered")
                except Exception as e:
                    print("Role assign error:", e)

            # --- DM confirmation ---
            try:
                emb_ok = discord.Embed(description=DM_SUCCESS, color=COLOR_OK)
                if ICON_URL:
                    emb_ok.set_author(name=f"{BRAND} Verify", icon_url=ICON_URL)
                else:
                    emb_ok.set_author(name=f"{BRAND} Verify")
                emb_ok.add_field(name="Email", value=email, inline=True)
                emb_ok.add_field(name="Player ID", value=f"`{player_id}`", inline=True)
                await dm.send(embed=emb_ok)
            except Exception as e:
                print("DM ok embed error:", e)

            return

# ===== Prefix commands =====
@bot.command(name="ping")
async def ping_prefix(ctx: commands.Context):
    print("!ping from", ctx.author, "in", ctx.channel)
    await ctx.reply("Pong!", delete_after=5)

@bot.command(name="setup_register")
@commands.has_permissions(administrator=True)
async def setup_register_prefix(ctx: commands.Context):
    print("!setup_register from", ctx.author, "in", ctx.channel)
    if ctx.guild is None or ctx.guild.id != GUILD_ID:
        await ctx.reply("Wrong guild.", delete_after=5); return
    ch = ctx.guild.get_channel(REGISTER_POST_CHANNEL_ID)
    if not ch:
        await ctx.reply("REGISTER_POST_CHANNEL_ID not found.", delete_after=5); return
    emb = discord.Embed(title=POST_TITLE, description=POST_DESC, color=0x5865F2)
    await ch.send(embed=emb, view=RegisterView())
    await ctx.reply("Register post sent.", delete_after=5)
      # == helpers: remove from CSV ==
def remove_submission_row(discord_user_id: int) -> bool:
    if not SAVE_PATH.exists():
        return False
    changed = False
    rows = []
    with SAVE_PATH.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            uid = r.get("discord_user_id", "")
            if uid and uid.isdigit() and int(uid) == discord_user_id:
                changed = True
                continue
            rows.append(r)
    if changed:
        with SAVE_PATH.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["discord_user_id", "email", "player_id"])
            w.writeheader()
            for r in rows:
                w.writerow(r)
    return changed

@bot.command(name="reset_user")
@commands.has_permissions(administrator=True)
async def reset_user(ctx: commands.Context, user_id_or_mention: str):
    """Admin: allow a user to re-submit (by ID or mention). Usage: !reset_user 123456789012345678"""
    uid = None
    if user_id_or_mention.isdigit():
        uid = int(user_id_or_mention)
    else:
        try:
            uid = int(user_id_or_mention.replace("<@", "").replace(">", "").replace("!", ""))
        except:
            uid = None
    if uid is None:
        await ctx.reply("Provide a valid user ID or mention.", delete_after=8)
        return

    removed_csv = remove_submission_row(uid)
    submitted_users.discard(uid)
    await ctx.reply(f"Reset done for `<@{uid}>` (csv_removed={removed_csv}).", delete_after=8)

@bot.command(name="sub_count")
@commands.has_permissions(administrator=True)
async def sub_count(ctx: commands.Context):
    await ctx.reply(f"Currently stored submissions in memory: **{len(submitted_users)}**", delete_after=8)

# ===== Slash commands (guild-bound) =====
@bot.tree.command(name="ping", description="Health check", guild=GOBJ)
async def ping_slash(interaction: discord.Interaction):
    print("/ping by", interaction.user)
    await interaction.response.send_message("Pong!", ephemeral=True)

@bot.tree.command(name="setup_register", description="Post the REGISTER button (admin only)", guild=GOBJ)
@app_commands.checks.has_permissions(administrator=True)
async def setup_register_slash(interaction: discord.Interaction):
    print("/setup_register by", interaction.user)
    if interaction.guild_id != GUILD_ID:
        await interaction.response.send_message("Wrong guild.", ephemeral=True); return
    guild = interaction.guild
    ch = guild.get_channel(REGISTER_POST_CHANNEL_ID) if guild else None
    if not ch:
        await interaction.response.send_message("REGISTER_POST_CHANNEL_ID not found.", ephemeral=True); return
    emb = discord.Embed(title=POST_TITLE, description=POST_DESC, color=0x5865F2)
    await ch.send(embed=emb, view=RegisterView())
    await interaction.response.send_message("Register post sent.", ephemeral=True)

# ===== on_ready =====
@bot.event
async def on_ready():
    global submitted_users
    submitted_users = load_submitted_user_ids()
    print(f"✅ Logged in as {bot.user} | Loaded {len(submitted_users)} submissions from CSV")

    # keep button alive across restarts
    bot.add_view(RegisterView())

    # fast sync to guild
    try:
        synced = await bot.tree.sync(guild=GOBJ)
        print(f"Slash synced for guild {GUILD_ID}: {len(synced)} cmd(s)")
    except Exception as e:
        print("Slash sync error:", e)

bot.run(TOKEN)
