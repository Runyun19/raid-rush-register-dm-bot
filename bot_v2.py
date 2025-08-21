# bot_v2.py
import os
import re
import csv
import json
import asyncio
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands

# ── ENV ──────────────────────────────────────────────────────────────────────
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
REGISTER_POST_CHANNEL_ID = int(os.getenv("REGISTER_POST_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
REGISTERED_ROLE_ID = int(os.getenv("REGISTERED_ROLE_ID", "0"))

# İletişim yönlendirmesi (default: @runyun & @aurilis)
CONTACT_MENTION = os.getenv(
    "CONTACT_MENTION",
    "<@1358693833428308150> & <@940252755237412945>"
)

print(
    "CFG =>",
    f"GUILD_ID={GUILD_ID}",
    f"REGISTER_POST_CHANNEL_ID={REGISTER_POST_CHANNEL_ID}",
    f"LOG_CHANNEL_ID={LOG_CHANNEL_ID}",
    f"REGISTERED_ROLE_ID={REGISTERED_ROLE_ID}",
    f"CONTACT_MENTION={CONTACT_MENTION}",
)

# ── KURALLAR / METINLER ──────────────────────────────────────────────────────
EXACT_DIGITS = 9
EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I)

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
    "Please send your **Email** and **Player ID** in one message separated by a space.\n"
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
    "I couldn’t DM you. Please enable **Direct Messages** from server members "
    "(User Settings → Privacy) and click **REGISTER** again."
)
EPHEM_ALREADY = (
    "You have already submitted your information. Updates are disabled.\n"
    f"If you need a change, please contact {CONTACT_MENTION}."
)

CONFIRM_TITLE = "Confirm your information"
CONFIRM_DESC = (
    "Please review your details below.\n\n"
    "If everything looks correct, click **Confirm**.\n"
    "If you need to change something, click **Edit** to re-enter your info.\n\n"
    f"If you still need help, contact {CONTACT_MENTION}."
)

# ── KALICILIK: CSV + LOG INDEX ───────────────────────────────────────────────
SAVE_PATH = Path("submissions.csv")
LOG_INDEX_PATH = Path("log_index.json")  # { "<discord_user_id>": "<log_message_id>" }

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

def update_submission(discord_user_id: int, new_email: Optional[str] = None, new_player_id: Optional[str] = None) -> bool:
    """CSV'de ilgili kullanıcı satırını günceller. True/False döner."""
    if not SAVE_PATH.exists():
        return False
    changed = False
    rows = []
    with SAVE_PATH.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            uid = r.get("discord_user_id", "")
            if uid and uid.isdigit() and int(uid) == discord_user_id:
                if new_email is not None:
                    r["email"] = new_email
                if new_player_id is not None:
                    r["player_id"] = new_player_id
                changed = True
            rows.append(r)
    if changed:
        with SAVE_PATH.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["discord_user_id", "email", "player_id"])
            w.writeheader()
            for r in rows:
                w.writerow(r)
    return changed

def load_log_index() -> dict:
    if LOG_INDEX_PATH.exists():
        try:
            return json.loads(LOG_INDEX_PATH.read_text())
        except Exception as e:
            print("log_index load error:", e)
    return {}

def save_log_index(index: dict):
    try:
        LOG_INDEX_PATH.write_text(json.dumps(index))
    except Exception as e:
        print("log_index save error:", e)

def update_log_message_embed(message: discord.Message, user: discord.User | discord.Member, email: str, player_id: str):
    emb = discord.Embed(title="New Submission (Updated)", color=0x2ECC71)
    emb.add_field(name="Discord", value=f"{user} (`{user.id}`)", inline=False)
    emb.add_field(name="Email", value=email, inline=True)
    emb.add_field(name="Player ID", value=player_id, inline=True)
    return emb

# ── BOT / INTENTS ────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
submitted_users: set[int] = set()

GOBJ = discord.Object(id=GUILD_ID)

