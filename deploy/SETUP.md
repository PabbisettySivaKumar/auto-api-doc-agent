# Phase 2 setup — GitHub App + webhook service (all repos)

This turns the agent into an always-on service that keeps docs in sync
across **every repo the App is installed on**, including repos you create
later. No per-repo workflow file needed.

## Architecture

```
Any repo → push to default branch
      │  (webhook, HMAC-signed)
      ▼
GitHub App  ──►  FastAPI service (service/webhook.py, always on)
                      │  verify signature → dispatch in background
                      ▼
                 pipeline.run_for_push
                      │  clone repo (installation token) → diff → detect
                      │  → retrieve docs → draft (Gemini) → self-check
                      ▼
                 open doc PR on that repo  (never commits to default branch)
```

## 1. Deploy the service (get a public URL first)

The GitHub App needs a URL to send webhooks to, so deploy before creating
the App. This project ships a **Render Blueprint** (`render.yaml`) for a
free-plan deploy — steps below. (Any container host also works; build with
`docker build -f deploy/Dockerfile -t auto-doc-agent .`.)

Env vars the service reads (see `.env.example`):

| Var | Needed for |
|---|---|
| `GITHUB_APP_ID` | App auth |
| `GITHUB_APP_PRIVATE_KEY` or `GITHUB_APP_PRIVATE_KEY_PATH` | App auth |
| `GITHUB_WEBHOOK_SECRET` | verifying inbound webhooks |
| `GEMINI_API_KEY` | real doc drafts (stub used if absent) |
| `CONFIDENCE_THRESHOLD` | PR vs. skip gate (default 0.6) |

### 1a. Deploy on Render (free plan)

1. Push this repo to GitHub (Render deploys from a connected repo).
2. Render dashboard → **New → Blueprint** → connect this repo. Render reads
   `render.yaml` and creates the `auto-api-doc-agent` web service on the
   **free** plan, building `deploy/Dockerfile`.
3. **Add the App private key as a Secret File** (not an env var):
   Service → **Environment** → **Secret Files** → add file named
   `app-private-key.pem`, paste the contents of the `.pem` GitHub gave you.
   It mounts at `/etc/secrets/app-private-key.pem`, which is what
   `GITHUB_APP_PRIVATE_KEY_PATH` in `render.yaml` already points to.
4. Fill in the secret env vars (marked `sync: false` in the Blueprint):
   `GITHUB_APP_ID`, `GITHUB_WEBHOOK_SECRET`, `GEMINI_API_KEY`.
   (You'll get the App ID + secret in step 2 of the App setup below, so you
   may deploy, create the App, then come back and fill these in — a redeploy
   picks them up.)
5. Note your service URL, e.g. `https://auto-api-doc-agent.onrender.com`.
   Its webhook sink is that URL + `/webhook`.

> **Free-plan cold starts:** Render sleeps the instance after ~15 min idle.
> That's handled two ways — see **section 5 (Keep it warm)**. Nothing is
> lost even during a cold start: the service returns `202` immediately and
> GitHub retries any delivery that times out while it wakes.

## 2. Create the GitHub App

Settings → Developer settings → **GitHub Apps** → **New GitHub App**.
Fill in using `deploy/app-manifest.yml` as the reference:

- **Webhook URL**: `https://YOUR-SERVICE-HOST/webhook`
- **Webhook secret**: a strong random string → also set as
  `GITHUB_WEBHOOK_SECRET` on the host.
- **Permissions**: Contents = Read & write, Pull requests = Read & write,
  Metadata = Read-only.
- **Subscribe to events**: Push.

After creating:
- Copy the **App ID** → `GITHUB_APP_ID`.
- **Generate a private key** → download the `.pem`. Either mount it and
  set `GITHUB_APP_PRIVATE_KEY_PATH`, or paste its contents into
  `GITHUB_APP_PRIVATE_KEY`.

## 3. Install the App

On the App page → **Install App** → choose your account → **All
repositories** (recommended for "all my repos") or select specific ones.
Future repos are covered automatically when you pick "All".

## 4. Verify

- Hit `GET https://YOUR-SERVICE-HOST/` — should return
  `github_app_configured: true`, `webhook_secret_configured: true`.
- In the App's **Advanced** tab, GitHub shows recent webhook deliveries
  (including the initial `ping`) with response codes — a `ping` should get
  `200 pong`.
- Push a commit that changes a documented endpoint/signature → a
  `docs: auto-sync…` PR should appear on that repo within a few seconds.

## 5. Keep it warm (free-plan cold-start fix)

Render's free instance sleeps after ~15 min idle. Ping its `/healthz` more
often than that and it stays up — and one always-on free service fits
inside Render's free 750 instance-hours/month (~730 h in a month), so this
stays free. **A self-ping can't work** (a sleeping service can't wake
itself) — the pinger must be external. Two options, use either:

**Option A — GitHub Actions (in this repo, already included).**
`.github/workflows/keep-warm.yml` curls `/healthz` every 10 minutes. Set a
repo **Variable** so it knows the URL:

- Repo → Settings → Secrets and variables → **Actions → Variables → New**
- Name `RENDER_SERVICE_URL`, value your base URL
  (e.g. `https://auto-api-doc-agent.onrender.com`)

Trigger it once manually (Actions tab → keep-warm → Run workflow) to
confirm. Note: GitHub disables scheduled workflows after 60 days of repo
inactivity — any push (or a manual run) re-enables it.

**Option B — UptimeRobot (external, most reliable).**
Create a free account → **New monitor** → HTTP(s) → URL
`https://<your-service>.onrender.com/healthz` → interval 5 min. Done. Also
gives you uptime alerts for free.

Either is enough; UptimeRobot is the most reliable because GitHub cron can
drift. Both together is belt-and-suspenders and still free.

## 6. Enable layered feature docs (optional — Phase D)

By default the service runs in `DOC_MODE=single` (push to default branch →
one `API.md` sync PR). To turn on the **two-tier feature docs that commit
onto the feature PR branch** (see `docs/PLAN-layered-docs.md`):

1. **Subscribe the App to Pull request events:** GitHub App settings →
   **Permissions & events** → under *Subscribe to events*, check
   **Pull request** (keep Push). Save. (Contents + Pull requests write
   permissions are already set from step 2.)
2. **Set `DOC_MODE=layered`** on the Render service (Environment) and save →
   it redeploys.
3. (Optional) `SOURCE_ROOT=src` if your code lives under a `src/` dir, so
   features resolve to the folder *below* it.

Behavior once enabled: on a PR opened/updated, the agent diffs `base..head`,
buckets changes by top-level folder (feature), and commits
`docs/features/<feature>.md` + an updated `docs/API.md` index **onto the PR
branch** — so docs merge with the feature. A loop-guard ignores the agent's
own (bot) commits; PRs from forks are skipped. The push-to-main trigger
stays active as a safety net.

**Recommended rollout:** enable on ONE test repo first (install the App on
just that repo, or use a throwaway), confirm the doc commit appears on a PR,
then widen. Roll back anytime by setting `DOC_MODE=single`.

## Notes

- Low-confidence runs (below `CONFIDENCE_THRESHOLD`) are logged but do
  **not** open a PR, to avoid noise across many repos.
- The service clones each repo to a temp dir per push and deletes it
  afterward; nothing persists on the host (`OUTPUT_DIR` is `/tmp/out` on
  Render, which is ephemeral — fine for the JSONL trajectory log at this
  stage; move eval logging to a DB later per PRD Phase 2).
