#!/usr/bin/env python3
"""
Test script specifically for Discord bot medal messages.
This simulates what medal messages the bot would send when a check-in earns medals.
Uses the same message construction logic as bot.py
"""
import os
import sys

# Try to import dotenv, give helpful error if not available
try:
    from dotenv import load_dotenv
except ImportError:
    print("=" * 60)
    print("ERROR: Missing dependencies")
    print("=" * 60)
    print("\nThis script requires dependencies from the poetry environment.")
    print("\nTo run this script, use:")
    print("  poetry run python3 test_medal_messages.py [options]")
    print("\nOr if poetry is not in your PATH:")
    print("  export PATH=\"/Users/benlang/.local/bin:$PATH\"")
    print("  poetry run python3 test_medal_messages.py [options]")
    print("\nFor help:")
    print("  poetry run python3 test_medal_messages.py --help")
    sys.exit(1)

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

load_dotenv()

from helpers import fetchone, fetchall, with_psycopg
from utils import get_tier
from base_queries import (
    get_current_challenge, 
    get_current_challenge_week, 
    insert_checkin,
    challenger_by_discord_id
)
import medals
import medal_log

# Copy medal name mapping and describe_medal function from bot.py
nice_medal_names = {
    "highest_tier_challenge": "Highest Overall Tier",
    "highest_tier_week": "Highest Weekly Tier",
    "gold": "Gold Week",
    "all_gold": "All Gold",
    "first_to_green": "First to Green",
    "green": "Green Week",
    "all_green": "All Green",
    "earliest_for_week": "Earliest Weekly Check-in",
    "latest_for_week": "Latest Weekly Check-in",
}


def describe_medal(medal_name):
    """Describe a medal with a nice name (same as bot.py)"""
    fallback = medal_name.replace("_", " ").replace("  ", " ").title()
    return nice_medal_names.get(medal_name, fallback)


def format_medal_message(medal):
    """
    Format a single medal message line (same logic as bot.py lines 195-213)
    This matches the exact message construction used in bot.py
    """
    nice_name = describe_medal(medal.medal_name)
    emoji = medal.medal_emoji or ""
    
    if medal.stolen_checkin_challenger_name:
        if medal.discord_id == medal.stolen_discord_id:
            # Self-steal: exceeded own record
            return f"\n\n<@{medal.discord_id}> still holds {emoji} {nice_name}, and has now surpassed it!"
        else:
            # Stolen from someone else
            return f"\n\n<@{medal.discord_id}> stole {emoji} {nice_name} from <@{medal.stolen_discord_id}>!"
    else:
        # Earned (not stolen)
        return f"\n\n<@{medal.discord_id}> earned {emoji} {nice_name}!"


