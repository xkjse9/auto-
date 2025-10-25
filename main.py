import discord
from discord.ext import commands
from discord import app_commands, ui, Interaction
import json
import os
from flask import Flask
import threading
import requests
import time
import traceback

# ---------- Discord Bot ----------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- JSON 儲存檔 ----------
DATA_FILE = "keywords.json"
def load_keywords():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            # 如果 JSON 壞掉，備份再回退空 dict，避免程式崩潰
            print(f"❗ 讀取 {DATA_FILE} 時發生錯誤，已備份並以空字典取代：{e}")
            try:
                os.rename(DATA_FILE, DATA_FILE + ".bak")
                print(f"備份檔案為 {DATA_FILE}.bak")
            except Exception as e2:
                print(f"備份失敗：{e2}")
            return {}
    else:
        return {}

keywords = load_keywords()

def save_keywords():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(keywords, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"⚠️ 儲存 {DATA_FILE} 時出錯：{e}")

# ---------- Modal ----------
class KeywordModal(ui.Modal, title="新增或修改關鍵字"):
    def __init__(self, key_to_edit=None):
        super().__init__()
        self.key_to_edit = key_to_edit
        self.keyword_input = ui.TextInput(
            label="要偵測的關鍵字或關鍵詞",
            placeholder="輸入關鍵字...",
            max_length=1000,
            default=key_to_edit if key_to_edit else ""
        )
        self.add_item(self.keyword_input)

        self.reply_input = ui.TextInput(
            label="回覆內容",
            placeholder="輸入回覆訊息...",
            style=discord.TextStyle.paragraph,
            max_length=2000,
            default=keywords.get(key_to_edit, "") if key_to_edit else ""
        )
        self.add_item(self.reply_input)

    async def on_submit(self, interaction: Interaction):
        key = self.keyword_input.value.strip()
        reply = self.reply_input.value.strip()
        if not key or not reply:
            await interaction.response.send_message("關鍵字或回覆不能為空", ephemeral=True)
            return
        if self.key_to_edit and self.key_to_edit != key:
            keywords.pop(self.key_to_edit, None)
        keywords[key] = reply
        save_keywords()
        await interaction.response.send_message(f"✅ 已儲存關鍵字 `{key}` 對應回覆 `{reply}`", ephemeral=True)

# ---------- 按鈕面板 ----------
class KeywordView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for key in keywords:
            # 若按鈕 label 太長可能會被截斷，但通常可用
            self.add_item(DeleteOrEditButton(key))

    @ui.button(label="新增關鍵字", style=discord.ButtonStyle.primary)
    async def add_keyword(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_modal(KeywordModal())

class DeleteOrEditButton(ui.Button):
    def __init__(self, key):
        label = key if isinstance(key, str) and len(key) <= 80 else (str(key)[:77] + "...")
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        # 用 custom_id 在 callback 裡區分
        self.key = key
        self.custom_id = f"keyword_button_{key}"

    async def callback(self, interaction: Interaction):
        options_view = ui.View(timeout=None)
        # 使用 unique custom_id 以便 on_interaction 能讀取到
        options_view.add_item(ui.Button(label="修改", style=discord.ButtonStyle.success, custom_id=f"edit_{self.key}"))
        options_view.add_item(ui.Button(label="刪除", style=discord.ButtonStyle.danger, custom_id=f"delete_{self.key}"))
        await interaction.response.send_message(f"管理關鍵字 `{self.key}`", view=options_view, ephemeral=True)

@bot.event
async def on_interaction(interaction: Interaction):
    # 先確認是 component 類型，並且含有 data
    try:
        if interaction.type != discord.InteractionType.component:
            return
        data = getattr(interaction, "data", None)
        if not data:
            return
        custom_id = data.get("custom_id", "")
        if not custom_id:
            return
        if custom_id.startswith("edit_"):
            key = custom_id[5:]
            await interaction.response.send_modal(KeywordModal(key_to_edit=key))
        elif custom_id.startswith("delete_"):
            key = custom_id[7:]
            keywords.pop(key, None)
            save_keywords()
            await interaction.response.send_message(f"🗑️ 已刪除關鍵字 `{key}`", ephemeral=True)
    except Exception:
        print("on_interaction 發生例外：")
        traceback.print_exc()

# ---------- 斜線指令 ----------
@bot.tree.command(name="keywords", description="開啟關鍵字管理面板")
async def keywords_command(interaction: Interaction):
    view = KeywordView()
    await interaction.response.send_message("🔧 關鍵字管理面板", view=view, ephemeral=True)

# ---------- 偵測訊息 ----------
@bot.event
async def on_message(message):
    try:
        if message.author.bot:
            return
        content = message.content or ""
        # 可以改成不區分大小寫： content_lower = content.lower()
        for key, reply in keywords.items():
            if key in content:
                await message.channel.send(reply)
                break
    except Exception:
        print("on_message 發生例外：")
        traceback.print_exc()
    finally:
        await bot.process_commands(message)

# ---------- 上線事件 ----------
@bot.event
async def on_ready():
    try:
        print(f"✅ {bot.user} 已上線")
        await bot.change_presence(activity=discord.Game(name="關鍵字監聽中"))
        try:
            synced = await bot.tree.sync()
            print(f"✅ 已同步 {len(synced)} 個斜線指令")
        except Exception as e:
            print(f"❌ 同步斜線指令時出錯：{e}")
    except Exception:
        print("on_ready 發生例外：")
        traceback.print_exc()

# ---------- Flask Web 伺服器 ----------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    # Flask 設置：threaded True 讓多請求時較穩定
    app.run(host="0.0.0.0", port=port, threaded=True)

# ---------- 自動 Ping 自己（僅在 RENDER_EXTERNAL_URL 有設定時啟動） ----------
def ping_self():
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        print("⚠️ RENDER_EXTERNAL_URL 未設，ping_self 不啟動（建議用 UptimeRobot 來 ping）")
        return
    print(f"🔁 ping_self 啟動，目標：{url}")
    while True:
        try:
            r = requests.get(url, timeout=10)
            print(f"🟢 Ping {url} -> {r.status_code}")
        except Exception as e:
            print(f"🔴 Ping 失敗: {e}")
        time.sleep(300)  # 每 5 分鐘 ping 一次

# ---------- 啟動多執行緒（Web） ----------
threading.Thread(target=run_web, daemon=True).start()
# 只有在有 RENDER_EXTERNAL_URL 時才啟用 ping 線程
if os.environ.get("RENDER_EXTERNAL_URL"):
    threading.Thread(target=ping_self, daemon=True).start()

# ---------- 啟動 Bot（主程式） ----------
TOKEN = os.environ.get("DISCORD_TOKEN", "")
print("DEBUG: DISCORD_TOKEN length =", len(TOKEN))
TOKEN = TOKEN.strip()
if not TOKEN:
    print("❌ 錯誤：未設定 DISCORD_TOKEN 環境變數或為空！請到 Render 設定後重新部署")
    # 安全退出（不啟動 bot）
    raise SystemExit(1)

try:
    bot.run(TOKEN)
except Exception as e:
    print("❌ bot.run 發生錯誤：")
    traceback.print_exc()
    raise
