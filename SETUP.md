# Local Development Setup Guide

This guide will help you get the Checkinarator Visualizer running locally for testing and development.

## Prerequisites

- Docker and Docker Compose (for Docker setup)
- OR Python 3.11 or 3.12 + Poetry (for local development)
- PostgreSQL database (local or remote)
- (Optional) Discord Bot Token (if testing Discord integration)
- (Optional) Twilio credentials (if testing SMS/email integration)

## Quick Start: Docker (Easiest Method)

Since this project includes Docker files, the easiest way to get started is using Docker:

### Step 1: Set up Environment Variables

Create a `.env` file in the root directory:

```bash
# Required - Database connection
DB_CONNECT_STRING=postgresql://username:password@host:port/database
# Or use separate variables:
DB_USER=your_db_user
DB_HOST=your_db_host
DB_PASSWORD=your_db_password

# Optional - for logging
LOGLEVEL=DEBUG

# Optional - for Discord bot
DISCORD_TOKEN=your_discord_bot_token

# Optional - for Twilio SMS/email integration
TWILIO_AUTH_TOKEN=your_twilio_auth_token
```

**Note:** If you have access to the encrypted `.env.sops` file and have set up age/sops keys, you can decrypt it:
```bash
./scripts/decrypt
```

### Step 2: Run with Docker Compose

```bash
# Build and start all services (web app + Discord bot)
docker-compose up --build

# Or run in detached mode (background)
docker-compose up -d --build

# View logs
docker-compose logs -f

# View logs for specific service
docker-compose logs -f main
docker-compose logs -f bot

# Stop services
docker-compose down
```

**Note:** The `docker-compose.yml` uses `network_mode: host`, which means the containers use your host's network directly. The web app runs on port **3000** by default (as configured in `scripts/entrypoint`).

The web app will be available at `http://localhost:3000`

**Optional:** If you want to use port mapping instead of host networking, you can:
1. Remove `network_mode: host` from the services
2. Uncomment the `ports` section:
   ```yaml
   ports:
     - "3000:3000"  # Maps container port 3000 to host port 3000
   ```

### Running Individual Services

You can also run just the web app or just the bot:

```bash
# Run only the web app
docker-compose up main

# Run only the Discord bot
docker-compose up bot
```

## Option 2: Local Development (Recommended for Active Development)

### Step 1: Install Dependencies

1. **Install Poetry** (if not already installed):
   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   ```

2. **Install Python dependencies**:
   ```bash
   poetry install
   ```

3. **Activate the Poetry shell**:
   ```bash
   poetry shell
   ```

### Step 2: System Dependencies

The application requires Cairo for SVG to PNG conversion:

**macOS:**
```bash
brew install cairo
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get update
sudo apt-get install libcairo2-dev
```

**Windows:**
Install Cairo from [GTK for Windows](https://www.gtk.org/docs/installations/windows/)

### Step 3: Database Setup

You'll need a PostgreSQL database. You can either:

**Option A: Use existing database** (if you have access to production/staging)

**Option B: Set up local PostgreSQL:**

1. **Install PostgreSQL** (if not installed):
   ```bash
   # macOS
   brew install postgresql@14
   brew services start postgresql@14
   
   # Linux
   sudo apt-get install postgresql postgresql-contrib
   sudo systemctl start postgresql
   ```

2. **Create database and user**:
   ```bash
   createdb checkin_viz
   # Or via psql:
   psql postgres
   CREATE DATABASE checkin_viz;
   CREATE USER checkin_user WITH PASSWORD 'your_password';
   GRANT ALL PRIVILEGES ON DATABASE checkin_viz TO checkin_user;
   \q
   ```

3. **Run database migrations/setup**:
   - You'll need the database schema. Check with the maintainers for SQL migration files or schema dump.
   - At minimum, you'll need tables: `challenges`, `challengers`, `challenger_challenges`, `checkins`, `challenge_weeks`, `medals`
   - You'll also need the `get_challenge_score` function (see `src/sql/get_challenge_score.sql`)

### Step 4: Environment Variables

Create a `.env` file in the root directory:

```bash
# Required
DB_CONNECT_STRING=postgresql://username:password@localhost:5432/checkin_viz
# Or use separate variables:
DB_USER=checkin_user
DB_HOST=localhost
DB_PASSWORD=your_password

# Optional - for logging
LOGLEVEL=DEBUG

# Optional - for Discord bot (only needed if running bot.py)
DISCORD_TOKEN=your_discord_bot_token

# Optional - for Twilio SMS/email integration
TWILIO_AUTH_TOKEN=your_twilio_auth_token
```

**Note:** If you have access to the encrypted `.env.sops` file and have set up age/sops keys, you can decrypt it:
```bash
./scripts/decrypt
```

### Step 5: Run the Application

**For the web application:**
```bash
cd src
python main.py
```

The app will run on `http://localhost:5000` (Flask default) or `http://127.0.0.1:5000`

**For production-like server (Gunicorn):**
```bash
cd src
gunicorn -w 4 -b 0.0.0.0:8000 main:app
```

**For the Discord bot (separate terminal):**
```bash
cd src
python bot.py
```

## Option 3: Hybrid Approach (Best of Both Worlds)

Run the web app locally for easier debugging, and only use Docker for services you don't need to modify:

```bash
# In one terminal - run web app locally
poetry shell
cd src
python main.py

# In another terminal - run Discord bot in Docker (if needed)
docker-compose up bot
```

## Testing the Setup

1. **Check database connection:**
   ```bash
   poetry shell
   python -c "from src.helpers import fetchall; print(fetchall('SELECT version()'))"
   ```

2. **Access the web interface:**
   - Open `http://localhost:5000` (or your configured port)
   - You should see the challenge visualization

3. **Test endpoints:**
   - `/` - Main dashboard
   - `/create_challenge` - Create a new challenge
   - `/calc` - Tier calculator

## Common Issues

### Issue: "Module not found" errors
**Solution:** Make sure you're in the Poetry shell: `poetry shell`

### Issue: "DB_CONNECT_STRING not set"
**Solution:** Create a `.env` file with your database connection string

### Issue: Cairo/SVG conversion errors
**Solution:** Install Cairo system library (see Step 2 above)

### Issue: Port already in use
**Solution:** Change the port in `main.py` or use a different port:
```python
app.run(debug=True, port=5001)
```

### Issue: Database connection errors
**Solution:** 
- Verify PostgreSQL is running: `pg_isready` or `psql -l`
- Check your connection string format: `postgresql://user:password@host:port/database`
- Verify database exists and user has permissions

## Development Tips

1. **Enable debug mode:** The Flask app runs in debug mode by default when using `python main.py`

2. **View logs:** Set `LOGLEVEL=DEBUG` in your `.env` for verbose logging

3. **Static files:** Static files are served from `src/static/`. Chart previews are generated there.

4. **Database queries:** Most queries are in `src/base_queries.py`. Check there for database interaction patterns.

5. **Skip optional services:** You can run the web app without Discord bot or Twilio - those are only needed for those specific integrations.

## Next Steps

- Create a test challenge via `/create_challenge`
- Add test check-ins via `/add-checkin` or the web interface
- Explore the chart generation in `src/chart.py`
- Check out the scoring logic in `src/rule_sets.py`

## Getting Help

- Check the main `README.md` for project overview
- Review `src/main.py` for available routes
- Check database schema with maintainers if you need to set up from scratch

