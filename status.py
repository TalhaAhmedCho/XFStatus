import os
import json
import subprocess
import shutil
import requests
import time
import datetime
from pathlib import Path
from typing import List, Dict, Any


# ================= ENV =================
def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


API_KEY = require_env("API_KEY")
PA_TOKEN = require_env("PA_TOKEN")
PREPO_NAME = require_env("PREPO_NAME")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")


# ================= PATHS =================
CLONE_DIR = Path("private_repo")
XUID_FILE = CLONE_DIR / "xuids.txt"
OUTPUT_FILE = "ApiData.json"
OUTPUT_IN_REPO = CLONE_DIR / OUTPUT_FILE


# ================= CONFIG =================
SLEEP_BETWEEN_REQUESTS = 2.5
MAX_RETRIES = 3
RETRY_BACKOFF = 5

headers = {
    "x-authorization": API_KEY,
    "accept": "application/json",
    "User-Agent": "GitHub-Action-XBL-Updater/1.0"
}


# ================= GIT =================
def clone_or_update_repo():
    if CLONE_DIR.exists():
        shutil.rmtree(CLONE_DIR, ignore_errors=True)

    subprocess.run(
        [
            "git", "config", "--global",
            f"url.https://x-access-token:{PA_TOKEN}@github.com/.insteadOf",
            "https://github.com/"
        ],
        check=True
    )

    subprocess.run(
        ["git", "clone", f"https://github.com/{PREPO_NAME}.git", str(CLONE_DIR)],
        check=True
    )


# ================= DATA =================
def read_xuids() -> List[str]:
    with open(XUID_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def fetch_with_retry(url: str) -> Any:
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers=headers, timeout=25)
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF * (2 ** attempt))
            else:
                raise


def fetch_all(xuids: List[str]):
    ids = ",".join(xuids)

    people = fetch_with_retry(
        f"https://xbl.io/api/v2/account/{ids}"
    ).get("people", [])

    time.sleep(SLEEP_BETWEEN_REQUESTS)

    presence_raw = fetch_with_retry(
        f"https://xbl.io/api/v2/{ids}/presence"
    )

    presence = presence_raw if isinstance(presence_raw, list) else presence_raw.get("presence", [])
    return people, presence


def merge_data(people: List[Dict], presence_list: List[Dict]) -> List[Dict]:
    presence_map = {p["xuid"]: p for p in presence_list if p.get("xuid")}

    return [
        {
            "account": user,
            "presence": presence_map.get(user.get("xuid"), {})
        }
        for user in people if user.get("xuid")
    ]


# ================= DISCORD =================
def send_discord_message(user: Dict):
    if not DISCORD_WEBHOOK:
        return

    account = user.get("account", {})
    presence = user.get("presence", {})

    gamertag = account.get("gamertag", "Unknown")
    avatar = account.get("displayPicRaw")
    state = presence.get("state", "Offline")

    color = 0x00ff00 if state == "Online" else 0xff0000

    lines = [f"**{state}**"]

    if state == "Online":
        device = "Unknown"
        devices = presence.get("devices", [])
        if devices:
            device = devices[0].get("type", "Unknown")

        lines.append(
            f"{device} - {account.get('presenceText', '')} - {account.get('presenceState', '')}"
        )

    embed = {
        "author": {
            "name": gamertag,
            "icon_url": avatar
        },
        "description": "\n".join(lines),
        "color": color,
    }

    requests.post(DISCORD_WEBHOOK, json={"embeds": [embed]}, timeout=10)


# ================= PREVIOUS STATE =================
def load_previous_data() -> Dict[str, Dict]:
    try:
        subprocess.run(
            ["git", "checkout", "HEAD~1", "--", OUTPUT_FILE],
            cwd=CLONE_DIR,
            check=False,
            capture_output=True
        )

        path = CLONE_DIR / OUTPUT_FILE
        if not path.exists():
            return {}

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return {
            u["account"]["xuid"]: u
            for u in data
            if u.get("account", {}).get("xuid")
        }

    finally:
        subprocess.run(
            ["git", "checkout", "HEAD", "--", OUTPUT_FILE],
            cwd=CLONE_DIR,
            check=False,
            capture_output=True
        )


# ================= MAIN =================
def main():
    original_dir = Path.cwd()

    try:
        clone_or_update_repo()
        xuids = read_xuids()

        people, presence = fetch_all(xuids)
        final_data = merge_data(people, presence)

        prev_data = load_previous_data()

        for user in final_data:
            account = user.get("account", {})
            presence_now = user.get("presence", {})

            xuid = account.get("xuid")
            if not xuid:
                continue

            current_state = presence_now.get("state", "Offline")
            prev_user = prev_data.get(xuid)
            prev_state = prev_user.get("presence", {}).get("state") if prev_user else None

            if prev_state is not None and current_state != prev_state:
                send_discord_message(user)

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(final_data, f, indent=4, ensure_ascii=False)

        shutil.copy(OUTPUT_FILE, OUTPUT_IN_REPO)

        os.chdir(CLONE_DIR)

        # 🔑 FIX: Git identity set
        subprocess.run(["git", "config", "user.name", "github-actions"], check=True)
        subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)

        subprocess.run(["git", "add", OUTPUT_FILE], check=True)

        if subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout.strip():
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            subprocess.run(
                ["git", "commit", "-m", f"Update ApiData.json [auto] - {now}"],
                check=True
            )
            subprocess.run(["git", "push"], check=True)

    finally:
        os.chdir(original_dir)


if __name__ == "__main__":
    main()
