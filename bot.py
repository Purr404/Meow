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
SOURCE_LANGUAGE = "en"
MIN_TEXT_LENGTH = 2
COOLDOWN_SECONDS = 5  # Reduced cooldown for better UX

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

# Flag to language mapping
FLAG_TO_LANG = {
    '🇺🇸': 'en', '🇪🇸': 'es', '🇫🇷': 'fr', '🇩🇪': 'de',
    '🇮🇹': 'it', '🇵🇹': 'pt', '🇷🇺': 'ru', '🇯🇵': 'ja',
    '🇰🇷': 'ko', '🇨🇳': 'zh', '🇸🇦': 'ar', '🇮🇳': 'hi',
    '🇻🇳': 'vi', '🇹🇭': 'th', '🇮🇩': 'id', '🇹🇷': 'tr',
    '🇵🇱': 'pl', '🇳🇱': 'nl', '🇸🇪': 'sv', '🇩🇰': 'da',
    '🇫🇮': 'fi', '🇳🇴': 'no'
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
            value="• English messages will be auto-translated for you\n• Use `!translate [lang] [text]` for manual translations",
            inline=False
        )
        
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

class FlagTranslationView(ui.View):
    def __init__(self, message_id, translator):
        super().__init__(timeout=300)
        self.message_id = message_id
        self.translator = translator
        
        # Create flag select menu
        options = []
        for code, info in LANGUAGES.items():
            if code != 'en':  # Don't include English (source language)
                options.append(SelectOption(
                    label=info['name'],
                    value=code,
                    emoji=info['flag'],
                    description=f"Translate to {info['name']}"
                ))
        
        # Split into chunks if needed
        for i in range(0, len(options), 25):
            select = ui.Select(
                placeholder="Select a language to translate...",
                options=options[i:i+25],
                custom_id=f"flag_select_{i}"
            )
            select.callback = self.flag_select_callback
            self.add_item(select)

    async def flag_select_callback(self, interaction: discord.Interaction):
        lang_code = interaction.data['values'][0]
        lang_info = LANGUAGES.get(lang_code)
        
        # Get the original message
        try:
            message = await interaction.channel.fetch_message(self.message_id)
            
            # Check if message is from bot
            if message.author.bot:
                await interaction.response.send_message("Cannot translate bot messages.", ephemeral=True)
                return
            
            # Translate the message
            translated = self.translator.translate_text(message.content, lang_code, SOURCE_LANGUAGE)
            
            if not translated:
                await interaction.response.send_message("Translation failed. Please try again.", ephemeral=True)
                return
            
            # Create embed
            embed = discord.Embed(color=discord.Color.blue())
            embed.set_author(
                name=f"Original by {message.author.display_name}",
                icon_url=message.author.avatar.url if message.author.avatar else None
            )
            
            # Original text
            if len(message.content) > 500:
                original_display = message.content[:497] + "..."
            else:
                original_display = message.content
            
            embed.add_field(
                name=f"🇺🇸 Original",
                value=original_display,
                inline=False
            )
            
            # Translated text
            if len(translated) > 500:
                translated_display = translated[:497] + "..."
            else:
                translated_display = translated
            
            embed.add_field(
                name=f"{lang_info['flag']} {lang_info['name']}",
                value=translated_display,
                inline=False
            )
            
            # Send as reply to original message
            await interaction.response.send_message(
                f"**Translation requested by {interaction.user.mention}**",
                embed=embed,
                mention_author=False
            )
            
        except Exception as e:
            logger.error(f"Flag translation error: {e}")
            await interaction.response.send_message("Error translating message.", ephemeral=True)

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
            if not text or len(text) < MIN_TEXT_LENGTH:
                return None
            
            # Cache key
            cache_key = hashlib.md5(f"{text}:{target_lang}:{source_lang}".encode()).hexdigest()
            
            # Check cache
            if cache_key in self.translation_cache:
                return self.translation_cache[cache_key]
            
            # Translate
            logger.info(f"Translating: '{text[:50]}...' → {target_lang}")
            result = self.google_translator.translate(text, dest=target_lang, src=source_lang)
            
            if result and result.text:
                self.translation_cache[cache_key] = result.text
                return result.text
            return None
        except Exception as e:
            logger.error(f"Translation error: {e}")
            return None

    def is_english_text(self, text):
        """Better English detection - translate ALL English messages"""
        # Clean the text
        text = text.lower().strip()
        
        # Check if text is too short
        if len(text) < MIN_TEXT_LENGTH:
            return False
        
        # Common English words and patterns
        english_indicators = [
            'the', 'and', 'you', 'that', 'have', 'for', 'with', 'this',
            'are', 'not', 'but', 'what', 'all', 'was', 'can', 'your',
            'there', 'their', 'they', 'like', 'just', 'know', 'will',
            'about', 'how', 'which', 'when', 'where', 'who', 'why',
            'good', 'more', 'some', 'time', 'people', 'year', 'day',
            'thing', 'make', 'take', 'come', 'look', 'want', 'need',
            'thank', 'thanks', 'hello', 'hi', 'hey', 'please', 'sorry'
        ]
        
        # Check for English words
        text_words = set(text.split())
        english_count = sum(1 for word in english_indicators if word in text_words)
        
        # If we found at least 1 English indicator word, consider it English
        # OR if it's mostly Latin characters
        latin_chars = sum(1 for c in text if 'a' <= c <= 'z' or c == ' ')
        latin_percentage = latin_chars / len(text) if text else 0
        
        return english_count > 0 or latin_percentage > 0.7

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
async def send_translation_embed(original_message, translated_text, target_lang, requesting_user=None):
    """Create and send translation embed"""
    lang_info = LANGUAGES.get(target_lang, {'name': target_lang.upper(), 'flag': '🌐'})
    
    embed = discord.Embed(color=discord.Color.blue())
    
    # Set author
    embed.set_author(
        name=f"Message by {original_message.author.display_name}",
        icon_url=original_message.author.avatar.url if original_message.author.avatar else None
    )
    
    # Original text
    original_display = original_message.content
    if len(original_display) > 800:
        original_display = original_display[:797] + "..."
    
    embed.add_field(
        name=f"🇺🇸 Original",
        value=original_display,
        inline=False
    )
    
    # Translated text
    translated_display = translated_text
    if len(translated_display) > 800:
        translated_display = translated_display[:797] + "..."
    
    embed.add_field(
        name=f"{lang_info['flag']} {lang_info['name']}",
        value=translated_display,
        inline=False
    )
    
    # Add flag reaction UI
    view = FlagTranslationView(original_message.id, translator)
    
    if requesting_user:
        # Send as reply with mention
        return await original_message.reply(
            f"**Translation for {requesting_user.mention}**",
            embed=embed,
            view=view,
            mention_author=False
        )
    else:
        # Send as regular reply
        return await original_message.reply(
            embed=embed,
            view=view,
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
    
    # Check cooldown
    if not translator.check_cooldown(message.author.id):
        return
    
    # Skip short messages
    if len(message.content.strip()) < MIN_TEXT_LENGTH:
        return
    
    # Check if message is in English (translate ALL English messages)
    if not translator.is_english_text(message.content):
        return
    
    logger.info(f"📨 Auto-translating message from {message.author}")
    
    # Get all members in the channel
    try:
        members = []
        if isinstance(message.channel, discord.TextChannel):
            members = [member for member in message.channel.members if not member.bot]
        
        # Find unique languages needed
        languages_needed = set()
        for member in members:
            user_lang = translator.get_user_language(member.id)
            if user_lang != SOURCE_LANGUAGE:
                languages_needed.add((user_lang, member.id))
        
        # Send translations for each language
        for lang_code, user_id in languages_needed:
            if lang_code in LANGUAGES:
                # Translate
                translated = translator.translate_text(message.content, lang_code, SOURCE_LANGUAGE)
                if translated:
                    # Get user mention
                    user = message.guild.get_member(user_id)
                    if user:
                        # Send translation
                        await send_translation_embed(message, translated, lang_code, user)
                        await asyncio.sleep(0.5)  # Small delay between translations
                
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
            description="This channel will now auto-translate English messages to users' preferred languages.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Quick Setup:",
            value="1. Users use `!mylang` to select their language\n2. Send English messages\n3. Messages auto-translate for each user",
            inline=False
        )
        embed.add_field(
            name="Additional Features:",
            value="• Use the dropdown menu on any translation to translate to other languages\n• Use `!translate [lang] [text]` for manual translations",
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
    
    # Group languages
    popular = []
    asian = []
    european = []
    others = []
    
    for code, info in LANGUAGES.items():
        if code in ['es', 'fr', 'de', 'it', 'pt']:
            european.append(f"{info['flag']} `{code}` - {info['name']}")
        elif code in ['ja', 'ko', 'zh', 'vi', 'th']:
            asian.append(f"{info['flag']} `{code}` - {info['name']}")
        elif code in ['ru', 'ar', 'hi', 'tr']:
            others.append(f"{info['flag']} `{code}` - {info['name']}")
        elif code != 'en':
            popular.append(f"{info['flag']} `{code}` - {info['name']}")
    
    if popular:
        embed.add_field(name="Popular", value="\n".join(popular[:8]), inline=True)
    if european:
        embed.add_field(name="European", value="\n".join(european[:8]), inline=True)
    if asian:
        embed.add_field(name="Asian", value="\n".join(asian), inline=True)
    if others:
        embed.add_field(name="Others", value="\n".join(others[:8]), inline=False)
    
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
        
        translated = translator.translate_text(text, target_lang)
        
        if translated:
            lang_info = LANGUAGES[target_lang]
            
            embed = discord.Embed(color=discord.Color.blue())
            embed.set_author(name=f"Translation by {ctx.author.display_name}", 
                           icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
            
            # Original text
            if len(text) > 800:
                original_display = text[:797] + "..."
            else:
                original_display = text
            
            embed.add_field(name=f"🇺🇸 Original", value=original_display, inline=False)
            
            # Translated text
            if len(translated) > 800:
                translated_display = translated[:797] + "..."
            else:
                translated_display = translated
            
            embed.add_field(name=f"{lang_info['flag']} {lang_info['name']}", value=translated_display, inline=False)
            
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
        description="**Auto-translates English messages to users' preferred languages**",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="🚀 Quick Start",
        value="1. Admin: `!auto enable`\n2. Users: `!mylang` (select from dropdown)\n3. Send English messages → Auto-translation!",
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
        name="🎯 Translation Features",
        value="• Auto-translate English messages\n• Click dropdown on translations for more languages\n• Manual translation with `!translate`",
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