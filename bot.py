import discord
from discord.ext import commands
import requests
import os
from dotenv import load_dotenv
import asyncio
import sqlite3
from datetime import datetime
import json
import re

load_dotenv()

# ========== CONFIGURATION ==========
AUTO_TRANSLATE_CHANNELS = []  # Add your channel IDs
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
                show_original BOOLEAN DEFAULT 1,
                method TEXT DEFAULT 'thread',
                updated_at TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channel_settings (
                channel_id INTEGER PRIMARY KEY,
                enabled BOOLEAN DEFAULT 0,
                method TEXT DEFAULT 'thread'
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
            return None
        
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
        
        # Check for common non-English words
        common_non_english = {
            'es': ['hola', 'gracias', 'por favor', 'cómo', 'qué'],
            'fr': ['bonjour', 'merci', 's\'il vous plaît', 'comment', 'quoi'],
            'de': ['hallo', 'danke', 'bitte', 'wie', 'was'],
            'it': ['ciao', 'grazie', 'per favore', 'come', 'cosa'],
            'pt': ['olá', 'obrigado', 'por favor', 'como', 'o que'],
            'vi': ['xin chào', 'cảm ơn', 'làm ơn', 'như thế nào', 'cái gì'],
            'ja': ['こんにちは', 'ありがとう', 'お願いします', 'どうやって', '何'],
            'ko': ['안녕하세요', '감사합니다', '부탁합니다', '어떻게', '무엇'],
        }
        
        text_lower = text.lower()
        for lang, words in common_non_english.items():
            if any(word in text_lower for word in words):
                return lang
        
        # Default to English if no other language detected
        return 'en'
    
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
    
    def is_channel_enabled(self, channel_id):
        """Check if auto-translate is enabled for channel"""
        return channel_id in AUTO_TRANSLATE_CHANNELS
    
    def check_cooldown(self, user_id):
        """Check user cooldown"""
        now = datetime.now()
        last_time = self.user_cooldowns.get(user_id)
        
        if last_time and (now - last_time).seconds < COOLDOWN_SECONDS:
            return False
        
        self.user_cooldowns[user_id] = now
        return True

# ========== BOT SETUP ==========
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)
translator = SelectiveTranslator()

# ========== SOLUTION 1: THREAD-BASED (Recommended) ==========
async def create_per_user_threads(message, user_languages):
    """Create separate threads for each language group"""
    original_author = message.author
    original_content = message.content
    
    # Create a main thread for translations
    thread_name = f"Translations for {original_author.display_name}"
    
    try:
        # Create a public thread
        thread = await message.create_thread(
            name=thread_name,
            auto_archive_duration=60
        )
        
        # Send original message in thread
        await thread.send(
            f"**Original message by {original_author.mention}:**\n"
            f"{original_content}\n\n"
            f"**Translations below ↓**"
        )
        
        # Create language-specific channels within thread
        for user_id, lang_code in user_languages.items():
            user = await bot.fetch_user(user_id)
            lang_info = LANGUAGES.get(lang_code, {'name': lang_code.upper(), 'flag': '🌐'})
            
            # Translate for this user
            translated = translator.translate_text(original_content, lang_code, SOURCE_LANGUAGE)
            
            if translated:
                # Send user-specific message
                await thread.send(
                    f"{lang_info['flag']} **For {user.mention} ({lang_info['name']}):**\n"
                    f"{translated}"
                )
        
        # Add control message
        await thread.send(
            f"\n🔧 **Thread Controls:**\n"
            f"• Set your language: `!mylang [code]`\n"
            f"• Available languages: `!langs`\n"
            f"• This thread auto-archives after 1 hour"
        )
        
    except Exception as e:
        print(f"❌ Error creating thread: {e}")

# ========== SOLUTION 2: REACTION-BASED (Simple) ==========
async def send_reaction_translations(message, user_languages):
    """Send translations via reactions and hidden messages"""
    original_author = message.author
    
    # Add translation reactions
    available_languages = set(user_languages.values())
    
    for lang_code in available_languages:
        flag = LANGUAGES.get(lang_code, {}).get('flag', '🌐')
        try:
            await message.add_reaction(flag)
        except:
            pass
    
    # Send instruction
    instruction = await message.reply(
        f"**🌐 This message has translations available!**\n"
        f"React with your country's flag to see translation in your language.\n"
        f"Set your language first with `!mylang [code]`",
        mention_author=False
    )
    
    # Store message info for later
    await store_translation_info(message.id, user_languages)

