# Checkinarator Visualizer 

Simple chart generator which displays checkins by those in the challenges

## Running the App

This app is dockerized and can be both run locally or as a container.

### Dependencies

This app uses poetry for dependency managment.
[Install poetry following the instructions on their site](https://github.com/python-poetry/poetry) 
and then run `poetry install`. From there use `poetry shell` and then the entrypoint with `python src/main.py`.

### Secrets

In order to access the data in the database `DB_CONNECT_STRING` needs to be set.
This value is stored in a [sops](https://github.com/getsops/sops) encrypted `.env`
file and can be encrypted and decrypted using the scripts in `./scripts` assuming
you have access to an allowed key. Before you can access these secrets you'll have to 
generate a new [age key pair](https://github.com/FiloSottile/age) and provide your public
key to someone who already has access. Once they resign the secrete with your public key
you'll be able to decrypt using the decrypt script.

#### Using age and sops

- Install [age](https://github.com/FiloSottile/age?tab=readme-ov-file#installation)
- Generate a key:
  - `age-keygen -o key.txt`
  - Put the key file somewhere you'll remember. Do not share it with anyone.
  - Save the public key(it's also in the file). This you can and should share.
- Add the public key to `age-keys.txt` in this repo.
  - Its a comma seperated file so add `,<public key>` to the end of it
- Push the new public key file to github
- Ask a maintainer to update the encrypted file with your key
- Fetch the updated `.env.sops` file
- Install [sops](https://github.com/getsops/sops)
- Run `./scripts/decrypt`
  - For this to work you'll have to make sure the `key.txt` you generated is in the right place. The [sops docs explain this](https://github.com/getsops/sops?tab=readme-ov-file#23encrypting-using-age). But realistically it means either:
    - On Windows: `%AppData%\sops\age\keys.txt`
    - On Mac: `$HOME/Library/Application Support/sops/age/keys.txt`
    - Manually: Set `SOPS_AGE_KEY_FILE=path/to/keys.txt`
- After running the script there will now be a file `.env` which contains the decrypted variables. **Do not share this file, or the contents of it, with anyone.**

## Local Development

A specific docker compose file is provided to make local development easy. You still need to
be able to decrypt the secrets as the local development db is seeded from production but
the application itself will only connect to the local db. To run the local development setup
simply use `docker compose -f docker-compose-local.yml up`. This will create:

- A local development postgres db exposed at `:5432`
  - username: postgres
  - password: password
- [pgweb](https://sosedoff.github.io/pgweb/), a simple to use postgres ui, which you can view at http://localhost:8081/
- A dbseeder which seeds a complete challenge and the current challenge
- The web ui which you can view at http://localhost:3000
- The discord bot

The bot and web source code is volumed so changes to the app just require you to restart the specific container:

- Web: `docker container restart checkin-viz-web-1`
- Bot: `docker container restart checkin-viz-bot-1`

Changes to scheduled-task or worker code require rebuilding and recreating the
`rq-cron` and `rq-worker` services.

### Discord safety in local development

The local Compose configuration enables `DISCORD_DEVELOPMENT_MODE` for the bot
and Discord-enabled workers. In this mode, Pycord command synchronization is
disabled, so starting a local bot cannot create, update, or delete the Discord
application's command registrations. The bot also rejects slash commands outside
the configured `#bot-testing` channel. Ordinary message processing and scheduled
Discord messages use that same channel.

Do not remove `DISCORD_DEVELOPMENT_MODE`, `DISCORD_SYNC_COMMANDS`, or the local
`ALLOWED_MESSAGE_CHANNEL_ID` override when running with production bot
credentials. To intentionally synchronize commands from a development instance,
set `DISCORD_SYNC_COMMANDS=true` for that run. This updates the shared Discord
application when using production bot credentials, so a separate development bot
application is preferred for command-registration work.

The local web, bot, and worker services also enable
`DEV_FALLBACK_TO_LATEST_CHALLENGE`. If a seed snapshot no longer contains a
challenge active on today's date, local development uses the snapshot's latest
challenge and week. Production continues to require date-active records.

**NOTE**: When doing local development never test against the production db.

## Discord Bot Commands

### Personal tier records

The **🏆 Highest Ever Personal Tier** medal is earned on a participant's first
real check-in and whenever a check-in strictly exceeds their previous highest
numeric tier across **all challenges**. Existing check-in history is the baseline;
starting a new challenge does not reset the record. Ties and lower tiers do not
earn it again. Automatic mulligan check-ins do not count.

The medal is saved in the existing medal history and cannot be stolen. Both typed
and calculator-submitted check-ins announce it immediately, including during the
early-week silence window for other medals. Announcements mention the participant
and include the new tier; when there is a previous record, they also include its
tier and original local check-in date. If that tier was achieved more than once,
the date it was first achieved is used. Removing a check-in with `/uncheckin`
also removes its medal, and future comparisons use the remaining history.

Examples:

- `@user earned 🏆 Highest Ever Personal Tier with a T5 check-in!`
- `@user earned 🏆 Highest Ever Personal Tier with a T12 check-in, exceeding their T9 check-in on January 2, 2025!`

Two additional non-stealable 🏆 records use the same numeric-tier, first-record,
tie, mulligan, previous-date, and historical-baseline rules:

- **Highest Seasonal Personal Tier** groups challenges by the season and four-digit
  year in their names (for example, `Summer 2026 Part 1` and `Summer 2026 Part 2`).
  Matching is case-insensitive; `Autumn` is treated as `Fall`. Winter uses the year
  in the challenge name, not the month/year of the check-in. A name without both a
  recognized season and year does not award a seasonal medal; rename it correctly
  rather than guessing a season from dates.
- **Highest Yearly Personal Tier** groups all real check-ins by the calendar year
  in each check-in's originally recorded timezone, independently of challenge names.

Seasonal and yearly announcements include the period and follow **normal early-week
suppression**, appearing in the opening roundup when appropriate. Only the all-time
personal record bypasses suppression. The medal case shows the selected challenge's
seasonal record and the participant's current local calendar-year record, including
their first-achieved dates. With no active challenge week, the all-time and current
year records remain available. All three records can be earned by multiple users
independently and are retained in challenge summaries.

Earliest/latest weekly and overall medals continue to be tracked, reacted to, and
listed with their holders in `/medal-case`, but are omitted from live medal replies,
opening roundups, and challenge-summary announcements.

No database migration or historical announcement replay is required. To run the
PostgreSQL regression tests, set `TEST_DB_CONNECT_STRING` to a local test database
and run `poetry run python -m unittest discover -s tests`. These tests use temporary
tables and roll back all fixture data.

### Commands

The Discord bot supports a small set of slash commands to help manage challenges:

- `/chart`: Display the current challenge chart as an image.
- `/medal-case`: Privately list all current stealable medal holders for the current
  challenge/week, with your own medals first and each holder's tier or original
  local check-in time, plus your all-time, selected-season, and current-year personal
  tier records and the dates first achieved. The all-time record is shown between challenges, even
  if it predates the introduction of the personal-record medal.
- `/green`: Check whether the current week is a green week.
- `/join`: Opt into the current challenge.
- `/quit`: Opt out of the current challenge.
- `/calculate_tier`: Open a modal to calculate your check-in tier based on calories and time.
  The private result includes **Submit Tn Check-in**, which saves the higher of
  the two tiers and posts a bot confirmation mentioning you in the configured
  check-in channel. Medal reactions and replies credit your account. Results
  expire after 10 minutes or at midnight in your timezone; each result can be
  submitted once. If confirmation fails after saving, check `/chart` before
  submitting again.
- `/bmr`: Calculate and save your BMR. The command asks for sex, age, height, and weight, then saves only the resulting BMR and reports the change from your previous BMR if one was already set.
- `/testpodium`: Test the podium/results message for the most recently ended challenge.
- `/uncheckin`: Remove **your own** last tier check-in for **today**. If you have a check-in today, the bot will delete the most recent one and post a public message in the channel saying `@user's last check-in from today was removed.` so everyone can see that the check-in was undone.
