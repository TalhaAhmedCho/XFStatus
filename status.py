import os
import json
import subprocess
import shutil
import requests
import time
import datetime
from pathlib import Path
from typing import List, Dict, Union, Any

def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

API_KEY = require_env("API_KEY")
PA_TOKEN = require_env("PA_TOKEN")
PREPO_NAME = require_env("PREPO_NAME")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")  # optional

CLONE_DIR = Path("private_repo")
XUID_FILE = CLONE_DIR / "xuids.txt"
OUTPUT_FILE = "ApiData.json"
PREV_FILE = "ApiData_previous.json"

SLEEP_BETWEEN_REQUESTS = 2.5
MAX_RETRIES = 3
RETRY_BACKOFF = 5

headers = {
    "x-authorization": API_KEY,
    "accept": "application/json",
    "User-Agent": "GitHub-Action-XBL-Updater/1.0"
}

def mask_xuids(xuids: List[str]) -> str:
    masked = []
    for x in xuids:
        if len(x) > 8:
            masked.append(x[:4] + "****" + x[-4:])
        else:
            masked.append("****")
    return ",".join(masked[:3]) + ("..." if len(xuids) > 3 else "")

def clone_or_update_repo():
    if CLONE_DIR.exists():
        print(f"Removing existing clone directory: {CLONE_DIR}")
        shutil.rmtree(CLONE_DIR, ignore_errors=True)

    print(f"Cloning repository: {PREPO_NAME} (safely)")
    subprocess.run(
        ["git", "config", "--global",
         "url.https://x-access-token:" + PA_TOKEN + "@github.com/.insteadOf",
         "https://github.com/"],
        check=True
    )
    subprocess.run(["git", "clone", f"https://github.com/{PREPO_NAME}.git", str(CLONE_DIR)], check=True)

def read_xuids() -> List[str]:
    if not XUID_FILE.exists():
        raise FileNotFoundError(f"xuids.txt not found in {CLONE_DIR}")

    with open(XUID_FILE, "r", encoding="utf-8") as f:
        xuids = [line.strip() for line in f if line.strip()]

    print(f"Loaded {len(xuids)} XUIDs from xuids.txt")
    return xuids

def fetch_with_retry(url: str, desc: str, retries: int = MAX_RETRIES) -> Any:
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=25)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            status = getattr(e.response, 'status_code', None)
            print(f"Attempt {attempt+1}/{retries+1} failed for {desc}: {e}")
            if status:
                print(f"   Status: {status}")
            if attempt < retries:
                sleep_time = RETRY_BACKOFF * (2 ** attempt)
                print(f"   Retrying in {sleep_time}s...")
                time.sleep(sleep_time)
            else:
                raise

def fetch_all(xuids: List[str]) -> tuple[List[Dict], List[Dict]]:
    if not xuids:
        return [], []

    ids_str = ",".join(xuids)
    masked = mask_xuids(xuids)
    print(f"Fetching all {len(xuids)} users in single batch [{masked}]...")

    account_url = f"https://xbl.io/api/v2/account/{ids_str}"
    account_data = fetch_with_retry(account_url, "Account endpoint")
    people = account_data.get("people", []) if isinstance(account_data, dict) else []

    time.sleep(SLEEP_BETWEEN_REQUESTS)

    presence_url = f"https://xbl.io/api/v2/{ids_str}/presence"
    presence_data = fetch_with_retry(presence_url, "Presence endpoint")
    presence_list = presence_data if isinstance(presence_data, list) else presence_data.get("presence", []) or []

    return people, presence_list

