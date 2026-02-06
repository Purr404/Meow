import discord
from discord.ext import commands
from discord import ui, SelectOption
import os
from dotenv import load_dotenv
import asyncio
import sqlite3
from datetime import datetime
from googletrans import Translator as GoogleTranslator
import logging
from contextlib import closing
import hashlib
import psycopg2
from psycopg2.extras import DictCursor
from urllib.parse import urlparse

load_dotenv()

# ========== LOGGING SETUP ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# ========== CONFIGURATION ==========
COOLDOWN_SECONDS = 5
MAX_TRANSLATIONS_PER_MESSAGE = 5  # Limit translations to prevent spam

# Language mapping with flags
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

# ========== UI COMPONENTS ==========
class LanguageSelectView(ui.View):
    def __init__(self, user_id, translator):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.translator = translator
        
        # Create select menu options
        options = []
        for code, info in LANGUAGES.items():
            options.append(SelectOption(
                label=info['name'],
                value=code,
                emoji=info['flag'],
                description=f"Code: {code}"
            ))
        
        # Split into multiple select menus if needed (Discord limit: 25 options per menu)
        self.select_menus = []
        for i in range(0, len(options), 25):
            select = ui.Select(
                placeholder="Select your language...",
                options=options[i:i+25],
                custom_id=f"lang_select_{i}"
            )
            select.callback = self.select_callback
            self.add_item(select)
            self.select_menus.append(select)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This menu is not for you!", ephemeral=True)
            return
        
        lang_code = interaction.data['values'][0]
        lang_info = LANGUAGES.get(lang_code)
        
        # Save user preference
        self.translator.set_user_language(self.user_id, lang_code)
        
        embed = discord.Embed(
            title="✅ Language Set",
            description=f"Your language has been set to:\n{lang_info['flag']} **{lang_info['name']}** ({lang_code})",
            color=discord.Color.green()
        )
        embed.add_field(
            name="What happens now?",
            value="• Messages in other languages will be auto-translated to your language\n• Use `!translate [lang] [text]` for manual translations",
            inline=False
        )
        
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

