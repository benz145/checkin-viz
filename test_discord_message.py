#!/usr/bin/env python3
"""
Test script to simulate Discord message processing
This simulates what happens when you send a message through Discord
"""
import os
import sys
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

load_dotenv()

from helpers import fetchone, with_psycopg
from utils import get_tier
from base_queries import get_current_challenge, challenger_by_discord_id, get_current_challenge_week, insert_checkin

def test_tier_extraction_only(message_content):
    """
    Just test tier extraction without saving to database
    No Discord ID or name needed!
    """
    print(f"\n{'='*60}")
    print(f"Testing Tier Extraction: '{message_content}'")
    print(f"{'='*60}\n")
    
    tier = get_tier(message_content)
    
    if tier == "unknown":
        print("✗ No tier detected in message")
        print("   The bot would ignore this message")
        return None
    
    print(f"✓ Tier detected: {tier}")
    
    tier_number = int(tier[1:])
    if tier_number > 10:
        print("🔥 Would add 🔥 reaction (T10+ check-in)")
    
    print("\n✓ Tier extraction works! (No database save)")
    return tier

def simulate_message_processing(message_content, user_identifier=None, use_name=False):
    """
    Simulate what happens when a Discord message is sent
    This mimics the on_message handler in bot.py
    
    Args:
        message_content: The message to process
        user_identifier: Either Discord ID (string) or challenger name
        use_name: If True, look up by name instead of Discord ID
    """
    print(f"\n{'='*60}")
    print(f"Simulating Discord Message: '{message_content}'")
    if user_identifier:
        print(f"User: {user_identifier} ({'name' if use_name else 'Discord ID'})")
    print(f"{'='*60}\n")
    
    # Step 1: Extract tier (same as bot.py line 137)
    tier = get_tier(message_content)
    
    if tier == "unknown":
        print("✗ No tier detected in message")
        print("   The bot would ignore this message")
        return None
    
    print(f"✓ Tier detected: {tier}")
    
    if not user_identifier:
        print("⚠️  No user identifier provided - cannot save to database")
        print("   This is just a tier extraction test")
        return None
    
    # Step 2: Check if user exists
    if use_name:
        challenger = fetchone(
            "select * from challengers where name = %s",
            [user_identifier],
        )
        if not challenger:
            print(f"✗ User with name '{user_identifier}' not found in database")
            print("\n   Available challengers:")
            all_challengers = fetchone("SELECT name FROM challengers LIMIT 10", [])
            if all_challengers:
                print("   (Check database for full list)")
            return None
    else:
        challenger = fetchone(
            "select * from challengers where discord_id = %s",
            [str(user_identifier)],
        )
        if not challenger:
            print(f"✗ User with Discord ID '{user_identifier}' not found in database")
            print("\n   To add yourself, run this SQL:")
            print(f"   INSERT INTO challengers (name, discord_id, tz, bmr)")
            print(f"   VALUES ('Your Name', '{user_identifier}', 'America/New_York', 2000);")
            return None
    
    print(f"✓ User found: {challenger.name}")
    
    # Step 3: Get current challenge week
    try:
        challenge_week = get_current_challenge_week(challenger.tz)
        challenge = get_current_challenge()
        
        if not challenge_week or not challenge:
            print("✗ No active challenge or challenge week found")
            return None
        
        print(f"✓ Challenge: {challenge.name}")
        print(f"✓ Challenge Week ID: {challenge_week.id}")
    except Exception as e:
        print(f"✗ Error getting challenge: {e}")
        return None
    
    # Step 4: Save check-in (same as bot.py line 187)
    try:
        checkin_id = with_psycopg(insert_checkin(message_content, tier, challenger, challenge_week.id))
        print(f"✓ Check-in saved! ID: {checkin_id}")
        
        # Step 5: Check for special reactions
        tier_number = int(tier[1:])
        if tier_number > 10:
            print("🔥 Would add 🔥 reaction (T10+ check-in)")
        
        return checkin_id
    except Exception as e:
        print(f"✗ Error saving check-in: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  # Just test tier extraction (no Discord ID needed):")
        print("  python3 test_discord_message.py 'MESSAGE'")
        print("\n  # Test with full database save (use Discord ID):")
        print("  python3 test_discord_message.py 'MESSAGE' DISCORD_ID")
        print("\n  # Test with full database save (use challenger name):")
        print("  python3 test_discord_message.py 'MESSAGE' --name 'Challenger Name'")
        print("\nExamples:")
        print("  python3 test_discord_message.py 'T1 checkin'")
        print("  python3 test_discord_message.py 'T1 checkin' '123456789012345678'")
        print("  python3 test_discord_message.py 'T1 checkin' --name 'John Doe'")
        sys.exit(1)
    
    message = sys.argv[1]
    
    print("\n" + "="*60)
    print("Discord Message Processing Test")
    print("="*60)
    
    # If only message provided, just test tier extraction
    if len(sys.argv) == 2:
        tier = test_tier_extraction_only(message)
        if tier:
            print(f"\n✓ Tier extraction successful: {tier}")
            print("\nTo save to database, provide a Discord ID or name:")
            print("  python3 test_discord_message.py 'T1 checkin' YOUR_DISCORD_ID")
            print("  python3 test_discord_message.py 'T1 checkin' --name 'Your Name'")
        return
    
    # Check if using --name flag
    use_name = False
    user_identifier = None
    
    if len(sys.argv) >= 3:
        if sys.argv[2] == '--name' and len(sys.argv) >= 4:
            use_name = True
            user_identifier = sys.argv[3]
        else:
            user_identifier = sys.argv[2]
    
    checkin_id = simulate_message_processing(message, user_identifier, use_name)
    
    if checkin_id:
        print(f"\n✓ Success! Check-in ID {checkin_id} was created")
        print("\nTo verify in database:")
        print(f"  SELECT * FROM checkins WHERE id = {checkin_id};")
    else:
        print("\n✗ Failed to process message")
    
    print()

if __name__ == "__main__":
    main()

