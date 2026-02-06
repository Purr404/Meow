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

# Language mapping with flags AND roles

LANGUAGES = {
    'en': {'name': 'English', 'flag': '🇺🇸', 'role_name': 'English Speaker'},
    'es': {'name': 'Spanish', 'flag': '🇪🇸', 'role_name': 'Spanish Speaker'},
    'fr': {'name': 'French', 'flag': '🇫🇷', 'role_name': 'French Speaker'},
    'de': {'name': 'German', 'flag': '🇩🇪', 'role_name': 'German Speaker'},
    'it': {'name': 'Italian', 'flag': '🇮🇹', 'role_name': 'Italian Speaker'},
    'pt': {'name': 'Portuguese', 'flag': '🇵🇹', 'role_name': 'Portuguese Speaker'},
    'ru': {'name': 'Russian', 'flag': '🇷🇺', 'role_name': 'Russian Speaker'},
    'ja': {'name': 'Japanese', 'flag': '🇯🇵', 'role_name': 'Japanese Speaker'},
    'ko': {'name': 'Korean', 'flag': '🇰🇷', 'role_name': 'Korean Speaker'},
    'zh': {'name': 'Chinese', 'flag': '🇨🇳', 'role_name': 'Chinese Speaker'},
    'ar': {'name': 'Arabic', 'flag': '🇸🇦', 'role_name': 'Arabic Speaker'},
    'hi': {'name': 'Hindi', 'flag': '🇮🇳', 'role_name': 'Hindi Speaker'},
    'vi': {'name': 'Vietnamese', 'flag': '🇻🇳', 'role_name': 'Vietnamese Speaker'},
    'th': {'name': 'Thai', 'flag': '🇹🇭', 'role_name': 'Thai Speaker'},
    'id': {'name': 'Indonesian', 'flag': '🇮🇩', 'role_name': 'Indonesian Speaker'},
    'tr': {'name': 'Turkish', 'flag': '🇹🇷', 'role_name': 'Turkish Speaker'},
    'pl': {'name': 'Polish', 'flag': '🇵🇱', 'role_name': 'Polish Speaker'},
    'nl': {'name': 'Dutch', 'flag': '🇳🇱', 'role_name': 'Dutch Speaker'},
    'sv': {'name': 'Swedish', 'flag': '🇸🇪', 'role_name': 'Swedish Speaker'},
    'da': {'name': 'Danish', 'flag': '🇩🇰', 'role_name': 'Danish Speaker'},
    'fi': {'name': 'Finnish', 'flag': '🇫🇮', 'role_name': 'Finnish Speaker'},
    'no': {'name': 'Norwegian', 'flag': '🇳🇴', 'role_name': 'Norwegian Speaker'},
}

# customize role names or keep them as shown above


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
    
    # Get user language with guild context
    if isinstance(message.channel, discord.TextChannel):
        source_lang = translator.detect_language(message.content)
        logger.info(f"🔍 Detected language: {source_lang}")
        
        # Get all members in the channel
        members = [member for member in message.channel.members if not member.bot]
        
        # Group users by their preferred language
        language_groups = {}
        
        for member in members:
            # Pass guild to get_user_language
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

