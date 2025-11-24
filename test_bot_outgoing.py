#!/usr/bin/env python3
"""
Test script for bot's outgoing messages
Tests what the bot would send: replies, reactions, slash command responses, etc.
"""
import os
import sys
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

load_dotenv()

from helpers import fetchone, fetchall
from base_queries import get_current_challenge, get_current_challenge_week, checkins_this_week
from chart import checkin_chart, week_heat_map_from_checkins, write_og_image
from rule_sets import calculate_total_score
from green import determine_if_green
import medals
import medal_log
import random

# Bot's nice medal names (from bot.py)
nice_medal_names = {
    "earliest_for_week": "earliest checkin this week",
    "first_to_green": "first to green",
    "gold": "gold",
    "green": "green",
    "highest_tier_challenge": "highest tier for the challenge",
    "highest_tier_week": "highest tier this week",
    "latest_for_week": "latest checkin this week",
}

def test_green_week_response():
    """Test what the /green command would send"""
    print("=" * 60)
    print("Testing /green Command Response")
    print("=" * 60)
    
    green_week = determine_if_green()
    
    if green_week == True:
        print("✓ Bot would send: 'It's a green week!!!!'")
        print("  With a random GIF from yes_gifs list")
        print("  (Embed with image)")
    else:
        print("✓ Bot would send: 'Not this week!'")
        print("  With a random GIF from no_gifs list")
        print("  (Embed with image)")
    
    print(f"\n  Green week status: {green_week}")
    print()

def test_chart_generation():
    """Test chart generation for /chart command"""
    print("=" * 60)
    print("Testing /chart Command Response")
    print("=" * 60)
    
    try:
        current_challenge = get_current_challenge()
        if not current_challenge:
            print("✗ No active challenge found")
            return
        
        selected_challenge_week = get_current_challenge_week()
        checkins = checkins_this_week(selected_challenge_week.id)
        total_points = calculate_total_score(current_challenge.id)
        
        week, latest, achievements = week_heat_map_from_checkins(
            checkins,
            current_challenge.id,
            current_challenge.rule_set,
        )
        week = sorted(
            week, key=lambda x: -total_points[x.name] if x.name in total_points else 0
        )
        total_checkins = {x[1]: x[0] for x in fetchall("select * from get_challenge_score(%s, FALSE)", [current_challenge.id])}
        
        chart = checkin_chart(
            week,
            1000,
            600,
            current_challenge.id,
            selected_challenge_week.green,
            selected_challenge_week.bye_week,
            total_points,
            achievements,
            total_checkins,
            fetchone("select count(*) * 5 as total_possible from challenge_weeks where challenge_id = %s;", [current_challenge.id])[0],
            fetchone("select count(*) * 5 as total_possible from challenge_weeks where challenge_id = %s and id < %s;", (current_challenge.id, selected_challenge_week.id))[0] + min(selected_challenge_week.start.weekday() + 1, 5),
        )
        
        # Write the chart image
        write_og_image(chart, selected_challenge_week.id)
        
        print("✓ Chart generated successfully!")
        print(f"  Challenge: {current_challenge.name}")
        print(f"  Week ID: {selected_challenge_week.id}")
        print(f"  Participants: {len(week)}")
        print(f"  Chart image saved to: src/static/preview-{selected_challenge_week.id}.png")
        print("\n  Bot would send this image file via Discord")
        print("  (Ephemeral response - only visible to the user who ran the command)")
        
    except Exception as e:
        print(f"✗ Error generating chart: {e}")
        import traceback
        traceback.print_exc()
    
    print()

def test_medal_reply_message(checkin_id=None, discord_id=None):
    """Test what medal reply message would be sent"""
    print("=" * 60)
    print("Testing Medal Reply Message")
    print("=" * 60)
    
    if not checkin_id and not discord_id:
        print("⚠️  No checkin_id or discord_id provided")
        print("  This would be generated after a check-in is saved")
        print("\n  To test with a real check-in:")
        print("    python3 test_bot_outgoing.py --medal-reply CHECKIN_ID")
        print("    python3 test_bot_outgoing.py --medal-reply-by-user DISCORD_ID")
        return
    
    try:
        current_challenge = get_current_challenge()
        if not current_challenge:
            print("✗ No active challenge found")
            return
        
        challenge_week = get_current_challenge_week()
        
        # Update medals
        medals.update_medal_table(current_challenge.id, challenge_week.id)
        log = medal_log.get_medal_log(challenge_week.id)
        
        # Find relevant medals
        if checkin_id:
            relevant_medals = [medal for medal in log if medal.checkin_id == checkin_id]
        elif discord_id:
            # Get most recent check-in for this user
            recent_checkin = fetchone(
                """
                SELECT c.id FROM checkins c
                JOIN challengers ch ON c.challenger = ch.id
                WHERE ch.discord_id = %s AND c.challenge_week_id = %s
                ORDER BY c.time DESC LIMIT 1
                """,
                [str(discord_id), challenge_week.id]
            )
            if recent_checkin:
                relevant_medals = [medal for medal in log if medal.checkin_id == recent_checkin.id]
            else:
                print(f"✗ No recent check-in found for Discord ID {discord_id}")
                return
        else:
            relevant_medals = []
        
        if relevant_medals:
            print("✓ Medal reply message would be:")
            print()
            medal_message = ""
            for medal in relevant_medals:
                if medal.stolen_checkin_challenger_name:
                    medal_message += f"\n <@{medal.discord_id}> stole {nice_medal_names[medal.medal_name]} {medal.medal_emoji} from <@{medal.stolen_discord_id}>!"
                else:
                    medal_message += f"\n <@{medal.discord_id}> got {nice_medal_names[medal.medal_name]} {medal.medal_emoji}!"
            
            print(medal_message)
            print("\n  Bot would:")
            print("  - Add reaction emoji to the original message")
            print("  - Reply with the medal message")
        else:
            print("✓ No medals for this check-in")
            print("  Bot would process silently (no reply)")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
    
    print()

