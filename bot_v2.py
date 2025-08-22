# bot_v2.py

import os, re, csv, io, base64, json, asyncio, datetime
from pathlib import Path

import gspread
from google.oauth2 import service_account

import discord
from discord.ext import commands
from discord import app_commands

# ─────────────────────────────────────────────────────────────────────
# ENV
# ─────────────────────────────────────────────────────────────────────
TOKEN = os.getenv("DISCORD_TOKEN")

GUILD_ID = int(os.getenv("GUILD_ID", "0"))
REGISTER_POST_CHANNEL_ID = int(os.getenv("REGISTER_POST_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
MOD_COMMANDS_CHANNEL_ID = int(os.getenv("MOD_COMMANDS_CHANNEL_ID", "0"))
REGISTERED_ROLE_ID = int(os.getenv("REGISTERED_ROLE_ID", "0"))

# Google Sheets kimlik bilgileri (ikisi de desteklenir)
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
GOOGLE_SERVICE_ACCOUNT_B64  = os.getenv("GOOGLE_SERVICE_ACCOUNT_B64", "").strip()
GS_SHEET_ID   = os.getenv("GOOGLE_SHEET_ID", "").strip()
GS_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "submissions").strip()

# ─────────────────────────────────────────────────────────────────────
# Sabitler / Kurallar / Metinler
# ─────────────────────────────────────────────────────────────────────
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
    "3️⃣ In that DM, send your **Email** and **Player ID** together in one message, separated by a space.\n\n"
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
DM_HINT = "Please use: `email@example.com 123456789`"
DM_INVALID_EMAIL = "Invalid email format. " + DM_HINT
DM_INVALID_DIGITS = "Player ID must contain only digits. " + DM_HINT
DM_INVALID_LENGTH = f"Player ID must be exactly {EXACT_DIGITS} digits. " + DM_HINT
DM_TIMEOUT = "Timed out waiting for your reply. Click REGISTER again to restart."
DM_SUCCESS = "✅ Saved. Your code will be sent by email."
EPHEM_OPEN_DM = ("I couldn’t DM you. Enable **Direct Messages** "
                 "from server members (Privacy) and click **REGISTER** again.")
EPHEM_ALREADY = "You have already submitted. Updates are disabled."

# ─────────────────────────────────────────────────────────────────────
# In-memory & CSV yedek
# ─────────────────────────────────────────────────────────────────────
submitted_users: set[int] = set()
SAVE_PATH = Path("submissions.csv")  # yerel yedek (opsiyonel)

def csv_append(discord_user_id: int, email: str, player_id: str):
    new_file = not SAVE_PATH.exists()
    with SAVE_PATH.open("a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["discord_user_id","discord_name","email","player_id",
                        "status","log_message_id","updated_by","updated_at"])
        w.writerow([discord_user_id,"",email,player_id,"confirmed","","",
                    datetime.datetime.utcnow().isoformat()])

def csv_remove(discord_user_id: int):
    if not SAVE_PATH.exists(): return False
    rows, changed = [], False
    with SAVE_PATH.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get("discord_user_id","") == str(discord_user_id):
                changed = True
            else:
                rows.append(r)
    if changed:
        with SAVE_PATH.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["discord_user_id","discord_name","email","player_id",
                                              "status","log_message_id","updated_by","updated_at"])
            w.writeheader()
            for r in rows: w.writerow(r)
    return changed

# ─────────────────────────────────────────────────────────────────────
# Discord
# ─────────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
GOBJ = discord.Object(id=GUILD_ID)

def ensure_mod_channel(ctx_or_inter) -> bool:
    """Komutların yalnızca mod kanalında çalışması için kontrol."""
    if MOD_COMMANDS_CHANNEL_ID == 0:
        return True
    ch_id = getattr(getattr(ctx_or_inter, "channel", None), "id", None)
    return ch_id == MOD_COMMANDS_CHANNEL_ID