@bot.event
async def on_member_update(before, after):
    """Detect when a member gets a new role and update language preference"""
    # Check if roles changed
    if before.roles != after.roles:
        new_roles = set(after.roles) - set(before.roles)
        
        for role in new_roles:
            # Check if this is a language role
            for lang_code, lang_info in LANGUAGES.items():
                if role.name == lang_info['role_name']:
                    # Update user's language preference
                    translator.set_user_language(after.id, lang_code)
                    
                    # Log it
                    logger.info(f"🔄 Auto-set language for {after.name} to {lang_code} from role")
                    
                    # Optional: Send DM to user
                    try:
                        embed = discord.Embed(
                            title="🌍 Language Preference Updated",
                            description=f"Your language preference has been automatically set to **{lang_info['name']}** because you received the **{role.name}** role!",
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

# ========== COMMANDS ==========
@bot.command(name="mylang")
async def set_language(ctx, language_code: str = None):
    """Set your preferred language or sync with your role"""
    # If no language code provided, check current role or show menu
    if not language_code:
        # Check if user already has a language role
        user_lang_from_role = None
        for role in ctx.author.roles:
            for lang_code, lang_info in LANGUAGES.items():
                if role.name == lang_info['role_name']:
                    user_lang_from_role = lang_code
                    break
            if user_lang_from_role:
                break
        
        # If user has a language role, use it
        if user_lang_from_role:
            translator.set_user_language(ctx.author.id, user_lang_from_role)
            lang_info = LANGUAGES[user_lang_from_role]
            
            embed = discord.Embed(
                title="✅ Language Synced from Role",
                description=f"Your language has been automatically set to:\n{lang_info['flag']} **{lang_info['name']}** ({user_lang_from_role})",
                color=discord.Color.green()
            )
            embed.add_field(
                name="How it works:",
                value="• Your language preference is now synced with your role\n• Use `!mylang [code]` to override if needed\n• Use `!mylang` without code to see the menu",
                inline=False
            )
            
            await ctx.send(embed=embed)
            return
        
        # Otherwise show the dropdown menu
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
        return
    
    # If language code is provided
    language_code = language_code.lower()
    
    if language_code not in LANGUAGES:
        embed = discord.Embed(
            title="❌ Invalid Language Code",
            description=f"`{language_code}` is not a valid language code.\nUse `!langs` to see available languages.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    # Set the language
    translator.set_user_language(ctx.author.id, language_code)
    lang_info = LANGUAGES[language_code]
    
    # Check if user wants to get the corresponding role
    embed = discord.Embed(
        title="✅ Language Set",
        description=f"Your language has been set to:\n{lang_info['flag']} **{lang_info['name']}** ({language_code})",
        color=discord.Color.green()
    )
    
    # Check if role exists in the guild
    role = discord.utils.get(ctx.guild.roles, name=lang_info['role_name'])
    if role:
        # Check if bot has permission to manage roles
        if ctx.guild.me.guild_permissions.manage_roles:
            # Check if user already has the role
            if role in ctx.author.roles:
                embed.add_field(
                    name="Role Status",
                    value=f"You already have the **{role.name}** role",
                    inline=False
                )
            else:
                # Ask if user wants the role
                embed.add_field(
                    name="Want the language role?",
                    value=f"React with ✅ to get the **{role.name}** role\nThis helps others know what languages you speak!",
                    inline=False
                )
                msg = await ctx.send(embed=embed)
                await msg.add_reaction("✅")
                
                # Wait for reaction
                def check(reaction, user):
                    return user == ctx.author and str(reaction.emoji) == "✅" and reaction.message.id == msg.id
                
                try:
                    reaction, user = await bot.wait_for('reaction_add', timeout=30.0, check=check)
                    
                    # Add the role
                    await ctx.author.add_roles(role)
                    
                    success_embed = discord.Embed(
                        title="✅ Role Added!",
                        description=f"You've been given the **{role.name}** role!",
                        color=discord.Color.green()
                    )
                    await ctx.send(embed=success_embed)
                    
                except asyncio.TimeoutError:
                    pass
                
                return
    
    await ctx.send(embed=embed)

@bot.command(name="langs")
async def list_languages(ctx):
    """List all available languages with role status"""
    embed = discord.Embed(
        title="🌍 Available Languages",
        description="Set your language with `!mylang` command",
        color=discord.Color.blue()
    )
    
    # Check which roles exist in this guild
    existing_roles = []
    missing_roles = []
    
    for code, info in LANGUAGES.items():
        role = discord.utils.get(ctx.guild.roles, name=info['role_name'])
        if role:
            existing_roles.append(f"{info['flag']} `{code}` - **{info['name']}** ✅")
        else:
            missing_roles.append(f"{info['flag']} `{code}` - {info['name']}")
    
    if existing_roles:
        embed.add_field(
            name="Available in this server ✅",
            value="\n".join(existing_roles[:15]),
            inline=False
        )
    
    if missing_roles:
        embed.add_field(
            name="Not yet available (admins can create)",
            value="\n".join(missing_roles[:15]),
            inline=False
        )
    
    if len(existing_roles) > 15 or len(missing_roles) > 15:
        embed.set_footer(text=f"Showing 15 of {len(LANGUAGES)} languages. Use !mylang [code] to set.")
    
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

@bot.command(name="createlangroles")
@commands.has_permissions(administrator=True)
async def create_language_roles(ctx):
    """Create all language roles in the server (Admin only)"""
    embed = discord.Embed(
        title="🛠 Creating Language Roles",
        description="This will create all language roles in the server...",
        color=discord.Color.blue()
    )
    
    msg = await ctx.send(embed=embed)
    
    created_count = 0
    existing_count = 0
    
    for lang_code, lang_info in LANGUAGES.items():
        role_name = lang_info['role_name']
        
        # Check if role already exists
        role = discord.utils.get(ctx.guild.roles, name=role_name)
        
        if role:
            existing_count += 1
            continue
        
        # Create the role
        try:
            # You can customize the color if you want
            role = await ctx.guild.create_role(
                name=role_name,
                color=discord.Color.random(),
                reason="Language role for translation bot",
                mentionable=True
            )
            created_count += 1
            
            # Update embed
            updated_embed = discord.Embed(
                title="🛠 Creating Language Roles",
                description=f"Created {created_count} new roles...",
                color=discord.Color.blue()
            )
            updated_embed.add_field(
                name="Latest",
                value=f"✅ Created role: **{role_name}**",
                inline=False
            )
            await msg.edit(embed=updated_embed)
            
            # Small delay to avoid rate limits
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.error(f"Failed to create role {role_name}: {e}")
    
    # Final summary
    final_embed = discord.Embed(
        title="✅ Language Roles Created",
        color=discord.Color.green()
    )
    final_embed.add_field(name="New Roles", value=str(created_count), inline=True)
    final_embed.add_field(name="Existing Roles", value=str(existing_count), inline=True)
    final_embed.add_field(name="Total", value=str(len(LANGUAGES)), inline=True)
    
    if created_count > 0:
        final_embed.add_field(
            name="Next Steps",
            value="1. Arrange roles in hierarchy as needed\n2. Use `!mylang` to test the system\n3. Users can now get roles during onboarding",
            inline=False
        )
    
    await msg.edit(embed=final_embed)

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