import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio
import sqlite3
from datetime import datetime, timedelta
from googletrans import Translator as GoogleTranslator
import re
import logging
from contextlib import closing
import hashlib

load_dotenv()

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

# Language mapping with flags and names
LANGUAGES = {
    'en': {'name': 'English', 'flag': '🇺🇸', 'emoji': '🇺🇸'},
    'es': {'name': 'Spanish', 'flag': '🇪🇸', 'emoji': '🇪🇸'},
    'fr': {'name': 'French', 'flag': '🇫🇷', 'emoji': '🇫🇷'},
    'de': {'name': 'German', 'flag': '🇩🇪', 'emoji': '🇩🇪'},
    'it': {'name': 'Italian', 'flag': '🇮🇹', 'emoji': '🇮🇹'},
    'pt': {'name': 'Portuguese', 'flag': '🇵🇹', 'emoji': '🇵🇹'},
    'ru': {'name': 'Russian', 'flag': '🇷🇺', 'emoji': '🇷🇺'},
    'ja': {'name': 'Japanese', 'flag': '🇯🇵', 'emoji': '🇯🇵'},
    'ko': {'name': 'Korean', 'flag': '🇰🇷', 'emoji': '🇰🇷'},
    'zh': {'name': 'Chinese', 'flag': '🇨🇳', 'emoji': '🇨🇳'},
    'ar': {'name': 'Arabic', 'flag': '🇸🇦', 'emoji': '🇸🇦'},
    'hi': {'name': 'Hindi', 'flag': '🇮🇳', 'emoji': '🇮🇳'},
    'vi': {'name': 'Vietnamese', 'flag': '🇻🇳', 'emoji': '🇻🇳'},
    'th': {'name': 'Thai', 'flag': '🇹🇭', 'emoji': '🇹🇭'},
    'id': {'name': 'Indonesian', 'flag': '🇮🇩', 'emoji': '🇮🇩'},
    'tr': {'name': 'Turkish', 'flag': '🇹🇷', 'emoji': '🇹🇷'},
    'pl': {'name': 'Polish', 'flag': '🇵🇱', 'emoji': '🇵🇱'},
    'nl': {'name': 'Dutch', 'flag': '🇳🇱', 'emoji': '🇳🇱'},
    'sv': {'name': 'Swedish', 'flag': '🇸🇪', 'emoji': '🇸🇪'},
    'da': {'name': 'Danish', 'flag': '🇩🇰', 'emoji': '🇩🇰'},
    'fi': {'name': 'Finnish', 'flag': '🇫🇮', 'emoji': '🇫🇮'},
    'no': {'name': 'Norwegian', 'flag': '🇳🇴', 'emoji': '🇳🇴'},
}

# Reverse mapping: flag emoji to language code
FLAG_TO_LANG = {
    '🇺🇸': 'en', '🇪🇸': 'es', '🇫🇷': 'fr', '🇩🇪': 'de',
    '🇮🇹': 'it', '🇵🇹': 'pt', '🇷🇺': 'ru', '🇯🇵': 'ja',
    '🇰🇷': 'ko', '🇨🇳': 'zh', '🇸🇦': 'ar', '🇮🇳': 'hi',
    '🇻🇳': 'vi', '🇹🇭': 'th', '🇮🇩': 'id', '🇹🇷': 'tr',
    '🇵🇱': 'pl', '🇳🇱': 'nl', '🇸🇪': 'sv', '🇩🇰': 'da',
    '🇫🇮': 'fi', '🇳🇴': 'no'
}

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
            # Clean the text
            text = text.strip()
            if not text or len(text) < 2:
                return None
            
            # Cache key
            cache_key = hashlib.md5(f"{text}:{target_lang}:{source_lang}".encode()).hexdigest()
            
            # Check cache
            cached = self._get_cached_translation(cache_key)
            if cached:
                return cached
            
            # Translate
            logger.info(f"Translating: '{text[:50]}...' → {target_lang}")
            result = self.google_translator.translate(
                text, 
                dest=target_lang, 
                src=source_lang
            )
            
            if result and result.text:
                # Cache the result
                self._cache_translation(cache_key, text, result.text, target_lang, source_lang)
                return result.text
            return None
        except Exception as e:
            logger.error(f"Translation error: {e}")
            return None

    def _get_cached_translation(self, cache_key):
        """Get translation from cache"""
        # Memory cache
        if cache_key in self.translation_cache:
            return self.translation_cache[cache_key]
        
        # Database cache
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT translated_text FROM translation_cache WHERE cache_key = ?",
                    (cache_key,)
                )
                result = cursor.fetchone()
                if result:
                    self.translation_cache[cache_key] = result[0]
                    return result[0]
        except Exception as e:
            logger.error(f"Cache error: {e}")
        return None

    def _cache_translation(self, cache_key, original_text, translated_text, target_lang, source_lang):
        """Cache translation"""
        self.translation_cache[cache_key] = translated_text
        
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO translation_cache 
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (cache_key, original_text, translated_text, target_lang, source_lang))
                conn.commit()
        except Exception as e:
            logger.error(f"Cache save error: {e}")

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
async def create_translation_embed(original_message, translated_text, target_lang, translator_name="Google Translate"):
    """Create a clean embed for translations"""
    lang_info = LANGUAGES.get(target_lang, {'name': target_lang.upper(), 'emoji': '🌐'})
    
    embed = discord.Embed(
        color=discord.Color.blue()
    )
    
    # Set author from original message
    embed.set_author(
        name=f"{original_message.author.display_name}",
        icon_url=original_message.author.avatar.url if original_message.author.avatar else None
    )
    
    # Original text (truncated if too long)
    original_display = original_message.content
    if len(original_display) > 500:
        original_display = original_display[:497] + "..."
    
    embed.add_field(
        name=f"🇺🇸 Original (English)",
        value=original_display,
        inline=False
    )
    
    # Translated text
    translated_display = translated_text
    if len(translated_display) > 500:
        translated_display = translated_display[:497] + "..."
    
    embed.add_field(
        name=f"{lang_info['emoji']} {lang_info['name']} Translation",
        value=translated_display,
        inline=False
    )
    
    # Footer with metadata
    embed.set_footer(
        text=f"Translated via {translator_name} • React with a flag to translate!"
    )
    
    return embed