async def resolve_member(ctx: commands.Context, who: str) -> discord.Member | None:
    """ID, mention veya isimle üyeyi bul."""
    guild = ctx.guild
    if not guild: return None
    # numeric id
    if who.isdigit():
        return guild.get_member(int(who)) or await guild.fetch_member(int(who))
    # mention
    who = who.replace("<@", "").replace(">", "").replace("!", "")
    if who.isdigit():
        return guild.get_member(int(who)) or await guild.fetch_member(int(who))
    # name search
    who = who.lower()
    for m in guild.members:
        if who in str(m).lower():
            return m
    return None

def now_iso() -> str:
    return datetime.datetime.utcnow().isoformat()

# ─────────────────────────────────────────────────────────────────────
# Google Sheets helpers
# ─────────────────────────────────────────────────────────────────────
def _debug_env_short(val: str, label: str) -> str:
    if not val:
        return f"{label}=<empty>"
    return f"{label}=len:{len(val)} head:{val[:20]!r}"

def gs_client():
    """
    1) GOOGLE_SERVICE_ACCOUNT_JSON varsa: doğrudan JSON string'ini kullanır
    2) Yoksa GOOGLE_SERVICE_ACCOUNT_B64 varsa: decode edip JSON'a çevirir
    """
    print("[GS] init:",
          _debug_env_short(GOOGLE_SERVICE_ACCOUNT_JSON, "JSON"),
          "|",
          _debug_env_short(GOOGLE_SERVICE_ACCOUNT_B64, "B64"),
          "| SHEET_ID:", GS_SHEET_ID, "| SHEET_NAME:", GS_SHEET_NAME)

    if not GS_SHEET_ID or not GS_SHEET_NAME:
        print("[GS] Missing GS_SHEET_ID or GS_SHEET_NAME")
        return None, None

    data = None
    if GOOGLE_SERVICE_ACCOUNT_JSON:
        try:
            data = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        except Exception as e:
            print("[GS] JSON env parse error:", repr(e))
    if data is None and GOOGLE_SERVICE_ACCOUNT_B64:
        try:
            data = json.loads(base64.b64decode(GOOGLE_SERVICE_ACCOUNT_B64).decode("utf-8"))
        except Exception as e:
            print("[GS] B64 env decode/parse error:", repr(e))
    if data is None:
        print("[GS] No usable credentials data found.")
        return None, None

    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = service_account.Credentials.from_service_account_info(data, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(GS_SHEET_ID)
        # worksheet hazırla
        try:
            ws = sh.worksheet(GS_SHEET_NAME)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(GS_SHEET_NAME, rows=1000, cols=12)
            ws.append_row(["discord_user_id","discord_name","email","player_id",
                           "status","log_message_id","updated_by","updated_at"])
        return gc, ws
    except Exception as e:
        print("[GS] gs_client fatal error:", repr(e))
        return None, None

def gs_upsert(discord_id: int, payload: dict) -> bool:
    """
    A sütununda discord_user_id varsa UPDATE, yoksa APPEND.
    """
    try:
        _, ws = gs_client()
        if not ws:
            print("[GS] upsert: worksheet not ready")
            return False

        # ID'yi bul
        cell = None
        try:
            try:
                cell = ws.find(str(discord_id), in_column=1)
            except TypeError:
                cell = ws.find(str(discord_id))
        except Exception:
            cell = None

        now = now_iso()
        row_values = [
            str(discord_id),
            payload.get("discord_name", ""),
            payload.get("email", ""),
            payload.get("player_id", ""),
            payload.get("status", "ok"),
            payload.get("log_message_id", ""),
            payload.get("updated_by", "bot"),
            payload.get("updated_at", now),
        ]

        if cell and getattr(cell, "row", None):
            row_idx = cell.row
            ws.update(f"A{row_idx}:H{row_idx}", [row_values])
            print(f"[GS] updated row {row_idx} for {discord_id}")
        else:
            ws.append_row(row_values, value_input_option="USER_ENTERED")
            print(f"[GS] appended new row for {discord_id}")

        return True
    except Exception as e:
        print("[GS] upsert error:", repr(e))
        return False

def gs_fetch_all_as_csv_bytes() -> bytes | None:
    """Tüm sheet’i CSV olarak döndürür (export için)."""
    try:
        _, ws = gs_client()
        if not ws: return None
        rows = ws.get_all_values()
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerows(rows)
        return out.getvalue().encode("utf-8")
    except Exception as e:
        print("[GS] export error:", repr(e))
        return None

# ─────────────────────────────────────────────────────────────────────
# DM akışı + REGISTER butonu
# ─────────────────────────────────────────────────────────────────────
class ConfirmView(discord.ui.View):
    def __init__(self, owner_id: int, email: str, player_id: str, timeout=90):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.email = email
        self.player_id = player_id
        self.result = None  # True/False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = True
        await interaction.response.send_message("Saved ✅", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = False
        await interaction.response.send_message(
            "Cancelled. If you need help, ping <@runyun> or <@aurilis>.", ephemeral=True)
        self.stop()

class RegisterView(discord.ui.View):
    def __init__(self, timeout=None):
        super().__init__(timeout=timeout)

    @discord.ui.button(label=BTN_LABEL, style=discord.ButtonStyle.primary, custom_id="rr_register_btn")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user

        if user.id in submitted_users:
            await interaction.response.send_message(EPHEM_ALREADY, ephemeral=True)
            return

        # DM aç
        try:
            dm = await user.create_dm()
            await dm.send(DM_GREETING)
        except:
            await interaction.response.send_message(EPHEM_OPEN_DM, ephemeral=True)
            return

        await interaction.response.send_message("DM sent. Please check your inbox.", ephemeral=True)

        def check(m: discord.Message):
            return m.author.id == user.id and isinstance(m.channel, discord.DMChannel)

        attempts = 3
        while attempts > 0:
            try:
                msg: discord.Message = await bot.wait_for("message", check=check, timeout=120)
            except asyncio.TimeoutError:
                await dm.send(DM_TIMEOUT)
                return

            content = msg.content.strip().replace("\n", " ")
            parts = content.split()
            if len(parts) != 2:
                await dm.send(DM_HINT); attempts -= 1; continue

            email, player_id = parts[0].strip(), parts[1].strip()
            if not EMAIL_RE.fullmatch(email):
                await dm.send(DM_INVALID_EMAIL); attempts -= 1; continue
            if not player_id.isdigit():
                await dm.send(DM_INVALID_DIGITS); attempts -= 1; continue
            if len(player_id) != EXACT_DIGITS:
                await dm.send(DM_INVALID_LENGTH); attempts -= 1; continue

            # Son onay
            emb = discord.Embed(title="Confirm your details", color=0x3498DB)
            emb.add_field(name="Email", value=email, inline=True)
            emb.add_field(name="Player ID", value=f"`{player_id}`", inline=True)
            emb.set_footer(text="If wrong, press Cancel and try again.")
            view = ConfirmView(owner_id=user.id, email=email, player_id=player_id)
            await dm.send(embed=emb, view=view)

            try:
                await view.wait()
            except:
                pass

            if view.result is not True:
                return  # iptal edildi

            # Onaylandı → kaydet
            submitted_users.add(user.id)

            guild = bot.get_guild(GUILD_ID)
            log_message_id = ""
            if guild:
                # Log
                log_ch = guild.get_channel(LOG_CHANNEL_ID)
                if log_ch:
                    e = discord.Embed(title="New Submission", color=0x3498DB)
                    e.add_field(name="Discord", value=f"{user} (`{user.id}`)", inline=False)
                    e.add_field(name="Email", value=email, inline=True)
                    e.add_field(name="Player ID", value=player_id, inline=True)
                    m = await log_ch.send(embed=e)
                    log_message_id = str(m.id)

                # Rol
                if REGISTERED_ROLE_ID:
                    role = guild.get_role(REGISTERED_ROLE_ID)
                    if role:
                        member = guild.get_member(user.id) or await guild.fetch_member(user.id)
                        if member:
                            try:
                                await member.add_roles(role, reason="Successfully registered")
                            except Exception as e_add:
                                print("Role add error:", e_add)

            # Sheet + CSV
            now = now_iso()
            gs_upsert(user.id, {
                "discord_user_id": str(user.id),
                "discord_name": str(user),
                "email": email,
                "player_id": player_id,
                "status": "confirmed",
                "log_message_id": log_message_id,
                "updated_by": str(user.id),
                "updated_at": now
            })
            csv_append(user.id, email, player_id)

            # DM ok
            ok = discord.Embed(description=DM_SUCCESS, color=COLOR_OK)
            ok.set_author(name=f"{BRAND} Verify")
            ok.add_field(name="Email", value=email, inline=True)
            ok.add_field(name="Player ID", value=f"`{player_id}`", inline=True)
            await dm.send(embed=ok)
            return

        await dm.send("Too many invalid attempts. Click REGISTER again to restart.")

# ─────────────────────────────────────────────────────────────────────
# Prefix Komutlar (yalnızca MOD_COMMANDS_CHANNEL_ID)
# ─────────────────────────────────────────────────────────────────────
@bot.command(name="ping")
async def ping_prefix(ctx: commands.Context):
    await ctx.reply("Pong!")

@bot.command(name="setup_register")
@commands.has_permissions(administrator=True)
async def setup_register(ctx: commands.Context):
    if not ensure_mod_channel(ctx): return
    guild = ctx.guild
    ch = guild.get_channel(REGISTER_POST_CHANNEL_ID) if guild else None
    if not ch:
        await ctx.reply("REGISTER_POST_CHANNEL_ID not found."); return
    emb = discord.Embed(title=POST_TITLE, description=POST_DESC, color=0x5865F2)
    await ch.send(embed=emb, view=RegisterView())
    await ctx.reply("Register post sent.")

@bot.command(name="reset_user")
@commands.has_permissions(manage_guild=True)
async def reset_user(ctx: commands.Context, who: str):
    if not ensure_mod_channel(ctx): return
    member = await resolve_member(ctx, who)
    if not member:
        await ctx.reply("User not found."); return
    submitted_users.discard(member.id)
    csv_remove(member.id)
    gs_upsert(member.id, {
        "discord_user_id": str(member.id),
        "discord_name": str(member),
        "status": "reset",
        "updated_by": str(ctx.author),
        "updated_at": now_iso()
    })
    await ctx.reply(f"Reset done for <@{member.id}>.")

@bot.command(name="update_email")
@commands.has_permissions(manage_guild=True)
async def update_email(ctx: commands.Context, who: str, new_email: str):
    if not ensure_mod_channel(ctx): return
    member = await resolve_member(ctx, who)
    if not member:
        await ctx.reply("User not found."); return
    if not EMAIL_RE.fullmatch(new_email):
        await ctx.reply("Invalid email."); return
    gs_upsert(member.id, {
        "discord_user_id": str(member.id),
        "discord_name": str(member),
        "email": new_email,
        "updated_by": str(ctx.author),
        "updated_at": now_iso()
    })
    await ctx.reply(f"Email updated for <@{member.id}> → `{new_email}`")

@bot.command(name="update_record")
@commands.has_permissions(manage_guild=True)
async def update_record(ctx: commands.Context, who: str, new_email: str, new_player_id: str):
    if not ensure_mod_channel(ctx): return
    member = await resolve_member(ctx, who)
    if not member:
        await ctx.reply("User not found."); return
    if not EMAIL_RE.fullmatch(new_email):
        await ctx.reply("Invalid email."); return
    if not (new_player_id.isdigit() and len(new_player_id)==EXACT_DIGITS):
        await ctx.reply("Invalid Player ID."); return
    gs_upsert(member.id, {
        "discord_user_id": str(member.id),
        "discord_name": str(member),
        "email": new_email,
        "player_id": new_player_id,
        "updated_by": str(ctx.author),
        "updated_at": now_iso()
    })
    await ctx.reply(f"Record updated for <@{member.id}>.")

@bot.command(name="edit_log")
@commands.has_permissions(manage_guild=True)
async def edit_log(ctx: commands.Context, who: str):
    if not ensure_mod_channel(ctx): return
    member = await resolve_member(ctx, who)
    if not member:
        await ctx.reply("User not found."); return

    _, ws = gs_client()
    email = player_id = log_msg_id = ""
    if ws:
        for r in ws.get_all_records():
            if str(r.get("discord_user_id","")) == str(member.id):
                email = r.get("email","")
                player_id = r.get("player_id","")
                log_msg_id = r.get("log_message_id","")
                break

    guild = ctx.guild
    log_ch = guild.get_channel(LOG_CHANNEL_ID) if guild else None
    if not log_ch:
        await ctx.reply("LOG_CHANNEL_ID not found."); return

    e = discord.Embed(title="Submission (edited)", color=0x3498DB)
    e.add_field(name="Discord", value=f"{member} (`{member.id}`)", inline=False)
    e.add_field(name="Email", value=email or "-", inline=True)
    e.add_field(name="Player ID", value=player_id or "-", inline=True)

    if log_msg_id:
        try:
            msg = await log_ch.fetch_message(int(log_msg_id))
            await msg.edit(embed=e)
            await ctx.reply("Log message updated."); return
        except Exception as ex:
            print("fetch/edit log msg error:", ex)

    msg = await log_ch.send(embed=e)
    gs_upsert(member.id, {
        "discord_user_id": str(member.id),
        "log_message_id": str(msg.id),
        "updated_by": str(ctx.author),
        "updated_at": now_iso()
    })
    await ctx.reply("Log re-posted and link saved.")

@bot.command(name="grant_registered")
@commands.has_permissions(manage_roles=True)
async def grant_registered(ctx: commands.Context, who: str):
    if not ensure_mod_channel(ctx): return
    member = await resolve_member(ctx, who)
    if not member:
        await ctx.reply("User not found."); return
    role = ctx.guild.get_role(REGISTERED_ROLE_ID) if ctx.guild else None
    if not role:
        await ctx.reply("Registered role not found."); return
    try:
        await member.add_roles(role, reason="Manual grant")
        await ctx.reply(f"Role granted to <@{member.id}>.")
    except Exception as e_add:
        await ctx.reply(f"Role add error: `{e_add}`")

@bot.command(name="sub_count")
@commands.has_permissions(manage_guild=True)
async def sub_count(ctx: commands.Context):
    if not ensure_mod_channel(ctx): return
    await ctx.reply(f"In-memory submissions: **{len(submitted_users)}**")

@bot.command(name="export_csv")
@commands.has_permissions(manage_guild=True)
async def export_csv(ctx: commands.Context):
    if not ensure_mod_channel(ctx): return
    data = gs_fetch_all_as_csv_bytes()
    if not data:
        await ctx.reply("Sheet not configured."); return
    await ctx.reply(file=discord.File(io.BytesIO(data), filename="submissions.csv"))

# ─────────────────────────────────────────────────────────────────────
# SLASH (mod kanal kısıtı)
# ─────────────────────────────────────────────────────────────────────
@bot.tree.command(name="ping", description="Health check", guild=GOBJ)
async def ping_slash(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!", ephemeral=True)

@bot.tree.command(name="setup_register", description="Post the REGISTER button", guild=GOBJ)
@app_commands.checks.has_permissions(administrator=True)
async def setup_register_slash(interaction: discord.Interaction):
    if not ensure_mod_channel(interaction):
        await interaction.response.send_message("Use this in the mod commands channel.", ephemeral=True)
        return
    guild = interaction.guild
    ch = guild.get_channel(REGISTER_POST_CHANNEL_ID) if guild else None
    if not ch:
        await interaction.response.send_message("REGISTER_POST_CHANNEL_ID not found.", ephemeral=True); return
    emb = discord.Embed(title=POST_TITLE, description=POST_DESC, color=0x5865F2)
    await ch.send(embed=emb, view=RegisterView())
    await interaction.response.send_message("Register post sent.", ephemeral=True)

# ─────────────────────────────────────────────────────────────────────
# on_ready
# ─────────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    # Sheet varsa header’ı garantile ve mevcut kayıtları belleğe yükle
    _, ws = gs_client()
    if ws:
        try:
            for r in ws.get_all_records():
                uid = str(r.get("discord_user_id","")).strip()
                if uid.isdigit():
                    submitted_users.add(int(uid))
        except Exception as e:
            print("[GS] preload error:", repr(e))

    # Restart sonrası butonun çalışması için
    bot.add_view(RegisterView())

    # Hızlı slash sync
    try:
        synced = await bot.tree.sync(guild=GOBJ)
        print(f"Slash synced: {len(synced)}")
    except Exception as e:
        print("Slash sync err:", e)

    print(f"✅ Logged in as {bot.user}")

bot.run(TOKEN)
