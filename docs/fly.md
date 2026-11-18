# Phone connector on Fly.io: what you do

This guide takes you from nothing to logging a meal photo from the Claude app on your phone. Everything here is yours to do: no step has been done for you, nothing is deployed, and no account exists yet. Budget about an hour.

What you end up with: a small always-on server on Fly.io at `https://<app>.fly.dev`, added to claude.ai as a custom connector, that reads and writes **your** FatSecret food diary. Only you can use it: the connector signs in with your own user name and a long connector password, and the server holds your FatSecret token in Fly secrets.

You need:

- a computer with [uv](https://docs.astral.sh/uv/) and a clone of this repository (`git clone git@github.com:Ivan091/fatsecret-mcp.git`);
- a FatSecret account you log your meals with (the one in the FatSecret app);
- a Fly.io account with a card on file (about $2 to $5 a month for one small machine; Fly bills by use);
- a claude.ai account with custom connectors (the Free plan allows one).

## 1. FatSecret developer account and keys

1. Go to [platform.fatsecret.com](https://platform.fatsecret.com) and register a developer account. This is separate from your FatSecret app account; the same e-mail is fine.
2. Accept the [API terms](https://platform.fatsecret.com/terms). The free **Basic** plan is enough: 5,000 requests a day, US catalog in English.
3. In the developer console, open your application's keys and copy the **OAuth 1.0** credentials: the **Consumer Key** and the **Consumer Secret**. Ignore the OAuth 2.0 client ID and secret.
4. Leave the IP restrictions empty. OAuth 1.0 calls are not IP-restricted, so Fly's changing outbound addresses are fine. If `check` later reports error 21, an IP restriction was set: remove it.

Keep the two values private. They go into a local `.env` file (git-ignored) and Fly secrets, nowhere else.

## 2. Prepare the configuration on your computer

In the repository clone, create `.env`:

```sh
FATSECRET_CONSUMER_KEY=<consumer key>
FATSECRET_CONSUMER_SECRET=<consumer secret>
FATSECRET_MCP_SIGNING_KEY=<random value, see below>
```

Generate the signing key once and keep it (changing it later signs your connector out):

```sh
uv run python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

## 3. Link your FatSecret account (three-legged OAuth)

This is the one-time step that lets the server act on your diary. It runs FatSecret's OAuth 1.0 PIN flow on `authentication.fatsecret.com`, in your own browser:

```sh
uv sync
uv run --env-file .env fatsecret-mcp add-user
```

1. It prints a FatSecret link. Open it, sign in with **your FatSecret app account** (not the developer account), allow access, and type the PIN FatSecret shows back into the terminal.
2. Answer the questions: display name, a user `id` to sign in with (for example `me`), daily targets in kcal and grams, timezone (`Europe/Warsaw` is the default). Meal hours are asked for but this fork ignores them: Claude always asks you for the meal.
3. It shows a **connector password** once, like `xxxx-xxxx-xxxx-xxxx-xxxx`. Save it in your password manager now.
4. It prints a line `FATSECRET_MCP_USERS='[...]'`. Add it to `.env`.

Check that the link works (one FatSecret request; prints no secrets):

```sh
uv run --env-file .env fatsecret-mcp check
```

## 4. Deploy to Fly.io

1. Install `flyctl` ([fly.io/docs/flyctl/install](https://fly.io/docs/flyctl/install/)) and run `fly auth login`.
2. Pick an app name, say `my-fatsecret`, and put it in `fly.toml` in place of `CHANGE-ME-fatsecret-mcp`. Then create the app without deploying:

   ```sh
   fly apps create my-fatsecret
   ```

3. Set the secrets. Paste the `FATSECRET_MCP_USERS` value **without** the surrounding single quotes:

   ```sh
   fly secrets set --stage \
     FATSECRET_CONSUMER_KEY='<consumer key>' \
     FATSECRET_CONSUMER_SECRET='<consumer secret>' \
     FATSECRET_MCP_SIGNING_KEY='<signing key>' \
     FATSECRET_MCP_BASE_URL='https://my-fatsecret.fly.dev' \
     FATSECRET_MCP_USERS='[{"id": "me", ...}]'
   ```

   `FATSECRET_MCP_BASE_URL` is the public address with no path and no trailing slash.

4. Deploy. Fly builds the image from the `Dockerfile` on its own builder:

   ```sh
   fly deploy --ha=false
   fly scale count 1
   ```

   Keep exactly **one** machine: confirmed drafts are remembered in memory, and a second machine could write a draft twice. `fly.toml` keeps it always on (`auto_stop_machines = "off"`) and replaces it in place on a deploy.

5. Check it: `curl https://my-fatsecret.fly.dev/health` returns `{"status":"ok"}`, and `curl -i https://my-fatsecret.fly.dev/mcp` returns `401`.

6. Optional: in the Fly dashboard, set a spending alert under Billing.

To update later: `git pull`, then `fly deploy`. If the release changed tools, remove and re-add the connector in claude.ai so it sees the new tool descriptions.

## 5. Add the connector in claude.ai

1. On claude.ai (web), open **Settings > Connectors** (on some plans **Customize > Connectors**), choose **Add custom connector**.
2. Name it `FatSecret`, URL `https://my-fatsecret.fly.dev/mcp`. Leave the OAuth client ID and secret **empty**.
3. Click **Connect**. A sign-in page from your server opens: enter your user `id` and the connector password from step 3. It names `claude.ai` as where your browser returns.
4. In the connector's tool settings, set `search_foods`, `get_diary_day` and `get_period_summary` to **Always allow**, and keep `confirm_draft` on **Needs approval**, so every write to your diary asks you first. `draft_entries` writes nothing and can be allowed too.
5. The connector now appears in the Claude app on your phone as well.

## 6. Install the skill

Open `docs/skill/SKILL.md` in this repository. In claude.ai, open the skills settings (**Settings > Capabilities > Skills** at the time of writing) and replace your current "Food Image Analyzer" skill with it (or upload it as a new skill and turn the old one off). Then, in a new chat on your phone: send a meal photo, check the list, say which meal it was, and approve the save.

## Revoking access

- Lost phone: increase `session_generation` in `FATSECRET_MCP_USERS`, then `fly secrets set FATSECRET_MCP_USERS='...'`. Every connector session ends; your password stays.
- Everything at once: set a new `FATSECRET_MCP_SIGNING_KEY`.
- Cut off FatSecret access entirely: delete the app with `fly apps destroy my-fatsecret` and remove `.env`. The FatSecret token itself can't be revoked by the server, so also delete every copy of `FATSECRET_MCP_USERS`.

More detail on the sign-in and trust model: [connector](connector.md), [SECURITY.md](../SECURITY.md), [limits](limits.md).