# ========== TRANSLATOR ==========
class SelectiveTranslator:
    def __init__(self):
        self.google_translator = GoogleTranslator()
        self.user_cooldowns = {}
        self.translation_cache = {}
        self.message_cooldowns = {}  # Track message translations
        self._init_db()
        logger.info("✅ Translator initialized")

    def get_connection(self):
        """Get database connection - supports both SQLite and PostgreSQL"""
        database_url = os.environ.get('DATABASE_URL')
        
        if database_url:
            # Use PostgreSQL from Railway
            try:
                result = urlparse(database_url)
                conn = psycopg2.connect(
                    database=result.path[1:],  # Remove leading slash
                    user=result.username,
                    password=result.password,
                    host=result.hostname,
                    port=result.port,
                    sslmode='require'  # Railway requires SSL
                )
                logger.info("📊 Using PostgreSQL (Railway)")
                return conn
            except Exception as e:
                logger.error(f"❌ PostgreSQL connection error: {e}")
                logger.info("🔄 Falling back to SQLite...")
        
        # Fallback to SQLite for local development
        import sqlite3
        from contextlib import closing
        logger.info("📁 Using SQLite (local)")
        return closing(sqlite3.connect('translations.db', check_same_thread=False))

    def _init_db(self):
        """Initialize database tables"""
        try:
        conn = self.get_connection()
        
        # Check if it's PostgreSQL or SQLite
        is_postgres = hasattr(conn, 'cursor') and not hasattr(conn, '__enter__')
        
           if is_postgres:
            # PostgreSQL connection
            cursor = conn.cursor()
            
            # Check if tables exist
            cursor.execute("SELECT to_regclass('public.channel_settings')")
            table_exists = cursor.fetchone()[0]
            
            if table_exists:
                # Table exists, check and fix column type
                try:
                    cursor.execute("ALTER TABLE channel_settings ALTER COLUMN enabled TYPE BOOLEAN USING enabled::boolean")
                    conn.commit()
                    logger.info("✅ Fixed boolean column type in existing table")
                except Exception as alter_error:
                    logger.warning(f"Could not alter column: {alter_error}")
                    # Column might already be correct type
            
            # Create user_preferences table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id BIGINT PRIMARY KEY,
                    language_code TEXT DEFAULT 'en',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create channel_settings table - Use TRUE/FALSE for PostgreSQL
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channel_settings (
                    channel_id BIGINT PRIMARY KEY,
                    enabled BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create translation_cache table
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
            
            conn.commit()
            cursor.close()
            conn.close()
            logger.info("✅ PostgreSQL tables initialized")
            
        else:
            # SQLite connection (using context manager)
            with conn as sqlite_conn:
                cursor = sqlite_conn.cursor()
                
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
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
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
                
                sqlite_conn.commit()
            logger.info("✅ SQLite tables initialized")
            
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")

    def _execute_query(self, query, params=None, fetchone=False, fetchall=False):
        """Helper method to execute queries for both PostgreSQL and SQLite"""
        try:
            conn = self.get_connection()
            
            # Check if it's PostgreSQL or SQLite
            is_postgres = hasattr(conn, 'cursor') and not hasattr(conn, '__enter__')
            
            if is_postgres:
                # PostgreSQL
                cursor = conn.cursor()
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                
                result = None
                if fetchone:
                    result = cursor.fetchone()
                elif fetchall:
                    result = cursor.fetchall()
                
                if not query.strip().upper().startswith('SELECT'):
                    conn.commit()
                
                cursor.close()
                conn.close()
                return result
            else:
                # SQLite (using context manager)
                with conn as sqlite_conn:
                    cursor = sqlite_conn.cursor()
                    if params:
                        cursor.execute(query, params)
                    else:
                        cursor.execute(query)
                    
                    result = None
                    if fetchone:
                        result = cursor.fetchone()
                    elif fetchall:
                        result = cursor.fetchall()
                    
                    if not query.strip().upper().startswith('SELECT'):
                        sqlite_conn.commit()
                    
                    return result
                    
        except Exception as e:
            logger.error(f"Database query error: {e}")
            return None

    def translate_text(self, text, target_lang, source_lang="auto"):
        """Translate text using Google Translate"""
        try:
            text = text.strip()
            if not text or len(text) < 2:
                return None
            
            # Cache key
            cache_key = hashlib.md5(f"{text}:{target_lang}:{source_lang}".encode()).hexdigest()
            
            # Check cache
            if cache_key in self.translation_cache:
                return self.translation_cache[cache_key]
            
            # Check database cache
            result = self._execute_query(
                "SELECT translated_text FROM translation_cache WHERE cache_key = %s AND created_at > CURRENT_TIMESTAMP - INTERVAL '1 day'",
                (cache_key,),
                fetchone=True
            )
            
            if result and result[0]:
                self.translation_cache[cache_key] = result[0]
                return result[0]
            
            # Translate
            logger.info(f"Translating: '{text[:50]}...' ({source_lang}) → {target_lang}")
            google_result = self.google_translator.translate(text, dest=target_lang, src=source_lang)
            
            if google_result and google_result.text:
                # Cache in memory
                self.translation_cache[cache_key] = google_result.text
                
                # Cache in database
                self._execute_query(
                    '''INSERT INTO translation_cache (cache_key, original_text, translated_text, target_lang, source_lang)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (cache_key) DO UPDATE SET
                           translated_text = EXCLUDED.translated_text,
                           created_at = CURRENT_TIMESTAMP''',
                    (cache_key, text, google_result.text, target_lang, source_lang)
                )
                
                return google_result.text
            return None
        except Exception as e:
            logger.error(f"Translation error: {e}")
            return None

    def get_user_language(self, user_id):
        """Get user's preferred language"""
        result = self._execute_query(
            "SELECT language_code FROM user_preferences WHERE user_id = %s",
            (user_id,),
            fetchone=True
        )
        return result[0] if result else 'en'

    def set_user_language(self, user_id, language_code):
        """Save user's language preference"""
        self._execute_query(
            '''INSERT INTO user_preferences (user_id, language_code)
               VALUES (%s, %s)
               ON CONFLICT (user_id) DO UPDATE SET
                   language_code = EXCLUDED.language_code,
                   updated_at = CURRENT_TIMESTAMP''',
            (user_id, language_code)
        )

    def enable_channel(self, channel_id):
        """Enable auto-translate for a channel"""
        self._execute_query(
            '''INSERT INTO channel_settings (channel_id, enabled)
               VALUES (%s, TRUE)
               ON CONFLICT (channel_id) DO UPDATE SET
                   enabled = TRUE,
                   created_at = CURRENT_TIMESTAMP''',
            (channel_id,)
        )

    def disable_channel(self, channel_id):
        """Disable auto-translate for a channel"""
        self._execute_query(
            '''INSERT INTO channel_settings (channel_id, enabled)
               VALUES (%s, FALSE)
               ON CONFLICT (channel_id) DO UPDATE SET
                   enabled = FALSE''',
            (channel_id,)
        )

    def is_channel_enabled(self, channel_id):
        """Check if auto-translate is enabled for channel"""
        result = self._execute_query(
            "SELECT enabled FROM channel_settings WHERE channel_id = %s",
            (channel_id,),
            fetchone=True
        )
        return bool(result[0]) if result else False

    # Keep all other methods exactly the same
    def detect_language(self, text):
        """Detect language of text"""
        try:
            text = text.strip()
            if len(text) < 2:
                return 'en'
            
            detection = self.google_translator.detect(text)
            if detection and detection.lang:
                lang_code = detection.lang
                if '-' in lang_code:
                    lang_code = lang_code.split('-')[0]
                return lang_code
            return 'en'
        except Exception as e:
            logger.error(f"Language detection error: {e}")
            return 'en'

    def should_translate_for_user(self, message_lang, user_lang, user_id, message_author_id):
        """Determine if we should translate for a user"""
        if message_lang == user_lang:
            return False
        if user_id == message_author_id:
            return False
        if user_lang == 'en' and message_lang == 'en':
            return False
        return True

    def check_cooldown(self, user_id):
        """Check user cooldown"""
        now = datetime.now()
        last_time = self.user_cooldowns.get(user_id)

        if last_time and (now - last_time).seconds < COOLDOWN_SECONDS:
            return False

        self.user_cooldowns[user_id] = now
        return True

    def check_message_cooldown(self, message_id):
        """Check if we already translated this message recently"""
        now = datetime.now()
        last_time = self.message_cooldowns.get(message_id)
        
        old_messages = []
        for msg_id, timestamp in self.message_cooldowns.items():
            if (now - timestamp).seconds > 300:
                old_messages.append(msg_id)
        
        for msg_id in old_messages:
            self.message_cooldowns.pop(msg_id, None)
        
        if last_time and (now - last_time).seconds < 10:
            return False
        
        self.message_cooldowns[message_id] = now
        return True

# ========== BOT SETUP ==========
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
translator = SelectiveTranslator()

# ========== HELPER FUNCTIONS ==========
async def send_grouped_translations(message, language_groups):
    """Send grouped translations by language"""
    try:
        # Detect source language
        source_lang = translator.detect_language(message.content)
        source_info = LANGUAGES.get(source_lang, {'name': source_lang.upper(), 'flag': '🌐'})
        
        # Sort languages by number of users (most users first)
        sorted_languages = sorted(language_groups.items(), key=lambda x: len(x[1]), reverse=True)
        
        # Limit to prevent spam
        sorted_languages = sorted_languages[:MAX_TRANSLATIONS_PER_MESSAGE]
        
        translations_sent = 0
        
        for target_lang, users in sorted_languages:
            # Skip if no users
            if not users:
                continue
                
            # Translate once per language
            translated = translator.translate_text(message.content, target_lang, source_lang)
            if not translated:
                continue
            
            target_info = LANGUAGES.get(target_lang, {'name': target_lang.upper(), 'flag': '🌐'})
            
            # Create mention string for users
            mention_list = []
            for user_id in users:
                user = message.guild.get_member(user_id)
                if user:
                    mention_list.append(user.mention)
            
            if not mention_list:
                continue
            
            # Create embed
            embed = discord.Embed(color=discord.Color.blue())
            
            # Set author
            embed.set_author(
                name=f"Message by {message.author.display_name}",
                icon_url=message.author.avatar.url if message.author.avatar else None
            )
            
            # Original text
            original_display = message.content
            if len(original_display) > 500:
                original_display = original_display[:497] + "..."
            
            embed.add_field(
                name=f"{source_info['flag']} {source_info['name']}",
                value=original_display,
                inline=False
            )
            
            # Translated text
            translated_display = translated
            if len(translated_display) > 500:
                translated_display = translated_display[:497] + "..."
            
            embed.add_field(
                name=f"{target_info['flag']} {target_info['name']}",
                value=translated_display,
                inline=False
            )
            
            # Send the translation
            if len(mention_list) > 1:
                # Group mention
                mentions_text = f"**For:** {', '.join(mention_list)}"
            else:
                # Single mention
                mentions_text = f"**For:** {mention_list[0]}"
            
            await message.reply(
                f"{mentions_text}\n",
                embed=embed,
                mention_author=False
            )
            
            translations_sent += 1
            await asyncio.sleep(0.5)  # Small delay between translations
        
        return translations_sent > 0
        
    except Exception as e:
        logger.error(f"Error sending grouped translations: {e}")
        return False

# ========== EVENT HANDLERS ==========
@bot.event
async def on_ready():
    logger.info(f'✅ {bot.user} is online!')
    
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="!help | Auto-translate"
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

    # Skip if it starts with command prefix (already processed)
    if message.content.startswith('!'):
        return
    
    # Skip short messages
    if len(message.content.strip()) < 2:
        return
    
    # Check message cooldown (prevent duplicate translations)
    if not translator.check_message_cooldown(message.id):
        return
    
    logger.info(f"📨 Processing message from {message.author}")
    
    # Detect source language
    source_lang = translator.detect_language(message.content)
    logger.info(f"🔍 Detected language: {source_lang}")
    
    # Get all members in the channel
    try:
        if isinstance(message.channel, discord.TextChannel):
            members = [member for member in message.channel.members if not member.bot]
        else:
            return
        
        # Group users by their preferred language
        language_groups = {}
        
        for member in members:
            user_lang = translator.get_user_language(member.id)
            
            # Check if we should translate for this user
            if translator.should_translate_for_user(source_lang, user_lang, member.id, message.author.id):
                # Add user to language group
                if user_lang not in language_groups:
                    language_groups[user_lang] = []
                language_groups[user_lang].append(member.id)
        
        # If we have languages to translate to, send grouped translations
        if language_groups:
            logger.info(f"🎯 Translating to {len(language_groups)} language groups")
            await send_grouped_translations(message, language_groups)
            
    except Exception as e:
        logger.error(f"Error in auto-translation: {e}")

# ========== COMMANDS ==========
@bot.command(name="mylang")
async def set_language(ctx):
    """Set your preferred language with dropdown menu"""
    embed = discord.Embed(
        title="🌍 Select Your Language",
        description="Choose your preferred language from the dropdown menu below:",
        color=discord.Color.blue()
    )
    
    current_lang = translator.get_user_language(ctx.author.id)
    if current_lang in LANGUAGES:
        current_info = LANGUAGES[current_lang]
        embed.add_field(
            name="Current Language",
            value=f"{current_info['flag']} **{current_info['name']}**",
            inline=False
        )
    
    view = LanguageSelectView(ctx.author.id, translator)
    await ctx.send(embed=embed, view=view)

@bot.command(name="auto")
@commands.has_permissions(manage_channels=True)
async def toggle_auto(ctx, action: str = None):
    """Enable/disable auto-translate in this channel"""
    if not action:
        enabled = translator.is_channel_enabled(ctx.channel.id)
        
        embed = discord.Embed(
            title="⚙️ Auto-Translate Status",
            color=discord.Color.blue()
        )
        
        if enabled:
            embed.description = "✅ **ENABLED** in this channel"
        else:
            embed.description = "❌ **DISABLED** in this channel"
            embed.add_field(
                name="Enable:",
                value="Use `!auto enable` to turn on auto-translation",
                inline=False
            )
        
        await ctx.send(embed=embed)
        return
    
    action = action.lower()
    
    if action == 'enable':
        translator.enable_channel(ctx.channel.id)
        
        embed = discord.Embed(
            title="✅ Auto-Translate Enabled",
            description="This channel will now auto-translate messages to each user's preferred language.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="How it works:",
            value="1. Use `!mylang` to select language\n2. Any message will be auto-translated\n",
            inline=False
        )
        
        
        await ctx.send(embed=embed)

    elif action == 'disable':
        translator.disable_channel(ctx.channel.id)
        
        embed = discord.Embed(
            title="❌ Auto-Translate Disabled",
            description="Auto-translation has been turned off for this channel.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

    else:
        embed = discord.Embed(
            title="❌ Invalid Action",
            description="Use: `!auto enable` or `!auto disable`",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command(name="langs")
async def list_languages(ctx):
    """List all available languages"""
    embed = discord.Embed(
        title="🌍 Available Languages",
        description="Set your language with `!mylang` command",
        color=discord.Color.blue()
    )
    
    # Show popular languages first
    popular_codes = ['en', 'es', 'fr', 'de', 'it', 'pt', 'ru', 'ja', 'ko', 'zh', 'ar', 'hi', 'vi']
    popular_langs = []
    other_langs = []
    
    for code, info in LANGUAGES.items():
        if code in popular_codes:
            popular_langs.append(f"{info['flag']} `{code}` - {info['name']}")
        else:
            other_langs.append(f"{info['flag']} `{code}` - {info['name']}")
    
    if popular_langs:
        embed.add_field(name="Popular Languages", value="\n".join(popular_langs), inline=False)
    
    if other_langs:
        # Split other languages into chunks
        chunks = [other_langs[i:i + 10] for i in range(0, len(other_langs), 10)]
        for i, chunk in enumerate(chunks):
            embed.add_field(name=f"More Languages" if i == 0 else " ", value="\n".join(chunk), inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name="translate")
async def translate_command(ctx, target_lang: str = None, *, text: str = None):
    """Manually translate text"""
    if not target_lang or not text:
        embed = discord.Embed(
            title="❌ Usage",
            description="`!translate [language] [text]`\n**Example:** `!translate vi Hello everyone!`",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    async with ctx.typing():
        target_lang = target_lang.lower()
        
        if target_lang not in LANGUAGES:
            embed = discord.Embed(
                title="❌ Invalid Language",
                description="Use `!langs` to see available languages",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
        
        # Detect source language
        source_lang = translator.detect_language(text)
        source_info = LANGUAGES.get(source_lang, {'name': source_lang.upper(), 'flag': '🌐'})
        
        translated = translator.translate_text(text, target_lang, source_lang)
        
        if translated:
            target_info = LANGUAGES[target_lang]
            
            embed = discord.Embed(color=discord.Color.blue())
            embed.set_author(name=f"Translation by {ctx.author.display_name}", 
                           icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
            
            # Original text
            if len(text) > 800:
                original_display = text[:797] + "..."
            else:
                original_display = text
            
            embed.add_field(name=f"{source_info['flag']} {source_info['name']}", value=original_display, inline=False)
            
            # Translated text
            if len(translated) > 800:
                translated_display = translated[:797] + "..."
            else:
                translated_display = translated
            
            embed.add_field(name=f"{target_info['flag']} {target_info['name']}", value=translated_display, inline=False)
            
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title="❌ Translation Failed",
                description="Please try again with different text.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)

@bot.command(name="ping")
async def ping(ctx):
    """Check bot latency"""
    latency = round(bot.latency * 1000)
    
    embed = discord.Embed(
        title="🏓 Pong!",
        color=discord.Color.green()
    )
    embed.add_field(name="Latency", value=f"{latency}ms", inline=True)
    embed.add_field(name="Status", value="✅ Online", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name="help")
async def help_command(ctx):
    """Show help menu"""
    embed = discord.Embed(
        title="Translation Bot Help",
        description="**Auto-translates any message to each user's preferred language**",
        color=discord.Color.blue()
    )
   
    embed.add_field(
        name="👤 User Commands",
        value="• `!mylang` - Set your language (dropdown menu)\n• `!translate [lang] [text]` - Manual translation\n• `!langs` - List all languages",
        inline=False
    )
       
    await ctx.send(embed=embed)

# ========== RUN BOT ==========
if __name__ == "__main__":
    token = os.getenv('DISCORD_BOT_TOKEN')
    if token:
        logger.info("Starting translation bot...")
        bot.run(token)
    else:
        logger.error("❌ ERROR: DISCORD_BOT_TOKEN not found!")