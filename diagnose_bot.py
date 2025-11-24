#!/usr/bin/env python3
"""
Diagnostic script to check why the Discord bot might be failing
"""
import os
import sys
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

load_dotenv()

print("=" * 60)
print("Discord Bot Diagnostic")
print("=" * 60)
print()

# Check 1: Discord Token
print("1. Checking Discord Token...")
token = os.getenv("DISCORD_TOKEN")
if token:
    masked = token[:10] + "..." + token[-10:] if len(token) > 20 else "***"
    print(f"   ✓ Token found: {masked}")
    if len(token) < 50:
        print("   ⚠️  Token seems short - might be invalid")
    else:
        print("   ✓ Token length looks reasonable")
else:
    print("   ✗ DISCORD_TOKEN not found in environment")
    print("   Check your .env file")
print()

# Check 2: Database Connection
print("2. Checking Database Connection...")
try:
    from helpers import fetchone
    result = fetchone("SELECT version()")
    print(f"   ✓ Database connected: {result.version[:50]}...")
except Exception as e:
    print(f"   ✗ Database connection failed: {e}")
    print("   Bot needs database to function")
print()

# Check 3: Discord Library
print("3. Checking Discord Library...")
try:
    import discord
    print(f"   ✓ discord.py imported: {discord.__version__}")
except ImportError as e:
    print(f"   ✗ Failed to import discord: {e}")
    print("   Run: poetry install")
print()

# Check 4: Required Modules
print("4. Checking Required Modules...")
modules = [
    'chart', 'rule_sets', 'green', 'medals', 'medal_log',
    'base_queries', 'helpers', 'utils'
]
failed = []
for module in modules:
    try:
        __import__(module)
        print(f"   ✓ {module}")
    except ImportError as e:
        print(f"   ✗ {module}: {e}")
        failed.append(module)

if failed:
    print(f"\n   ⚠️  Missing modules: {', '.join(failed)}")
print()

# Check 5: Active Challenge
print("5. Checking Active Challenge...")
try:
    from base_queries import get_current_challenge
    challenge = get_current_challenge()
    if challenge:
        print(f"   ✓ Active challenge: {challenge.name}")
    else:
        print("   ⚠️  No active challenge found")
        print("   Bot can still run but may have limited functionality")
except Exception as e:
    print(f"   ✗ Error checking challenge: {e}")
print()

# Check 6: Bot Initialization
print("6. Testing Bot Initialization...")
try:
    import discord
    intents = discord.Intents.default()
    intents.message_content = True
    bot = discord.Bot(intents=intents)
    print("   ✓ Bot object created successfully")
    
    if token:
        print("   ✓ Token available for bot.run()")
        print("   ⚠️  Note: bot.run() will try to connect to Discord")
        print("   This will fail if:")
        print("     - Token is invalid/expired")
        print("     - Bot doesn't have required permissions")
        print("     - Network issues")
    else:
        print("   ✗ Cannot test bot.run() without token")
except Exception as e:
    print(f"   ✗ Failed to create bot: {e}")
    import traceback
    traceback.print_exc()
print()

# Summary
print("=" * 60)
print("Summary")
print("=" * 60)
print()

issues = []
if not token:
    issues.append("Missing DISCORD_TOKEN")
if failed:
    issues.append(f"Missing modules: {', '.join(failed)}")

if issues:
    print("⚠️  Issues found:")
    for issue in issues:
        print(f"   - {issue}")
    print("\nFix these issues before running the bot.")
else:
    print("✓ All basic checks passed!")
    print("\nIf the bot still fails to run, the issue might be:")
    print("  1. Invalid/expired Discord token")
    print("  2. Bot not added to Discord server")
    print("  3. Missing bot permissions")
    print("  4. Network/firewall issues")
    print("\nTry running the bot and check the error message:")
    print("  cd src")
    print("  poetry run python3 bot.py")

print()

