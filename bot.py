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
import logging
from contextlib import closing
import hashlib
from functools import lru_cache
import shutil
import yaml
import json

load_dotenv()

# ========== ENVIRONMENT VALIDATION ==========
def validate_environment():
    """Validate all required environment variables"""
    required_vars = ['DISCORD_BOT_TOKEN']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        raise ValueError(f"Missing environment variables: {', '.join(missing_vars)}")
    
    # Validate token format
    token = os.getenv('DISCORD_BOT_TOKEN')
    if token and (not token.startswith('MT') or len(token) < 50):
        print("⚠️ Warning: Token format looks incorrect")
    
    return True

# ========== LOGGING SETUP ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('translator_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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

# ========== UTILITY FUNCTIONS ==========
def sanitize_text(text: str, max_length: int = 2000) -> str:
    """Sanitize text for Discord"""
    if not text:
        return ""
    
    # Remove excessive mentions
    text = re.sub(r'<@!?\d+>', '[USER]', text)
    # Remove excessive emojis
    text = re.sub(r'<:\w+:\d+>', '[EMOJI]', text)
    # Limit length
    if len(text) > max_length:
        text = text[:max_length-3] + '...'
    return text

# ========== TRANSLATOR ==========
class SelectiveTranslator:
    def __init__(self):
        self.google_translator = GoogleTranslator()
        self.user_cooldowns = {}
        self.translation_cache = {}
        self.db_path = 'selective_translations.db'
        self._init_db()
        logger.info("✅ Translator initialized with Google Translate")

    def _init_db(self):
        """Initialize database with better structure"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id INTEGER PRIMARY KEY,
                    language_code TEXT DEFAULT 'en',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channel_settings (
                    channel_id INTEGER PRIMARY KEY,
                    enabled BOOLEAN DEFAULT 0,
                    guild_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Add cache table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS translation_cache (
                    cache_key TEXT PRIMARY KEY,
                    original_text TEXT,
                    translated_text TEXT,
                    target_lang TEXT,
                    source_lang TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Add index for faster queries
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_guild_channels ON channel_settings(guild_id)')
            
            conn.commit()
        logger.info("✅ Database initialized with optimized structure")

    def get_connection(self):
        """Get database connection with context manager"""
        return closing(sqlite3.connect(self.db_path, check_same_thread=False))

    def translate_text(self, text, target_lang, source_lang="auto"):
        """Translate using Google Translate with caching"""
        try:
            # Check cache first
            cache_key = self._get_cache_key(text, target_lang, source_lang)
            cached = self._get_cached_translation(cache_key)
            
            if cached:
                logger.info(f"♻️ Using cached translation for: '{text[:50]}...' → {target_lang}")
                return cached
            
            logger.info(f"🌐 Translating: '{text[:50]}...' → {target_lang}")
            result = self.google_translator.translate(text, dest=target_lang, src=source_lang)
            
            if result and result.text:
                # Cache the result
                self._cache_translation(cache_key, text, result.text, target_lang, source_lang)
                logger.info(f"🌐 Translation success: '{result.text[:50]}...'")
                return result.text
            return None
        except Exception as e:
            logger.error(f"❌ Google Translate error: {e}")
            return None

    def _get_cache_key(self, text, target_lang, source_lang):
        """Generate cache key"""
        return hashlib.md5(f"{text}:{target_lang}:{source_lang}".encode()).hexdigest()

    def _get_cached_translation(self, cache_key):
        """Get translation from cache"""
        # Check memory cache first
        if cache_key in self.translation_cache:
            return self.translation_cache[cache_key]
        
        # Check database cache
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT translated_text FROM translation_cache WHERE cache_key = ? AND created_at > datetime('now', '-1 day')",
                    (cache_key,)
                )
                result = cursor.fetchone()
                if result:
                    self.translation_cache[cache_key] = result[0]
                    return result[0]
        except Exception as e:
            logger.error(f"Cache retrieval error: {e}")
        
        return None

    def _cache_translation(self, cache_key, original_text, translated_text, target_lang, source_lang):
        """Cache translation"""
        # Memory cache
        self.translation_cache[cache_key] = translated_text
        
        # Database cache
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO translation_cache 
                    (cache_key, original_text, translated_text, target_lang, source_lang)
                    VALUES (?, ?, ?, ?, ?)
                ''', (cache_key, original_text, translated_text, target_lang, source_lang))
                conn.commit()
        except Exception as e:
            logger.error(f"Cache storage error: {e}")

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
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT language_code FROM user_preferences WHERE user_id = ?",
                    (user_id,)
                )
                result = cursor.fetchone()
                return result[0] if result else 'en'
        except Exception as e:
            logger.error(f"Database error in get_user_language: {e}")
            return 'en'

    def set_user_language(self, user_id, language_code):
        """Save user's language preference"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO user_preferences (user_id, language_code, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                ''', (user_id, language_code))
                conn.commit()
                logger.info(f"📝 Set language for user {user_id}: {language_code}")
        except Exception as e:
            logger.error(f"Database error in set_user_language: {e}")

    def enable_channel(self, channel_id, guild_id=None):
        """Enable auto-translate for a channel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO channel_settings (channel_id, enabled, guild_id, created_at)
                    VALUES (?, 1, ?, CURRENT_TIMESTAMP)
                ''', (channel_id, guild_id))
                conn.commit()
                logger.info(f"✅ Enabled auto-translate for channel {channel_id}")
        except Exception as e:
            logger.error(f"Database error in enable_channel: {e}")

    def disable_channel(self, channel_id):
        """Disable auto-translate for a channel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO channel_settings (channel_id, enabled)
                    VALUES (?, 0)
                ''', (channel_id,))
                conn.commit()
                logger.info(f"❌ Disabled auto-translate for channel {channel_id}")
        except Exception as e:
            logger.error(f"Database error in disable_channel: {e}")

    def is_channel_enabled(self, channel_id):
        """Check if auto-translate is enabled for channel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT enabled FROM channel_settings WHERE channel_id = ?",
                    (channel_id,)
                )
                result = cursor.fetchone()
                return bool(result[0]) if result else False
        except Exception as e:
            logger.error(f"Database error in is_channel_enabled: {e}")
            return False

    def get_enabled_channels(self):
        """Get all enabled channel IDs"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT channel_id FROM channel_settings WHERE enabled = 1"
                )
                results = cursor.fetchall()
                return [row[0] for row in results]
        except Exception as e:
            logger.error(f"Database error in get_enabled_channels: {e}")
            return []

    def check_cooldown(self, user_id):
        """Check user cooldown"""
        now = datetime.now()
        last_time = self.user_cooldowns.get(user_id)

        if last_time and (now - last_time).seconds < COOLDOWN_SECONDS:
            return False

        self.user_cooldowns[user_id] = now
        return True

    def get_statistics(self):
        """Get bot statistics"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Count users
                cursor.execute("SELECT COUNT(*) FROM user_preferences")
                user_count = cursor.fetchone()[0]
                
                # Count channels
                cursor.execute("SELECT COUNT(*) FROM channel_settings WHERE enabled = 1")
                channel_count = cursor.fetchone()[0]
                
                # Language distribution
                cursor.execute("""
                    SELECT language_code, COUNT(*) as count 
                    FROM user_preferences 
                    GROUP BY language_code 
                    ORDER BY count DESC
                """)
                lang_dist = cursor.fetchall()
                
                # Cache stats
                cursor.execute("SELECT COUNT(*) FROM translation_cache")
                cache_count = cursor.fetchone()[0]
                
                return {
                    'user_count': user_count,
                    'channel_count': channel_count,
                    'lang_dist': lang_dist,
                    'cache_count': cache_count
                }
        except Exception as e:
            logger.error(f"Database error in get_statistics: {e}")
            return {}

    def backup_database(self, backup_path=None):
        """Backup database"""
        try:
            if not backup_path:
                backup_path = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            
            shutil.copy2(self.db_path, backup_path)
            logger.info(f"✅ Database backed up to {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"Backup error: {e}")
            return None

# ========== BOT SETUP ==========
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
translator = SelectiveTranslator()

# ========== EVENT HANDLERS ==========
@bot.event
async def on_ready():
    logger.info(f'✅ {bot.user} is online!')
    enabled_channels = translator.get_enabled_channels()
    logger.info(f'🌍 Auto-translate ready for {len(enabled_channels)} channels')

    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="!help for commands"
    ))

@bot.event
async def on_message(message):
    try:
        # Process commands
        await bot.process_commands(message)

        # Ignore bots
        if message.author.bot:
            return

        # Check if auto-translate is enabled for this channel
        if not translator.is_channel_enabled(message.channel.id):
            return

        logger.info(f"📨 Message in #{message.channel.name} from {message.author}")

        # Check cooldown
        if not translator.check_cooldown(message.author.id):
            return

        # Skip short messages
        if len(message.content.strip()) < MIN_TEXT_LENGTH:
            return

        # Detect language of message
        detected_lang = translator.detect_language(message.content)
        logger.info(f"🔍 Detected language: {detected_lang}")

        # Only translate if message is in source language
        if detected_lang != SOURCE_LANGUAGE:
            logger.info(f"⚠️ Not translating - message is in {detected_lang}, not {SOURCE_LANGUAGE}")
            return

        logger.info(f"✅ Message is in {SOURCE_LANGUAGE}, proceeding with translation...")

        # Get all members who can see this channel
        try:
            members = []
            if isinstance(message.channel, discord.TextChannel):
                members = [member for member in message.channel.members if not member.bot]
            else:
                return

            logger.info(f"👥 Found {len(members)} members in channel")

            # Collect users who need translation
            user_languages = {}
            for member in members:
                user_lang = translator.get_user_language(member.id)
                logger.debug(f"   👤 {member.display_name}: {user_lang}")

                # Only add if user's language is different from source
                if user_lang != SOURCE_LANGUAGE:
                    user_languages[member.id] = user_lang

            logger.info(f"🎯 Translating for {len(user_languages)} users")

            if not user_languages:
                logger.info("❌ No users need translation")
                return

            # Create thread for translations using optimized method
            await create_translation_thread_optimized(message, user_languages)

        except Exception as e:
            logger.error(f"❌ Error in on_message processing: {e}")

    except discord.errors.HTTPException as e:
        if e.status == 429:  # Rate limit
            retry_after = e.retry_after if hasattr(e, 'retry_after') else 5
            logger.warning(f"⏰ Rate limited, retrying after {retry_after}s")
            await asyncio.sleep(retry_after)
            return
        logger.error(f"Discord HTTP error: {e}")
    except Exception as e:
        logger.error(f"❌ Unexpected error in on_message: {e}")

# Original function (kept for compatibility)
async def create_translation_thread(message, user_languages):
    """Create a thread with translations for each user"""
    try:
        # Create a public thread
        thread = await message.create_thread(
            name=f"Translations for {message.author.display_name}",
            auto_archive_duration=60
        )
        logger.info(f"🧵 Created thread: {thread.name}")

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
                sanitized = sanitize_text(translated)
                # Check if this is the message author
                if user_id == message.author.id:
                    # For author, don't mention them
                    await thread.send(
                        f"{lang_info['flag']} **{lang_info['name']} Translation:**\n"
                        f"{sanitized}"
                    )
                else:
                    # For other users, mention them
                    await thread.send(
                        f"{lang_info['flag']} **For {user.mention} ({lang_info['name']}):**\n"
                        f"{sanitized}"
                    )
                translation_count += 1
                logger.info(f"   ✅ Sent {lang_code} translation")

        if translation_count > 0:
            await thread.send(
                f"\n🔧 *Set your language with `!mylang [code]`*"
            )
        else:
            await thread.send("❌ No translations were generated.")
            await thread.delete(delay=10)

    except discord.Forbidden:
        logger.error("❌ Bot doesn't have permission to create threads!")
        await message.channel.send(
            "⚠️ **Missing Permissions!**\n"
            "I need **'Manage Threads'** and **'Create Public Threads'** permissions."
        )
    except Exception as e:
        logger.error(f"❌ Error creating thread: {e}")
        await message.channel.send(f"❌ Error: {str(e)}")

# New optimized function
async def create_translation_thread_optimized(message, user_languages):
    """Optimized version of thread creation with grouped translations"""
    try:
        # Group by language to avoid duplicate translations
        language_groups = {}
        for user_id, lang_code in user_languages.items():
            if lang_code not in language_groups:
                language_groups[lang_code] = []
            language_groups[lang_code].append(user_id)
        
        # Translate once per language (not per user)
        translations = {}
        translation_tasks = []
        
        for lang_code in language_groups.keys():
            # Use asyncio.to_thread for non-blocking translation
            task = asyncio.to_thread(
                translator.translate_text, 
                message.content, 
                lang_code, 
                SOURCE_LANGUAGE
            )
            translation_tasks.append((lang_code, task))
        
        # Wait for all translations
        for lang_code, task in translation_tasks:
            try:
                translated = await task
                if translated:
                    translations[lang_code] = translated
            except Exception as e:
                logger.error(f"Translation error for {lang_code}: {e}")
        
        # Create thread if we have translations
        if translations:
            thread = await message.create_thread(
                name=f"🌍 Translations",
                auto_archive_duration=60
            )
            logger.info(f"🧵 Created optimized thread: {thread.name}")
            
            # Send original message
            await thread.send(
                f"**Original message by {message.author.mention}:**\n"
                f"{message.content}"
            )
            
            # Send grouped translations
            for lang_code, translated_text in translations.items():
                user_ids = language_groups[lang_code]
                mentions = []
                
                for user_id in user_ids:
                    if user_id != message.author.id:
                        mentions.append(f"<@{user_id}>")
                
                lang_info = LANGUAGES.get(lang_code, {'name': lang_code.upper(), 'flag': '🌐'})
                sanitized = sanitize_text(translated_text)
                
                if mentions:
                    await thread.send(f"{lang_info['flag']} **For {', '.join(mentions)} ({lang_info['name']}):**\n{sanitized}")
                else:
                    # This is for the author only
                    await thread.send(f"{lang_info['flag']} **{lang_info['name']} Translation:**\n{sanitized}")
            
            if translations:
                await thread.send(f"\n🔧 *Set your language with `!mylang [code]`*")
        else:
            logger.info("❌ No translations generated")

    except discord.Forbidden:
        logger.error("❌ Bot doesn't have permission to create threads!")
        await message.channel.send(
            "⚠️ **Missing Permissions!**\n"
            "I need **'Manage Threads'** and **'Create Public Threads'** permissions."
        )
    except Exception as e:
        logger.error(f"❌ Error creating optimized thread: {e}")
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
        translator.enable_channel(ctx.channel.id, ctx.guild.id if ctx.guild else None)
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
            sanitized = sanitize_text(translated)
            await ctx.send(f"{lang_info['flag']} **{lang_info['name']}:** {sanitized}")
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
        value="`!mylang [code]` - Set language\n`!translate [lang] [text]` - Manual\n`!langs` - List languages\n`!stats` - View statistics",
        inline=False
    )

    embed.add_field(
        name="🛠️ Admin Commands",
        value="`!auto enable` - Enable channel\n`!auto disable` - Disable\n`!auto status` - Show channels\n`!backup` - Backup database",
        inline=False
    )

    embed.add_field(
        name="📊 Utility",
        value="`!ping` - Check latency\n`!cleanup` - Clear cache\n`!stats` - View statistics",
        inline=False
    )

    await ctx.send(embed=embed)

@bot.command(name="test")
async def test_command(ctx):
    """Test auto-translate"""
    translator.enable_channel(ctx.channel.id, ctx.guild.id if ctx.guild else None)
    translator.set_user_language(ctx.author.id, 'vi')

    msg = await ctx.send("**TEST:** Hello everyone!")

    try:
        thread = await msg.create_thread(name="TEST", auto_archive_duration=60)
        translated = translator.translate_text("Hello everyone!", "vi")

        if translated:
            sanitized = sanitize_text(translated)
            await thread.send(f"🇻🇳 **Vietnamese:** {sanitized}")
            await ctx.send(f"✅ **TEST SUCCESS!** Check thread: {thread.mention}")
        else:
            await thread.send("❌ Translation failed")
            await ctx.send("❌ Translation API issue")

    except Exception as e:
        logger.error(f"Test command error: {e}")
        await ctx.send(f"❌ Error: {str(e)}")

# ========== NEW COMMANDS ==========
@bot.command(name="stats")
async def show_stats(ctx):
    """Show bot statistics"""
    async with ctx.typing():
        stats = translator.get_statistics()
        
        if not stats:
            await ctx.send("❌ Unable to retrieve statistics.")
            return
        
        embed = discord.Embed(
            title="📊 Bot Statistics",
            color=discord.Color.green()
        )
        
        embed.add_field(name="👥 Total Users", value=stats['user_count'], inline=True)
        embed.add_field(name="📺 Enabled Channels", value=stats['channel_count'], inline=True)
        embed.add_field(name="💾 Cache Entries", value=stats['cache_count'], inline=True)
        
        # Language distribution
        if stats['lang_dist']:
            lang_text = "\n".join([f"{LANGUAGES.get(code, {}).get('flag', '🌐')} `{code}`: {count}" 
                                  for code, count in stats['lang_dist'][:10]])
            embed.add_field(name="🌍 Top Languages", value=lang_text, inline=False)
        
        # Add timestamp
        embed.set_footer(text=f"Statistics as of {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        await ctx.send(embed=embed)

@bot.command(name="backup")
@commands.has_permissions(administrator=True)
async def backup_data(ctx):
    """Backup database"""
    async with ctx.typing():
        backup_path = translator.backup_database()
        
        if backup_path:
            # Try to send the backup file
            try:
                if os.path.getsize(backup_path) < 8000000:  # Discord's 8MB limit
                    await ctx.send(f"✅ Backup created!", file=discord.File(backup_path))
                else:
                    await ctx.send(f"✅ Backup created: `{backup_path}`\n⚠️ File too large to send via Discord.")
            except Exception as e:
                logger.error(f"Error sending backup file: {e}")
                await ctx.send(f"✅ Backup created: `{backup_path}`")
        else:
            await ctx.send("❌ Backup failed.")

@bot.command(name="cleanup")
@commands.has_permissions(manage_messages=True)
async def cleanup_cache(ctx):
    """Clean up translation cache"""
    async with ctx.typing():
        try:
            # Clear memory cache
            translator.translation_cache.clear()
            
            # Clear old database cache entries
            with translator.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM translation_cache WHERE created_at < datetime('now', '-7 days')")
                deleted = cursor.rowcount
                conn.commit()
            
            await ctx.send(f"✅ Cache cleaned up! Removed {deleted} old entries.")
        except Exception as e:
            logger.error(f"Cache cleanup error: {e}")
            await ctx.send("❌ Cache cleanup failed.")

@bot.command(name="debug")
@commands.has_permissions(administrator=True)
async def debug_info(ctx):
    """Show debug information"""
    embed = discord.Embed(
        title="🐛 Debug Information",
        color=discord.Color.orange()
    )
    
    # Bot info
    embed.add_field(name="Bot Latency", value=f"{round(bot.latency * 1000)}ms", inline=True)
    embed.add_field(name="Guilds", value=len(bot.guilds), inline=True)
    
    # Translation info
    enabled_channels = translator.get_enabled_channels()
    embed.add_field(name="Enabled Channels", value=len(enabled_channels), inline=True)
    
    # Memory info
    import sys
    embed.add_field(name="Python Version", value=sys.version.split()[0], inline=True)
    
    # Cache info
    embed.add_field(name="Cache Size", value=len(translator.translation_cache), inline=True)
    
    await ctx.send(embed=embed)

# ========== RUN BOT ==========
if __name__ == "__main__":
    try:
        validate_environment()
        token = os.getenv('DISCORD_BOT_TOKEN')
        if token:
            logger.info("Starting bot...")
            bot.run(token)
        else:
            logger.error("❌ ERROR: DISCORD_BOT_TOKEN not found!")
    except ValueError as e:
        logger.error(f"❌ Configuration error: {e}")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")