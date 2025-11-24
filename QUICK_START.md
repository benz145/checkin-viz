# Quick Start Guide

Your local development environment is now set up! Here's how to run the application.

## Running the Application

### Option 1: Use the run script (Easiest)

```bash
./run_local.sh
```

This will start the Flask app on `http://localhost:5000`

### Option 2: Manual run

```bash
# Set up environment variables
export PATH="/Users/benlang/.local/bin:$PATH"
export PKG_CONFIG_PATH="$(brew --prefix cairo)/lib/pkgconfig:$PKG_CONFIG_PATH"
export DYLD_LIBRARY_PATH="$(brew --prefix cairo)/lib:$DYLD_LIBRARY_PATH"

# Run the app
cd src
poetry run python3 main.py
```

### Option 3: Using Poetry shell

```bash
# Set up environment variables (add to your ~/.zshrc for persistence)
export PATH="/Users/benlang/.local/bin:$PATH"
export PKG_CONFIG_PATH="$(brew --prefix cairo)/lib/pkgconfig:$PKG_CONFIG_PATH"
export DYLD_LIBRARY_PATH="$(brew --prefix cairo)/lib:$DYLD_LIBRARY_PATH"

# Activate Poetry shell
poetry shell

# Run the app
cd src
python3 main.py
```

## What Was Set Up

✅ Poetry installed and configured  
✅ Cairo library installed (for SVG conversion)  
✅ Python dependencies installed  
✅ Environment variables configured (`.env` file decrypted)  
✅ Database connection verified  
✅ Flask app loads successfully  

## Accessing the Application

Once running, access the app at:
- **Main dashboard**: http://localhost:5000
- **Create challenge**: http://localhost:5000/create_challenge
- **Tier calculator**: http://localhost:5000/calc

## Running the Discord Bot (Optional)

If you have a `DISCORD_TOKEN` in your `.env` file:

```bash
# Set up environment variables
export PATH="/Users/benlang/.local/bin:$PATH"
export PKG_CONFIG_PATH="$(brew --prefix cairo)/lib/pkgconfig:$PKG_CONFIG_PATH"
export DYLD_LIBRARY_PATH="$(brew --prefix cairo)/lib:$DYLD_LIBRARY_PATH"

# Run the bot
cd src
poetry run python3 bot.py
```

## Troubleshooting

### If you get "Cairo library not found" errors:

Make sure the environment variables are set:
```bash
export PKG_CONFIG_PATH="$(brew --prefix cairo)/lib/pkgconfig:$PKG_CONFIG_PATH"
export DYLD_LIBRARY_PATH="$(brew --prefix cairo)/lib:$DYLD_LIBRARY_PATH"
```

### If database connection fails:

Check your `.env` file has the correct `DB_CONNECT_STRING`:
```bash
cat .env | grep DB_CONNECT_STRING
```

### To update dependencies:

```bash
poetry update
```

## Next Steps

- Explore the codebase in the `src/` directory
- Check out the available routes in `src/main.py`
- Review the chart generation in `src/chart.py`
- Look at the scoring logic in `src/rule_sets.py`

