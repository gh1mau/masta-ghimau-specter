import requests
import json
import time
import os
import urllib3
from datetime import datetime, timedelta

# Disable SSL warnings for fallback mode
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# CONFIGURATION
# ============================================================
NVD_API_BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"
OUTPUT_PATH = os.path.join("data", "vulndb.json")
MAX_RETRIES = 3
RESULTS_PER_PAGE = 2000  # Maximum allowed by NVD API

# OPTIONAL: Get API Key from https://nvd.nist.gov/developers/request-an-api-key
API_KEY = os.getenv("NVD_API_KEY")

# Base headers - User-Agent is REQUIRED by NVD API
BASE_HEADERS = {
    "User-Agent": "Masta-Specter-VulnDB-Updater/2.0 (Windows; Python-requests/2.0)",
    "Accept": "application/json"
}

if API_KEY:
    BASE_HEADERS["apiKey"] = API_KEY
    DELAY = 0.6  # With API key
    print("[INFO] Using API Key - Fast mode")
else:
    DELAY = 6.0  # Without API key: 6 seconds (NVD rate limit: 5 requests per 30 sec)
    print("[WARNING] No API Key - Slow mode (6s delay enforced)")

# ============================================================
# FUNCTIONS
# ============================================================
def load_existing_database():
    """Load existing database to preserve data if API fails"""
    if os.path.exists(OUTPUT_PATH):
        try:
            with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                count = data.get("metadata", {}).get("total_cves", 0)
                print(f"[INFO] Loaded existing database: {count} CVEs cached")
                return data
        except Exception as e:
            print(f"[WARNING] Could not load existing database: {e}")
    return None

def fetch_cves(keyword, existing_cves=None):
    """
    Fetch ALL CVEs from NVD API 2.0 with pagination support
    Returns: List of all CVEs (or existing data if API fails)
    """
    all_cves = []
    start_index = 0
    total_results = None
    page_count = 0
    
    print(f"[NVD] Starting full fetch for '{keyword}'...")
    
    while True:
        params = {
            "keywordSearch": keyword,
            "resultsPerPage": RESULTS_PER_PAGE,
            "startIndex": start_index
        }
        
        success = False
        response_data = None
        
        # Retry logic for each page
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                print(f"[NVD] Fetching page {page_count + 1} (index {start_index})... ", end="")
                
                # Try with SSL verification first
                try:
                    response = requests.get(
                        NVD_API_BASE,
                        params=params,
                        headers=BASE_HEADERS,
                        timeout=60,
                        verify=True
                    )
                except requests.exceptions.SSLError:
                    response = requests.get(
                        NVD_API_BASE,
                        params=params,
                        headers=BASE_HEADERS,
                        timeout=60,
                        verify=False
                    )
                
                if response.status_code == 200:
                    data = response.json()
                    vulnerabilities = data.get("vulnerabilities", [])
                    
                    # Get total results on first request
                    if total_results is None:
                        total_results = data.get("totalResults", 0)
                        print(f"Total available: {total_results} CVEs")
                    
                    # Process this page
                    for item in vulnerabilities:
                        cve = item.get("cve", {})
                        cve_id = cve.get("id", "N/A")
                        
                        # Get English description
                        descriptions = cve.get("descriptions", [])
                        description = "No description available"
                        for desc in descriptions:
                            if desc.get("lang") == "en":
                                description = desc.get("value", "")
                                break
                        
                        # Get severity (CVSS v3.1 or v3.0)
                        metrics = cve.get("metrics", {})
                        severity = "UNKNOWN"
                        if "cvssMetricV31" in metrics and metrics["cvssMetricV31"]:
                            severity = metrics["cvssMetricV31"][0].get("cvssData", {}).get("baseSeverity", "UNKNOWN")
                        elif "cvssMetricV30" in metrics and metrics["cvssMetricV30"]:
                            severity = metrics["cvssMetricV30"][0].get("cvssData", {}).get("baseSeverity", "UNKNOWN")
                        
                        all_cves.append({
                            "id": cve_id,
                            "description": description,
                            "published": cve.get("published", ""),
                            "lastModified": cve.get("lastModified", ""),
                            "severity": severity,
                            "references": [ref.get("url", "") for ref in cve.get("references", [])[:3]]
                        })
                    
                    print(f"Got {len(vulnerabilities)} CVEs (Total collected: {len(all_cves)})")
                    success = True
                    response_data = data
                    break
                    
                elif response.status_code == 404:
                    print(f"Error 404")
                    time.sleep(DELAY * attempt)
                    
                elif response.status_code == 403:
                    print(f"Error 403 - Rate limited, waiting 30s...")
                    time.sleep(30)
                    
                elif response.status_code == 503:
                    print(f"Error 503 - Server busy")
                    time.sleep(10)
                    
                else:
                    print(f"Error {response.status_code}")
                    time.sleep(DELAY)
                    
            except requests.exceptions.Timeout:
                print(f"Timeout")
                time.sleep(DELAY * attempt)
                
            except requests.exceptions.RequestException as e:
                print(f"Network error: {e}")
                time.sleep(DELAY * attempt)
                
            except json.JSONDecodeError:
                print(f"Invalid JSON")
                time.sleep(DELAY)
                
            except Exception as e:
                print(f"Error: {e}")
                time.sleep(DELAY)
        
        if not success:
            print(f"[NVD] Failed to fetch page at index {start_index}")
            break
        
        # Check if we have all results
        if len(all_cves) >= total_results:
            print(f"[NVD] All pages fetched for '{keyword}'")
            break
            
        # Move to next page
        start_index += RESULTS_PER_PAGE
        page_count += 1
        
        # Rate limiting between pages
        if len(all_cves) < total_results:
            time.sleep(DELAY)
    
    print(f"[NVD] Completed: {len(all_cves)} CVEs fetched for '{keyword}'")
    
    # If we got nothing but have existing data, return that
    if len(all_cves) == 0 and existing_cves and isinstance(existing_cves, list):
        print(f"[NVD] Using cached data ({len(existing_cves)} CVEs)")
        return existing_cves
        
    return all_cves

