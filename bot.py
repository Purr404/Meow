import discord
from discord.ext import commands
import requests
import os
from dotenv import load_dotenv
import asyncio
import sqlite3
from datetime import datetime
from datetime import datetime, timedelta
import re

load_dotenv()

# ========== CONFIGURATION ==========
SOURCE_LANGUAGE = "en"  # Messages in this language get translated
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
        self.endpoints = [
            "https://translate.terraprint.co",
            "https://libretranslate.de",
            "https://translate.argosopentech.com"
        ]
        self.current_endpoint = 0
        self.user_cooldowns = {}
        self.setup_database()
    
    def setup_database(self):
        """Setup SQLite database for user preferences"""
        conn = sqlite3.connect('selective_translations.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id INTEGER PRIMARY KEY,
                language_code TEXT DEFAULT 'en',
                updated_at TIMESTAMP
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
    
    def get_endpoint(self):
        return self.endpoints[self.current_endpoint]
    
    def rotate_endpoint(self):
        self.current_endpoint = (self.current_endpoint + 1) % len(self.endpoints)
    
    def translate_text(self, text, target_lang, source_lang="auto"):
        """Translate text using free API"""
        if len(text) > MAX_TEXT_LENGTH:
            text = text[:MAX_TEXT_LENGTH]
        
        for _ in range(len(self.endpoints)):
            endpoint = self.get_endpoint()
            try:
                response = requests.post(
                    f"{endpoint}/translate",
                    json={
                        "q": text,
                        "source": source_lang,
                        "target": target_lang,
                        "format": "text"
                    },
                    timeout=10
                )
                
                if response.status_code == 200:
                    return response.json().get('translatedText')
                elif response.status_code == 429:
                    self.rotate_endpoint()
                    continue
            except:
                self.rotate_endpoint()
                continue
        
        return None
    
    def detect_language(self, text):
        """Simple language detection"""
        if len(text) < MIN_TEXT_LENGTH:
            return 'en'  # Default to English for short messages
        
        # Check for non-English characters
        non_english_patterns = {
            'zh': re.compile(r'[\u4e00-\u9fff]'),
            'ja': re.compile(r'[\u3040-\u309f\u30a0-\u30ff]'),
            'ko': re.compile(r'[\uac00-\ud7af]'),
            'ar': re.compile(r'[\u0600-\u06ff]'),
            'ru': re.compile(r'[\u0400-\u04ff]'),
            'th': re.compile(r'[\u0e00-\u0e7f]'),
            'vi': re.compile(r'[áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ]', re.IGNORECASE),
        }
        
        for lang, pattern in non_english_patterns.items():
            if pattern.search(text):
                return lang
        
        # Simple English detection - check for common English words
        english_words = ['the', 'and', 'you', 'that', 'have', 'for', 'with', 'this', 'are', 'but', 'not', 'what']
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
            INSERT OR REPLACE INTO user_preferences 
            (user_id, language_code, updated_at) 
            VALUES (?, ?, ?)
        ''', (user_id, language_code, datetime.now()))
        
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
intents = discord.Intents.all()  # CHANGED: Use ALL intents
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
translator = SelectiveTranslator()

# ========== EVENT HANDLERS ==========
@bot.event
async def on_ready():
    print(f'✅ {bot.user} is online!')
    
    # Load enabled channels from database
    enabled_channels = translator.get_enabled_channels()
    print(f'🌍 Auto-translate ready for {len(enabled_channels)} channels')
    
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name=f"translations in {len(enabled_channels)} channels"
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
    
    print(f"📨 Message in enabled channel #{message.channel.name}")
    
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
            if member.id == message.author.id:
                continue  # Skip original author
            
            user_lang = translator.get_user_language(member.id)
            print(f"   👤 {member.display_name}: {user_lang}")
            
            # Only add if user's language is different from source
            if user_lang != SOURCE_LANGUAGE:
                user_languages[member.id] = user_lang
        
        if not user_languages:
            print("❌ No users need translation (all users have English set)")
            return
        
        print(f"🎯 Translating for {len(user_languages)} users: {user_languages}")
        
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
            auto_archive_duration=60,
            reason="Auto-translation thread"
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
            if translation_count >= 5:  # Limit to 5 translations per thread
                break
                
            user = await bot.fetch_user(user_id)
            lang_info = LANGUAGES.get(lang_code, {'name': lang_code.upper(), 'flag': '🌐'})
            
            # Translate for this user
            translated = translator.translate_text(message.content, lang_code, SOURCE_LANGUAGE)
            
            if translated:
                # Send user-specific message
                await thread.send(
                    f"{lang_info['flag']} **For {user.mention} ({lang_info['name']}):**\n"
                    f"{translated}"
                )
                translation_count += 1
                print(f"   ✅ Sent {lang_code} translation to {user.display_name}")
        
        if translation_count > 0:
            await thread.send(
                f"\n🔧 *Set your language with `!mylang [code]` | "
                f"Thread auto-archives in 1 hour*"
            )
        else:
            await thread.send("❌ No translations were generated. Translation service might be down.")
            await thread.delete(delay=10)  # Delete empty thread
            
    except discord.Forbidden:
        print("❌ Bot doesn't have permission to create threads!")
        await message.channel.send(
            "⚠️ **Missing Permissions!**\n"
            "I need **'Manage Threads'** and **'Create Public Threads'** permissions "
            "to create translation threads."
        )
    except Exception as e:
        print(f"❌ Error creating thread: {e}")
        await message.channel.send(f"❌ Error creating translation thread: {str(e)}")

# ========== COMMANDS ==========
@bot.command(name="mylang", aliases=['lang', 'language'])
async def set_language(ctx, lang_code: str = None):
    """Set your preferred language for translations"""
    if not lang_code:
        # Show current language
        current_lang = translator.get_user_language(ctx.author.id)
        lang_info = LANGUAGES.get(current_lang, {'name': current_lang.upper(), 'flag': '🌐'})
        
        embed = discord.Embed(
            title=f"{lang_info['flag']} Your Language Settings",
            description=f"**Current language:** {lang_info['name']} ({current_lang})",
            color=discord.Color.blue()
        )
        
        # Show popular languages
        popular = [
            ('🇺🇸', 'en', 'English'),
            ('🇪🇸', 'es', 'Spanish'),
            ('🇫🇷', 'fr', 'French'),
            ('🇩🇪', 'de', 'German'),
            ('🇯🇵', 'ja', 'Japanese'),
            ('🇰🇷', 'ko', 'Korean'),
            ('🇻🇳', 'vi', 'Vietnamese'),
            ('🇨🇳', 'zh', 'Chinese'),
            ('🇷🇺', 'ru', 'Russian'),
        ]
        
        lang_list = "\n".join([f"{flag} `!mylang {code}` - {name}" for flag, code, name in popular])
        
        embed.add_field(
            name="Quick Set",
            value=lang_list,
            inline=False
        )
        
        embed.add_field(
            name="How it works",
            value=f"• Messages in **{SOURCE_LANGUAGE.upper()}** will be translated for you\n"
                  f"• Translations appear in threads\n"
                  f"• Only you see your language's translation",
            inline=False
        )
        
        await ctx.send(embed=embed)
        return
    
    lang_code = lang_code.lower()
    
    # Validate language
    if lang_code not in LANGUAGES:
        await ctx.send(f"❌ Invalid language code. Use `!langs` to see available languages.")
        return
    
    # Save preference
    translator.set_user_language(ctx.author.id, lang_code)
    lang_info = LANGUAGES[lang_code]
    
    embed = discord.Embed(
        title="✅ Language Preference Saved",
        description=f"{lang_info['flag']} Your language has been set to **{lang_info['name']}** ({lang_code})",
        color=discord.Color.green()
    )
    
    # Check if current channel is enabled
    if translator.is_channel_enabled(ctx.channel.id):
        embed.add_field(
            name="Auto-Translate Active",
            value=f"✅ English messages in this channel will be translated to {lang_info['name']} for you!",
            inline=False
        )
    else:
        embed.add_field(
            name="Note",
            value=f"ℹ️ This channel doesn't have auto-translate enabled.\n"
                  f"Ask an admin to use `!auto enable`",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name="auto", aliases=['autotranslate'])
@commands.has_permissions(manage_channels=True)
async def toggle_auto(ctx, action: str = None):
    """Enable/disable auto-translate in this channel"""
    channel = ctx.channel
    
    if action is None:
        # Show status
        enabled = translator.is_channel_enabled(channel.id)
        
        if enabled:
            embed = discord.Embed(
                title="✅ Auto-Translate Enabled",
                description=f"Auto-translate is **enabled** in {channel.mention}",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Settings",
                value=f"• Source language: **{SOURCE_LANGUAGE.upper()}**\n"
                      f"• Translation method: **Thread-based**\n"
                      f"• Users see only their language's translation",
                inline=False
            )
        else:
            embed = discord.Embed(
                title="❌ Auto-Translate Disabled",
                description=f"Auto-translate is **disabled** in {channel.mention}",
                color=discord.Color.red()
            )
        
        embed.add_field(
            name="Commands",
            value="`!auto enable` - Enable here\n"
                  "`!auto disable` - Disable here\n"
                  "`!auto status` - Show all enabled channels\n"
                  "`!auto test` - Test auto-translate",
            inline=False
        )
        
        await ctx.send(embed=embed)
        return
    
    action = action.lower()
    
    if action in ['enable', 'on', 'start']:
        translator.enable_channel(channel.id)
        
        embed = discord.Embed(
            title="✅ Auto-Translate Enabled",
            description=f"Auto-translate has been enabled in {channel.mention}",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="For Users",
            value="1. Set your language: `!mylang [code]`\n"
                  "2. English messages will auto-translate\n"
                  "3. Translations appear in threads\n"
                  "4. Each user sees ONLY their language",
            inline=False
        )
        
        embed.add_field(
            name="Required Bot Permissions",
            value="• Manage Threads\n• Create Public Threads\n• Send Messages\n• Embed Links",
            inline=False
        )
        
        await ctx.send(embed=embed)
        
    elif action in ['disable', 'off', 'stop']:
        translator.disable_channel(channel.id)
        
        embed = discord.Embed(
            title="❌ Auto-Translate Disabled",
            description=f"Auto-translate has been disabled in {channel.mention}",
            color=discord.Color.red()
        )
        
        await ctx.send(embed=embed)
        
    elif action == 'status':
        enabled_channels = translator.get_enabled_channels()
        
        if not enabled_channels:
            await ctx.send("❌ Auto-translate is not enabled in any channels.")
            return
        
        channels_list = []
        for channel_id in enabled_channels:
            ch = bot.get_channel(channel_id)
            if ch:
                channels_list.append(f"• {ch.mention} (`#{ch.name}`)")
            else:
                channels_list.append(f"• Unknown channel (`{channel_id}`)")
        
        embed = discord.Embed(
            title="📋 Auto-Translate Channels",
            description="\n".join(channels_list),
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Total: {len(enabled_channels)} channels")
        await ctx.send(embed=embed)
    
    elif action == 'test':
        """Test if auto-translate is working"""
        enabled = translator.is_channel_enabled(channel.id)
        user_lang = translator.get_user_language(ctx.author.id)
        
        embed = discord.Embed(
            title="🧪 Auto-Translate Test",
            color=discord.Color.blue()
        )
        
        embed.add_field(name="Channel Enabled", value="✅ YES" if enabled else "❌ NO", inline=True)
        embed.add_field(name="Your Language", value=user_lang.upper(), inline=True)
        embed.add_field(name="Source Language", value=SOURCE_LANGUAGE.upper(), inline=True)
        
        if enabled and user_lang != SOURCE_LANGUAGE:
            embed.add_field(
                name="Result", 
                value="✅ **READY** - English messages will translate for you!", 
                inline=False
            )
        elif not enabled:
            embed.add_field(
                name="Result", 
                value="❌ Channel not enabled. Use `!auto enable`", 
                inline=False
            )
        else:
            embed.add_field(
                name="Result", 
                value=f"⚠️ Set non-English language: `!mylang vi` (or ko, ja, etc.)", 
                inline=False
            )
        
        await ctx.send(embed=embed)
    
    else:
        await ctx.send("❌ Invalid action. Use: `enable`, `disable`, `status`, or `test`")

@bot.command(name="langs", aliases=['languages'])
async def list_languages(ctx):
    """List all available languages"""
    # Create pages
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
                value="Set your language: `!mylang [code]`\nExample: `!mylang ko` for Korean",
                inline=False
            )
        
        await ctx.send(embed=embed)

@bot.command(name="translate", aliases=['tr'])
async def translate_command(ctx, target_lang: str = None, *, text: str = None):
    """Manual translation command"""
    if not target_lang or not text:
        embed = discord.Embed(
            title="🌐 Manual Translation",
            description="**Usage:** `!translate [language] [text]`\n"
                       "**Example:** `!translate vi Hello everyone!`\n\n"
                       "**Auto-translate flow:**\n"
                       "1. Admin enables channel: `!auto enable`\n"
                       "2. User sets language: `!mylang vi`\n"
                       "3. English messages auto-translate to Vietnamese\n"
                       "4. Each user sees only their language",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)
        return
    
    async with ctx.typing():
        translated = translator.translate_text(text, target_lang)
        
        if translated:
            lang_info = LANGUAGES.get(target_lang, {'name': target_lang.upper(), 'flag': '🌐'})
            
            embed = discord.Embed(
                title=f"{lang_info['flag']} Translation to {lang_info['name']}",
                description=translated,
                color=discord.Color.green()
            )
            embed.add_field(name="Original", value=text, inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Translation failed. Please try again.")

@bot.command(name="ping")
async def ping(ctx):
    """Check bot status"""
    latency = round(bot.latency * 1000)
    enabled_channels = translator.get_enabled_channels()
    
    embed = discord.Embed(
        title="🏓 Bot Status",
        color=discord.Color.green()
    )
    embed.add_field(name="Latency", value=f"{latency}ms", inline=True)
    embed.add_field(name="Active Channels", value=str(len(enabled_channels)), inline=True)
    embed.add_field(name="Uptime", value="24/7 on Railway", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name="help")
async def help_command(ctx):
    """Show help information"""
    embed = discord.Embed(
        title="🌐 Selective Translation Bot Help",
        description="**Each user sees translations ONLY in their language!**",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="👤 User Commands",
        value="`!mylang [code]` - Set your language\n"
              "`!mylang` - Show your current language\n"
              "`!translate [lang] [text]` - Manual translation\n"
              "`!langs` - List all languages\n"
              "`!ping` - Check bot status",
        inline=False
    )
    
    embed.add_field(
        name="🛠️ Admin Commands",
        value="`!auto enable` - Enable in this channel\n"
              "`!auto disable` - Disable in this channel\n"
              "`!auto status` - Show enabled channels\n"
              "`!auto test` - Test auto-translate",
        inline=False
    )
    
    embed.add_field(
        name="🚀 Quick Setup",
        value="1. Admin: `!auto enable` (in desired channel)\n"
              "2. User: `!mylang ko` (Korean user)\n"
              "3. User: `!mylang vi` (Vietnamese user)\n"
              "4. Send English message → Thread with translations!",
        inline=False
    )
    
    embed.set_footer(text="Deployed on Railway | Free translation service")
    await ctx.send(embed=embed)


# DEBUG ----------

@bot.command(name="debugmsg")
async def debug_message(ctx, *, text: str = None):
    """Debug why auto-translate isn't working"""
    if not text:
        text = "Hello everyone!"
    
    print(f"\n" + "="*50)
    print(f"🔍 DEBUG MESSAGE TRIGGERED")
    print(f"="*50)
    
    # Check channel
    channel_enabled = translator.is_channel_enabled(ctx.channel.id)
    print(f"📌 Channel {ctx.channel.id} enabled: {channel_enabled}")
    
    # Check your language
    your_lang = translator.get_user_language(ctx.author.id)
    print(f"👤 Your language: {your_lang}")
    
    # Detect message language
    detected = translator.detect_language(text)
    print(f"🔍 Detected language: {detected}")
    
    # Check cooldown
    cooldown_ok = translator.check_cooldown(ctx.author.id)
    print(f"⏰ Cooldown check: {cooldown_ok}")
    
    # Simulate what on_message does
    if not channel_enabled:
        await ctx.send("❌ Channel not enabled! Use `!auto enable`")
        return
    
    if not cooldown_ok:
        await ctx.send("⚠️ On cooldown")
        return
    
    if detected != SOURCE_LANGUAGE:
        await ctx.send(f"⚠️ Message detected as `{detected}`, not `{SOURCE_LANGUAGE}`")
        return
    
    # Check members
    members = ctx.channel.members
    print(f"👥 Members in channel: {len(members)}")
    
    user_languages = {}
    for member in members:
        if member.bot or member.id == ctx.author.id:
            continue
        
        member_lang = translator.get_user_language(member.id)
        print(f"   👤 {member.display_name}: {member_lang}")
        
        if member_lang != SOURCE_LANGUAGE:
            user_languages[member.id] = member_lang
    
    print(f"🎯 Users needing translation: {len(user_languages)}")
    print(f"🎯 User languages: {user_languages}")
    
    if not user_languages:
        await ctx.send("❌ No users need translation (all have English set or no users in channel)")
        return
    
    # Try to create thread
    try:
        print("🔄 Attempting to create thread...")
        thread = await ctx.message.create_thread(
            name=f"DEBUG Translations for {ctx.author.display_name}",
            auto_archive_duration=60
        )
        print(f"✅ Thread created: {thread.name}")
        
        # Test translation
        test_lang = list(user_languages.values())[0]
        print(f"🔄 Testing translation to {test_lang}...")
        translated = translator.translate_text(text, test_lang)
        print(f"✅ Translation result: {translated[:50]}...")
        
        if translated:
            await thread.send(f"🇺🇸 **Original:** {text}")
            await thread.send(f"🌐 **Test translation ({test_lang}):** {translated}")
            await thread.send("✅ **DEBUG:** Auto-translate logic is working!")
            await ctx.send(f"✅ Debug complete! Check thread: {thread.mention}")
        else:
            await thread.send("❌ Translation failed - API might be down")
            await ctx.send("❌ Translation failed")
            
    except Exception as e:
        print(f"❌ Thread creation error: {e}")
        await ctx.send(f"❌ Thread creation failed: {str(e)}")
    
    print("="*50 + "\n")

@bot.command(name="fix")
async def fix_all(ctx):
    """Fix common issues"""
    # Enable channel
    translator.enable_channel(ctx.channel.id)
    
    # Set your language to Vietnamese
    translator.set_user_language(ctx.author.id, "vi")
    
    embed = discord.Embed(
        title="🔧 Auto-Fix Applied",
        color=discord.Color.green()
    )
    embed.add_field(name="Channel", value="✅ Enabled for auto-translate", inline=False)
    embed.add_field(name="Your Language", value="✅ Set to Vietnamese (vi)", inline=False)
    embed.add_field(name="Next Step", value="Send `!debugmsg Hello` to test", inline=False)
    
    await ctx.send(embed=embed)

#END DEBUG--------

# ========== RUN BOT ==========
if __name__ == "__main__":
    token = os.getenv('DISCORD_BOT_TOKEN')
    if token:
        bot.run(token)
    else:
        print("❌ ERROR: DISCORD_BOT_TOKEN not found!")
        print("Add it to Railway Variables")