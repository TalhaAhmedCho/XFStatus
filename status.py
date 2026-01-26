import os
import json
import subprocess
import shutil
import requests
import time
from pathlib import Path
from typing import Union, List, Dict

def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

API_KEY = require_env("API_KEY")
PA_TOKEN = require_env("PA_TOKEN")
PREPO_NAME = require_env("PREPO_NAME")

CLONE_DIR = Path("private_repo")
XUID_FILE = CLONE_DIR / "xuids.txt"
OUTPUT_FILE = "ApiData.json"
OUTPUT_IN_REPO = CLONE_DIR / OUTPUT_FILE

BATCH_SIZE = 8               # OpenXBL free tier-এ সাধারণত 150 req/hour → batch size ছোট রাখা ভালো
SLEEP_BETWEEN_BATCHES = 2.5  # সেকেন্ড (rate limit safety margin)

headers = {
    "x-authorization": API_KEY,
    "accept": "application/json",
    "User-Agent": "GitHub-Action-XBL-Updater/1.0"
}


def clone_or_update_repo():
    """Clone repo using credential helper to avoid leaking PAT in logs"""
    if CLONE_DIR.exists():
        print(f"Removing existing clone directory: {CLONE_DIR}")
        shutil.rmtree(CLONE_DIR, ignore_errors=True)

    print(f"Cloning repository: {PREPO_NAME} (safely)")

    # Set global credential helper for this session
    subprocess.run(
        ["git", "config", "--global",
         "url.https://x-access-token:" + PA_TOKEN + "@github.com/.insteadOf",
         "https://github.com/"],
        check=True
    )

    # Clone without token in URL
    subprocess.run(["git", "clone", f"https://github.com/{PREPO_NAME}.git", str(CLONE_DIR)], check=True)


def read_xuids() -> List[str]:
    if not XUID_FILE.exists():
        raise FileNotFoundError(f"xuids.txt not found in {CLONE_DIR}")

    with open(XUID_FILE, "r", encoding="utf-8") as f:
        xuids = [line.strip() for line in f if line.strip()]

    print(f"Loaded {len(xuids)} XUIDs from xuids.txt")
    return xuids


def fetch_batch(url_template: str, xuids_batch: List[str]) -> Union[Dict, List]:
    ids_str = ",".join(xuids_batch)
    url = url_template.format(ids_str)

    try:
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"❌ API request failed for batch {xuids_batch[:3]}... : {e}")

        status_code = None
        if e.response is not None:
            status_code = e.response.status_code
            print(f"   Status code: {status_code}")
            if status_code == 429:
                print("   Rate limited → consider increasing SLEEP_BETWEEN_BATCHES or reducing BATCH_SIZE")
        else:
            print("   No response received (timeout / connection issue?)")

        # Optional: log full response if available
        if e.response is not None:
            try:
                print("   Response body snippet:", e.response.text[:200])
            except:
                pass

        raise  # re-raise so main can catch


def fetch_in_batches(xuids: List[str]) -> tuple[List[Dict], List[Dict]]:
    info_url_t = "https://xbl.io/api/v2/account/{}"
    presence_url_t = "https://xbl.io/api/v2/{}/presence"

    all_people: List[Dict] = []
    all_presence: List[Dict] = []

    for i in range(0, len(xuids), BATCH_SIZE):
        batch = xuids[i:i + BATCH_SIZE]
        print(f"Fetching batch {i//BATCH_SIZE + 1} ({len(batch)} users)")

        # Info
        info_data = fetch_batch(info_url_t, batch)
        people = info_data.get("people", []) if isinstance(info_data, dict) else []
        all_people.extend(people)

        # Presence
        presence_data = fetch_batch(presence_url_t, batch)
        if isinstance(presence_data, list):
            all_presence.extend(presence_data)
        elif isinstance(presence_data, dict):
            # fallback if wrapped
            all_presence.extend(presence_data.get("presence", []))
        else:
            print(f"Warning: Unexpected presence response type: {type(presence_data)}")

        time.sleep(SLEEP_BETWEEN_BATCHES)

    return all_people, all_presence


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


def main():
    original_dir = Path.cwd()

    try:
        clone_or_update_repo()

        xuids = read_xuids()
        if not xuids:
            print("No XUIDs found → nothing to do")
            return

        print("Starting API fetches...")
        people, presence = fetch_in_batches(xuids)

        print(f"Got {len(people)} user info entries, {len(presence)} presence entries")

        final_data = merge_data(people, presence)

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(final_data, f, indent=4, ensure_ascii=False)

        print(f"Data written to {OUTPUT_FILE}")

        shutil.copy(OUTPUT_FILE, OUTPUT_IN_REPO)

        # Git operations
        os.chdir(CLONE_DIR)

        subprocess.run(["git", "config", "user.name", "github-actions"], check=True)
        subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)

        subprocess.run(["git", "add", "ApiData.json"], check=True)

        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, check=False
        )

        if status_result.stdout.strip():
            subprocess.run(["git", "commit", "-m", "Update ApiData.json [auto]"], check=True)

            # Push using the same credential helper (already set globally)
            subprocess.run(["git", "push"], check=True)
            print("✅ Changes committed and pushed")
        else:
            print("No changes in ApiData.json → skipping commit/push")

    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        raise
    finally:
        # Restore original working directory
        os.chdir(original_dir)


if __name__ == "__main__":
    main()