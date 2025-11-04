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

# ====== 評價系統 ======
class ReviewModal(discord.ui.Modal, title="提交評價"):
    def __init__(self, target_user: discord.User, messages_to_delete: list):
        super().__init__()
        self.target_user = target_user
        self.messages_to_delete = messages_to_delete

        self.product = ui.TextInput(label="購買商品名稱", placeholder="請輸入商品名稱", max_length=50)
        self.rating = ui.TextInput(label="評分（1-5）", placeholder="請輸入 1 到 5", max_length=1)
        self.feedback = ui.TextInput(label="評語", style=discord.TextStyle.paragraph, placeholder="寫點評語吧...", max_length=200)
        self.add_item(self.product)
        self.add_item(self.rating)
        self.add_item(self.feedback)

    async def on_submit(self, interaction: Interaction):
        if interaction.user.id != self.target_user.id:
            await interaction.response.send_message("❌ 你不是評價對象，無法提交。", ephemeral=True)
            return
        try:
            guild_id = str(interaction.guild.id)
            channel_id = review_channels.get(guild_id)
            if not channel_id:
                await interaction.response.send_message("❌ 尚未設定評價頻道。", ephemeral=True)
                return

            channel = bot.get_channel(channel_id)
            if not channel:
                await interaction.response.send_message("❌ 找不到評價頻道。", ephemeral=True)
                return

            try:
                rating_val = int(self.rating.value.strip())
            except ValueError:
                await interaction.response.send_message("❌ 評分格式錯誤，請輸入 1 到 5 的整數。", ephemeral=True)
                return
            if rating_val < 1 or rating_val > 5:
                await interaction.response.send_message("❌ 評分需為 1 到 5。", ephemeral=True)
                return

            stars = "⭐" * rating_val + "☆" * (5 - rating_val)
            now = datetime.datetime.now(timezone(timedelta(hours=8)))

            embed = discord.Embed(
                title=f"📝 新的商品評價 - {self.product.value}",
                description=f"來自：{interaction.user.mention}",
                color=discord.Color.blurple(),
                timestamp=now
            )
            embed.add_field(name="商品", value=self.product.value, inline=False)
            embed.add_field(name="評分", value=f"{stars} (`{rating_val}/5`)", inline=False)
            embed.add_field(name="評價內容", value=self.feedback.value or "（使用者未留下內容）", inline=False)
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            embed.set_footer(text="感謝您的回饋！")

            await channel.send(embed=embed)
            await interaction.response.send_message(f"✅ 你的評價已提交到 {channel.mention}", ephemeral=True)

            for msg in self.messages_to_delete:
                try: await msg.delete()
                except: pass

        except Exception:
            traceback.print_exc()
            await interaction.response.send_message("❌ 評價提交失敗，請稍後再試。", ephemeral=True)

class ReviewButton(ui.View):
    def __init__(self, target_user: discord.User, messages_to_delete: list):
        super().__init__(timeout=None)
        self.target_user = target_user
        self.messages_to_delete = messages_to_delete

    @ui.button(label="填寫評價", style=discord.ButtonStyle.success)
    async def leave_review(self, interaction: Interaction, button: ui.Button):
        if interaction.user.id != self.target_user.id:
            await interaction.response.send_message("❌ 你不是評價對象，無法填寫。", ephemeral=True)
            return
        await interaction.response.send_modal(ReviewModal(self.target_user, self.messages_to_delete))

@bot.tree.command(name="setreviewchannel", description="設定評價發送頻道（管理員限定）")
@app_commands.checks.has_permissions(administrator=True)
async def setreviewchannel(interaction: Interaction, channel: discord.TextChannel):
    try:
        save_review_channel(interaction.guild.id, channel.id)
        embed = discord.Embed(
            title="✅ 設定成功",
            description=f"已設定評價頻道為 {channel.mention}",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(timezone(timedelta(hours=8)))
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text="請確保機器人有頻道發言權限")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception:
        traceback.print_exc()
        await interaction.response.send_message("❌ 設定頻道失敗，請稍後再試。", ephemeral=True)

@bot.tree.command(name="reviews", description="叫出評價介面（選擇一個人來填寫）")
@app_commands.describe(user="選擇要被評價的使用者")
async def reviews(interaction: Interaction, user: discord.User):
    messages_to_delete = []
    msg1 = await interaction.channel.send(f"{user.mention} 麻煩點擊下方按鈕來填寫評價~")
    messages_to_delete.append(msg1)

    view = ReviewButton(target_user=user, messages_to_delete=messages_to_delete)
    embed = discord.Embed(
        title="📝 評價系統",
        description=f"只有 {user.mention} 可以點擊下方按鈕來填寫評價。",
        color=discord.Color.purple(),
        timestamp=datetime.datetime.now(timezone(timedelta(hours=8)))
    )
    msg2 = await interaction.channel.send(embed=embed, view=view)
    messages_to_delete.append(msg2)
    await interaction.response.send_message("✅ 已送出評價介面。", ephemeral=True)

