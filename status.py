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
XUIDS_FILE_LINK = require_env("XUIDS_FILE_LINK")

CLONE_DIR = "private_repo"

# 1️⃣ clean clone directory if exists
if os.path.exists(CLONE_DIR):
    shutil.rmtree(CLONE_DIR)

# 2️⃣ safer clone (token not printed)
subprocess.run(
    ["git", "clone", f"https://github.com/{PREPO_NAME}.git", CLONE_DIR],
    check=True,
    env={**os.environ, "GIT_ASKPASS": "echo", "GIT_TERMINAL_PROMPT": "0"}
)

# read xuids.txt
with open(f"{CLONE_DIR}/xuids.txt", "r", encoding="utf-8") as f:
    xuids_list = [line.strip() for line in f if line.strip()]

# 5️⃣ empty XUID guard
if not xuids_list:
    raise RuntimeError("XUID list is empty")

XUIDS = ",".join(xuids_list)
print("📥 Successfully XUIDs Load Completed")

url_info = f"https://xbl.io/api/v2/account/{XUIDS}"
url_presence = f"https://xbl.io/api/v2/{XUIDS}/presence"

headers = {
    "x-authorization": API_KEY,
    "accept": "application/json"
}

# 3️⃣ API status validation
info_r = requests.get(url_info, headers=headers)
info_r.raise_for_status()
info_res = info_r.json()

presence_r = requests.get(url_presence, headers=headers)
presence_r.raise_for_status()
presence_res = presence_r.json()

# 4️⃣ response structure validation
if not isinstance(presence_res, list):
    raise RuntimeError("Invalid presence API response")

presence_map = {
    p["xuid"]: p.get("lastSeen", {})
    for p in presence_res
}

FINAL_DATA = []

for user in info_res.get("people", []):
    xuid = user["xuid"]
    last_seen = presence_map.get(xuid)

    if last_seen:
        # 6️⃣ consistent lastSeenDateTimeUtc
        user["lastSeenDateTimeUtc"] = last_seen.get("timestamp")

        merged_user = {}
        for key, value in user.items():
            merged_user[key] = value
            if key == "isXbox360Gamerpic":
                merged_user["deviceType"] = last_seen.get("deviceType")
                merged_user["titleId"] = last_seen.get("titleId")
                merged_user["titleName"] = last_seen.get("titleName")

        user = merged_user

    FINAL_DATA.append(user)

with open("ApiData.json", "w", encoding="utf-8") as f:
    json.dump(FINAL_DATA, f, indent=4, ensure_ascii=False)

print("✅ Data successfully written to ApiData.json")

shutil.copy("ApiData.json", f"{CLONE_DIR}/ApiData.json")

os.chdir(CLONE_DIR)
subprocess.run(["git", "config", "user.name", "github-actions"], check=True)
subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
subprocess.run(["git", "add", "ApiData.json"], check=True)

result = subprocess.run(
    ["git", "status", "--porcelain"],
    capture_output=True,
    text=True
)

if result.stdout.strip():
    subprocess.run(["git", "commit", "-m", "Update ApiData.json"], check=True)
    subprocess.run(["git", "push"], check=True)
    print("🚀 ApiData.json updated in private repo")
else:
    print("ℹ️ No changes detected, skipping push")

# 7️⃣ sensitive file cleanup
os.remove("../ApiData.json")
