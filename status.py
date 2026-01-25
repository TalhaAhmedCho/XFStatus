import os
import json
import subprocess
import shutil
import requests

def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

API_KEY = require_env("API_KEY")
PA_TOKEN = require_env("PA_TOKEN")
PREPO_NAME = require_env("PREPO_NAME")

REPO_URL = f"https://{PA_TOKEN}@github.com/{PREPO_NAME}.git"
CLONE_DIR = "private_repo"

# clone private repo (read purpose)
subprocess.run(["git", "clone", REPO_URL, CLONE_DIR], check=True)

# read xuids.txt
with open(f"{CLONE_DIR}/xuids.txt", "r", encoding="utf-8") as f:
    XUIDS = ",".join(
        line.strip()
        for line in f
        if line.strip()
    )

print(f"📥 Successfully XUIDs Load Completed")

url_info = f"https://xbl.io/api/v2/account/{XUIDS}"
url_presence = f"https://xbl.io/api/v2/{XUIDS}/presence"

headers = {
    "x-authorization": API_KEY,
    "accept": "application/json"
}

info_res = requests.get(url_info, headers=headers).json()
presence_res = requests.get(url_presence, headers=headers).json()

# 🔹 presence map (xuid → lastSeen)
presence_map = {
    p["xuid"]: p.get("lastSeen", {})
    for p in presence_res
}

FINAL_DATA = []

for user in info_res.get("people", []):
    xuid = user["xuid"]
    last_seen = presence_map.get(xuid)

    if last_seen:
        # 🔹 timestamp → lastSeenDateTimeUtc overwrite
        if "timestamp" in last_seen:
            user["lastSeenDateTimeUtc"] = last_seen["timestamp"]

        # 🔹 insert lastSeen details after isXbox360Gamerpic
        merged_user = {}
        for key, value in user.items():
            merged_user[key] = value

            if key == "isXbox360Gamerpic":
                merged_user["deviceType"] = last_seen.get("deviceType")
                merged_user["titleId"] = last_seen.get("titleId")
                merged_user["titleName"] = last_seen.get("titleName")

        user = merged_user

    FINAL_DATA.append(user)

# 🔹 Final output (single merged object per user)
with open("ApiData.json", "w", encoding="utf-8") as f:
    json.dump(FINAL_DATA, f, indent=4, ensure_ascii=False)
print("Data successfully written to ApiData.json")

# Copy ApiData.json
shutil.copy("ApiData.json", f"{CLONE_DIR}/ApiData.json")

# Commit & push
os.chdir(CLONE_DIR)
subprocess.run(["git", "config", "user.name", "github-actions"], check=True)
subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)

subprocess.run(["git", "add", "ApiData.json"], check=True)

# commit only if changed
result = subprocess.run(
    ["git", "status", "--porcelain"],
    capture_output=True,
    text=True
)

if result.stdout.strip():
    subprocess.run(["git", "commit", "-m", "Update ApiData.json"], check=True)
    subprocess.run(["git", "push"], check=True)
    print("✅ ApiData.json updated in private repo")
else:
    print("ℹ️ No changes detected, skipping push")