async def send_auto_translation(message, target_lang, mention_user=False):
    """Send an auto-translation for a message"""
    try:
        translated = translator.translate_text(message.content, target_lang, SOURCE_LANGUAGE)
        if not translated:
            return False
        
        # Create embed
        embed = await create_translation_embed(message, translated, target_lang)
        
        # Send the translation
        if mention_user:
            # Get user who needs translation
            user_lang = translator.get_user_language(message.author.id)
            if user_lang == target_lang:
                reply = await message.reply(
                    f"**Translation for you:**",
                    embed=embed,
                    mention_author=False
                )
            else:
                reply = await message.reply(
                    embed=embed,
                    mention_author=False
                )
        else:
            reply = await message.reply(
                embed=embed,
                mention_author=False
            )
        
        # Add flag reactions for quick translations
        popular_flags = ['🇪🇸', '🇫🇷', '🇩🇪', '🇯🇵', '🇰🇷', '🇻🇳', '🇨🇳']
        for flag in popular_flags[:3]:  # Add 3 popular flags
            try:
                await reply.add_reaction(flag)
            except:
                pass
        
        return True
    except Exception as e:
        logger.error(f"Error sending auto-translation: {e}")
        return False

# ========== EVENT HANDLERS ==========
@bot.event
async def on_ready():
    logger.info(f'✅ {bot.user} is online!')
    
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="!help | React with flags to translate!"
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
    
    # Detect if message is in English (simple check)
    english_words = ['the', 'and', 'you', 'that', 'have', 'for', 'with', 'this', 'thank', 'thanks']
    text_lower = message.content.lower()
    is_english = any(f' {word} ' in f' {text_lower} ' for word in english_words)
    
    if not is_english:
        return
    
    logger.info(f"📨 Auto-translating message from {message.author}")
    
    # Get all members who can see this channel
    try:
        members = []
        if isinstance(message.channel, discord.TextChannel):
            members = [member for member in message.channel.members if not member.bot]
        
        # Find users who need translation
        users_to_translate = {}
        for member in members:
            user_lang = translator.get_user_language(member.id)
            if user_lang != SOURCE_LANGUAGE and user_lang not in users_to_translate:
                users_to_translate[user_lang] = member.id
        
        # Send translations for each language
        for lang_code in users_to_translate.keys():
            if lang_code in LANGUAGES:
                await asyncio.sleep(0.5)  # Small delay between translations
                await send_auto_translation(message, lang_code, mention_user=True)
                
    except Exception as e:
        logger.error(f"Error in auto-translation: {e}")

