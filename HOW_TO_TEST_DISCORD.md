# How to Send Test Messages Through the Discord Bot

There are **two ways** to test the Discord bot:

## Method 1: Through Discord (Real Bot Testing)

This is the **actual way** the bot works in production.

### Step 1: Start the Bot

```bash
# Set up environment
export PATH="/Users/benlang/.local/bin:$PATH"
export PKG_CONFIG_PATH="$(brew --prefix cairo)/lib/pkgconfig:$PKG_CONFIG_PATH"
export DYLD_LIBRARY_PATH="$(brew --prefix cairo)/lib:$DYLD_LIBRARY_PATH"

# Start the bot
cd src
poetry run python3 bot.py
```

You should see: `{bot.user} is ready and online!`

### Step 2: Go to Discord

1. **Open Discord** (desktop app or web)
2. **Navigate to a server/channel** where the bot is present
3. **Make sure the bot has permission** to read messages in that channel

### Step 3: Send Test Messages

In the Discord channel, type and send any of these messages:

**Valid check-in messages:**
- `T1 checkin`
- `T2`
- `checkin T3`
- `Just did a T4 workout!`
- `T5 check-in today`
- `T10 checkin` (will get 🔥 reaction)
- `T12` (will get 🔥 reaction)

**The bot will:**
- Process the message automatically
- Save it to the database
- Add reactions if you earn medals
- Reply with medal achievements
- Add 🔥 reaction for T10+ check-ins

### Step 4: Watch the Bot Logs

In the terminal where the bot is running, you'll see:
```
DISCORD: tier from message: T1
DISCORD: challenger ...
DISCORD: inserted checkin id: ...
```

### Step 5: Test Slash Commands

In Discord, type `/` and you'll see the bot's commands:
- `/chart` - View the current week's chart
- `/green` - Check if it's a green week
- `/join` - Join the challenge
- `/quit` - Quit the challenge
- `/calculate_tier` - Calculate tier from calories/time

---

## Method 2: Simulate Messages (Testing Without Discord)

This method **simulates** what happens when a message is sent, without needing Discord.

### Prerequisites

1. **Get your Discord ID:**
   - Enable Developer Mode in Discord (Settings > Advanced > Developer Mode)
   - Right-click your profile > Copy ID
   - It will look like: `123456789012345678`

2. **Make sure you're in the database:**
   ```bash
   poetry run python3 test_discord_setup.py YOUR_DISCORD_ID
   ```

### Run the Test Script

```bash
# Test a message
poetry run python3 test_discord_message.py "T1 checkin" YOUR_DISCORD_ID

# Examples:
poetry run python3 test_discord_message.py "T2" YOUR_DISCORD_ID
poetry run python3 test_discord_message.py "Just did a T3 workout!" YOUR_DISCORD_ID
poetry run python3 test_discord_message.py "T5 checkin" YOUR_DISCORD_ID
```

### What the Script Does

The script simulates the exact same logic as the bot:
1. ✅ Extracts tier from message
2. ✅ Looks up your Discord ID in the database
3. ✅ Gets the current challenge week
4. ✅ Saves the check-in to the database
5. ✅ Shows what reactions would be added

### Verify the Check-in

After running the script, verify it was saved:

```sql
-- Check recent check-ins
SELECT * FROM checkins 
ORDER BY time DESC 
LIMIT 5;
```

---

## Quick Start Guide

### First Time Setup

1. **Verify your setup:**
   ```bash
   poetry run python3 test_discord_setup.py
   ```

2. **Get your Discord ID:**
   - Discord Settings > Advanced > Enable Developer Mode
   - Right-click your profile > Copy ID

3. **Check if you're in the database:**
   ```bash
   poetry run python3 test_discord_setup.py YOUR_DISCORD_ID
   ```

4. **If you're not in the database**, add yourself:
   ```sql
   INSERT INTO challengers (name, discord_id, tz, bmr) 
   VALUES ('Your Name', 'YOUR_DISCORD_ID', 'America/New_York', 2000);
   ```

### Testing Workflow

**Option A: Test with Discord (Recommended for full testing)**
```bash
# Terminal 1: Start bot
cd src && poetry run python3 bot.py

# Discord: Send "T1 checkin" in a channel
# Watch terminal for logs
```

**Option B: Test without Discord (Quick testing)**
```bash
# Test message processing
poetry run python3 test_discord_message.py "T1 checkin" YOUR_DISCORD_ID

# Verify in database
# Check the checkins table
```

---

## Troubleshooting

### "User not found in database"
- Your Discord ID must be in the `challengers` table
- Run: `poetry run python3 test_discord_setup.py YOUR_DISCORD_ID`
- Add yourself if needed (see SQL above)

### "No active challenge found"
- There must be a current challenge
- Check: `SELECT * FROM challenges WHERE start <= CURRENT_DATE AND "end" >= CURRENT_DATE;`

### Bot doesn't respond in Discord
- Make sure the bot is running
- Check bot has permission to read messages
- Verify bot is in the server/channel
- Check bot logs for errors

### Message not detected
- Message must contain "T" followed by a number
- Examples: `T1`, `T2`, `t3`, `T10`
- Case doesn't matter: `t1` works the same as `T1`

---

## Example Test Session

```bash
# 1. Verify setup
poetry run python3 test_discord_setup.py YOUR_DISCORD_ID

# 2. Test message processing (simulation)
poetry run python3 test_discord_message.py "T1 checkin" YOUR_DISCORD_ID
poetry run python3 test_discord_message.py "T5" YOUR_DISCORD_ID

# 3. Start the bot (for real Discord testing)
cd src
poetry run python3 bot.py

# 4. In Discord:
#    - Send: T1 checkin
#    - Send: T2
#    - Type: /chart
#    - Type: /green

# 5. Check database
#    SELECT * FROM checkins ORDER BY time DESC LIMIT 5;
```

---

## Message Format Reference

**Valid formats (will be processed):**
- `T1 checkin` ✓
- `checkin T2` ✓
- `T3` ✓
- `Just did a T4 workout!` ✓
- `t5 check-in` ✓ (case insensitive)
- `T10 checkin` ✓ (gets 🔥 reaction)
- `T12` ✓ (gets 🔥 reaction)

**Invalid formats (will be ignored):**
- `checkin` ✗ (no tier)
- `T` ✗ (no number)
- `tier 1` ✗ (no "T" prefix)
- `no tier here` ✗

The regex pattern is: `.*(t\d+).*` (case-insensitive)

