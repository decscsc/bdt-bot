#!/usr/init/env python3
"""
CTDOTEAM - Discord Bot (Auto Quest + Token Checker + Setup Welcome, Birthday, Verify, Agree & Help)
Created by ph.huyy | Vinh Phuc, Viet Nam
"""

import requests
import time
import json
import random
import sys
import os
import re
import base64
import traceback
import string
from datetime import datetime
from typing import Optional

# Thư viện Discord.py
import discord
from discord.ext import commands, tasks
from discord import app_commands

# Thư viện Flask để chạy Web Server giả lập cho Render
from flask import Flask
import threading

# ── Config ─────────────────────────────────────────────────────────────────────
API_BASE = "https://discord.com/api/v9"
POLL_INTERVAL = 60          
HEARTBEAT_INTERVAL = 20     
AUTO_ACCEPT = True          
LOG_PROGRESS = True
DEBUG = True                

SUPPORTED_TASKS = [
    "WATCH_VIDEO",
    "PLAY_ON_DESKTOP",
    "STREAM_ON_DESKTOP",
    "PLAY_ACTIVITY",
    "WATCH_VIDEO_ON_MOBILE",
]

# Lưu trữ token người dùng kèm thời hạn 2 tuần (14 ngày = 1209600 giây)
SAVED_USER_TOKENS = {} 
TOKEN_EXPIRE_SECONDS = 14 * 24 * 60 * 60  


# ── Logging ────────────────────────────────────────────────────────────────────
class Colors:
    RESET  = "\033[0m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"


def log(msg: str, level: str = "info"):
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = {
        "info":     f"{Colors.CYAN}[INFO]{Colors.RESET}",
        "ok":       f"{Colors.GREEN}[  OK]{Colors.RESET}",
        "warn":     f"{Colors.YELLOW}[WARN]{Colors.RESET}",
        "error":    f"{Colors.RED}[ ERR]{Colors.RESET}",
        "progress": f"{Colors.DIM}[PROG]{Colors.RESET}",
        "debug":    f"{Colors.DIM}[DBG ]{Colors.RESET}",
    }.get(level, f"[{level.upper()}]")

    if level == "debug" and not DEBUG:
        return
    if LOG_PROGRESS or level != "progress":
        print(f"{Colors.DIM}{ts}{Colors.RESET} {prefix} {msg}")


# ── Build number fetcher & Quest API Logic ──────────────────────────────────────
def fetch_latest_build_number() -> int:
    FALLBACK = 504649
    try:
        log("Đang lấy build number mới nhất từ Discord...", "info")
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        r = requests.get("https://discord.com/app", headers={"User-Agent": ua}, timeout=15)
        if r.status_code != 200:
            return FALLBACK
        scripts = re.findall(r'/assets/([a-f0-9]+)\.js', r.text)
        if not scripts:
            scripts_alt = re.findall(r'src="(/assets/[^"]+\.js)"', r.text)
            scripts = [s.split('/')[-1].replace('.js', '') for s in scripts_alt]
        if not scripts:
            return FALLBACK
        for asset_hash in scripts[-5:]:
            try:
                ar = requests.get(f"https://discord.com/assets/{asset_hash}.js", headers={"User-Agent": ua}, timeout=15)
                m = re.search(r'buildNumber["\s:]+["\s]*(\d{5,7})', ar.text)
                if m:
                    return int(m.group(1))
            except Exception:
                continue
        return FALLBACK
    except Exception:
        return FALLBACK


def make_super_properties(build_number: int) -> str:
    obj = {
        "os": "Windows", "browser": "Discord Client", "release_channel": "stable",
        "client_version": "1.0.9175", "os_version": "10.0.26100", "os_arch": "x64",
        "app_arch": "x64", "system_locale": "en-US",
        "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9175 Chrome/128.0.6613.186 Electron/32.2.7 Safari/537.36",
        "browser_version": "32.2.7", "client_build_number": build_number, "native_build_number": 59498,
        "client_event_source": None,
    }
    return base64.b64encode(json.dumps(obj).encode()).decode()


