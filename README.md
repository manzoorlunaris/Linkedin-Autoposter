# LinkedIn Auto-Poster

Connects multiple LinkedIn accounts (each with a fixed topic), and every day
an AI agent researches what's trending on that topic, writes a caption,
generates an image, and publishes the post automatically — no manual input
after setup.

## Stack
- **Backend**: Django + Django Ninja (REST API)
- **Database**: SQLite by default (one file, zero setup — same as any project where `migrate` just creates `db.sqlite3` for you). Swap to Postgres later only if you actually need it.
- **Scheduling**: a plain Django management command run on a timer (cron, or a simple loop) — **no Celery, no Redis**
- **AI**: OpenAI (`web_search` tool — trend research + caption, one call) + Gemini (image generation)
- **Frontend**: Plain HTML/CSS/JS dashboard (no build step, no framework)

## What YOU need to provide (nothing else to build)
Fill these into `.env` (copy from `.env.example`) — this is the ONLY global config:

| Variable | Where to get it |
|---|---|
| `LINKEDIN_REDIRECT_URI` | `http://localhost:8000/api/linkedin/callback` for local dev — same URL for every account, register it in each LinkedIn app |
| `OPENAI_API_KEY` | https://platform.openai.com |
| `GEMINI_API_KEY` | https://aistudio.google.com |
| `FERNET_KEY` | Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `DJANGO_SECRET_KEY` | Any long random string |

**LinkedIn Client ID / Client Secret are NOT in `.env`** — each channel/account enters its own from the dashboard when clicking **Connect LinkedIn** (see below). This means a non-technical person can connect accounts without touching code or the server.

## Run it (plain — recommended, no Docker needed)
```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# fill in the values from the table above — leave DATABASE_URL unset, SQLite is used automatically

python manage.py migrate
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver
```
Dashboard: http://localhost:8000

### Schedule the daily posting check
`dispatch_due_posts` is the command that checks which accounts are due and posts for them. Run it every ~5 minutes:

**Linux/Mac — cron** (`crontab -e`):
```
*/5 * * * * cd /path/to/linkedin_autoposter && /path/to/venv/bin/python manage.py dispatch_due_posts >> /path/to/logfile.log 2>&1
```

**Windows — Task Scheduler**: create a task that runs every 5 minutes:
```
"C:\path\to\venv\Scripts\python.exe" manage.py dispatch_due_posts
```
(Working directory set to the project folder.)

**No cron available / just testing**: run it manually anytime to trigger due posts immediately:
```bash
python manage.py dispatch_due_posts
```

## Run it with Docker instead (optional, one command)
```bash
cp .env.example .env
# fill in the values
docker-compose up --build
```
This starts the web server plus a lightweight `scheduler` container that runs `dispatch_due_posts` every 5 minutes in a loop — no separate cron setup needed. Dashboard: http://localhost:8000

## Using it
1. **First**, create a login for yourself/each teammate — from the project folder:
   ```bash
   python manage.py createsuperuser
   ```
   (or `python manage.py shell` → `User.objects.create_user('name', password='...')` for a non-admin login). Each person gets their own username/password — **channels are private per user**, nobody sees anyone else's.
2. Open the dashboard (`/`) → you'll be redirected to `/login/` if not signed in
3. **+ New channel**
4. Give it a label, a fixed topic (e.g. "Digital Marketing"), and a daily posting time
5. Click **Connect LinkedIn** on that channel → a popup asks for that channel's own LinkedIn **Client ID** and **Client Secret** (create a free app at [linkedin.com/developers/apps](https://www.linkedin.com/developers/apps), add "Sign In with LinkedIn using OpenID Connect" + "Share on LinkedIn" products, and register this server's `LINKEDIN_REDIRECT_URI` as an authorized redirect URL on that app)
6. Click **Connect** in the popup → you're taken to LinkedIn to authorize → redirected back to the dashboard
7. If the credentials were valid, that channel now shows **Live** with a green status light and "Reconnect" instead of "Connect LinkedIn". If they were wrong, a toast explains what to check (bad Client ID/Secret, or redirect URI not registered on that LinkedIn app) and the channel stays disconnected — try again
8. Repeat for each account/topic — each one can use a completely different LinkedIn app/credentials
9. That's it — the scheduler (cron or the Docker `scheduler` service) checks every 5 minutes for accounts whose scheduled time (± jitter) has arrived and runs the full generate → post pipeline automatically
10. Use **Post now** to trigger one immediately for testing, and **Log** to see caption/image/status history per channel

## Privacy / multi-user
- Login is required for the dashboard and every API endpoint — nobody can view or touch anything without signing in.
- Every channel belongs to exactly one user (`owner`). A logged-in user only ever sees, edits, connects, or posts for their **own** channels — other users' channels return a 404, not an error revealing they exist.
- The daily cron (`dispatch_due_posts`) still posts for every active account across all users — that's a server-side process, not tied to a logged-in session.
- To add a teammate/client login: `python manage.py createsuperuser` (full admin access, can also use `/admin/`) or create a plain user via the shell for someone who should only use the dashboard, not `/admin/`.

## How a post is generated (fully automatic, no user input)
1. The scheduler fires at (or just after) the account's scheduled time (± random jitter, to avoid a robotic fixed-second pattern)
2. OpenAI (`web_search` tool) researches current trends on the account's topic and writes the caption in one call
3. Gemini generates a matching image
4. The image is uploaded to LinkedIn, then the post is published to that account's own profile via `w_member_social` — no LinkedIn app-approval process is needed for this, since each account authorizes its own posts individually (this is not the Community Management API / company-Pages flow, which does require approval and is not what this app uses)

## Project layout
```
config/            Django settings, urls
poster/
  models.py         LinkedInAccount, GeneratedPost
  services/
    encryption.py       Fernet encrypt/decrypt for tokens
    linkedin_client.py  OAuth + posting (registerUpload → upload → ugcPosts)
    openai_service.py   trend research + caption (Responses API + web_search)
    gemini_service.py   image generation
    post_pipeline.py    ties the above together into one generate_and_post(account_id) call
  management/commands/
    dispatch_due_posts.py   run on a timer (cron/Task Scheduler/Docker loop) — checks due accounts and posts
  api.py            Django Ninja REST endpoints (accounts CRUD, LinkedIn OAuth, post-now, post log)
  admin.py          Django admin (view/edit accounts & posts)
templates/          dashboard.html, base.html
static/             css/style.css, js/dashboard.js
```

## Notes / things worth knowing before production use
- LinkedIn access tokens expire (~60 days); refresh tokens are used automatically via `ensure_fresh_token()` in `linkedin_client.py` — but LinkedIn refresh tokens themselves can also expire, so a "reconnect" flow is included (just click **Connect LinkedIn** again).
- Rate-limit / ToS risk is behavioral, not an approval gate: don't fire every account at the exact same second every day — the jitter window setting exists for this reason, keep it on.
- `dispatch_due_posts` currently posts once per account per calendar day. To post more/less often, adjust the check in the command.
- Media storage defaults to local disk (`/media`). For production behind multiple containers/servers, point it at S3 (env vars are already stubbed in `.env.example`).
- SQLite is fine at this scale (a handful of accounts, one post/day each — low write volume, single server). If you later run multiple app servers or need heavier concurrent writes, switch `DATABASE_URL` to Postgres — the code doesn't change, only the env var.