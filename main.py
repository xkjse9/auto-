import os
import discord
from discord.ext import commands
from discord import app_commands, ui, Interaction
import json
import traceback
import logging
import datetime
from datetime import timezone, timedelta
from flask import Flask
import threading

# ====== 基本設定 ======
logging.basicConfig(level=logging.INFO)

TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("[ERROR] 找不到 DISCORD_TOKEN，請在 Render 環境變數中設定。")

# ====== Discord Bot ======
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ====== Flask ======
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ====== JSON 儲存 ======
REVIEW_CHANNEL_FILE = "review_channel.json"
DATA_FILE = "keywords.json"

review_channels = {}
if os.path.exists(REVIEW_CHANNEL_FILE):
    try:
        with open(REVIEW_CHANNEL_FILE, "r", encoding="utf-8") as f:
            review_channels = json.load(f)
    except Exception:
        traceback.print_exc()

def save_review_channel(guild_id, channel_id):
    review_channels[str(guild_id)] = channel_id
    try:
        with open(REVIEW_CHANNEL_FILE, "w", encoding="utf-8") as f:
            json.dump(review_channels, f, ensure_ascii=False, indent=2)
    except Exception:
        traceback.print_exc()

keywords = {}
if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            keywords = json.load(f)
    except Exception:
        traceback.print_exc()

def save_keywords():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(keywords, f, ensure_ascii=False, indent=4)
    except Exception:
        traceback.print_exc()

# ====== Bot 事件 ======
TEST_GUILD_ID = int(os.environ.get("TEST_GUILD_ID", 0))

@bot.event
async def on_ready():
    try:
        if TEST_GUILD_ID:
            guild = discord.Object(id=TEST_GUILD_ID)
            await bot.tree.sync(guild=guild)
            print(f"[INFO] 已登入 {bot.user}，指令同步到測試伺服器 {TEST_GUILD_ID}")
        else:
            await bot.tree.sync()
            print(f"[INFO] 已登入 {bot.user}，全域指令同步完成")
        await bot.change_presence(activity=discord.Game(name="泡芙商城營業中"))
    except Exception:
        traceback.print_exc()

# ====== 關鍵字系統 ======
class KeywordModal(ui.Modal, title="新增或修改關鍵字"):
    def __init__(self, key_to_edit=None):
        super().__init__()
        self.key_to_edit = key_to_edit
        self.keyword_input = ui.TextInput(
            label="關鍵字", 
            placeholder="輸入關鍵字...", 
            default=key_to_edit or ""
        )
        self.reply_input = ui.TextInput(
            label="回覆內容", 
            style=discord.TextStyle.paragraph, 
            placeholder="輸入回覆訊息..."
        )
        self.add_item(self.keyword_input)
        self.add_item(self.reply_input)

    async def on_submit(self, interaction: Interaction):
        guild_id = str(interaction.guild_id)
        if guild_id not in keywords:
            keywords[guild_id] = {}

        key = self.keyword_input.value.strip()
        reply = self.reply_input.value.strip()

        if not key or not reply:
            await interaction.response.send_message("❌ 關鍵字或回覆不能為空", ephemeral=True)
            return

        # 若是修改舊的關鍵字名稱
        if self.key_to_edit and self.key_to_edit != key:
            keywords[guild_id].pop(self.key_to_edit, None)

        keywords[guild_id][key] = reply
        save_keywords()
        await interaction.response.send_message(
            f"✅ 已儲存關鍵字 `{key}` 對應回覆 `{reply}`", ephemeral=True
        )

# ====== 按鈕類別 ======
class DeleteOrEditButton(ui.Button):
    def __init__(self, guild_id, key):
        label = key if len(str(key)) <= 80 else str(key)[:77] + "..."
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.guild_id = guild_id
        self.key = key

    async def callback(self, interaction: Interaction):
        view = ui.View(timeout=None)

        # 修改按鈕
        class EditButton(ui.Button):
            def __init__(self, parent):
                super().__init__(label="修改", style=discord.ButtonStyle.success)
                self.parent = parent

            async def callback(self, inner_interaction: Interaction):
                await inner_interaction.response.send_modal(
                    KeywordModal(key_to_edit=self.parent.key)
                )

        # 刪除按鈕
        class DeleteButton(ui.Button):
            def __init__(self, parent):
                super().__init__(label="刪除", style=discord.ButtonStyle.danger)
                self.parent = parent

            async def callback(self, inner_interaction: Interaction):
                guild_id = self.parent.guild_id
                key = self.parent.key
                if guild_id in keywords:
                    keywords[guild_id].pop(key, None)
                    save_keywords()
                await inner_interaction.response.send_message(
                    f"🗑️ 已刪除關鍵字 `{key}`", ephemeral=True
                )

        view.add_item(EditButton(self))
        view.add_item(DeleteButton(self))

        await interaction.response.send_message(
            f"管理關鍵字 `{self.key}`", view=view, ephemeral=True
        )

# ====== 關鍵字面板 ======
class KeywordView(ui.View):
    def __init__(self, guild_id: str):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        for key in keywords.get(guild_id, {}):
            self.add_item(DeleteOrEditButton(guild_id, key))

    @ui.button(label="新增關鍵字", style=discord.ButtonStyle.primary)
    async def add_keyword(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_modal(KeywordModal())

# ====== 指令 ======
@bot.tree.command(name="keywords", description="開啟關鍵字管理面板")
async def keywords_command(interaction: Interaction):
    guild_id = str(interaction.guild_id)
    view = KeywordView(guild_id)
    await interaction.response.send_message(
        f"🔧 關鍵字管理面板（伺服器：{interaction.guild.name}）", 
        view=view, 
        ephemeral=True
    )

# ====== 關鍵字觸發 ======
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    guild_id = str(message.guild.id)
    for key, reply in keywords.get(guild_id, {}).items():
        if key in message.content:
            await message.channel.send(reply)
            break

    await bot.process_commands(message)

# ====== 啟動 ======
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.run(TOKEN)