# ── Confirm View ─────────────────────────────────────────────────────────────
class ConfirmView(discord.ui.View):
    def __init__(self, requester_id: int, timeout: float | None = 120):
        super().__init__(timeout=timeout)
        self.requester_id = requester_id
        self.confirmed: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.requester_id

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.success)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="✏️ Edit", style=discord.ButtonStyle.secondary)
    async def edit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        await interaction.response.defer()
        self.stop()

# ── REGISTER BUTTON VIEW ─────────────────────────────────────────────────────
class RegisterView(discord.ui.View):
    def __init__(self, timeout=None):
        super().__init__(timeout=timeout)

    @discord.ui.button(label=BTN_LABEL, style=discord.ButtonStyle.primary, custom_id="rr_register_btn")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        print("Button click from:", user, user.id)

        # 1) tekrar kayıt blok
        if user.id in submitted_users:
            await interaction.response.send_message(EPHEM_ALREADY, ephemeral=True)
            return

        # 2) DM aç
        try:
            dm = await user.create_dm()
            await dm.send(DM_GREETING)
        except Exception as e:
            print("DM open error:", e)
            await interaction.response.send_message(EPHEM_OPEN_DM, ephemeral=True)
            return

        # 3) ephemeral onay
        await interaction.response.send_message("I've sent you a DM. Please check your inbox.", ephemeral=True)

        # 4) DM mesaj bekleme
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
                except Exception:
                    pass
                attempts -= 1
                continue

            email, player_id = parts[0].strip(), parts[1].strip()

            if not EMAIL_RE.fullmatch(email):
                try:
                    await dm.send(DM_INVALID_EMAIL)
                except Exception:
                    pass
                attempts -= 1
                continue

            if not player_id.isdigit():
                try:
                    await dm.send(DM_INVALID_DIGITS)
                except Exception:
                    pass
                attempts -= 1
                continue

            if len(player_id) != EXACT_DIGITS:
                try:
                    await dm.send(DM_INVALID_LENGTH)
                except Exception:
                    pass
                attempts -= 1
                continue

            # 5) SON ONAY (Confirm/Edit)
            try:
                emb_confirm = discord.Embed(title=CONFIRM_TITLE, description=CONFIRM_DESC, color=0xF1C40F)
                emb_confirm.add_field(name="Email", value=email, inline=True)
                emb_confirm.add_field(name="Player ID", value=f"`{player_id}`", inline=True)
                view = ConfirmView(requester_id=user.id)
                await dm.send(embed=emb_confirm, view=view)
                await view.wait()
            except Exception as e:
                print("Confirm view error:", e)
                attempts -= 1
                continue

            if view.confirmed is False:
                try:
                    await dm.send("Okay, please resend your details in the correct format.\n" + DM_HINT)
                except Exception:
                    pass
                continue

            if view.confirmed is None:
                try:
                    await dm.send("Confirmation timed out. Please click REGISTER again to restart.")
                except Exception:
                    pass
                return

            # 6) VALID & CONFIRMED → kaydet, logla, rol ver, DM onay
            submitted_users.add(user.id)
            try:
                append_submission(user.id, email, player_id)
            except Exception as e:
                print("CSV append error:", e)

            guild = bot.get_guild(GUILD_ID)

            # 6a) log kanala
            saved_log_id = None
            if guild:
                log_ch = guild.get_channel(LOG_CHANNEL_ID)
                if log_ch:
                    try:
                        emb = discord.Embed(title="New Submission", color=0x3498DB)
                        emb.add_field(name="Discord", value=f"{user} (`{user.id}`)", inline=False)
                        emb.add_field(name="Email", value=email, inline=True)
                        emb.add_field(name="Player ID", value=player_id, inline=True)
                        msg_log = await log_ch.send(embed=emb)
                        saved_log_id = msg_log.id
                    except Exception as e:
                        print("Log embed error:", e)
                        try:
                            msg_log = await log_ch.send(f"<@{user.id}> email `{email}` | player id `{player_id}`")
                            saved_log_id = msg_log.id
                        except Exception as e2:
                            print("Log plaintext error:", e2)

            # 6a-2) log_index'e yaz
            if saved_log_id:
                index = load_log_index()
                index[str(user.id)] = str(saved_log_id)
                save_log_index(index)

            # 6b) rol ver
            try:
                if guild and REGISTERED_ROLE_ID:
                    role = guild.get_role(REGISTERED_ROLE_ID)
                    me = guild.me
                    print(
                        f"[ROLE] target_role={role} id={REGISTERED_ROLE_ID} "
                        f"role_pos={getattr(role,'position',None)} managed={getattr(role,'managed',None)} | "
                        f"bot_top={me.top_role} pos={me.top_role.position} "
                        f"manage_roles={me.guild_permissions.manage_roles}"
                    )

                    if role:
                        member = guild.get_member(user.id)
                        if member is None:
                            try:
                                member = await guild.fetch_member(user.id)
                            except Exception as fe:
                                print("[ROLE] fetch_member error:", fe)
                                member = None

                        if member:
                            try:
                                await member.add_roles(role, reason="Successfully registered")
                                print(f"[ROLE] Assigned: {role.name} -> {member}")
                            except Exception as e_add:
                                print("[ROLE] add_roles error:", repr(e_add))
                        else:
                            print("[ROLE] Member not found in guild for role assignment.")
                    else:
                        print("[ROLE] Role not found by REGISTERED_ROLE_ID.")
            except Exception as e:
                print("[ROLE] assign block error:", repr(e))

            # 6c) DM onay
            try:
                emb_ok = discord.Embed(description=DM_SUCCESS, color=COLOR_OK)
                emb_ok.set_author(name=f"{BRAND} Verify")
                emb_ok.add_field(name="Email", value=email, inline=True)
                emb_ok.add_field(name="Player ID", value=f"`{player_id}`", inline=True)
                await dm.send(embed=emb_ok)
            except Exception as e:
                print("DM ok embed error:", e)

            return  # başarıyla tamamlandı

        # 7) çok fazla deneme
        try:
            await dm.send("Too many invalid attempts. Please click REGISTER again to restart.")
        except Exception:
            pass

