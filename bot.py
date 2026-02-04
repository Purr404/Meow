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

load_dotenv()

# ========== LOGGING SETUP ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# ========== CONFIGURATION ==========
COOLDOWN_SECONDS = 5

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
        self.db_path = 'translations.db'
        self._init_db()
        logger.info("✅ Translator initialized")

    def _init_db(self):
        """Initialize database"""
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

    def get_connection(self):
        """Get database connection"""
        return closing(sqlite3.connect(self.db_path, check_same_thread=False))

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
            
            # Translate
            logger.info(f"Translating: '{text[:50]}...' ({source_lang}) → {target_lang}")
            result = self.google_translator.translate(text, dest=target_lang, src=source_lang)
            
            if result and result.text:
                self.translation_cache[cache_key] = result.text
                return result.text
            return None
        except Exception as e:
            logger.error(f"Translation error: {e}")
            return None

    def detect_language(self, text):
        """Detect language of text"""
        try:
            text = text.strip()
            if len(text) < 2:
                return 'en'
            
            # Use Google Translate to detect language
            detection = self.google_translator.detect(text)
            if detection and detection.lang:
                return detection.lang
            return 'en'
        except Exception as e:
            logger.error(f"Language detection error: {e}")
            return 'en'

    def should_translate_for_user(self, message_lang, user_lang, user_id, message_author_id):
        """Determine if we should translate for a user"""
        # Don't translate if same language
        if message_lang == user_lang:
            return False
        
        # Don't translate user's own messages to themselves
        if user_id == message_author_id:
            return False
        
        # Don't translate to/from English if user has English set (no need)
        if user_lang == 'en' and message_lang == 'en':
            return False
        
        return True

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
            logger.error(f"DB error: {e}")
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
        except Exception as e:
            logger.error(f"DB error: {e}")

    def enable_channel(self, channel_id):
        """Enable auto-translate for a channel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO channel_settings (channel_id, enabled, created_at)
                    VALUES (?, 1, CURRENT_TIMESTAMP)
                ''', (channel_id,))
                conn.commit()
        except Exception as e:
            logger.error(f"DB error: {e}")

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
        except Exception as e:
            logger.error(f"DB error: {e}")

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
            logger.error(f"DB error: {e}")
            return False

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

# ========== HELPER FUNCTIONS ==========
async def send_translation_embed(original_message, translated_text, source_lang, target_lang, target_user=None):
    """Create and send translation embed"""
    source_info = LANGUAGES.get(source_lang, {'name': source_lang.upper(), 'flag': '🌐'})
    target_info = LANGUAGES.get(target_lang, {'name': target_lang.upper(), 'flag': '🌐'})
    
    embed = discord.Embed(color=discord.Color.blue())
    
    # Set author
    embed.set_author(
        name=f"Message by {original_message.author.display_name}",
        icon_url=original_message.author.avatar.url if original_message.author.avatar else None
    )
    
    # Original text with language flag
    original_display = original_message.content
    if len(original_display) > 800:
        original_display = original_display[:797] + "..."
    
    embed.add_field(
        name=f"{source_info['flag']} {source_info['name']}",
        value=original_display,
        inline=False
    )
    
    # Translated text
    translated_display = translated_text
    if len(translated_display) > 800:
        translated_display = translated_display[:797] + "..."
    
    embed.add_field(
        name=f"{target_info['flag']} {target_info['name']}",
        value=translated_display,
        inline=False
    )
    
    # Add translation note
    if target_user:
        embed.set_footer(text=f"Translated for {target_user.display_name}")
    
    if target_user:
        # Send as reply with mention
        return await original_message.reply(
            f"**Translation for {target_user.mention}**",
            embed=embed,
            mention_author=False
        )
    else:
        # Send as regular reply
        return await original_message.reply(
            embed=embed,
            mention_author=False
        )

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
    
    # Skip short messages
    if len(message.content.strip()) < 2:
        return
    
    # Check cooldown
    if not translator.check_cooldown(message.author.id):
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
        
        # Process each user in the channel
        translation_tasks = []
        for member in members:
            user_lang = translator.get_user_language(member.id)
            
            # Check if we should translate for this user
            if translator.should_translate_for_user(source_lang, user_lang, member.id, message.author.id):
                logger.info(f"  👤 {member.display_name}: {source_lang} → {user_lang}")
                
                # Create translation task
                task = asyncio.create_task(
                    process_translation_for_user(message, source_lang, user_lang, member)
                )
                translation_tasks.append(task)
        
        # Wait for all translations to complete
        if translation_tasks:
            await asyncio.gather(*translation_tasks, return_exceptions=True)
            
    except Exception as e:
        logger.error(f"Error in auto-translation: {e}")

async def process_translation_for_user(message, source_lang, target_lang, user):
    """Process translation for a specific user"""
    try:
        # Translate the message
        translated = translator.translate_text(message.content, target_lang, source_lang)
        if translated:
            # Send the translation
            await send_translation_embed(message, translated, source_lang, target_lang, user)
            await asyncio.sleep(0.5)  # Small delay between translations
    except Exception as e:
        logger.error(f"Error translating for user {user}: {e}")

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
            value="1. Users use `!mylang` to select their language\n2. Any message in any language will be auto-translated\n3. Each user gets translations in their preferred language",
            inline=False
        )
        embed.add_field(
            name="Example:",
            value="• User A sets language to Hindi (`!mylang` → Hindi)\n• User B sets language to Spanish (`!mylang` → Spanish)\n• User C sends message in English\n→ User A sees Hindi translation\n→ User B sees Spanish translation",
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
        title="🤖 Translation Bot Help",
        description="**Auto-translates any message to each user's preferred language**",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="🚀 Quick Start",
        value="1. Admin: `!auto enable`\n2. Users: `!mylang` (select from dropdown)\n3. Any message → Auto-translated for each user!",
        inline=False
    )
    
    embed.add_field(
        name="👤 User Commands",
        value="• `!mylang` - Set your language (dropdown menu)\n• `!translate [lang] [text]` - Manual translation\n• `!langs` - List all languages",
        inline=False
    )
    
    embed.add_field(
        name="🛠️ Admin Commands",
        value="• `!auto enable` - Enable auto-translate\n• `!auto disable` - Disable auto-translate",
        inline=False
    )
    
    embed.add_field(
        name="🎯 How Auto-Translate Works",
        value="• Messages in ANY language are detected\n• Each user gets translation in their preferred language\n• No dropdowns on translations - clean UI",
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