@bot.event
async def on_reaction_add(reaction, user):
    """Handle flag reactions for on-demand translation"""
    # Ignore bot reactions
    if user.bot:
        return
    
    # Check if reaction is a flag emoji
    emoji_str = str(reaction.emoji)
    if emoji_str not in FLAG_TO_LANG:
        return
    
    # Get the message
    message = reaction.message
    
    # Don't translate bot messages or translations
    if message.author.bot:
        return
    
    # Check cooldown
    if not translator.check_cooldown(user.id):
        try:
            await reaction.remove(user)
        except:
            pass
        return
    
    lang_code = FLAG_TO_LANG[emoji_str]
    lang_info = LANGUAGES.get(lang_code)
    
    # Translate the message
    async with message.channel.typing():
        translated = translator.translate_text(message.content, lang_code, SOURCE_LANGUAGE)
        
        if not translated:
            try:
                await reaction.remove(user)
            except:
                pass
            return
        
        # Create embed
        embed = await create_translation_embed(message, translated, lang_code)
        
        # Send as reply to the reaction
        try:
            # Check if we already translated this message for this language
            async for msg in message.channel.history(limit=10):
                if msg.author == bot.user and msg.reference and msg.reference.message_id == message.id:
                    # Check if embed already has this language
                    for field in msg.embeds[0].fields if msg.embeds else []:
                        if lang_info['name'] in field.name:
                            # Already translated, just acknowledge
                            try:
                                await reaction.remove(user)
                            except:
                                pass
                            return
            
            # Send new translation
            reply = await message.reply(
                f"**{lang_info['emoji']} Translation requested by {user.mention}**",
                embed=embed,
                mention_author=False
            )
            
            # Add other popular flag reactions
            popular_flags = ['🇪🇸', '🇫🇷', '🇩🇪', '🇯🇵', '🇰🇷', '🇻🇳', '🇨🇳']
            for flag in popular_flags[:3]:
                if flag != emoji_str:
                    try:
                        await reply.add_reaction(flag)
                    except:
                        pass
            
        except Exception as e:
            logger.error(f"Error sending reaction translation: {e}")