def generate_signatures(cves_dict):
    """Generate exposure signatures from CVEs"""
    keywords_map = {
        "wordpress": ["wp-content", "wp-includes", "wordpress", "wp-admin"],
        "joomla": ["joomla", "com_content", "com_users", "option=com_"],
        "drupal": ["drupal", "sites/default", "node/"],
        "apache": ["apache", "httpd", ".htaccess", "server-status"],
        "nginx": ["nginx", "conf", "ngx_"],
        "php": ["php", ".php", "phpinfo"]
    }
    
    signatures = {}
    for platform, keyword_list in keywords_map.items():
        signatures[platform] = {
            "indicators": keyword_list,
            "cve_count": len(cves_dict.get(platform, []))
        }
    
    return signatures

# ============================================================
# MAIN
# ============================================================
def main():
    print("="*60)
    print("Masta Ghimau Specter - CVE Database Updater (FULL FETCH)")
    print("="*60)
    print(f"[INFO] API Endpoint: {NVD_API_BASE}")
    print(f"[INFO] Results per page: {RESULTS_PER_PAGE}")
    print(f"[INFO] Output: {OUTPUT_PATH}")
    print("-"*60)
    
    # Ensure data directory exists
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    
    # Load existing data for fallback
    existing_db = load_existing_database()
    existing_cves = existing_db.get("cves", {}) if existing_db else {}
    
    all_cves = {}
    
    # 1. WordPress
    print("\n[1/5] Fetching WordPress CVEs...")
    all_cves["wordpress"] = fetch_cves("wordpress", existing_cves.get("wordpress"))
    time.sleep(DELAY)
    
    # 2. Joomla
    print("\n[2/5] Fetching Joomla CVEs...")
    all_cves["joomla"] = fetch_cves("joomla", existing_cves.get("joomla"))
    time.sleep(DELAY)
    
    # 3. Drupal
    print("\n[3/5] Fetching Drupal CVEs...")
    all_cves["drupal"] = fetch_cves("drupal", existing_cves.get("drupal"))
    time.sleep(DELAY)
    
    # 4. Generic (Apache, Nginx, PHP)
    print("\n[4/5] Fetching generic CVEs...")
    all_cves["generic"] = []
    
    generic_keywords = [
        ("apache http server", "apache"),
        ("nginx", "nginx"), 
        ("php", "php")
    ]
    
    for keyword, key in generic_keywords:
        existing_generic = existing_cves.get("generic", [])
        existing_filtered = [c for c in existing_generic if keyword.lower() in c.get("description", "").lower()] if existing_generic else []
        
        cves = fetch_cves(keyword, existing_filtered)
        all_cves["generic"].extend(cves)
        time.sleep(DELAY)
    
    # 5. Generate Signatures
    print("\n[5/5] Generating exposure signatures...")
    signatures = generate_signatures(all_cves)
    
    # Calculate totals
    total_cves = (
        len(all_cves.get("wordpress", [])) + 
        len(all_cves.get("joomla", [])) + 
        len(all_cves.get("drupal", [])) + 
        len(all_cves.get("generic", []))
    )
    
    # Build database structure
    database = {
        "metadata": {
            "last_updated": datetime.now().isoformat(),
            "next_update": (datetime.now() + timedelta(days=7)).isoformat(),
            "schema_version": "2.0",
            "source": "NVD API 2.0",
            "total_cves": total_cves,
            "api_key_used": bool(API_KEY),
            "results_per_page": RESULTS_PER_PAGE
        },
        "cves": all_cves,
        "signatures": signatures
    }
    
    # Save database
    print(f"\n[SAVE] Writing database to: {OUTPUT_PATH}")
    try:
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(database, f, indent=2, ensure_ascii=False)
        print("[SAVE] Database saved successfully")
    except Exception as e:
        print(f"[SAVE] Error saving database: {e}")
        return
    
    # Summary
    print("\n" + "="*60)
    print("DATABASE UPDATE SUMMARY")
    print("="*60)
    print(f"Total CVEs: {total_cves}")
    print(f"  - WordPress: {len(all_cves.get('wordpress', []))}")
    print(f"  - Joomla: {len(all_cves.get('joomla', []))}")
    print(f"  - Drupal: {len(all_cves.get('drupal', []))}")
    print(f"  - Generic: {len(all_cves.get('generic', []))}")
    print("-"*60)
    print(f"Output: {os.path.abspath(OUTPUT_PATH)}")
    print(f"Last Updated: {database['metadata']['last_updated'][:10]}")
    print(f"Next Update: {database['metadata']['next_update'][:10]}")
    print("="*60)
    
    # Validation
    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            test_load = json.load(f)
        print("[VALIDATE] Database structure is valid")
        
        if total_cves == 0:
            print("\n[WARNING] No CVEs found! API might be unavailable.")
        else:
            print(f"\n[SUCCESS] CVE database updated with {total_cves} entries!")
            
    except Exception as e:
        print(f"[VALIDATE] Error: {e}")

if __name__ == "__main__":
    main()
