#!/usr/bin/env python3
"""
Script to verify Discord bot setup and test message processing
"""
import os
import sys
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

load_dotenv()

from helpers import fetchone, fetchall
from utils import get_tier
from base_queries import get_current_challenge, challenger_by_discord_id

def test_tier_extraction():
    """Test the get_tier function with various message formats"""
    print("=" * 60)
    print("Testing Tier Extraction")
    print("=" * 60)
    
    test_messages = [
        "T1 checkin",
        "checkin T2",
        "Just did a T3 workout!",
        "T4",
        "t5 check-in",
        "T10 checkin",
        "T12",
        "no tier here",
        "checkin",
    ]
    
    for msg in test_messages:
        tier = get_tier(msg)
        status = "✓" if tier != "unknown" else "✗"
        print(f"{status} '{msg}' → {tier}")
    
    print()

def test_database_connection():
    """Test database connection"""
    print("=" * 60)
    print("Testing Database Connection")
    print("=" * 60)
    
    try:
        result = fetchone("SELECT version()")
        print(f"✓ Database connected: {result.version[:50]}...")
        return True
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        return False

def test_active_challenge():
    """Check if there's an active challenge"""
    print("=" * 60)
    print("Testing Active Challenge")
    print("=" * 60)
    
    try:
        challenge = get_current_challenge()
        if challenge:
            print(f"✓ Active challenge found:")
            print(f"  - ID: {challenge.id}")
            print(f"  - Name: {challenge.name}")
            print(f"  - Start: {challenge.start}")
            print(f"  - End: {challenge.end}")
            return challenge
        else:
            print("✗ No active challenge found")
            return None
    except Exception as e:
        print(f"✗ Error checking challenge: {e}")
        return None

def test_discord_user(discord_id):
    """Test if a Discord user exists in the database"""
    print("=" * 60)
    print(f"Testing Discord User: {discord_id}")
    print("=" * 60)
    
    if not discord_id:
        print("✗ No Discord ID provided")
        print("  To get your Discord ID:")
        print("  1. Enable Developer Mode in Discord")
        print("  2. Right-click your profile > Copy ID")
        return None
    
    try:
        challenger = challenger_by_discord_id(str(discord_id))
        if challenger:
            print(f"✓ User found in database:")
            print(f"  - Name: {challenger.name}")
            print(f"  - Discord ID: {challenger.discord_id}")
            print(f"  - Timezone: {challenger.tz}")
            print(f"  - BMR: {challenger.bmr}")
            return challenger
        else:
            print(f"✗ User with Discord ID '{discord_id}' not found in database")
            print("\n  To add yourself, run this SQL:")
            print(f"  INSERT INTO challengers (name, discord_id, tz, bmr)")
            print(f"  VALUES ('Your Name', '{discord_id}', 'America/New_York', 2000);")
            return None
    except Exception as e:
        print(f"✗ Error checking user: {e}")
        return None

def test_discord_token():
    """Check if Discord token is set"""
    print("=" * 60)
    print("Testing Discord Token")
    print("=" * 60)
    
    token = os.getenv("DISCORD_TOKEN")
    if token:
        # Mask the token for security
        masked = token[:10] + "..." + token[-10:] if len(token) > 20 else "***"
        print(f"✓ Discord token is set: {masked}")
        return True
    else:
        print("✗ DISCORD_TOKEN not found in environment")
        print("  Add it to your .env file:")
        print("  DISCORD_TOKEN=your_token_here")
        return False

def main():
    print("\n" + "=" * 60)
    print("Discord Bot Setup Verification")
    print("=" * 60 + "\n")
    
    # Test 1: Tier extraction
    test_tier_extraction()
    
    # Test 2: Database connection
    db_ok = test_database_connection()
    print()
    
    if not db_ok:
        print("⚠️  Cannot continue without database connection")
        return
    
    # Test 3: Active challenge
    challenge = test_active_challenge()
    print()
    
    # Test 4: Discord token
    token_ok = test_discord_token()
    print()
    
    # Test 5: Discord user (optional)
    if len(sys.argv) > 1:
        discord_id = sys.argv[1]
        test_discord_user(discord_id)
    else:
        print("=" * 60)
        print("Discord User Check (Skipped)")
        print("=" * 60)
        print("To check your Discord user, run:")
        print(f"  python3 {sys.argv[0]} YOUR_DISCORD_ID")
        print()
    
    # Summary
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Database: {'✓' if db_ok else '✗'}")
    print(f"Active Challenge: {'✓' if challenge else '✗'}")
    print(f"Discord Token: {'✓' if token_ok else '✗'}")
    print()
    
    if db_ok and challenge and token_ok:
        print("✓ Ready to run the Discord bot!")
        print("\nTo start the bot:")
        print("  cd src")
        print("  poetry run python3 bot.py")
    else:
        print("⚠️  Please fix the issues above before running the bot")
    print()

if __name__ == "__main__":
    main()