def test_medal_messages_for_checkin(checkin_id):
    """Test medal messages for a specific check-in ID"""
    print(f"\n{'='*60}")
    print(f"Testing Medal Messages for Check-in ID: {checkin_id}")
    print(f"{'='*60}\n")
    
    try:
        # Get check-in details
        checkin = fetchone(
            """
            SELECT c.id, c.tier, c.time, c.challenge_week_id, ch.name as challenger_name, ch.discord_id
            FROM checkins c
            JOIN challengers ch ON c.challenger = ch.id
            WHERE c.id = %s
            """,
            [checkin_id]
        )
        
        if not checkin:
            print(f"✗ Check-in ID {checkin_id} not found")
            return
        
        challenge = get_current_challenge()
        if not challenge:
            print("✗ No active challenge found")
            return
        
        print(f"✓ Check-in found:")
        print(f"  Challenger: {checkin.challenger_name}")
        print(f"  Discord ID: {checkin.discord_id}")
        print(f"  Tier: {checkin.tier}")
        print(f"  Time: {checkin.time}")
        print(f"  Challenge Week ID: {checkin.challenge_week_id}")
        print()
        
        # Update medals (same as bot.py)
        medals.update_medal_table(challenge.id, checkin.challenge_week_id)
        
        # Get medal log
        log = medal_log.get_medal_log(checkin.challenge_week_id)
        
        # Find relevant medals for this check-in
        relevant_medals = [medal for medal in log if medal.checkin_id == checkin_id]
        
        if not relevant_medals:
            print("✓ No medals earned for this check-in")
            print("  Bot would process silently (no reply, no reactions)")
            return
        
        print(f"✓ Found {len(relevant_medals)} medal(s) for this check-in\n")
        print("=" * 60)
        print("MEDAL MESSAGE THE BOT WOULD SEND:")
        print("=" * 60)
        print()
        
        medal_message = ""
        reactions = []
        
        for medal in relevant_medals:
            # Show what reaction would be added
            reactions.append(medal.medal_emoji)
            print(f"  Would add reaction: {medal.medal_emoji}")
            print(f"  Medal: {describe_medal(medal.medal_name)}")
            if medal.stolen_checkin_challenger_name:
                if medal.discord_id == medal.stolen_discord_id:
                    print(f"  Type: Self-exceeded (exceeded own record)")
                else:
                    print(f"  Type: Stolen from {medal.stolen_checkin_challenger_name}")
            else:
                print(f"  Type: Earned")
            print()
            
            # Build message using same logic as bot.py
            medal_message += format_medal_message(medal)
        
        print("=" * 60)
        print("FULL REPLY MESSAGE:")
        print("=" * 60)
        print(medal_message)
        print()
        
        print("=" * 60)
        print("SUMMARY:")
        print("=" * 60)
        print(f"  Reactions to add: {', '.join(reactions)}")
        print(f"  Reply message: {len(medal_message.strip())} characters")
        print(f"  Number of medals: {len(relevant_medals)}")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()


def test_medal_messages_for_user(discord_id, checkin_message=None):
    """Test medal messages for a user's most recent check-in, or create a new one"""
    print(f"\n{'='*60}")
    print(f"Testing Medal Messages for Discord ID: {discord_id}")
    if checkin_message:
        print(f"Creating new check-in: '{checkin_message}'")
        print(f"{'⚠️  WARNING: This will create a REAL check-in in the database!'}")
    else:
        print("Using most recent check-in")
    print(f"{'='*60}\n")
    
    try:
        challenger = challenger_by_discord_id(str(discord_id))
        if not challenger:
            print(f"✗ User with Discord ID '{discord_id}' not found in database")
            print("\n   To add yourself, run this SQL:")
            print(f"   INSERT INTO challengers (name, discord_id, tz, bmr)")
            print(f"   VALUES ('Your Name', '{discord_id}', 'America/New_York', 2000);")
            return
        
        print(f"✓ User found: {challenger.name}")
        
        challenge_week = get_current_challenge_week(challenger.tz)
        challenge = get_current_challenge()
        
        if not challenge_week or not challenge:
            print("✗ No active challenge or challenge week found")
            return
        
        checkin_id = None
        
        if checkin_message:
            # Create a new check-in
            tier = get_tier(checkin_message)
            if tier == "unknown":
                print(f"✗ No tier detected in message: '{checkin_message}'")
                return
            
            print(f"✓ Tier detected: {tier}")
            checkin_id = with_psycopg(insert_checkin(checkin_message, tier, challenger, challenge_week.id))
            print(f"✓ Check-in created! ID: {checkin_id}")
        else:
            # Use most recent check-in
            recent_checkin = fetchone(
                """
                SELECT c.id FROM checkins c
                WHERE c.challenger = %s AND c.challenge_week_id = %s
                ORDER BY c.time DESC LIMIT 1
                """,
                [challenger.id, challenge_week.id]
            )
            
            if not recent_checkin:
                print(f"✗ No check-ins found for {challenger.name} in current week")
                print("\n   Create a check-in first:")
                print(f"   python3 test_medal_messages.py --user {discord_id} --message 'T1 checkin'")
                return
            
            checkin_id = recent_checkin.id
            print(f"✓ Using most recent check-in ID: {checkin_id}")
        
        print()
        test_medal_messages_for_checkin(checkin_id)
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()