def merge_data(people: List[Dict], presence_list: List[Dict]) -> List[Dict]:
    presence_map = {p.get("xuid", ""): p.get("lastSeen", {}) for p in presence_list if p.get("xuid")}

    final = []
    for user in people:
        xuid = user.get("xuid")
        if not xuid:
            continue

        last_seen = presence_map.get(xuid, {})

        merged = user.copy()

        if last_seen:
            if "timestamp" in last_seen:
                merged["lastSeenDateTimeUtc"] = last_seen["timestamp"]

            new_merged = {}
            inserted = False
            for k, v in merged.items():
                new_merged[k] = v
                if k == "isXbox360Gamerpic":
                    new_merged["deviceType"] = last_seen.get("deviceType")
                    new_merged["titleId"] = last_seen.get("titleId")
                    new_merged["titleName"] = last_seen.get("titleName")
                    inserted = True

            if not inserted:
                new_merged["deviceType"] = last_seen.get("deviceType")
                new_merged["titleId"] = last_seen.get("titleId")
                new_merged["titleName"] = last_seen.get("titleName")

            merged = new_merged

        final.append(merged)

    return final

def get_username(user: Dict) -> str:
    return (
        user.get("gamertag") or
        user.get("displayName") or
        user.get("realName") or
        "Unknown User"
    )

def send_discord_message(username: str, status: str, details: str = ""):
    if not DISCORD_WEBHOOK:
        print("DISCORD_WEBHOOK_URL not set → skipping Discord message")
        return

    color = 0x00ff00 if status == "Online" else 0xff0000

    embed = {
        "title": username,
        "description": f"**{status}**\n{details}".strip(),
        "color": color,
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "footer": {"text": "XFStatus Auto Update"}
    }

    payload = {"embeds": [embed]}

    try:
        resp = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"Discord message sent: {username} - {status}")
    except Exception as e:
        print(f"Discord send failed: {e}")

def main():
    original_dir = Path.cwd()
    try:
        clone_or_update_repo()
        xuids = read_xuids()

        if not xuids:
            print("No XUIDs found → nothing to do")
            return

        print("Starting API fetches...")
        people, presence = fetch_all(xuids)
        print(f"Got {len(people)} user info entries, {len(presence)} presence entries")

        final_data = merge_data(people, presence)

        # Load previous data for comparison
        prev_data = {}
        prev_path = CLONE_DIR / PREV_FILE
        if prev_path.exists():
            with open(prev_path, "r", encoding="utf-8") as f:
                prev_list = json.load(f)
                prev_data = {u.get("xuid"): u for u in prev_list if u.get("xuid")}

        # Check status changes
        for user in final_data:
            xuid = user.get("xuid")
            if not xuid:
                continue

            username = get_username(user)
            current_state = user.get("presenceState", "Offline")

            prev_user = prev_data.get(xuid, {})
            prev_state = prev_user.get("presenceState", "Offline") if prev_user else None

            # Only send if status changed or first time
            if current_state != prev_state or not prev_user:
                if current_state == "Online":
                    status_text = "Online"
                    details = ""
                else:
                    last_seen = user.get("lastSeen", {}) or {}
                    device = last_seen.get("deviceType", "Unknown")
                    game = last_seen.get("titleName", "No game")
                    status_text = "Offline"
                    details = f"{device} - {game}"

                send_discord_message(username, status_text, details)

        # Save current as latest
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(final_data, f, indent=4, ensure_ascii=False)

        print(f"Data written to {OUTPUT_FILE}")
        shutil.copy(OUTPUT_FILE, OUTPUT_IN_REPO)

        # Save as previous for next run
        shutil.copy(OUTPUT_FILE, CLONE_DIR / PREV_FILE)

        os.chdir(CLONE_DIR)
        subprocess.run(["git", "config", "user.name", "github-actions"], check=True)
        subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
        subprocess.run(["git", "add", "ApiData.json", "ApiData_previous.json"], check=True)

        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, check=False
        )

        if status_result.stdout.strip():
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            commit_msg = f"Update ApiData.json [auto] - {now}"
            subprocess.run(["git", "commit", "-m", commit_msg], check=True)
            subprocess.run(["git", "push"], check=True)
            print("✅ Changes committed and pushed")
        else:
            print("No changes → skipping commit/push")

    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        raise
    finally:
        os.chdir(original_dir)

if __name__ == "__main__":
    main()