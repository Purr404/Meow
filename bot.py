import discord
from discord.ext import commands
import requests
import os
from dotenv import load_dotenv
import asyncio
import sqlite3
from datetime import datetime
from googletrans import Translator as GoogleTranslator
import re

load_dotenv()

# ========== CONFIGURATION ==========
SOURCE_LANGUAGE = "en"
MAX_TEXT_LENGTH = 1000
MIN_TEXT_LENGTH = 3
COOLDOWN_SECONDS = 30

# Language mapping
LANGUAGES = {
    'en': {'name': 'English', 'flag': '🇺🇸'},
    'es': {'name': 'Spanish', 'flag': '🇪🇸'},
    'fr': {'name': 'French', 'flag': '🇫🇷'},
    'de': {'name': 'German', 'flag': '🇩🇪'},
    'it': {'name': 'Italian', 'flag': '🇮🇹'},
    'pt': {'name': 'Portuguese', 'flag': '🇵🇹'},
    'ru': {'name': 'Russian', 'flag': '🇷🇺'},
    'ja': {'name': 'Japanese', 'flag': '🇯🇵'},
    'ko': {'name': 'Korean', 'flag': '🇰🇷'},
    'zh': {'name': 'Chinese', 'flag': '🇨🇳'},
    'ar': {'name': 'Arabic', 'flag': '🇸🇦'},
    'hi': {'name': 'Hindi', 'flag': '🇮🇳'},
    'vi': {'name': 'Vietnamese', 'flag': '🇻🇳'},
    'th': {'name': 'Thai', 'flag': '🇹🇭'},
    'id': {'name': 'Indonesian', 'flag': '🇮🇩'},
    'tr': {'name': 'Turkish', 'flag': '🇹🇷'},
    'pl': {'name': 'Polish', 'flag': '🇵🇱'},
    'nl': {'name': 'Dutch', 'flag': '🇳🇱'},
    'sv': {'name': 'Swedish', 'flag': '🇸🇪'},
    'da': {'name': 'Danish', 'flag': '🇩🇰'},
    'fi': {'name': 'Finnish', 'flag': '🇫🇮'},
    'no': {'name': 'Norwegian', 'flag': '🇳🇴'},
}