async def store_translation_info(message_id, user_languages):
    """Store translation info for reaction handling"""
    # In a real implementation, you'd store this in a database
    # For simplicity, we'll just print it
    print(f"📝 Stored translation info for message {message_id}: {user_languages}")

# ========== SOLUTION 3: WEBHOOK-BASED (Most Advanced) ==========
async def send_webhook_translations(message, user_languages):
    """Use webhooks to send personalized messages"""
    channel = message.channel
    
    # Group users by language
    language_groups = {}
    for user_id, lang_code in user_languages.items():
        if lang_code not in language_groups:
            language_groups[lang_code] = []
        language_groups[lang_code].append(user_id)
    
    # Create webhook for each language group
    for lang_code, user_ids in language_groups.items():
        if lang_code == SOURCE_LANGUAGE:
            continue  # Skip if same as source
        
        lang_info = LANGUAGES.get(lang_code, {'name': lang_code.upper(), 'flag': '🌐'})
        
        # Translate message
        translated = translator.translate_text(message.content, lang_code, SOURCE_LANGUAGE)
        
        if translated:
            # Create or get webhook
            webhooks = await channel.webhooks()
            webhook = None
            
            for wh in webhooks:
                if wh.name == f"Translator-{lang_code}":
                    webhook = wh
                    break
            
            if not webhook:
                webhook = await channel.create_webhook(
                    name=f"Translator-{lang_code}",
                    reason="Auto-translation webhook"
                )
            
            # Prepare mention string for users
            mentions = []
            for user_id in user_ids[:5]:  # Limit to 5 mentions
                user = await bot.fetch_user(user_id)
                mentions.append(user.mention)
            
            mention_text = " ".join(mentions) if mentions else ""
            
            # Send via webhook
            await webhook.send(
                content=f"{lang_info['flag']} **Translation ({lang_info['name']})**\n"
                       f"{translated}\n\n"
                       f"{mention_text}" if mention_text else "",
                username=f"Translator ({lang_info['name']})",
                avatar_url=bot.user.avatar.url if bot.user.avatar else None,
                allowed_mentions=discord.AllowedMentions(users=True)
            )

# ========== EVENT HANDLERS ==========
@bot.event
async def on_ready():
    print(f'✅ {bot.user} is online!')
    print(f'🌍 Selective translation bot ready')
    
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="messages & translating selectively"
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
    
    # Detect language of message
    detected_lang = translator.detect_language(message.content)
    
    # Only translate if message is in source language
    if detected_lang != SOURCE_LANGUAGE:
        return
    
    # Get all members who can see this channel
    members = []
    if isinstance(message.channel, discord.TextChannel):
        members = [member for member in message.channel.members if not member.bot]
    else:
        return
    
    # Collect users who need translation
    user_languages = {}
    for member in members:
        if member.id == message.author.id:
            continue  # Skip original author
        
        user_lang = translator.get_user_language(member.id)
        
        # Only add if user's language is different from source
        if user_lang != SOURCE_LANGUAGE:
            user_languages[member.id] = user_lang
    
    if not user_languages:
        return
    
    # ===== CHOOSE TRANSLATION METHOD =====
    # Method 1: Thread-based (Recommended)
    await create_per_user_threads(message, user_languages)
    
    # Method 2: Reaction-based (Simple)
    # await send_reaction_translations(message, user_languages)
    
    # Method 3: Webhook-based (Advanced)
    # await send_webhook_translations(message, user_languages)

