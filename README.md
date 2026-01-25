## XFStatus — Xbox Friend Status Exporter (GitHub Actions + xbl.io)

A small automation that:

1. Reads your Xbox friends’ XUIDs from a **private GitHub repo** (`xuids.txt`)
2. Fetches **profile + presence** from **xbl.io**
3. Merges presence info into the profile payload
4. Writes the result to `ApiData.json`
5. Commits + pushes `ApiData.json` back into that private repo

> Designed to run on-demand via **GitHub Actions** (`workflow_dispatch`).

---

### What you get

- **Single JSON output**: `ApiData.json` (array of users)
- **Presence merge**:
  - Overwrites `lastSeenDateTimeUtc` with presence `timestamp` (when available)
  - Injects `deviceType`, `titleId`, `titleName` after `isXbox360Gamerpic`
- **Private-repo sync**:
  - Updates `ApiData.json` in your private repo only when it actually changes

---

### Repo structure

```text
.
├─ status.py                 # main script
├─ ApiData.json              # generated output (committed only if you want)
└─ .github/workflows/
   └─ XFStatus.yml           # GitHub Actions workflow
```

---

### How it works (high level)

1. The workflow runs `python status.py`.
2. `status.py` loads required environment variables.
3. It clones your private repo into `private_repo/`.
4. Reads XUIDs from `private_repo/xuids.txt`.
5. Calls:
   - `GET https://xbl.io/api/v2/account/{XUIDS}`
   - `GET https://xbl.io/api/v2/{XUIDS}/presence`
6. Builds a `presence_map` and merges `lastSeen` fields into the people list.
7. Writes output to `ApiData.json`.
8. Copies `ApiData.json` into the cloned repo and pushes changes.

---

### Requirements

#### Runtime

- Python **3.11+**
- `requests`

#### Accounts/Keys

- xbl.io API key
- A GitHub Personal Access Token (PAT) that can read/write your **private** repo

---

### Environment variables

`status.py` requires these:

| Name | Required | Description |
|------|----------|-------------|
| `API_KEY` | Yes | Your `xbl.io` API key (used as `x-authorization`) |
| `PA_TOKEN` | Yes | GitHub token used to clone/push the private repo |
| `PREPO_NAME` | Yes | Private repo in the format `OWNER/REPO` (example: `myuser/my-private-repo`) |

---

### Private repo expected files

Your private repo **must** contain:

- `xuids.txt`

Example `xuids.txt`:

```text
25332748XXXXXXXX
25332749YYYYYYYY
25332750ZZZZZZZZ
```

Each line should be a single XUID.

---

### Setup: GitHub Actions (recommended)

#### 1) Add repository secrets

Go to:

**Settings → Secrets and variables → Actions → New repository secret**

Add:

- `API_KEY` — your xbl.io API key
- `PA_TOKEN` — your GitHub PAT (see next section)
- `PREPO_NAME` — like `OWNER/REPO`

#### 2) Create a GitHub PAT (for private repo push)

Create a PAT from GitHub settings.

Minimum permissions (classic PAT guidance):

- `repo` (to clone + push to a private repo)

Security notes:

- Treat `PA_TOKEN` like a password
- Store it only in GitHub Secrets (never commit it)

#### 3) Run the workflow

Open the Actions tab → **Xbox Friend Status** → **Run workflow**.

---

### Setup: Run locally (optional)

#### 1) Install dependencies

```bash
python -m pip install --upgrade pip
pip install requests
```

#### 2) Export env vars

PowerShell example:

```powershell
$env:API_KEY = "your_xbl_io_key"
$env:PA_TOKEN = "github_pat_..."
$env:PREPO_NAME = "OWNER/REPO"
```

#### 3) Run

```bash
python -u status.py
```

Output:

- Writes `ApiData.json` locally
- Pushes `ApiData.json` into the private repo (if changed)

---

### Output format notes

`ApiData.json` is an array of user objects returned from xbl.io, with extra fields when presence is available:

- `lastSeenDateTimeUtc` (overwritten when `lastSeen.timestamp` exists)
- `deviceType`
- `titleId`
- `titleName`

If a user has no `lastSeen`, the script keeps the original user payload.

---

### Troubleshooting

#### Missing env var errors

If you see:

- `Missing required environment variable: ...`

Make sure you set the secret/env var in:

- GitHub Actions Secrets, or
- Your local shell environment

#### Git clone/push failures

- Confirm `PREPO_NAME` is exactly `OWNER/REPO`
- Confirm your PAT has private repo access (`repo`)
- Confirm the private repo exists and is reachable

#### xbl.io API errors / empty data

- Verify `API_KEY` is valid
- Check xbl.io rate limits
- Confirm the XUIDs in `xuids.txt` are correct

---

### Security checklist

- Never commit tokens or keys
- Prefer GitHub Secrets for CI
- Keep `xuids.txt` in a private repo if it’s sensitive

---

### FAQ

#### Why clone a private repo instead of storing XUIDs here?

To avoid storing sensitive identifiers in a public repo and to keep `xuids.txt` managed privately.

#### Can this run on a schedule?

Yes. You can add `schedule:` in the workflow. Example:

```yaml
on:
  schedule:
    - cron: "0 */6 * * *"
  workflow_dispatch:
```

(Keeping manual run by leaving `workflow_dispatch`.)

---

### Roadmap ideas (optional)

- Add retry + better error handling for network calls
- Cache presence lookups / reduce API calls
- Upload `ApiData.json` as a workflow artifact
- Add a JSON schema / typed validation

---

### License

Add a license if you plan to share this publicly.