# ========== TRANSLATOR ==========
class SelectiveTranslator:
    def __init__(self):
        self.google_translator = GoogleTranslator()
        self.user_cooldowns = {}
        self.setup_database()
        print("✅ Translator initialized with Google Translate")

    def setup_database(self):
        """Setup SQLite database"""
        conn = sqlite3.connect('selective_translations.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id INTEGER PRIMARY KEY,
                language_code TEXT DEFAULT 'en'
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channel_settings (
                channel_id INTEGER PRIMARY KEY,
                enabled BOOLEAN DEFAULT 0
            )
        ''')
        
        conn.commit()
        conn.close()
        print("✅ Database initialized")

    def translate_text(self, text, target_lang, source_lang="auto"):
        """Translate using Google Translate"""
        try:
            print(f"🌐 Translating: '{text[:50]}...' → {target_lang}")
            result = self.google_translator.translate(text, dest=target_lang, src=source_lang)
            print(f"🌐 Translation success: '{result.text[:50]}...'")
            return result.text
        except Exception as e:
            print(f"❌ Google Translate error: {e}")
            return None

    def detect_language(self, text):
        """Simple language detection"""
        if len(text) < MIN_TEXT_LENGTH:
            return 'en'
        
        # Simple English detection
        english_words = ['the', 'and', 'you', 'that', 'have', 'for', 'with', 'this']
        text_lower = text.lower()
        
        for word in english_words:
            if f' {word} ' in f' {text_lower} ':
                return 'en'
        
        return 'en'  # Default to English

    def get_user_language(self, user_id):
        """Get user's preferred language"""
        conn = sqlite3.connect('selective_translations.db')
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT language_code FROM user_preferences WHERE user_id = ?",
            (user_id,)
        )
        result = cursor.fetchone()
        conn.close()
        
        return result[0] if result else 'en'

    def set_user_language(self, user_id, language_code):
        """Save user's language preference"""
        conn = sqlite3.connect('selective_translations.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO user_preferences (user_id, language_code)
            VALUES (?, ?)
        ''', (user_id, language_code))
        
        conn.commit()
        conn.close()
        print(f"📝 Set language for user {user_id}: {language_code}")

    def enable_channel(self, channel_id):
        """Enable auto-translate for a channel"""
        conn = sqlite3.connect('selective_translations.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO channel_settings (channel_id, enabled)
            VALUES (?, 1)
        ''', (channel_id,))
        
        conn.commit()
        conn.close()
        print(f"✅ Enabled auto-translate for channel {channel_id}")

    def disable_channel(self, channel_id):
        """Disable auto-translate for a channel"""
        conn = sqlite3.connect('selective_translations.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO channel_settings (channel_id, enabled)
            VALUES (?, 0)
        ''', (channel_id,))
        
        conn.commit()
        conn.close()
        print(f"❌ Disabled auto-translate for channel {channel_id}")

    def is_channel_enabled(self, channel_id):
        """Check if auto-translate is enabled for channel"""
        conn = sqlite3.connect('selective_translations.db')
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT enabled FROM channel_settings WHERE channel_id = ?",
            (channel_id,)
        )
        result = cursor.fetchone()
        conn.close()
        
        return bool(result[0]) if result else False

    def get_enabled_channels(self):
        """Get all enabled channel IDs"""
        conn = sqlite3.connect('selective_translations.db')
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT channel_id FROM channel_settings WHERE enabled = 1"
        )
        results = cursor.fetchall()
        conn.close()
        
        return [row[0] for row in results]

    def check_cooldown(self, user_id):
        """Check user cooldown"""
        now = datetime.now()
        last_time = self.user_cooldowns.get(user_id)
        
        if last_time and (now - last_time).seconds < COOLDOWN_SECONDS:
            return False
        
        self.user_cooldowns[user_id] = now
        return True

# ========== BOT SETUP ==========
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
translator = SelectiveTranslator()

# ========== EVENT HANDLERS ==========
@bot.event
async def on_ready():
    print(f'✅ {bot.user} is online!')
    enabled_channels = translator.get_enabled_channels()
    print(f'🌍 Auto-translate ready for {len(enabled_channels)} channels')
    
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="!help for commands"
    ))

@bot.event
async def on_message(message):
    # Process commands
    await bot.process_commands(message)
    
    # Ignore bots
    if message.author.bot:
        return
    
    # Check if auto-translate is enabled for this channel
    if not translator.is_channel_enabled(message.channel.id):
        return
    
    print(f"📨 Message in #{message.channel.name}")
    
    # Check cooldown
    if not translator.check_cooldown(message.author.id):
        return
    
    # Skip short messages
    if len(message.content.strip()) < MIN_TEXT_LENGTH:
        return
    
    # Detect language of message
    detected_lang = translator.detect_language(message.content)
    print(f"🔍 Detected language: {detected_lang}")
    
    # Only translate if message is in source language
    if detected_lang != SOURCE_LANGUAGE:
        print(f"⚠️ Not translating - message is in {detected_lang}, not {SOURCE_LANGUAGE}")
        return
    
    print(f"✅ Message is in {SOURCE_LANGUAGE}, proceeding with translation...")
    
    # Get all members who can see this channel
    try:
        members = []
        if isinstance(message.channel, discord.TextChannel):
            members = [member for member in message.channel.members if not member.bot]
        else:
            return
        
        print(f"👥 Found {len(members)} members in channel")
        
        # Collect users who need translation
        user_languages = {}
        for member in members:
            user_lang = translator.get_user_language(member.id)
            print(f"   👤 {member.display_name}: {user_lang}")
            
            # Only add if user's language is different from source
            if user_lang != SOURCE_LANGUAGE:
                user_languages[member.id] = user_lang
        
        print(f"🎯 Translating for {len(user_languages)} users: {user_languages}")
        
        if not user_languages:
            print("❌ No users need translation")
            return
        
        # Create thread for translations
        await create_translation_thread(message, user_languages)
        
    except Exception as e:
        print(f"❌ Error in on_message: {e}")

