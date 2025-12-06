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

**NOTE**: When doing local development never test against the production db.