class DiscordAPI:
    def __init__(self, token: str, build_number: int):
        self.token = token
        self.session = requests.Session()
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9175 Chrome/128.0.6613.186 Electron/32.2.7 Safari/537.36"
        sp = make_super_properties(build_number)
        self.session.headers.update({
            "Authorization": token, "Content-Type": "application/json", "Accept": "*/*",
            "User-Agent": ua, "X-Super-Properties": sp, "X-Discord-Locale": "en-US",
            "X-Discord-Timezone": "Asia/Ho_Chi_Minh", "Origin": "https://discord.com",
            "Referer": "https://discord.com/channels/@me",
        })

    def get(self, path: str, **kwargs) -> requests.Response:
        return self.session.get(f"{API_BASE}{path}", **kwargs)

    def post(self, path: str, payload: Optional[dict] = None, **kwargs) -> requests.Response:
        return self.session.post(f"{API_BASE}{path}", json=payload, **kwargs)

    def validate_token(self) -> dict:
        try:
            r = self.get("/users/@me")
            if r.status_code == 200:
                return r.json()
            return {}
        except Exception:
            return {}


# Helper functions cho Quest
def _get(d: Optional[dict], *keys):
    if d is None: return None
    for k in keys:
        if k in d: return d[k]
    return None

def get_task_config(quest: dict) -> Optional[dict]:
    return _get(quest.get("config", {}), "taskConfig", "task_config", "taskConfigV2", "task_config_v2")

def is_completable(quest: dict) -> bool:
    tc = get_task_config(quest)
    if not tc or "tasks" not in tc: return False
    return any(tc["tasks"].get(t) is not None for t in SUPPORTED_TASKS)

def is_enrolled(quest: dict) -> bool:
    us = _get(quest, "userStatus", "user_status")
    return bool(_get(us if isinstance(us, dict) else {}, "enrolledAt", "enrolled_at"))

def is_completed(quest: dict) -> bool:
    us = _get(quest, "userStatus", "user_status")
    return bool(_get(us if isinstance(us, dict) else {}, "completedAt", "completed_at"))

def get_task_type(quest: dict) -> Optional[str]:
    tc = get_task_config(quest)
    if not tc or "tasks" not in tc: return None
    for t in SUPPORTED_TASKS:
        if tc["tasks"].get(t) is not None: return t
    return None

def get_seconds_needed(quest: dict) -> int:
    tc = get_task_config(quest)
    tt = get_task_type(quest)
    return tc["tasks"][tt].get("target", 0) if tc and tt else 0

def get_seconds_done(quest: dict) -> float:
    tt = get_task_type(quest)
    us = _get(quest, "userStatus", "user_status")
    prog = (us.get("progress", {}) if isinstance(us, dict) else {}) or {}
    return prog.get(tt, {}).get("value", 0) if tt else 0