# ========== REACTION HANDLER ==========
@bot.event
async def on_reaction_add(reaction, user):
    """Handle translation reactions"""
    if user.bot:
        return
    
    # Check if this is a translation reaction
    message = reaction.message
    
    # Look for flag emojis
    flag_to_lang = {info['flag']: code for code, info in LANGUAGES.items()}
    
    if str(reaction.emoji) in flag_to_lang:
        lang_code = flag_to_lang[str(reaction.emoji)]
        
        # Check if user has this language set
        user_lang = translator.get_user_language(user.id)
        
        if user_lang == lang_code:
            # User reacted with their language flag
            # Here you would fetch and send the translation
            # For now, send a DM with translation
            try:
                translated = translator.translate_text(
                    message.content,
                    lang_code,
                    SOURCE_LANGUAGE
                )
                
                if translated:
                    lang_info = LANGUAGES.get(lang_code, {'name': lang_code.upper()})
                    await user.send(
                        f"**{lang_info['flag']} Translation ({lang_info['name']}):**\n"
                        f"{translated}\n\n"
                        f"*From: {message.author.display_name} in #{message.channel.name}*"
                    )
            except:
                pass

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
                  f"• You'll see translations in threads or via reactions\n"
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
    
    embed.add_field(
        name="What to expect",
        value=f"• Messages in {SOURCE_LANGUAGE.upper()} will be translated to {lang_info['name']}\n"
              f"• You'll see translations in separate threads\n"
              f"• React with {lang_info['flag']} to see translations",
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
        if channel.id in AUTO_TRANSLATE_CHANNELS:
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
                  "`!auto status` - Show all enabled channels",
            inline=False
        )
        
        await ctx.send(embed=embed)
        return
    
    action = action.lower()
    
    if action in ['enable', 'on', 'start']:
        if channel.id not in AUTO_TRANSLATE_CHANNELS:
            AUTO_TRANSLATE_CHANNELS.append(channel.id)
            
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
                      "4. Each user sees only their language",
                inline=False
            )
        else:
            embed = discord.Embed(
                title="⚠️ Already Enabled",
                description=f"Auto-translate is already enabled in {channel.mention}",
                color=discord.Color.orange()
            )
        
        await ctx.send(embed=embed)
        
    elif action in ['disable', 'off', 'stop']:
        if channel.id in AUTO_TRANSLATE_CHANNELS:
            AUTO_TRANSLATE_CHANNELS.remove(channel.id)
            
            embed = discord.Embed(
                title="❌ Auto-Translate Disabled",
                description=f"Auto-translate has been disabled in {channel.mention}",
                color=discord.Color.red()
            )
        else:
            embed = discord.Embed(
                title="⚠️ Already Disabled",
                description=f"Auto-translate is already disabled in {channel.mention}",
                color=discord.Color.orange()
            )
        
        await ctx.send(embed=embed)
        
    elif action == 'status':
        if not AUTO_TRANSLATE_CHANNELS:
            await ctx.send("❌ Auto-translate is not enabled in any channels.")
            return
        
        channels_list = []
        for channel_id in AUTO_TRANSLATE_CHANNELS:
            ch = bot.get_channel(channel_id)
            if ch:
                channels_list.append(f"• {ch.mention} ({ch.name})")
        
        embed = discord.Embed(
            title="📋 Auto-Translate Channels",
            description="\n".join(channels_list) if channels_list else "No channels",
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Total: {len(AUTO_TRANSLATE_CHANNELS)} channels")
        await ctx.send(embed=embed)
    
    else:
        await ctx.send("❌ Invalid action. Use: `enable`, `disable`, or `status`")

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
    
    embed = discord.Embed(
        title="🏓 Bot Status",
        color=discord.Color.green()
    )
    embed.add_field(name="Latency", value=f"{latency}ms", inline=True)
    embed.add_field(name="Active Channels", value=str(len(AUTO_TRANSLATE_CHANNELS)), inline=True)
    embed.add_field(name="Translation Method", value="Thread-based", inline=True)
    
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
        name="👤 For Users",
        value="`!mylang [code]` - Set your language\n"
              "`!mylang` - Show your current language\n"
              "`!translate [lang] [text]` - Manual translation\n"
              "`!langs` - List all languages",
        inline=False
    )
    
    embed.add_field(
        name="🛠️ For Admins",
        value="`!auto enable` - Enable in this channel\n"
              "`!auto disable` - Disable in this channel\n"
              "`!auto status` - Show enabled channels",
        inline=False
    )
    
    embed.add_field(
        name="🚀 Quick Setup",
        value="1. Admin: `!auto enable` (in desired channel)\n"
              "2. User1: `!mylang ko` (Korean user)\n"
              "3. User2: `!mylang vi` (Vietnamese user)\n"
              "4. Result: English messages create threads with Korean & Vietnamese translations",
        inline=False
    )
    
    embed.add_field(
        name="🎯 How it works",
        value="• Messages in English trigger translation\n"
              "• A thread is created for translations\n"
              "• Korean users see Korean translation\n"
              "• Vietnamese users see Vietnamese translation\n"
              "• Each user sees ONLY their language",
        inline=False
    )
    
    embed.set_footer(text="Deployed on Railway | Free translation service")
    await ctx.send(embed=embed)

# ========== RUN BOT ==========
if __name__ == "__main__":
    token = os.getenv('DISCORD_BOT_TOKEN')
    if token:
        bot.run(token)
    else:
        print("❌ ERROR: DISCORD_BOT_TOKEN not found!")
        print("Add it to Railway Variables")