import json
import os
import sys
import requests
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
APPS_FILE = 'apps.json'
TRACKED_FILE = 'tracked_apps.txt'
FDROID_BASE_URL = 'https://f-droid.org/en/packages/'

# --- UTILS ---
def load_apps():
    if not os.path.exists(APPS_FILE):
        return []
    try:
        with open(APPS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {APPS_FILE}: {e}")
        return []

def save_apps(apps):
    try:
        with open(APPS_FILE, 'w', encoding='utf-8') as f:
            # ensure_ascii=False prevents \uXXXX escaping, keeping file readable
            json.dump(apps, f, indent=2, ensure_ascii=False)
        print(f"✅ Saved changes to {APPS_FILE}")
    except Exception as e:
        print(f"Error saving {APPS_FILE}: {e}")

def get_fdroid_metadata(package_input):
    """Scrapes F-Droid for app details. Returns dict in OrionStore format."""
    
    # Clean input to get Package ID (handles full URLs or just IDs)
    package_id = package_input.strip()
    if 'f-droid.org' in package_id:
        package_id = package_id.rstrip('/').split('/')[-1]

    url = f"{FDROID_BASE_URL}{package_id}/"
    print(f"🔍 Fetching metadata for: {package_id}...")
    
    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            print(f"❌ Failed to fetch page (Status: {response.status_code})")
            return None
            
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 1. Basic Info
        title_tag = soup.find(class_='package-name')
        name = title_tag.get_text(strip=True) if title_tag else package_id
        
        summary_tag = soup.find(class_='package-summary')
        summary = summary_tag.get_text(strip=True) if summary_tag else "No description available."
        
        icon_tag = soup.find(class_='package-icon')
        icon_url = icon_tag['src'] if icon_tag else ""
        if icon_url and not icon_url.startswith('http'):
            icon_url = f"https://f-droid.org{icon_url}"
            
        # 2. Screenshots
        screenshots = []
        for img in soup.select('.screenshot-container img'):
            src = img.get('src')
            if src:
                if not src.startswith('http'):
                    src = f"https://f-droid.org{src}"
                screenshots.append(src)
                
        # 3. Latest Version & APK Link
        version = "Latest"
        download_url = "#"
        size = "Varies"
        
        # F-Droid lists versions. Usually the first one is the suggested one.
        version_item = soup.find(class_='package-version')
        if version_item:
            header = version_item.find(class_='package-version-header')
            if header:
                raw_ver = header.get_text(strip=True)
                # Cleanup: "Version 1.2.3 (Added on...)" -> "1.2.3"
                version = raw_ver.replace('Version', '').strip().split(' ')[0]
            
            apk_link = version_item.find('a', href=lambda x: x and x.endswith('.apk'))
            if apk_link:
                dl_href = apk_link['href']
                download_url = f"https://f-droid.org{dl_href}" if not dl_href.startswith('http') else dl_href
            
        # 4. Construct Object (Matching OrionStore Schema)
        return {
            "id": package_id.replace('.', '-'),
            "name": name,
            "description": summary,
            "icon": icon_url,
            "version": version,
            "latestVersion": version,
            "downloadUrl": download_url,
            "repoUrl": url,
            "githubRepo": "",  # Empty for F-Droid apps as we use direct downloadUrl
            "releaseKeyword": package_id,
            "packageName": package_id,
            "category": "Utility", # Default category
            "platform": "Android",
            "size": size,
            "author": "F-Droid",
            "screenshots": screenshots
        }

    except Exception as e:
        print(f"❌ Error scraping F-Droid: {e}")
        return None

# --- LOGIC ---

def sync_tracked_apps():
    """Reads tracked_apps.txt and ensures all listed apps are in apps.json."""
    if not os.path.exists(TRACKED_FILE):
        print(f"⚠️ {TRACKED_FILE} not found. Skipping sync.")
        return

    print(f"📂 Reading {TRACKED_FILE}...")
    with open(TRACKED_FILE, 'r') as f:
        # Filter out empty lines and comments
        lines = [l.strip() for l in f.readlines() if l.strip() and not l.startswith('#')]

    apps = load_apps()
    is_modified = False

    for line in lines:
        # Extract ID from URL if user pasted full URL
        package_id = line.rstrip('/').split('/')[-1]
        
        # Check if already in database (avoid duplicates)
        exists = any(app.get('packageName') == package_id for app in apps)
        
        if not exists:
            print(f"➕ New app detected in list: {package_id}")
            new_data = get_fdroid_metadata(package_id)
            if new_data:
                apps.append(new_data)
                is_modified = True
                print(f"   ✅ Added {new_data['name']}")
        else:
            print(f"   ✓ {package_id} is already tracked.")

    if is_modified:
        save_apps(apps)
    
    # Always run update check after sync
    update_all()

def update_all():
    """Checks for version updates for ALL F-Droid apps in apps.json."""
    apps = load_apps()
    updated_count = 0
    
    print(f"\n🔄 Checking updates for {len(apps)} apps...")
    
    for app in apps:
        # Only check apps that look like F-Droid apps
        repo = app.get('repoUrl', '')
        if 'f-droid.org' not in repo and app.get('author') != 'F-Droid':
            continue
            
        pkg = app.get('packageName')
        if not pkg: continue

        print(f"   Checking {app['name']} ({pkg})...")
        new_data = get_fdroid_metadata(pkg)
        
        if new_data:
            current_ver = app.get('latestVersion', '0.0.0')
            new_ver = new_data['latestVersion']
            
            # Simple string comparison to see if changed
            if new_ver != current_ver and new_ver != "Unknown":
                print(f"   🚀 Update found! {current_ver} -> {new_ver}")
                
                # Update specific fields
                app['version'] = new_ver
                app['latestVersion'] = new_ver
                app['downloadUrl'] = new_data['downloadUrl']
                # Refresh icon just in case
                if new_data['icon']: app['icon'] = new_data['icon']
                
                updated_count += 1
            else:
                print("   ✅ Up to date.")

    if updated_count > 0:
        save_apps(apps)
        print(f"\n🎉 Updated {updated_count} apps successfully!")
    else:
        print("\n✅ All apps are up to date.")

# --- MAIN ENTRY POINT ---
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python store_manager.py [sync|update]")
        sys.exit(1)
        
    command = sys.argv[1]
    
    if command == "sync":
        sync_tracked_apps()
    elif command == "update":
        update_all()
    else:
        print("Unknown command. Use 'sync' or 'update'.")