# ====== 關鍵字系統 ======
class KeywordModal(ui.Modal, title="新增或修改關鍵字"):
    def __init__(self, key_to_edit=None):
        super().__init__()
        self.key_to_edit = key_to_edit
        self.keyword_input = ui.TextInput(label="關鍵字", placeholder="輸入關鍵字...", default=key_to_edit or "")
        self.reply_input = ui.TextInput(label="回覆內容", style=discord.TextStyle.paragraph, placeholder="輸入回覆訊息...")
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
        if self.key_to_edit and self.key_to_edit != key:
            keywords[guild_id].pop(self.key_to_edit, None)
        keywords[guild_id][key] = reply
        save_keywords()
        await interaction.response.send_message(f"✅ 已儲存關鍵字 `{key}` 對應回覆 `{reply}`", ephemeral=True)

class DeleteOrEditButton(ui.Button):
    def __init__(self, guild_id, key):
        label = key if len(str(key)) <= 80 else str(key)[:77] + "..."
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.guild_id = guild_id
        self.key = key

    async def callback(self, interaction: Interaction):
        view = ui.View(timeout=None)
        view.add_item(ui.Button(label="修改", style=discord.ButtonStyle.success, custom_id=f"edit_{self.guild_id}_{self.key}"))
        view.add_item(ui.Button(label="刪除", style=discord.ButtonStyle.danger, custom_id=f"delete_{self.guild_id}_{self.key}"))
        await interaction.response.send_message(f"管理關鍵字 `{self.key}`", view=view, ephemeral=True)

class KeywordView(ui.View):
    def __init__(self, guild_id: str):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        for key in keywords.get(guild_id, {}):
            self.add_item(DeleteOrEditButton(guild_id, key))

    @ui.button(label="新增關鍵字", style=discord.ButtonStyle.primary)
    async def add_keyword(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_modal(KeywordModal())

@bot.event
async def on_interaction(interaction: Interaction):
    try:
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = interaction.data.get("custom_id", "")
        if custom_id.startswith("edit_"):
            _, guild_id, key = custom_id.split("_", 2)
            await interaction.response.send_modal(KeywordModal(key_to_edit=key))
        elif custom_id.startswith("delete_"):
            _, guild_id, key = custom_id.split("_", 2)
            if guild_id in keywords:
                keywords[guild_id].pop(key, None)
                save_keywords()
            await interaction.response.send_message(f"🗑️ 已刪除關鍵字 `{key}`", ephemeral=True)
    except Exception:
        traceback.print_exc()

@bot.tree.command(name="keywords", description="開啟關鍵字管理面板")
async def keywords_command(interaction: Interaction):
    guild_id = str(interaction.guild_id)
    view = KeywordView(guild_id)
    await interaction.response.send_message(f"🔧 關鍵字管理面板（伺服器：{interaction.guild.name}）", view=view, ephemeral=True)

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

# ====== 訂單系統 ======
class OrderModal(ui.Modal, title="🛒 填寫表單"):
    product = ui.TextInput(label="所需商品")
    account = ui.TextInput(label="帳號")
    password = ui.TextInput(label="密碼", style=discord.TextStyle.short)
    backup_codes = ui.TextInput(label="備用碼(逗號分隔)", style=discord.TextStyle.paragraph)

    def __init__(self, user: discord.User, channel: discord.TextChannel):
        super().__init__()
        self.target_user = user
        self.target_channel = channel
        self.add_item(self.product)
        self.add_item(self.account)
        self.add_item(self.password)
        self.add_item(self.backup_codes)

    async def on_submit(self, interaction: Interaction):
        codes = [c.strip() for c in self.backup_codes.value.split(",") if c.strip()]
        formatted_codes = "\n".join([f"🔹 {c}" for c in codes])
        embed = discord.Embed(title="新訂單提交", color=discord.Color.blue())
        embed.add_field(name="所需商品", value=self.product.value, inline=False)
        embed.add_field(name="帳號", value=self.account.value, inline=False)
        embed.add_field(name="密碼", value=self.password.value, inline=False)
        embed.add_field(name="備用碼", value=formatted_codes or "無", inline=False)
        await self.target_channel.send(embed=embed)
        await interaction.response.send_message("✅ 表單已提交！", ephemeral=True)
        try:
            if interaction.message:
                await interaction.message.delete()
        except:
            pass

class OrderButton(ui.View):
    def __init__(self, user: discord.User):
        super().__init__(timeout=None)
        self.user = user

    @ui.button(label="📝 填寫訂單", style=discord.ButtonStyle.primary)
    async def fill_order(self, interaction: Interaction, button: ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是給你的表單喔！", ephemeral=True)
            return
        await interaction.response.send_modal(OrderModal(user=self.user, channel=interaction.channel))

@bot.tree.command(name="開啟訂單", description="建立一個填寫訂單的表單介面")
@app_commands.describe(user="選擇可以填寫此訂單的用戶")
async def open_order(interaction: Interaction, user: discord.User):
    view = OrderButton(user)
    embed = discord.Embed(title="🛒 訂單表單", description=f"{user.mention} 請點擊下方按鈕填寫訂單", color=discord.Color.green())
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# ====== 啟動 ======
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.run(TOKEN)