# ── PREFIX KOMUTLAR ─────────────────────────────────────────────────────────
@bot.command(name="ping")
async def ping_prefix(ctx: commands.Context):
    print("!ping from", ctx.author, "in", ctx.channel)
    await ctx.reply("Pong!", delete_after=5)

@bot.command(name="setup_register")
@commands.has_permissions(administrator=True)
async def setup_register_prefix(ctx: commands.Context):
    print("!setup_register from", ctx.author, "in", ctx.channel)
    if ctx.guild is None or ctx.guild.id != GUILD_ID:
        await ctx.reply("Wrong guild.", delete_after=5)
        return
    ch = ctx.guild.get_channel(REGISTER_POST_CHANNEL_ID)
    if not ch:
        await ctx.reply("REGISTER_POST_CHANNEL_ID not found.", delete_after=5)
        return
    emb = discord.Embed(title=POST_TITLE, description=POST_DESC, color=0x5865F2)
    await ch.send(embed=emb, view=RegisterView())
    await ctx.reply("Register post sent.", delete_after=5)

@bot.command(name="role_diag")
@commands.has_permissions(administrator=True)
async def role_diag(ctx: commands.Context, member: discord.Member = None):
    guild = ctx.guild
    me = guild.me
    role = guild.get_role(REGISTERED_ROLE_ID)
    txt = [
        f"me.top_role = {me.top_role} (pos={me.top_role.position})",
        f"me.manage_roles = {me.guild_permissions.manage_roles}",
        f"target role = {role} (id={REGISTERED_ROLE_ID}, pos={getattr(role,'position',None)}, managed={getattr(role,'managed',None)})",
    ]
    await ctx.reply("\n".join(txt), delete_after=20)

