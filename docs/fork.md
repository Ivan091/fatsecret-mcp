# This fork

`Ivan091/fatsecret-mcp` is a personal fork of [jaronskijakub/fatsecret-mcp](https://github.com/jaronskijakub/fatsecret-mcp), set up for logging meal photos from the Claude phone app with Claude doing the food recognition. Pull requests go to this fork, never upstream.

## What differs from upstream

- **The meal is always asked, never guessed.** `draft_entries` refuses new entries without `meal`, and the time-of-day meal suggestion (`meal_suggested`, `previous_day_suggested`) is gone. `meal_hours` in a user's settings is still accepted, so existing configurations load, but nothing uses it.
- **Food items in grams.** A Food item can give `grams` instead of `serving_id` and `number_of_units`. The server picks the Food's gram Serving and computes the units, so Claude doesn't have to scale servings.
- **`kcal_per_100g` in search results.** Each match carries the kcal in 100 g that a grams item uses, so a weight computed from it logs exactly the kcal shown to the user.
- **Next search results.** `search_foods` takes `page` (0 to 4) and returns `next_page`, so a bad match can be replaced by the next three candidates.
- **Fly.io.** `fly.toml` and [fly.md](fly.md), the step-by-step guide for the account owner.
- **Skill.** [skill/SKILL.md](skill/SKILL.md), the meal-photo skill that drafts and logs through the connector.

## Code review before building on upstream (2026-11-18)

Reviewed at upstream commit `6e8c9b0` for leaks of FatSecret tokens or diary data, calls home, and untrusted code execution. Nothing blocking was found.

- **Outbound calls.** The only hosts contacted are `platform.fatsecret.com` (API), `authentication.fatsecret.com` (the one-time OAuth 1.0 PIN flow, run by the `add-user` CLI) and the two pinned client metadata documents at `claude.ai` and `chatgpt.com` during connector sign-in, fetched without redirects and capped at 64 KB. No telemetry: `opentelemetry-api` comes in through the `mcp` SDK, but no exporter or SDK is installed, so it does nothing.
- **Secrets.** Read from environment variables only. FatSecret tokens and secrets are `repr=False`; the HTTP client's request logs (which would contain signed URLs) are raised to WARNING, error messages drop FatSecret's text and exception details that could quote a signed URL, and log lines name only methods and error codes. HTTP access logs are off because sign-in URLs carry one-time codes.
- **Connector auth.** OAuth 2.1 with PKCE S256, no dynamic client registration, client IDs and callbacks pinned to Claude (and ChatGPT only when turned on). Connector passwords are about 99 bits, stored as scrypt hashes, with sign-in throttling and a dummy hash for unknown names. The sign-in page has a strict CSP, CSRF cookie and `frame-ancestors 'none'`. Tokens are HMAC-signed, bound to the server, user and app, and revocable per user with `session_generation`.
- **Untrusted code.** No `eval`, `exec`, `pickle`, `subprocess` or dynamic imports. The image runs as a non-root user, base images and GitHub Actions are pinned by digest or commit, and a test enforces that.
- **Dependencies.** `httpx2` and `httpcore2` are the HTTP stack the `mcp` 2.x SDK itself depends on, from PyPI, locked in `uv.lock`.
- **Things to know, not defects.** FatSecret's OAuth 1.0 format puts the token and signature in the request URL, which goes only to FatSecret over HTTPS. A stolen refresh token stays valid for up to 30 days unless `session_generation` is raised. The sign-in page's footer links to the upstream author's GitHub page (a static link, nothing is loaded from it). On a push to `main`, the fork's CI builds and pushes a container image to `ghcr.io/ivan091/fatsecret-mcp` (a private package until made public); the release workflow only runs on a version tag and would also try PyPI, so don't push tags.