def test_reaction_logic(tier):
    """Test what reactions would be added"""
    print("=" * 60)
    print(f"Testing Reaction Logic for {tier}")
    print("=" * 60)
    
    tier_number = int(tier[1:]) if tier.startswith('T') else int(tier)
    
    reactions = []
    
    # T10+ gets 🔥 reaction
    if tier_number > 10:
        reactions.append("🔥")
        print(f"✓ Would add 🔥 reaction (T10+ check-in)")
    
    # Medal reactions would be added if medals are earned
    # (tested separately in test_medal_reply_message)
    
    if not reactions:
        print("✓ No special reactions for this tier")
        print("  (Medal reactions would be added separately if earned)")
    
    print()

def test_slash_command_responses():
    """Test what slash commands would respond with"""
    print("=" * 60)
    print("Testing Slash Command Responses")
    print("=" * 60)
    
    print("\n/join command:")
    print("  Bot would respond: 'You ready to win?'")
    print("  With a button: 'Yes, I will win.'")
    print("  (When clicked, bot responds: 'Good luck {challenger.name}')")
    
    print("\n/quit command:")
    print("  Bot would respond: 'You sure?'")
    print("  With a button to confirm")
    print("  (When clicked, bot responds: 'You have disappointed us all {challenger.name}')")
    
    print("\n/calculate_tier command:")
    print("  Bot would open a modal with:")
    print("  - Input field: 'Calories Burnt'")
    print("  - Input field: 'Time Spent'")
    print("  (When submitted, bot sends an embed with tier results)")
    
    print("\n/chart command:")
    print("  Bot generates and sends chart image")
    print("  (See test_chart_generation() for details)")
    
    print("\n/green command:")
    print("  Bot sends embed with GIF and description")
    print("  (See test_green_week_response() for details)")
    
    print()

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Test bot outgoing messages')
    parser.add_argument('--green', action='store_true', help='Test /green command response')
    parser.add_argument('--chart', action='store_true', help='Test /chart command (generates chart)')
    parser.add_argument('--medal-reply', type=int, help='Test medal reply for checkin_id')
    parser.add_argument('--medal-reply-by-user', type=str, help='Test medal reply for Discord ID')
    parser.add_argument('--reaction', type=str, help='Test reaction logic for tier (e.g., T1, T12)')
    parser.add_argument('--slash-commands', action='store_true', help='Show all slash command responses')
    parser.add_argument('--all', action='store_true', help='Run all tests')
    
    args = parser.parse_args()
    
    if len(sys.argv) == 1:
        args.all = True
    
    print("\n" + "=" * 60)
    print("Discord Bot Outgoing Messages Test")
    print("=" * 60 + "\n")
    
    if args.all or args.green:
        test_green_week_response()
    
    if args.all or args.chart:
        test_chart_generation()
    
    if args.all or args.medal_reply:
        test_medal_reply_message(checkin_id=args.medal_reply)
    
    if args.all or args.medal_reply_by_user:
        test_medal_reply_message(discord_id=args.medal_reply_by_user)
    
    if args.all or args.reaction:
        if args.reaction:
            test_reaction_logic(args.reaction)
        elif args.all:
            # Test with a few example tiers
            print("Testing reaction logic with example tiers:")
            test_reaction_logic("T1")
            test_reaction_logic("T5")
            test_reaction_logic("T12")
    
    if args.all or args.slash_commands:
        test_slash_command_responses()
    
    if not any([args.green, args.chart, args.medal_reply, args.medal_reply_by_user, 
                args.reaction, args.slash_commands, args.all]):
        print("No tests specified. Use --help to see options.")
        print("\nQuick examples:")
        print("  python3 test_bot_outgoing.py --all")
        print("  python3 test_bot_outgoing.py --green")
        print("  python3 test_bot_outgoing.py --chart")
        print("  python3 test_bot_outgoing.py --reaction T12")
    
    print()

if __name__ == "__main__":
    main()