def list_recent_checkins_with_medals(limit=10):
    """List recent check-ins that have medals"""
    print(f"\n{'='*60}")
    print(f"Recent Check-ins with Medals (last {limit})")
    print(f"{'='*60}\n")
    
    try:
        challenge = get_current_challenge()
        if not challenge:
            print("✗ No active challenge found")
            return
        
        challenge_week = get_current_challenge_week()
        if not challenge_week:
            print("✗ No active challenge week found")
            return
        
        # Update medals first
        medals.update_medal_table(challenge.id, challenge_week.id)
        
        # Get medal log
        log = medal_log.get_medal_log(challenge_week.id)
        
        # Get unique check-in IDs with medals
        checkin_ids_with_medals = list(set([medal.checkin_id for medal in log]))
        
        if not checkin_ids_with_medals:
            print("✓ No check-ins with medals found in current week")
            return
        
        print(f"✓ Found {len(checkin_ids_with_medals)} check-in(s) with medals\n")
        
        # Get check-in details
        checkins = fetchall(
            """
            SELECT c.id, c.tier, c.time, ch.name as challenger_name, ch.discord_id
            FROM checkins c
            JOIN challengers ch ON c.challenger = ch.id
            WHERE c.id = ANY(%s)
            ORDER BY c.time DESC
            LIMIT %s
            """,
            [checkin_ids_with_medals, limit]
        )
        
        for checkin in checkins:
            relevant_medals = [m for m in log if m.checkin_id == checkin.id]
            medal_names = [describe_medal(m.medal_name) for m in relevant_medals]
            print(f"  Check-in ID {checkin.id}:")
            print(f"    Challenger: {checkin.challenger_name}")
            print(f"    Tier: {checkin.tier}")
            print(f"    Time: {checkin.time}")
            print(f"    Medals: {', '.join(medal_names)}")
            print(f"    Test with: python3 test_medal_messages.py --checkin {checkin.id}")
            print()
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Test Discord bot medal messages',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test medals for a specific check-in ID
  python3 test_medal_messages.py --checkin 123

  # Test medals for a user's most recent check-in
  python3 test_medal_messages.py --user 123456789012345678

  # Create a new check-in and test its medals
  python3 test_medal_messages.py --user 123456789012345678 --message "T5 checkin"

  # List recent check-ins with medals
  python3 test_medal_messages.py --list

  # List recent check-ins with medals (more results)
  python3 test_medal_messages.py --list --limit 20
        """
    )
    
    parser.add_argument('--checkin', type=int, help='Test medals for check-in ID')
    parser.add_argument('--user', type=str, help='Test medals for Discord ID (uses most recent check-in)')
    parser.add_argument('--message', type=str, help='Create new check-in with this message and test medals')
    parser.add_argument('--list', action='store_true', help='List recent check-ins with medals')
    parser.add_argument('--limit', type=int, default=10, help='Limit for --list (default: 10)')
    
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("Discord Bot Medal Messages Test")
    print("="*60)
    
    if args.list:
        list_recent_checkins_with_medals(args.limit)
    elif args.checkin:
        test_medal_messages_for_checkin(args.checkin)
    elif args.user:
        test_medal_messages_for_user(args.user, args.message)
    else:
        parser.print_help()
        print("\n" + "="*60)
        print("Quick Start:")
        print("="*60)
        print("1. List check-ins with medals:")
        print("   python3 test_medal_messages.py --list")
        print("\n2. Test a specific check-in:")
        print("   python3 test_medal_messages.py --checkin 123")
        print("\n3. Test for a user:")
        print("   python3 test_medal_messages.py --user YOUR_DISCORD_ID")
        print("\n4. Create check-in and test:")
        print("   python3 test_medal_messages.py --user YOUR_DISCORD_ID --message 'T5 checkin'")
    
    print()


if __name__ == "__main__":
    main()
