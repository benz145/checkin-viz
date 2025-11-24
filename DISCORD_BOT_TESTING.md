# Discord Bot Testing Guide

## How the Discord Bot Works

The Discord bot (`src/bot.py`) has two main ways to interact:

### 1. **Slash Commands** (Interactive Commands)
These are Discord slash commands that users can invoke:

- `/chart` - Display the current week's check-in chart
- `/green` - Check if it's a "green week" (special week with different rules)
- `/quit` - Quit the current challenge
- `/join` - Join the current challenge
- `/calculate_tier` - Calculate what tier your check-in would be based on calories/time

### 2. **Message-Based Check-ins** (Automatic Detection)
The bot automatically detects check-in messages in Discord channels. When a user sends a message containing a tier (like "T1", "T2", "T3", etc.), the bot:
- Extracts the tier from the message
- Saves the check-in to the database
- Awards medals if applicable
- Adds reactions (🔥 for T10+ check-ins)
- Replies with medal achievements

## Message Format for Check-ins

The bot uses regex to detect tiers in messages. **Any message containing "T" followed by a number** will be processed as a check-in.

**Examples of valid check-in messages:**
- `T1 checkin`
- `checkin T2`
- `T3`
- `Just did a T4 workout!`
- `T5 check-in today`

**The regex pattern:** `.*(t\d+).*` (case-insensitive)

## Requirements for Testing

### 1. **Your Discord User Must Be in the Database**

The bot looks up users by their Discord ID in the `challengers` table. You need:

```sql
-- Check if you exist in the database
SELECT * FROM challengers WHERE discord_id = 'YOUR_DISCORD_ID';

-- If you don't exist, you'll need to add yourself:
INSERT INTO challengers (name, discord_id, tz, bmr) 
VALUES ('Your Name', 'YOUR_DISCORD_ID', 'America/New_York', YOUR_BMR);
```

**To get your Discord ID:**
1. Enable Developer Mode in Discord (Settings > Advanced > Developer Mode)
2. Right-click on your profile > Copy ID

### 2. **There Must Be an Active Challenge**

The bot needs a current challenge to work. Check:

```sql
SELECT * FROM challenges 
WHERE start <= CURRENT_DATE AND "end" >= CURRENT_DATE;
```

### 3. **Bot Must Be Running**

The bot needs to be running and connected to Discord.

## How to Test

### Step 1: Start the Bot

```bash
# Set up environment
export PATH="/Users/benlang/.local/bin:$PATH"
export PKG_CONFIG_PATH="$(brew --prefix cairo)/lib/pkgconfig:$PKG_CONFIG_PATH"
export DYLD_LIBRARY_PATH="$(brew --prefix cairo)/lib:$DYLD_LIBRARY_PATH"

# Run the bot
cd src
poetry run python3 bot.py
```

You should see: `{bot.user} is ready and online!`

### Step 2: Test Slash Commands

In Discord, type `/` and you should see the bot's commands:
- `/chart` - Try this to see the current week's chart
- `/green` - Check if it's a green week
- `/calculate_tier` - Opens a modal to calculate tier

### Step 3: Test Message-Based Check-ins

1. **Send a test message in a Discord channel where the bot is present:**
   - Message: `T1 checkin`
   - Message: `T2`
   - Message: `Just did a T3 workout!`

2. **What should happen:**
   - The bot processes the message (no visible response if no medals)
   - If you get a medal, the bot will:
     - Add a reaction emoji (medal emoji)
     - Reply with a message about the medal
   - For T10+ check-ins, you'll get a 🔥 reaction

### Step 4: Check the Logs

The bot logs everything. Watch the terminal where the bot is running for:
- `DISCORD: tier from message: T1`
- `DISCORD: challenger ...`
- `DISCORD: inserted checkin id: ...`
- `DISCORD: medals for checkin ...`

## Testing Checklist

- [ ] Bot is running and shows "ready and online"
- [ ] Your Discord ID exists in the `challengers` table
- [ ] There's an active challenge in the database
- [ ] Slash commands appear when typing `/` in Discord
- [ ] `/chart` command works and sends an image
- [ ] `/green` command responds with a GIF
- [ ] `/calculate_tier` opens the modal
- [ ] Sending "T1 checkin" message is processed
- [ ] Check-in appears in the database
- [ ] Medals are awarded if applicable

## Troubleshooting

### Bot doesn't respond to messages
- Check that `intents.message_content = True` is set (it is in the code)
- Verify the bot has permission to read messages in the channel
- Check bot logs for errors

### "Challenger not found" errors
- Your Discord ID must be in the `challengers` table
- The `discord_id` field must match your actual Discord user ID (as a string)

### Check-ins not saving
- Check database connection
- Verify there's an active challenge
- Check bot logs for database errors

### Slash commands not appearing
- The bot needs to be running
- Commands may take a few minutes to register globally
- Try restarting the bot

## Code Flow for Message Check-ins

1. **`on_message` event** (line 131 in `bot.py`)
   - Triggered when any message is sent
   - Ignores messages from the bot itself

2. **`get_tier()` function** (from `utils.py`)
   - Extracts tier from message using regex: `.*(t\d+).*`
   - Returns tier like "T1", "T2", etc., or "unknown"

3. **`save_checkin()` function** (line 177 in `bot.py`)
   - Looks up challenger by Discord ID
   - Gets current challenge week
   - Inserts check-in into database
   - Returns check-in ID

4. **Medal Processing** (lines 149-166)
   - Updates medal table
   - Checks if this check-in earned any medals
   - Adds reactions and replies if medals were earned

## Example Test Session

```bash
# Terminal 1: Start the bot
cd src
poetry run python3 bot.py

# In Discord:
# 1. Type: /chart
#    → Should receive a chart image

# 2. Type: /green
#    → Should see a GIF response

# 3. Type: T1 checkin
#    → Should see check-in processed (check logs)

# 4. Type: T5 checkin
#    → Should see check-in processed, possibly medals

# 5. Type: T12 checkin
#    → Should see 🔥 reaction (for T10+)
```

## Database Verification

After sending a test check-in, verify it was saved:

```sql
-- Check recent check-ins
SELECT * FROM checkins 
ORDER BY time DESC 
LIMIT 10;

-- Check if your check-in is there
SELECT c.*, ch.name 
FROM checkins c
JOIN challengers ch ON c.challenger = ch.id
WHERE ch.discord_id = 'YOUR_DISCORD_ID'
ORDER BY c.time DESC;
```