@bot.command(name="grant_registered")
@commands.has_permissions(administrator=True)
async def grant_registered(ctx: commands.Context, target: discord.Member):
    guild = ctx.guild
    role = guild.get_role(REGISTERED_ROLE_ID)
    if not role:
        await ctx.reply("Role not found. Check REGISTERED_ROLE_ID.", delete_after=10)
        return
    try:
        await target.add_roles(role, reason="Manual grant test")
        await ctx.reply(f"Gave `{role.name}` to {target.mention}", delete_after=10)
    except Exception as e:
        await ctx.reply(f"add_roles error: `{e}`", delete_after=15)

@bot.command(name="reset_user")
@commands.has_permissions(administrator=True)
async def reset_user(ctx: commands.Context, user_id_or_mention: str):
    """Allow a user to re-submit (ID or mention). Usage: !reset_user 123456789012345678"""
    uid = None
    if user_id_or_mention.isdigit():
        uid = int(user_id_or_mention)
    else:
        try:
            uid = int(user_id_or_mention.replace("<@", "").replace(">", "").replace("!", ""))
        except Exception:
            uid = None
    if uid is None:
        await ctx.reply("Provide a valid user ID or mention.", delete_after=8)
        return

    removed_csv = remove_submission_row(uid)
    submitted_users.discard(uid)
    await ctx.reply(f"Reset done for `<@{uid}>` (csv_removed={removed_csv}).", delete_after=8)

@bot.command(name="update_email")
@commands.has_permissions(administrator=True)
async def update_email(ctx: commands.Context, user_mention_or_id: str, new_email: str):
    """CSV'de sadece e-postayı günceller ve log embed'ini eşler. Usage: !update_email @user new@example.com"""
    if not EMAIL_RE.fullmatch(new_email):
        await ctx.reply("Invalid email format.", delete_after=8)
        return
    try:
        if user_mention_or_id.isdigit():
            uid = int(user_mention_or_id)
        else:
            uid = int(user_mention_or_id.replace("<@", "").replace(">", "").replace("!", ""))
    except Exception:
        await ctx.reply("Provide a valid user mention or ID.", delete_after=8)
        return

    ok = update_submission(uid, new_email=new_email, new_player_id=None)
    if ok:
        await ctx.reply(f"Updated email for `<@{uid}>` → `{new_email}`", delete_after=10)
        # log mesajı varsa düzenle
        await _edit_log_from_csv(ctx.guild, uid)
    else:
        await ctx.reply("Record not found in CSV.", delete_after=10)

@bot.command(name="update_record")
@commands.has_permissions(administrator=True)
async def update_record(ctx: commands.Context, user_mention_or_id: str, new_email: str, new_player_id: str):
    """CSV'de e-posta + PlayerID günceller ve log embed'ini eşler. Usage: !update_record @user new@example.com 123456789"""
    if not EMAIL_RE.fullmatch(new_email):
        await ctx.reply("Invalid email format.", delete_after=8); return
    if not new_player_id.isdigit() or len(new_player_id) != EXACT_DIGITS:
        await ctx.reply(f"Player ID must be exactly {EXACT_DIGITS} digits.", delete_after=8); return
    try:
        if user_mention_or_id.isdigit():
            uid = int(user_mention_or_id)
        else:
            uid = int(user_mention_or_id.replace("<@", "").replace(">", "").replace("!", ""))
    except Exception:
        await ctx.reply("Provide a valid user mention or ID.", delete_after=8)
        return

    ok = update_submission(uid, new_email=new_email, new_player_id=new_player_id)
    if ok:
        await ctx.reply(
            f"Updated record for `<@{uid}>` → `{new_email}` / `{new_player_id}`",
            delete_after=10,
        )
        # log mesajı varsa düzenle
        await _edit_log_from_csv(ctx.guild, uid)
    else:
        await ctx.reply("Record not found in CSV.", delete_after=10)