class QuestAutocompleter:
    def __init__(self, api: DiscordAPI):
        self.api = api
        self.completed_ids: set = set()

    def fetch_quests(self) -> list:
        try:
            r = self.api.get("/quests/@me")
            if r.status_code == 200:
                data = r.json()
                return data.get("quests", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            return []
        except Exception:
            return []

    def enroll_quest(self, quest: dict) -> bool:
        qid = quest["id"]
        try:
            r = self.api.post(f"/quests/{qid}/enroll", {
                "location": 11, "is_targeted": False, "metadata_raw": None, "metadata_sealed": None,
                "traffic_metadata_raw": quest.get("traffic_metadata_raw"),
                "traffic_metadata_sealed": quest.get("traffic_metadata_sealed"),
            })
            return r.status_code in (200, 201, 204)
        except Exception:
            return False

    def auto_accept(self, quests: list) -> list:
        if not AUTO_ACCEPT: return quests
        for q in [q for q in quests if not is_enrolled(q) and not is_completed(q) and is_completable(q)]:
            self.enroll_quest(q)
            time.sleep(2)
        return self.fetch_quests()

    def complete_video(self, quest: dict):
        qid = quest["id"]
        needed, done = get_seconds_needed(quest), get_seconds_done(quest)
        while done < needed:
            ts = done + 7
            try:
                r = self.api.post(f"/quests/{qid}/video-progress", {"timestamp": min(needed, ts)})
                if r.status_code == 200:
                    if r.json().get("completed_at"): break
                    done = min(needed, ts)
                elif r.status_code == 429:
                    time.sleep(5); continue
            except Exception:
                pass
            time.sleep(1)

    def complete_heartbeat(self, quest: dict):
        qid = quest["id"]
        tt, needed, done = get_task_type(quest), get_seconds_needed(quest), get_seconds_done(quest)
        pid = random.randint(1000, 30000)
        while done < needed:
            try:
                r = self.api.post(f"/quests/{qid}/heartbeat", {"stream_key": f"call:0:{pid}", "terminal": False})
                if r.status_code == 200:
                    body = r.json()
                    prog = body.get("progress", {})
                    if prog and tt in prog: done = prog[tt].get("value", done)
                    if body.get("completed_at") or done >= needed: break
                elif r.status_code == 429:
                    time.sleep(10); continue
            except Exception:
                pass
            time.sleep(HEARTBEAT_INTERVAL)
        try:
            self.api.post(f"/quests/{qid}/heartbeat", {"stream_key": f"call:0:{pid}", "terminal": True})
        except Exception:
            pass

    def process_quest(self, quest: dict):
        qid, tt = quest.get("id"), get_task_type(quest)
        if not tt or qid in self.completed_ids: return
        if tt in ("WATCH_VIDEO", "WATCH_VIDEO_ON_MOBILE"):
            self.complete_video(quest)
        elif tt in ("PLAY_ON_DESKTOP", "STREAM_ON_DESKTOP", "PLAY_ACTIVITY"):
            self.complete_heartbeat(quest)
        self.completed_ids.add(qid)


# Lưu trữ cấu hình database tạm thời trên RAM
WELCOME_CONFIGS = {}
VERIFY_ROLE_CONFIGS = {}
AGREE_ROLE_CONFIGS = {}        
BIRTHDAY_CHANNEL_CONFIGS = {}  
USER_BIRTHDAYS = {}            

# ── Discord Bot & UI Modals/Views ──────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

async def try_react_custom_emoji(interaction: discord.Interaction):
    try:
        emoji_obj = bot.get_emoji(1503922700408586240)
        if emoji_obj and interaction.message:
            await interaction.message.add_reaction(emoji_obj)
    except Exception:
        pass


class BirthdayModal(discord.ui.Modal, title="🎂 Đăng ký thông tin Sinh Nhật"):
    day_input = discord.ui.TextInput(label="Ngày sinh (Day)", placeholder="Ví dụ: 25", min_length=1, max_length=2)
    month_input = discord.ui.TextInput(label="Tháng sinh (Month)", placeholder="Ví dụ: 12", min_length=1, max_length=2)
    year_input = discord.ui.TextInput(label="Năm sinh (Year)", placeholder="Ví dụ: 2008", min_length=4, max_length=4)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            d = int(self.day_input.value)
            m = int(self.month_input.value)
            y = int(self.year_input.value)
            USER_BIRTHDAYS[interaction.user.id] = {"day": d, "month": m, "year": y}
            
            embed = discord.Embed(
                title="✨ ĐĂNG KÝ SINH NHẬT THÀNH CÔNG!",
                description=f"Hệ thống đã ghi nhận ngày sinh của bạn: **{d:02d}/{m:02d}/{y}** 🎈",
                color=discord.Color.from_rgb(255, 105, 180)
            )
            embed.set_footer(text="Created by ph.huyy | Vĩnh Phúc, VN")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Ngày tháng năm sinh không hợp lệ!", ephemeral=True)

class BirthdayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎂 Đăng ký sinh nhật", style=discord.ButtonStyle.blurple, custom_id="persistent_birthday_button")
    async def birthday_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await try_react_custom_emoji(interaction)
        await interaction.response.send_modal(BirthdayModal())


class VerifyModal(discord.ui.Modal):
    def __init__(self, correct_code: str):
        super().__init__(title="🔒 Xác thực Captcha")
        self.correct_code = correct_code
        self.code_input = discord.ui.TextInput(
            label=f"Nhập lại chính xác mã: {correct_code}",
            placeholder="Nhập mã ở trên vào đây...",
            min_length=len(correct_code),
            max_length=len(correct_code)
        )
        self.add_item(self.code_input)

    async def on_submit(self, interaction: discord.Interaction):
        user_val = self.code_input.value.strip()
        if user_val == self.correct_code:
            role_name = VERIFY_ROLE_CONFIGS.get(interaction.guild.id, "Member")
            role = discord.utils.get(interaction.guild.roles, name=role_name)
            if not role:
                try:
                    role = await interaction.guild.create_role(name=role_name)
                except Exception:
                    pass
            if role and role not in interaction.user.roles:
                try:
                    await interaction.user.add_roles(role)
                    await interaction.response.send_message(f"🎉 Xác thực thành công! Nhận role **{role.name}**.", ephemeral=True)
                except Exception:
                    await interaction.response.send_message("⚠️ Bot thiếu quyền cấp role!", ephemeral=True)
            else:
                await interaction.response.send_message("ℹ️ Bạn đã xác thực từ trước!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Sai mã captcha!", ephemeral=True)

class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ Xác thực ngay", style=discord.ButtonStyle.green, custom_id="persistent_verify_button")
    async def verify_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await try_react_custom_emoji(interaction)
        chars = string.ascii_uppercase + string.digits
        random_code = ''.join(random.choices(chars, k=5))
        await interaction.response.send_modal(VerifyModal(random_code))


class AgreeRulesView(discord.ui.View):
    def __init__(self, role_name: str):
        super().__init__(timeout=None)
        self.role_name = role_name

    @discord.ui.button(label="Đồng ý", style=discord.ButtonStyle.green, custom_id="agree_rules_yes", emoji="✅")
    async def agree_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await try_react_custom_emoji(interaction)
        guild = interaction.guild
        role = discord.utils.get(guild.roles, name=self.role_name)
        if not role:
            try:
                role = await guild.create_role(name=self.role_name)
            except Exception:
                pass
        if role and role not in interaction.user.roles:
            try:
                await interaction.user.add_roles(role)
                await interaction.response.send_message(f"✅ Đã nhận role **{role.name}**.", ephemeral=True)
            except Exception:
                await interaction.response.send_message("⚠️ Bot thiếu quyền cấp role!", ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ Bạn đã có role này rồi!", ephemeral=True)

    @discord.ui.button(label="Không đồng ý", style=discord.ButtonStyle.red, custom_id="agree_rules_no", emoji="❌")
    async def disagree_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await try_react_custom_emoji(interaction)
        await interaction.response.send_message("❌ Bạn đã từ chối điều khoản.", ephemeral=True)


class TokenModal(discord.ui.Modal, title="🔑 Kiểm tra & Xác thực Token"):
    token_input = discord.ui.TextInput(
        label="Discord User Token",
        placeholder="Dán token cá nhân của bạn vào đây...",
        style=discord.TextStyle.short,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        token = self.token_input.value.strip()
        build_num = fetch_latest_build_number()
        api = DiscordAPI(token, build_num)
        
        user_data = api.validate_token()
        if not user_data or "id" not in user_data:
            await interaction.followup.send("❌ **Token không hợp lệ hoặc đã hết hạn!**", ephemeral=True)
            return
            
        user_id = user_data.get("id")
        
        # Lưu token kèm thời hạn 2 tuần
        expire_time = time.time() + TOKEN_EXPIRE_SECONDS
        SAVED_USER_TOKENS[user_id] = {
            "token": token,
            "expire_at": expire_time
        }
        
        # Tiến hành quét danh sách Quest của người dùng
        completer = QuestAutocompleter(api)
        quests = completer.fetch_quests()
        pending_quests = [
            q for q in quests 
            if not is_completed(q) and is_completable(q)
        ]
        
        username = user_data.get("username", "Unknown")
        global_name = user_data.get("global_name", username)
        
        embed = discord.Embed(
            title="✅ XÁC THỰC THÀNH CÔNG & QUÉT QUEST",
            description=f"Xin chào **{global_name}** (`{username}`). Token đã được lưu trữ trong 2 tuần.",
            color=discord.Color.green()
        )
        
        if pending_quests:
            quest_list_str = ""
            for idx, q in enumerate(pending_quests, 1):
                q_name = _get(q, "name") or _get(_get(q, "config", {}), "messages", {}).get("gameTitle", "Quest Discord")
                enrolled_status = "Đã nhận (Enrolled)" if is_enrolled(q) else "Chưa nhận (Not Enrolled)"
                quest_list_str += f"**{idx}.** {q_name} — *Trạng thái: {enrolled_status}*\n"
            
            embed.add_field(name=f"🎮 Các Quest CHƯA LÀM ({len(pending_quests)}):", value=quest_list_str, inline=False)
        else:
            embed.add_field(name="🎮 Trạng thái Quest:", value="Tuyệt vời! Bạn đã hoàn thành tất cả các Quest hiện có hoặc không có Quest nào khả dụng.", inline=False)
            
        await interaction.followup.send(embed=embed, ephemeral=True)


class TokenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔑 Nhập Token kiểm tra", style=discord.ButtonStyle.blurple, custom_id="persistent_token_button")
    async def token_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await try_react_custom_emoji(interaction)
        await interaction.response.send_modal(TokenModal())


@tasks.loop(hours=24)
async def check_birthdays_task():
    now = datetime.now()
    today_d, today_m = now.day, now.month
    for guild in bot.guilds:
        channel_id = BIRTHDAY_CHANNEL_CONFIGS.get(guild.id)
        if not channel_id: continue
        channel = guild.get_channel(channel_id)
        if not channel: continue
            
        for user_id, b_info in USER_BIRTHDAYS.items():
            if b_info["day"] == today_d and b_info["month"] == today_m:
                member = guild.get_member(user_id)
                if member:
                    embed = discord.Embed(
                        title="🎉 CHÚC MỪNG SINH NHẬT! 🥳",
                        description=f"Chúc mừng sinh nhật {member.mention}! 🎂🎁",
                        color=discord.Color.from_rgb(255, 215, 0)
                    )
                    try:
                        await channel.send(embed=embed)
                    except Exception:
                        pass


@tasks.loop(hours=1)
async def cleanup_expired_tokens():
    current_time = time.time()
    expired_users = [
        uid for uid, data in SAVED_USER_TOKENS.items() 
        if current_time > data["expire_at"]
    ]
    for uid in expired_users:
        del SAVED_USER_TOKENS[uid]


@bot.event
async def on_ready():
    bot.add_view(BirthdayView())
    bot.add_view(VerifyView())
    bot.add_view(AgreeRulesView("Member"))
    bot.add_view(TokenView())
    
    if not check_birthdays_task.is_running():
        check_birthdays_task.start()
    if not cleanup_expired_tokens.is_running():
        cleanup_expired_tokens.start()
        
    log(f"Discord Bot đã sẵn sàng: {bot.user.name}", "ok")
    try:
        synced = await bot.tree.sync()
        log(f"Đã đồng bộ {len(synced)} lệnh slash.", "ok")
    except Exception as e:
        log(f"Lỗi đồng bộ lệnh: {e}", "error")


@bot.event
async def on_member_join(member: discord.Member):
    config = WELCOME_CONFIGS.get(member.guild.id)
    if not config: return
    channel = member.guild.get_channel(config["channel_id"])
    if not channel: return
    
    custom_msg = config["message"].replace("{user}", member.mention).replace("{server}", member.guild.name)
    embed = discord.Embed(title="👋 Chào mừng!", description=custom_msg, color=discord.Color.blue())
    await channel.send(embed=embed)


# ── Lệnh Slash: /auto ──────────────────────────────────────────────────────────
@bot.tree.command(name="auto", description="Tự động quét và hoàn thành các Quest Discord chưa làm")
async def slash_auto(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_id = interaction.user.id
    
    user_token_data = SAVED_USER_TOKENS.get(user_id)
    if not user_token_data or time.time() > user_token_data["expire_at"]:
        await interaction.followup.send(
            "❌ Bạn chưa nhập token hoặc token đã hết hạn lưu trữ (2 tuần).\n"
            "Vui lòng sử dụng lệnh `/token` để nhập và lưu token trước khi chạy auto!", 
            ephemeral=True
        )
        return
        
    token = user_token_data["token"]
    build_num = fetch_latest_build_number()
    api = DiscordAPI(token, build_num)
    
    user_data = api.validate_token()
    if not user_data or "id" not in user_data:
        await interaction.followup.send("❌ **Token của bạn không hợp lệ hoặc đã hết hạn trên Discord!** Hãy cập nhật lại bằng lệnh `/token`.", ephemeral=True)
        return
        
    completer = QuestAutocompleter(api)
    quests = completer.fetch_quests()
    
    if not quests:
        await interaction.followup.send("⚠️ Không tìm thấy Quest nào khả dụng trên tài khoản của bạn.", ephemeral=True)
        return
        
    quests = completer.auto_accept(quests)
    actionable = [q for q in quests if is_enrolled(q) and not is_completed(q) and is_completable(q)]
    
    if not actionable:
        await interaction.followup.send("✅ Tuyệt vời! Tất cả các Quest hiện tại đã hoàn thành hoặc không có quest nào cần làm.", ephemeral=True)
        return
        
    embed = discord.Embed(
        title="🚀 HỆ THỐNG AUTO QUEST ĐANG CHẠY",
        description=f"Đã tìm thấy **{len(actionable)}** quest chưa hoàn thành. Bot đang tiến hành chạy ngầm để hoàn thành cho bạn...",
        color=discord.Color.from_rgb(0, 255, 127)
    )
    await interaction.followup.send(embed=embed, ephemeral=True)
    
    for q in actionable:
        try:
            completer.process_quest(q)
            time.sleep(2)
        except Exception:
            pass
            
    done_embed = discord.Embed(
        title="✨ HOÀN TẤT AUTO QUEST",
        description="Quá trình tự động chạy hoàn thành các nhiệm vụ đã kết thúc!",
        color=discord.Color.green()
    )
    await interaction.followup.send(embed=done_embed, ephemeral=True)


# ── Lệnh Slash: /token ─────────────────────────────────────────────────────────
@bot.tree.command(name="token", description="Gửi bảng giao diện để kiểm tra thông tin Discord User Token")
async def slash_token(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Thiếu quyền Quản trị viên!", ephemeral=True)
        return
    embed = discord.Embed(
        title="🔑 HỆ THỐNG KIỂM TRA TOKEN",
        description="Bấm vào nút bên dưới để mở bảng nhập, kiểm tra thông tin tài khoản và lưu token tự động trong 2 tuần.",
        color=discord.Color.blurple()
    )
    view = TokenView()
    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ Đã gửi bảng giao diện kiểm tra token!", ephemeral=True)


@bot.tree.command(name="agree", description="Gửi bảng nội quy")
async def slash_agree(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None, role_name: Optional[str] = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Thiếu quyền Quản trị viên!", ephemeral=True)
        return
    target_channel = channel or interaction.channel
    r_name = role_name or "Member"
    embed = discord.Embed(title="⚠️ XÁC NHẬN NỘI QUY", description="Bấm nút Đồng ý bên dưới để nhận role.", color=discord.Color.orange())
    view = AgreeRulesView(r_name)
    await target_channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ Đã gửi bảng nội quy thành công!", ephemeral=True)


@bot.tree.command(name="help", description="Hiển thị hướng dẫn sử dụng")
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 TRỢ GIÚP - CTDOTEAM", description="Danh sách các lệnh bot:", color=discord.Color.orange())
    embed.add_field(name="/auto", value="Tự động quét và chạy hoàn thành các Quest Discord chưa làm.", inline=False)
    embed.add_field(name="/token", value="Mở bảng nhập token, kiểm tra thông tin tài khoản và lưu trong 2 tuần.", inline=False)
    embed.add_field(name="/agree", value="Gửi bảng nội quy server để nhận role.", inline=False)
    embed.add_field(name="/setup", value="Cài đặt các tính năng hệ thống (Welcome, Birthday, Verify).", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="setup", description="Cài đặt hệ thống")
@app_commands.choices(feature=[
    app_commands.Choice(name="Welcome", value="welcome"),
    app_commands.Choice(name="Birthday", value="birthday"),
    app_commands.Choice(name="Verify", value="verify"),
])
async def setup(interaction: discord.Interaction, feature: str, channel: Optional[discord.TextChannel] = None, message: Optional[str] = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Thiếu quyền Quản trị viên!", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ Đã thiết lập tính năng `{feature}` thành công!", ephemeral=True)


# ── Flask Web Server ───────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route('/')
def home():
    return "Discord Bot is running and Web Server is active!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

web_thread = threading.Thread(target=run_web)
web_thread.daemon = True
web_thread.start()


if __name__ == "__main__":
    DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
    if not DISCORD_BOT_TOKEN:
        print("Vui lòng thiết lập biến môi trường DISCORD_BOT_TOKEN.")
        sys.exit(1)
    bot.run(DISCORD_BOT_TOKEN)
