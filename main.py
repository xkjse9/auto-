import os
TOKEN = os.environ.get("DISCORD_TOKEN")
print("DEBUG TOKEN:", repr(TOKEN))
if not TOKEN:
    print("❌ Token 沒讀到！")
else:
    print("✅ Token 已讀到")
