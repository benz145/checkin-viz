# Troubleshooting Test Commands

## Common Issues

### Issue 1: "command not found: poetry"

**Problem:** Poetry is not in your PATH.

**Solution:**
```bash
# Add Poetry to PATH for this session
export PATH="/Users/benlang/.local/bin:$PATH"

# Or add to your ~/.zshrc permanently
echo 'export PATH="/Users/benlang/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### Issue 2: "ModuleNotFoundError" or import errors

**Problem:** Running with system Python instead of Poetry's virtual environment.

**Solution:** Always use `poetry run`:
```bash
# ❌ Wrong
python3 test_discord_setup.py

# ✅ Correct
poetry run python3 test_discord_setup.py
```

### Issue 3: "Cairo library not found"

**Problem:** Environment variables not set.

**Solution:**
```bash
export PKG_CONFIG_PATH="$(brew --prefix cairo)/lib/pkgconfig:$PKG_CONFIG_PATH"
export DYLD_LIBRARY_PATH="$(brew --prefix cairo)/lib:$DYLD_LIBRARY_PATH"
```

### Issue 4: "DB_CONNECT_STRING not set"

**Problem:** `.env` file not loaded.

**Solution:** Make sure you're in the project root and `.env` exists:
```bash
cd "/Users/benlang/Desktop/Check-in Viz/checkin-viz"
ls -la .env  # Should show the file
```

## Quick Fix Script

Create a helper script to set up environment:

```bash
#!/bin/bash
# Save as: setup_env.sh

export PATH="/Users/benlang/.local/bin:$PATH"
export PKG_CONFIG_PATH="$(brew --prefix cairo)/lib/pkgconfig:$PKG_CONFIG_PATH"
export DYLD_LIBRARY_PATH="$(brew --prefix cairo)/lib:$DYLD_LIBRARY_PATH"

cd "/Users/benlang/Desktop/Check-in Viz/checkin-viz"

# Now run your test command
poetry run python3 "$@"
```

Usage:
```bash
chmod +x setup_env.sh
./setup_env.sh test_discord_setup.py
```

## Test Command Reference

All test commands should be run like this:

```bash
# From project root
cd "/Users/benlang/Desktop/Check-in Viz/checkin-viz"

# Set up environment (if needed)
export PATH="/Users/benlang/.local/bin:$PATH"
export PKG_CONFIG_PATH="$(brew --prefix cairo)/lib/pkgconfig:$PKG_CONFIG_PATH"
export DYLD_LIBRARY_PATH="$(brew --prefix cairo)/lib:$DYLD_LIBRARY_PATH"

# Run tests
poetry run python3 test_discord_setup.py
poetry run python3 test_discord_message.py "T1 checkin"
poetry run python3 test_bot_outgoing.py --green
```

## What Error Are You Seeing?

If you can share the exact error message, I can help debug it more specifically!

