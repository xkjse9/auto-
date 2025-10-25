import discord
from discord.ext import commands
from discord import app_commands, ui, Interaction
import json
import os
from flask import Flask
import threading

# ---------- Discord Bot ----------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- JSON 儲存檔 ----------
DATA_FILE = "keywords.json"
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        keywords = json.load(f)
else:
    keywords = {}

def save_keywords():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(keywords, f, ensure_ascii=False, indent=4)

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
        await interaction.response.send_message(f"已儲存關鍵字 `{key}` 對應回覆 `{reply}`", ephemeral=True)

# ---------- 按鈕面板 ----------
class KeywordView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for key in keywords:
            self.add_item(DeleteOrEditButton(key))

    @ui.button(label="新增關鍵字", style=discord.ButtonStyle.primary)
    async def add_keyword(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_modal(KeywordModal())

class DeleteOrEditButton(ui.Button):
    def __init__(self, key):
        super().__init__(label=key, style=discord.ButtonStyle.secondary)
        self.key = key

    async def callback(self, interaction: Interaction):
        options_view = ui.View(timeout=None)
        options_view.add_item(ui.Button(label="修改", style=discord.ButtonStyle.success, custom_id=f"edit_{self.key}"))
        options_view.add_item(ui.Button(label="刪除", style=discord.ButtonStyle.danger, custom_id=f"delete_{self.key}"))
        await interaction.response.send_message(f"管理關鍵字 `{self.key}`", view=options_view, ephemeral=True)

@bot.event
async def on_interaction(interaction: Interaction):
    if interaction.type != discord.InteractionType.component:
        return
    custom_id = interaction.data.get("custom_id", "")
    if custom_id.startswith("edit_"):
        key = custom_id[5:]
        await interaction.response.send_modal(KeywordModal(key_to_edit=key))
    elif custom_id.startswith("delete_"):
        key = custom_id[7:]
        keywords.pop(key, None)
        save_keywords()
        await interaction.response.send_message(f"已刪除關鍵字 `{key}`", ephemeral=True)

# ---------- 斜線指令 ----------
@bot.tree.command(name="keywords", description="開啟關鍵字管理面板")
async def keywords_command(interaction: Interaction):
    view = KeywordView()
    await interaction.response.send_message("關鍵字管理面板", view=view, ephemeral=True)

# ---------- 偵測訊息 ----------
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    for key, reply in keywords.items():
        if key in message.content:
            await message.channel.send(reply)
            break
    await bot.process_commands(message)

@bot.event
async def on_ready():
    print(f"{bot.user} 上線了")
    await bot.tree.sync()

# ---------- Flask Web 伺服器 ----------
app = Flask("")

@app.route("/")
def home():
    return "Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web).start()

# ---------- 從環境變數讀 Token ----------
TOKEN = os.environ["DISCORD_TOKEN"]
bot.run(TOKEN)