async def create_translation_thread(message, user_languages):
    """Create a thread with translations for each user"""
    try:
        # Create a public thread
        thread = await message.create_thread(
            name=f"Translations for {message.author.display_name}",
            auto_archive_duration=60
        )
        print(f"🧵 Created thread: {thread.name}")
        
        # Send original message in thread
        await thread.send(
            f"**Original message by {message.author.mention}:**\n"
            f"{message.content}"
        )
        
        # Send translations for each user
        translation_count = 0
        for user_id, lang_code in user_languages.items():
            if translation_count >= 5:
                break
            
            user = await bot.fetch_user(user_id)
            lang_info = LANGUAGES.get(lang_code, {'name': lang_code.upper(), 'flag': '🌐'})
            
            # Translate for this user
            translated = translator.translate_text(message.content, lang_code, SOURCE_LANGUAGE)
            
            if translated:
                # Check if this is the message author
                if user_id == message.author.id:
                    # For author, don't mention them
                    await thread.send(
                        f"{lang_info['flag']} **{lang_info['name']} Translation:**\n"
                        f"{translated}"
                    )
                else:
                    # For other users, mention them
                    await thread.send(
                        f"{lang_info['flag']} **For {user.mention} ({lang_info['name']}):**\n"
                        f"{translated}"
                    )
                translation_count += 1
                print(f"   ✅ Sent {lang_code} translation")
        
        if translation_count > 0:
            await thread.send(
                f"\n🔧 *Set your language with `!mylang [code]`*"
            )
        else:
            await thread.send("❌ No translations were generated.")
            await thread.delete(delay=10)
            
    except discord.Forbidden:
        print("❌ Bot doesn't have permission to create threads!")
        await message.channel.send(
            "⚠️ **Missing Permissions!**\n"
            "I need **'Manage Threads'** and **'Create Public Threads'** permissions."
        )
    except Exception as e:
        print(f"❌ Error creating thread: {e}")
        await message.channel.send(f"❌ Error: {str(e)}")

# ========== COMMANDS ==========
@bot.command(name="mylang")
async def set_language(ctx, lang_code: str = None):
    """Set your preferred language"""
    if not lang_code:
        current = translator.get_user_language(ctx.author.id)
        lang_info = LANGUAGES.get(current, {'name': current.upper(), 'flag': '🌐'})
        await ctx.send(f"🌐 Your language: **{lang_info['name']}** ({current})")
        return
    
    lang_code = lang_code.lower()
    
    if lang_code not in LANGUAGES:
        await ctx.send(f"❌ Invalid language code.")
        return
    
    translator.set_user_language(ctx.author.id, lang_code)
    lang_info = LANGUAGES[lang_code]
    await ctx.send(f"✅ Language set to: **{lang_info['name']}** ({lang_code})")

@bot.command(name="auto")
@commands.has_permissions(manage_channels=True)
async def toggle_auto(ctx, action: str = None):
    """Enable/disable auto-translate"""
    if not action:
        enabled = translator.is_channel_enabled(ctx.channel.id)
        status = "✅ **ENABLED**" if enabled else "❌ **DISABLED**"
        await ctx.send(f"Auto-translate: {status}\nEnable: `!auto enable`")
        return
    
    action = action.lower()
    
    if action == 'enable':
        translator.enable_channel(ctx.channel.id)
        await ctx.send("""
✅ **AUTO-TRANSLATE ENABLED!**

**Setup:**
1. Users: `!mylang vi` (Vietnamese)
2. Users: `!mylang ko` (Korean)  
3. Send English message → Auto-translation!
""")
    
    elif action == 'disable':
        translator.disable_channel(ctx.channel.id)
        await ctx.send("❌ Auto-translate disabled")
    
    elif action == 'status':
        enabled_channels = translator.get_enabled_channels()
        if not enabled_channels:
            await ctx.send("❌ No channels enabled.")
            return
        
        channels_list = []
        for channel_id in enabled_channels:
            ch = bot.get_channel(channel_id)
            if ch:
                channels_list.append(f"• #{ch.name}")
        
        await ctx.send(f"**Enabled channels:**\n" + "\n".join(channels_list))
    
    else:
        await ctx.send("❌ Invalid action. Use: `enable`, `disable`, or `status`")