# ========== COMMANDS ==========
@bot.command(name="mylang")
async def set_language(ctx, lang_code: str = None):
    """Set your preferred language for auto-translation"""
    if not lang_code:
        current = translator.get_user_language(ctx.author.id)
        lang_info = LANGUAGES.get(current, {'name': current.upper(), 'emoji': '🌐'})
        
        embed = discord.Embed(
            title="🌍 Your Language Settings",
            description=f"**Current language:** {lang_info['emoji']} {lang_info['name']}",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="How to change:",
            value="Use `!mylang [code]`\nExample: `!mylang vi`",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    lang_code = lang_code.lower()
    
    if lang_code not in LANGUAGES:
        # Show available languages
        lang_list = "\n".join([f"{info['emoji']} `{code}` - {info['name']}" 
                              for code, info in list(LANGUAGES.items())[:15]])
        
        embed = discord.Embed(
            title="❌ Invalid Language Code",
            description=f"Available languages:\n{lang_list}",
            color=discord.Color.red()
        )
        embed.set_footer(text="Use !langs to see all languages")
        await ctx.send(embed=embed)
        return
    
    translator.set_user_language(ctx.author.id, lang_code)
    lang_info = LANGUAGES[lang_code]
    
    embed = discord.Embed(
        title="✅ Language Set",
        description=f"Your language has been set to:\n{lang_info['emoji']} **{lang_info['name']}**",
        color=discord.Color.green()
    )
    embed.add_field(
        name="What happens now?",
        value="• English messages will be auto-translated for you\n• You can react with flags to translate any message",
        inline=False
    )
    await ctx.send(embed=embed)

@bot.command(name="auto")
@commands.has_permissions(manage_channels=True)
async def toggle_auto(ctx, action: str = None):
    """Enable/disable auto-translate in this channel"""
    if not action:
        enabled = translator.is_channel_enabled(ctx.channel.id)
        
        embed = discord.Embed(
            title="⚙️ Auto-Translate Settings",
            color=discord.Color.blue()
        )
        
        if enabled:
            embed.description = "✅ **ENABLED** in this channel"
            embed.add_field(
                name="How it works:",
                value="1. Users set language with `!mylang [code]`\n2. English messages auto-translate\n3. React with flags for quick translations",
                inline=False
            )
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
            description="This channel will now auto-translate English messages!",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Quick Setup:",
            value="1. `!mylang vi` - Set to Vietnamese\n2. `!mylang es` - Set to Spanish\n3. Send English message → Auto-translation!",
            inline=False
        )
        embed.add_field(
            name="Additional Features:",
            value="• React with flag emojis to translate any message\n• Use `!translate [lang] [text]` for manual translations",
            inline=False
        )
        
        await ctx.send(embed=embed)
        
        # Send a test message
        test_embed = discord.Embed(
            title="🧪 Test Message",
            description="Hello everyone! Welcome to the channel.",
            color=discord.Color.gold()
        )
        test_embed.set_footer(text="This should auto-translate for users with different languages set")
        test_msg = await ctx.send(embed=test_embed)
        
        # Add flag reactions
        for flag in ['🇪🇸', '🇫🇷', '🇯🇵', '🇰🇷', '🇻🇳']:
            try:
                await test_msg.add_reaction(flag)
            except:
                pass

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
        description="Set your language with `!mylang [code]`",
        color=discord.Color.blue()
    )
    
    # Split languages into two columns
    langs_list = list(LANGUAGES.items())
    mid = len(langs_list) // 2
    
    col1 = "\n".join([f"{info['emoji']} `{code}` - {info['name']}" 
                     for code, info in langs_list[:mid]])
    col2 = "\n".join([f"{info['emoji']} `{code}` - {info['name']}" 
                     for code, info in langs_list[mid:]])
    
    embed.add_field(name="Languages A-M", value=col1, inline=True)
    embed.add_field(name="Languages N-Z", value=col2, inline=True)
    
    embed.add_field(
        name="🎯 Quick Picks",
        value="• 🇻🇳 `vi` - Vietnamese\n• 🇰🇷 `ko` - Korean\n• 🇯🇵 `ja` - Japanese\n• 🇪🇸 `es` - Spanish\n• 🇫🇷 `fr` - French",
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
        
        translated = translator.translate_text(text, target_lang)
        
        if translated:
            lang_info = LANGUAGES[target_lang]
            
            embed = discord.Embed(color=discord.Color.blue())
            embed.set_author(name=f"Translation by {ctx.author.display_name}", 
                           icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
            
            if len(text) > 500:
                text = text[:497] + "..."
            if len(translated) > 500:
                translated = translated[:497] + "..."
            
            embed.add_field(name=f"🇺🇸 English", value=text, inline=False)
            embed.add_field(name=f"{lang_info['emoji']} {lang_info['name']}", value=translated, inline=False)
            
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
        description="**Auto-translates English messages + Flag reactions for quick translations**",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="🚀 Quick Start",
        value="1. Admin: `!auto enable`\n2. Users: `!mylang vi` (or any language)\n3. Send English message → Auto-translation!",
        inline=False
    )
    
    embed.add_field(
        name="👤 User Commands",
        value="• `!mylang [code]` - Set your language\n• `!translate [lang] [text]` - Manual translation\n• `!langs` - List all languages",
        inline=False
    )
    
    embed.add_field(
        name="🛠️ Admin Commands",
        value="• `!auto enable` - Enable auto-translate\n• `!auto disable` - Disable auto-translate",
        inline=False
    )
    
    embed.add_field(
        name="🎯 Flag Reactions",
        value="React to any message with:\n🇪🇸 🇫🇷 🇩🇪 🇯🇵 🇰🇷 🇻🇳 🇨🇳\nTo get instant translations!",
        inline=False
    )
    
    embed.set_footer(text="Made with ❤️ by Translation Bot")
    
    await ctx.send(embed=embed)

@bot.command(name="test")
async def test_command(ctx):
    """Test the translation system"""
    embed = discord.Embed(
        title="🧪 Translation Test",
        description="Testing the translation system...",
        color=discord.Color.gold()
    )
    
    test_msg = await ctx.send(embed=embed)
    
    # Enable channel if not already
    if not translator.is_channel_enabled(ctx.channel.id):
        translator.enable_channel(ctx.channel.id)
    
    # Set user language to Vietnamese for test
    translator.set_user_language(ctx.author.id, 'vi')
    
    # Send a test English message
    test_embed = discord.Embed(
        title="Test Message",
        description="Hello! This is a test message to check if translation works.",
        color=discord.Color.blue()
    )
    test_embed.add_field(name="Expected", value="Should auto-translate to Vietnamese", inline=False)
    
    test_message = await ctx.send(embed=test_embed)
    
    # Wait a bit then show what should happen
    await asyncio.sleep(2)
    
    result_embed = discord.Embed(
        title="✅ Test Complete",
        color=discord.Color.green()
    )
    result_embed.add_field(
        name="What should happen:",
        value="1. Your language is set to Vietnamese\n2. The test message should auto-translate\n3. You can react with flags to translate",
        inline=False
    )
    result_embed.add_field(
        name="Try it yourself:",
        value="React to any message with:\n🇪🇸 🇫🇷 🇩🇪 🇯🇵\nFor instant translations!",
        inline=False
    )
    
    await ctx.send(embed=result_embed)
    
    # Add flag reactions to test message
    for flag in ['🇪🇸', '🇫🇷', '🇩🇪', '🇯🇵']:
        try:
            await test_message.add_reaction(flag)
        except:
            pass

# ========== RUN BOT ==========
if __name__ == "__main__":
    token = os.getenv('DISCORD_BOT_TOKEN')
    if token:
        logger.info("Starting translation bot...")
        bot.run(token)
    else:
        logger.error("❌ ERROR: DISCORD_BOT_TOKEN not found!")