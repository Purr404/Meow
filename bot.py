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

# Language mapping with flags - ADDED role_name FIELD
LANGUAGES = {
    'en': {'name': 'English', 'flag': '🇺🇸', 'role_name': 'English'},
    'es': {'name': 'Spanish', 'flag': '🇪🇸', 'role_name': 'Spanish'},
    'fr': {'name': 'French', 'flag': '🇫🇷', 'role_name': 'French'},
    'de': {'name': 'German', 'flag': '🇩🇪', 'role_name': 'German'},
    'it': {'name': 'Italian', 'flag': '🇮🇹', 'role_name': 'Italian'},
    'pt': {'name': 'Portuguese', 'flag': '🇵🇹', 'role_name': 'Portuguese'},
    'ru': {'name': 'Russian', 'flag': '🇷🇺', 'role_name': 'Russian'},
    'ja': {'name': 'Japanese', 'flag': '🇯🇵', 'role_name': 'Japanese'},
    'ko': {'name': 'Korean', 'flag': '🇰🇷', 'role_name': 'Korean'},
    'zh': {'name': 'Chinese', 'flag': '🇨🇳', 'role_name': 'Chinese'},
    'ar': {'name': 'Arabic', 'flag': '🇸🇦', 'role_name': 'Arabic'},
    'hi': {'name': 'Hindi', 'flag': '🇮🇳', 'role_name': 'Hindi'},
    'vi': {'name': 'Vietnamese', 'flag': '🇻🇳', 'role_name': 'Vietnamese'},
    'th': {'name': 'Thai', 'flag': '🇹🇭', 'role_name': 'Thai'},
    'id': {'name': 'Indonesian', 'flag': '🇮🇩', 'role_name': 'Indonesian'},
    'tr': {'name': 'Turkish', 'flag': '🇹🇷', 'role_name': 'Turkish'},
    'pl': {'name': 'Polish', 'flag': '🇵🇱', 'role_name': 'Polish'},
    'nl': {'name': 'Dutch', 'flag': '🇳🇱', 'role_name': 'Dutch'},
    'sv': {'name': 'Swedish', 'flag': '🇸🇪', 'role_name': 'Swedish'},
    'da': {'name': 'Danish', 'flag': '🇩🇰', 'role_name': 'Danish'},
    'fi': {'name': 'Finnish', 'flag': '🇫🇮', 'role_name': 'Finnish'},
    'no': {'name': 'Norwegian', 'flag': '🇳🇴', 'role_name': 'Norwegian'},
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

    def _init_db(self):  # ← ADD THIS INDENTATION!
        """Initialize database tables"""
        try:
            conn = self.get_connection()

            # SIMPLIFIED: Just check if it's PostgreSQL by trying to create a cursor
            is_postgres = False
            try:
                # Try PostgreSQL style
                cursor = conn.cursor()
                is_postgres = True
            except:
                # If that fails, it's SQLite
                is_postgres = False

            if is_postgres:
                # PostgreSQL connection
                cursor = conn.cursor()

                # Simple table creation
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_preferences (
                        user_id BIGINT PRIMARY KEY,
                        language_code TEXT DEFAULT 'en',
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS channel_settings (
                        channel_id BIGINT PRIMARY KEY,
                        enabled BOOLEAN DEFAULT FALSE,
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

                conn.commit()
                cursor.close()
                conn.close()
                logger.info("✅ PostgreSQL tables initialized")
            else:
                # SQLite connection
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

    def get_user_language(self, user_id, guild=None):
        """Get user's preferred language - UPDATED TO CHECK ROLES"""
        # If guild is provided, check for language roles first
        if guild:
            member = guild.get_member(user_id)
            if member:
                # Check if user has any language role
                for role in member.roles:
                    for lang_code, lang_info in LANGUAGES.items():
                        if role.name == lang_info['role_name']:
                            # Update database with this preference
                            self.set_user_language(user_id, lang_code)
                            logger.info(f"🎯 Auto-detected language from role: {lang_code} for user {member.name}")
                            return lang_code
        
        # Fall back to database preference
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
    """Send all translations in ONE embed"""
    try:
        # Detect source language
        source_lang = translator.detect_language(message.content)
        source_info = LANGUAGES.get(source_lang, {'name': source_lang.upper(), 'flag': '🌐'})
        
        # Sort languages by number of users (most users first)
        sorted_languages = sorted(language_groups.items(), key=lambda x: len(x[1]), reverse=True)
        
        # Limit translations
        sorted_languages = sorted_languages[:MAX_TRANSLATIONS_PER_MESSAGE]
        
        # Don't proceed if no translations needed
        if not sorted_languages:
            return False
        
        # Count total users
        total_users = sum(len(users) for _, users in sorted_languages)
        
        # Create ONE embed
        embed = discord.Embed(
            color=discord.Color.blue(),

        )
        
        # Set author
        embed.set_author(
            name=f"{message.author.display_name}",
            icon_url=message.author.avatar.url if message.author.avatar else None
        )
        
        # Original message (always show)
        original_display = message.content
        if len(original_display) > 800:
            original_display = original_display[:797] + "..."
        
        embed.add_field(
            name=f"{source_info['flag']} Original ({source_info['name']})",
            value=original_display,
            inline=False
        )
        
        # Add ALL translations to the same embed
        translations_added = 0
        
        for target_lang, users in sorted_languages:
            if translations_added >= 9:  # Max 9 translations per embed
                break
                
            # Translate
            translated = translator.translate_text(message.content, target_lang, source_lang)
            if not translated:
                continue
            
            target_info = LANGUAGES.get(target_lang, {'name': target_lang.upper(), 'flag': '🌐'})
            user_count = len(users)
            
            # Format translation text
            translated_display = translated
            if len(translated_display) > 600:
                translated_display = translated_display[:597] + "..."
            
            # Add translation as a field
            if user_count > 1:
                count_text = f"{user_count} users"
            else:
                count_text = "1 user"
            
            embed.add_field(
                name=f"{target_info['flag']} {target_info['name']} ({count_text})",
                value=translated_display,
                inline=False
            )
            
            translations_added += 1
        
        # If we have translations, send the embed
        if translations_added > 0:
            # Add total users to footer
            if total_users > 1:
                footer_text = f"Translated for {total_users} users"
            else:
                footer_text = "Translated for 1 user"
            
            embed.set_footer(text=footer_text)
            
            # Send ONE embed
            await message.reply(
                embed=embed,
                mention_author=False
            )
            
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error sending grouped translations: {e}")
        return False

# ========== EVENT HANDLERS ==========
@bot.event
async def on_ready():
    logger.info(f'✅ {bot.user} is online!')
    
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="Meow~"
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
            # UPDATED: Pass guild to get_user_language for role checking
            user_lang = translator.get_user_language(member.id, message.guild)
            
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
    """Set your preferred language with dropdown menu - UPDATED FOR ROLE CHECKING"""
    # First check if user has a language role
    user_lang_from_role = None
    role_used = None
    
    for role in ctx.author.roles:
        for lang_code, lang_info in LANGUAGES.items():
            if role.name == lang_info['role_name']:
                user_lang_from_role = lang_code
                role_used = role
                break
        if user_lang_from_role:
            break
    
    # If user has a language role, auto-set it
    if user_lang_from_role:
        translator.set_user_language(ctx.author.id, user_lang_from_role)
        lang_info = LANGUAGES[user_lang_from_role]
        
        embed = discord.Embed(
            title="✅ Language Auto-Set from Role",
            description=f"I detected your **{role_used.name}** role and automatically set your language!",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Language Set",
            value=f"{lang_info['flag']} **{lang_info['name']}** ({user_lang_from_role})",
            inline=False
        )
        embed.add_field(
            name="Want a different language?",
            value="Use the dropdown menu below to choose a different language",
            inline=False
        )
        
        # Still show the dropdown menu so they can change if they want
        view = LanguageSelectView(ctx.author.id, translator)
        await ctx.send(embed=embed, view=view)
        return
    
    # If no role found, show the normal dropdown menu
    embed = discord.Embed(
        title="🌍 Select Your Language",
        description="Choose your preferred language from the dropdown menu below:",
        color=discord.Color.blue()
    )
    
    current_lang = translator.get_user_language(ctx.author.id, ctx.guild)
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
            value="1. Users set language with `!mylang` or get language roles\n2. Bot detects language of each message\n3. Translates to users' preferred languages\n4. Sends translations as a reply",
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
            popular_langs.append(f"{info['flag']} `{code}` - {info['name']} (Role: {info['role_name']})")
        else:
            other_langs.append(f"{info['flag']} `{code}` - {info['name']} (Role: {info['role_name']})")
    
    if popular_langs:
        embed.add_field(name="Popular Languages", value="\n".join(popular_langs), inline=False)
    
    if other_langs:
        # Split other languages into chunks
        chunks = [other_langs[i:i + 10] for i in range(0, len(other_langs), 10)]
        for i, chunk in enumerate(chunks):
            embed.add_field(name=f"More Languages" if i == 0 else " ", value="\n".join(chunk), inline=False)
    
    embed.add_field(
        name="Role Integration",
        value="• Get language roles during onboarding (English, Spanish, etc.)\n• Bot will auto-detect your language from roles\n• Use `!mylang` to confirm or override",
        inline=False
    )
    
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

@bot.command(name="swswswsw")
async def ping(ctx):
    """Check bot latency"""
    latency = round(bot.latency * 1000)
    
    embed = discord.Embed(
        title="Meoww~",
        color=discord.Color.green()
    )
    embed.add_field(name="Latency", value=f"{latency}ms", inline=True)
    embed.add_field(name="Status", value="✅ Online", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name="synclang")
async def sync_language(ctx):
    """Sync your language preference with your current roles"""
    user_lang_from_role = None
    detected_role = None
    
    # Find language role
    for role in ctx.author.roles:
        role_name = role.name
        for lang_code, lang_info in LANGUAGES.items():
            if role_name == lang_info['role_name']:
                user_lang_from_role = lang_code
                detected_role = role
                break
        if user_lang_from_role:
            break
    
    if not user_lang_from_role:
        embed = discord.Embed(
            title="❌ No Language Role Found",
            description="You don't have any language roles yet.",
            color=discord.Color.red()
        )
        embed.add_field(
            name="How to get a role:",
            value="• During server onboarding\n• Ask an admin\n• Use `!mylang` to set language first",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    # Set the language
    translator.set_user_language(ctx.author.id, user_lang_from_role)
    lang_info = LANGUAGES[user_lang_from_role]
    
    embed = discord.Embed(
        title="✅ Language Synced!",
        description=f"I detected your **{detected_role.name}** role and synced your language preference.",
        color=discord.Color.green()
    )
    embed.add_field(
        name="Language Set",
        value=f"{lang_info['flag']} **{lang_info['name']}** ({user_lang_from_role})",
        inline=False
    )
    
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
        value="• `!mylang` - Set your language (dropdown menu)\n• `!synclang` - Sync language from your role\n• `!translate [lang] [text]` - Manual translation\n• `!langs` - List all languages",
        inline=False
    )
    
    embed.add_field(
        name="🔄 Role Integration",
        value="• Get language roles during onboarding\n• Bot auto-detects your language from roles\n• Use `!mylang` to confirm or change",
        inline=False
    )
    
    await ctx.send(embed=embed)

# ========== EVENT FOR AUTO-DETECTING ROLE CHANGES ==========
@bot.event
async def on_member_update(before, after):
    """Detect when a member gets a new role and update language preference"""
    # Check if roles changed
    if before.roles != after.roles:
        new_roles = set(after.roles) - set(before.roles)
        
        for role in new_roles:
            role_name = role.name
            # Check if this is a language role
            for lang_code, lang_info in LANGUAGES.items():
                if role_name == lang_info['role_name']:
                    # Update user's language preference
                    translator.set_user_language(after.id, lang_code)
                    
                    # Log it
                    logger.info(f"🔄 Auto-set language for {after.name} to {lang_code} from role: {role_name}")
                    
                    # Send notification if possible
                    try:
                        embed = discord.Embed(
                            title="🌍 Language Preference Updated",
                            description=f"Your language preference has been automatically set to **{lang_info['name']}!**",
                            color=discord.Color.green()
                        )
                        embed.add_field(
                            name="What this means:",
                            value="• Messages will be auto-translated to your language\n• Use `!mylang` to change if needed",
                            inline=False
                        )
                        await after.send(embed=embed)
                    except:
                        pass  # User might have DMs disabled
                    break



# =======WELCOME======================

import random

class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 10 different welcome message templates
        self.welcome_messages = [
            "🌟 Welcome {member}! We're so glad you joined **{guild}**!",
            "🎉 A wild {member} appeared! Welcome to **{guild}**!",
            "🤝 Give it up for {member}! Welcome to our awesome community!",
            "🚀 {member} just landed in **{guild}**. Prepare for adventure!",
            "💫 Shine bright like a diamond, {member}! Welcome aboard!",
            "🎈 Pop goes the confetti! Welcome {member} to **{guild}**!",
            "🌍 Another traveler arrives! Welcome {member}, enjoy your stay!",
            "📢 Attention everyone! Please welcome {member} to the server!",
            "🍰 Welcome {member}! We have cake (and cool people) here!",
            "🔔 Ding dong! {member} is here! Let's make them feel at home!"
        ]

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Send a random welcome embed when a new member joins."""
        guild = member.guild
        async with self.bot.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT channel_id FROM welcome_channels WHERE guild_id = $1",
                guild.id
            )
        if not row:
            return

        channel = guild.get_channel(row['channel_id'])
        if not channel:
            return

        # Pick a random welcome message and format it
        template = random.choice(self.welcome_messages)
        welcome_text = template.format(
            member=member.mention,
            guild=guild.name,
            count=len(guild.members)
        )

        # Create the embed
        embed = discord.Embed(
            title=f"👋 New Member!",
            description=welcome_text,
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Member #{len(guild.members)}", icon_url=guild.icon.url if guild.icon else None)
        embed.timestamp = discord.utils.utcnow()

        try:
            await channel.send(embed=embed)
        except Exception as e:
            print(f"Failed to send welcome message: {e}")

    # ------------------------------------------------------------------
    # Command to set the welcome channel (unchanged)
    # ------------------------------------------------------------------
    @commands.command(name='setwelcome')
    @commands.has_permissions(administrator=True)
    async def set_welcome_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel where welcome messages will be sent."""
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO welcome_channels (guild_id, channel_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id) DO UPDATE SET channel_id = $2
            """, ctx.guild.id, channel.id)

        embed = discord.Embed(
            title="✅ Welcome channel set!",
            description=f"Welcome messages will now be sent to {channel.mention}",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @set_welcome_channel.error
    async def set_welcome_channel_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You need administrator permission to use this command.")

# ========END=========
await bot.add_cog(Welcome(bot))

# ========== RUN BOT ==========
if __name__ == "__main__":
    token = os.getenv('DISCORD_BOT_TOKEN')
    if token:
        logger.info("Starting translation bot...")
        bot.run(token)
    else:
        logger.error("❌ ERROR: DISCORD_BOT_TOKEN not found!")