@bot.command(name="edit_log")
@commands.has_permissions(administrator=True)
async def edit_log(ctx: commands.Context, user_mention_or_id: str):
    """Mevcut CSV'yi baz alarak ilgili kişinin log embed'ini yeniden yazar. Usage: !edit_log @user"""
    try:
        if user_mention_or_id.isdigit():
            uid = int(user_mention_or_id)
        else:
            uid = int(user_mention_or_id.replace("<@", "").replace(">", "").replace("!", ""))
    except Exception:
        await ctx.reply("Provide a valid user mention or ID.", delete_after=8)
        return

    await _edit_log_from_csv(ctx.guild, uid)
    await ctx.reply("Log message updated (if found).", delete_after=8)

async def _edit_log_from_csv(guild: discord.Guild, uid: int):
    """CSV'deki veriyi okuyup log_index.json içindeki mesajı düzenler."""
    if guild is None:
        return
    # CSV'den kayıt bul
    email = None
    player_id = None
    if SAVE_PATH.exists():
        with SAVE_PATH.open("r", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                v = r.get("discord_user_id", "")
                if v and v.isdigit() and int(v) == uid:
                    email = r.get("email", "")
                    player_id = r.get("player_id", "")
                    break
    if email is None:
        return

    # log_index'ten mesaj id al
    index = load_log_index()
    msg_id_str = index.get(str(uid))
    if not msg_id_str:
        return

    try:
        msg_id = int(msg_id_str)
    except:
        return

    log_ch = guild.get_channel(LOG_CHANNEL_ID)
    if not log_ch:
        return

    try:
        msg = await log_ch.fetch_message(msg_id)
    except Exception as e:
        print("fetch_message error:", e)
        return

    # embed'i güncelle
    try:
        new_emb = update_log_message_embed(msg, guild.get_member(uid) or guild._state.user, email, player_id)
        await msg.edit(content=None, embed=new_emb, view=None)
    except Exception as e:
        print("edit_log_message error:", e)

@bot.command(name="sub_count")
@commands.has_permissions(administrator=True)
async def sub_count(ctx: commands.Context):
    await ctx.reply(f"Currently stored submissions in memory: **{len(submitted_users)}**", delete_after=8)

# ── SLASH KOMUTLAR ──────────────────────────────────────────────────────────
@bot.tree.command(name="ping", description="Health check", guild=GOBJ)
async def ping_slash(interaction: discord.Interaction):
    print("/ping by", interaction.user)
    await interaction.response.send_message("Pong!", ephemeral=True)

@bot.tree.command(name="setup_register", description="Post the REGISTER button (admin only)", guild=GOBJ)
@app_commands.checks.has_permissions(administrator=True)
async def setup_register_slash(interaction: discord.Interaction):
    print("/setup_register by", interaction.user)
    if interaction.guild_id != GUILD_ID:
        await interaction.response.send_message("Wrong guild.", ephemeral=True)
        return
    guild = interaction.guild
    ch = guild.get_channel(REGISTER_POST_CHANNEL_ID) if guild else None
    if not ch:
        await interaction.response.send_message("REGISTER_POST_CHANNEL_ID not found.", ephemeral=True)
        return
    emb = discord.Embed(title=POST_TITLE, description=POST_DESC, color=0x5865F2)
    await ch.send(embed=emb, view=RegisterView())
    await interaction.response.send_message("Register post sent.", ephemeral=True)

# ── READY ───────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    global submitted_users
    submitted_users = load_submitted_user_ids()
    print(f"✅ Logged in as {bot.user} | Loaded {len(submitted_users)} submissions from CSV")

    bot.add_view(RegisterView())  # persistent view

    try:
        synced = await bot.tree.sync(guild=GOBJ)
        print(f"Slash synced for guild {GUILD_ID}: {len(synced)} cmd(s)")
    except Exception as e:
        print("Slash sync error:", e)

# ── RUN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set")
    bot.run(DISCORD_TOKEN)