@bot.command(name="langs")
async def list_languages(ctx):
    """List all available languages"""
    all_langs = list(LANGUAGES.items())
    
    for i in range(0, len(all_langs), 15):
        page_langs = all_langs[i:i+15]
        lang_list = []
        
        for code, info in page_langs:
            lang_list.append(f"{info['flag']} `{code}` - {info['name']}")
        
        embed = discord.Embed(
            title="🌍 Available Languages" if i == 0 else "🌍 Languages (cont.)",
            description="\n".join(lang_list),
            color=discord.Color.gold()
        )
        
        if i == 0:
            embed.add_field(
                name="Usage",
                value="Set your language: `!mylang [code]`",
                inline=False
            )
        
        await ctx.send(embed=embed)

@bot.command(name="translate")
async def translate_command(ctx, target_lang: str = None, *, text: str = None):
    """Manual translation"""
    if not target_lang or not text:
        await ctx.send("**Usage:** `!translate [language] [text]`\n**Example:** `!translate vi Hello`")
        return
    
    async with ctx.typing():
        translated = translator.translate_text(text, target_lang)
        
        if translated:
            lang_info = LANGUAGES.get(target_lang, {'name': target_lang.upper(), 'flag': '🌐'})
            await ctx.send(f"{lang_info['flag']} **{lang_info['name']}:** {translated}")
        else:
            await ctx.send("❌ Translation failed.")

@bot.command(name="ping")
async def ping(ctx):
    """Check bot status"""
    latency = round(bot.latency * 1000)
    enabled_channels = translator.get_enabled_channels()
    await ctx.send(f"🏓 Pong! `{latency}ms` | Channels: `{len(enabled_channels)}`")

@bot.command(name="help")
async def help_command(ctx):
    """Show help"""
    embed = discord.Embed(
        title="🤖 Translation Bot Help",
        description="**Auto-translates English messages to each user's language**",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="🚀 Quick Start",
        value="1. Admin: `!auto enable`\n2. User: `!mylang vi`\n3. Send English message!",
        inline=False
    )
    
    embed.add_field(
        name="👤 User Commands",
        value="`!mylang [code]` - Set language\n`!translate [lang] [text]` - Manual\n`!langs` - List languages",
        inline=False
    )
    
    embed.add_field(
        name="🛠️ Admin Commands",
        value="`!auto enable` - Enable channel\n`!auto disable` - Disable\n`!auto status` - Show channels",
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name="test")
async def test_command(ctx):
    """Test auto-translate"""
    translator.enable_channel(ctx.channel.id)
    translator.set_user_language(ctx.author.id, 'vi')
    
    msg = await ctx.send("**TEST:** Hello everyone!")
    
    try:
        thread = await msg.create_thread(name="TEST", auto_archive_duration=60)
        translated = translator.translate_text("Hello everyone!", "vi")
        
        if translated:
            await thread.send(f"🇻🇳 **Vietnamese:** {translated}")
            await ctx.send(f"✅ **TEST SUCCESS!** Check thread: {thread.mention}")
        else:
            await thread.send("❌ Translation failed")
            await ctx.send("❌ Translation API issue")
            
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

# ========== RUN BOT ==========
if __name__ == "__main__":
    token = os.getenv('DISCORD_BOT_TOKEN')
    if token:
        bot.run(token)
    else:
        print("❌ ERROR: DISCORD_BOT_TOKEN not found!")