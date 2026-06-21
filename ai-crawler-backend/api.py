from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import redis
import requests
import threading
import time
import os
import re
import json
import random
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import dns.resolver
import socket
from datetime import datetime
from difflib import SequenceMatcher
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict
from collections import deque
import xml.etree.ElementTree as ET


class RateLimiter:
    def __init__(self, min_delay=0.1, max_delay=0.5):
        self.min_delay = min_delay
        self.max_delay = max_delay
    
    def wait_if_needed(self):
        # 1. Generate random delay (The ffuf trick)
        jitter = random.uniform(self.min_delay, self.max_delay)
        # 2. Execution pause
        time.sleep(jitter)

# These initializations are now correct for the new class
subdomain_limiter = RateLimiter(min_delay=0.2, max_delay=1.0)  
directory_limiter = RateLimiter(min_delay=0.2, max_delay=1.0)  

# User-Agent rotation pool
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0',
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
]

HEADERS_POOL = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Sec-Fetch-Mode": "navigate"
    }
]

def get_random_user_agent():
    """Get a random user agent from the pool"""
    return random.choice(USER_AGENTS)


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
CACHE_TTL = 86400  

# Mount React build folder
frontend_path = os.path.join(os.path.dirname(__file__), "frontend_build")
app.mount("/static", StaticFiles(directory=os.path.join(frontend_path, "static")), name="static")

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(frontend_path, "index.html"))

# ----- Enhanced deep crawling logic -----
tasks = {}

# Load subdomain wordlist from file
def load_subdomain_wordlist(limit=500):
    """Load subdomain wordlist from local file"""
    try:
        wordlist_path = os.path.join(os.path.dirname(__file__), "wordlists", "subdomains.txt")
        with open(wordlist_path, 'r', encoding='utf-8', errors='ignore') as f:
            # Read all lines, strip whitespace, remove empty lines
            wordlist = [line.strip() for line in f if line.strip()]
            total_loaded = len(wordlist)
            actual_limit = min(limit, total_loaded)
            print(f"[WORDLIST] Loaded {total_loaded} subdomains from file, using first {actual_limit}")
            return wordlist[:actual_limit]
    except FileNotFoundError:
        print("[WORDLIST] ⚠️  Warning: wordlist file not found at 'wordlists/subdomains.txt'")
        print("[WORDLIST] Using fallback minimal wordlist")
        # Fallback to small default list
        return [
            'www', 'mail', 'remote', 'blog', 'webmail', 'server', 'ns1', 'ns2', 
            'smtp', 'secure', 'vpn', 'api', 'dev', 'staging', 'admin', 'portal', 
            'app', 'test', 'demo', 'm', 'mobile', 'cdn', 'assets', 'static'
        ]
    except Exception as e:
        print(f"[WORDLIST] ❌ Error loading wordlist: {e}")
        return []
SUBDOMAIN_WORDLIST = load_subdomain_wordlist(limit=500)  

# Directory wordlists
def load_directory_wordlist(limit=500):
    """Load directory wordlist from local file"""
    try:
        wordlist_path = os.path.join(os.path.dirname(__file__), "wordlists", "directories.txt")
        with open(wordlist_path, 'r', encoding='utf-8', errors='ignore') as f:
            wordlist = []
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if not line.startswith('/'):
                        line = '/' + line
                    wordlist.append(line)
            
            total_loaded = len(wordlist)
            actual_limit = min(limit, total_loaded)
            print(f"[WORDLIST] Loaded {total_loaded} directories from file, using first {actual_limit}")
            return wordlist[:actual_limit]
    except FileNotFoundError:
        print("[WORDLIST] ⚠️  Warning: directory wordlist file not found at 'wordlists/directories.txt'")
        print("[WORDLIST] Using fallback minimal directory wordlist")
        return [
            '/admin', '/administrator', '/api', '/assets', '/images', '/js', '/css',
            '/uploads', '/upload', '/download', '/downloads', '/docs', '/doc', 
            '/backup', '/backups', '/config', '/configuration', '/login', '/signin',
            '/dashboard', '/panel', '/cpanel', '/phpmyadmin', '/phpMyAdmin',
            '/wp-admin', '/wp-content', '/wp-includes', '/wordpress'
        ]
    except Exception as e:
        print(f"[WORDLIST] ❌ Error loading directory wordlist: {e}")
        return []
DIRECTORY_WORDLIST = load_directory_wordlist(limit=500)

# Subdomain takeover signatures
TAKEOVER_SIGNATURES = {
    'Heroku': {
        'cname_patterns': ['herokuapp.com'],
        'fingerprints': ['no such app', 'no such application', 'heroku | no such app'],
        'http_status': [404, 503]
    },
    'GitHub Pages': {
        'cname_patterns': ['github.io'],
        'fingerprints': ['there isn\'t a github pages site here', 'repository not found', '404 not found'],
        'http_status': [404]
    },
    'AWS S3': {
        'cname_patterns': ['s3.amazonaws.com', 's3-website'],
        'fingerprints': ['nosuchbucket', 'the specified bucket does not exist'],
        'http_status': [404]
    },
    'Azure': {
        'cname_patterns': ['azurewebsites.net', 'cloudapp.azure.com', 'cloudapp.net'],
        'fingerprints': ['404 web site not found', 'error 404', 'this web app has been stopped'],
        'http_status': [404]
    },
    'Netlify': {
        'cname_patterns': ['netlify.app', 'netlify.com'],
        'fingerprints': ['not found', 'page not found'],
        'http_status': [404]
    },
    'Shopify': {
        'cname_patterns': ['myshopify.com'],
        'fingerprints': ['sorry, this shop is currently unavailable', 'only one step left'],
        'http_status': [404]
    },
    'AWS CloudFront': {
        'cname_patterns': ['cloudfront.net'],
        'fingerprints': ['the request could not be satisfied', 'bad request'],
        'http_status': [403, 404]
    },
    'Fastly': {
        'cname_patterns': ['fastly.net'],
        'fingerprints': ['fastly error: unknown domain'],
        'http_status': [404]
    },
    'Pantheon': {
        'cname_patterns': ['pantheonsite.io'],
        'fingerprints': ['404 error unknown site'],
        'http_status': [404]
    },
    'Tumblr': {
        'cname_patterns': ['tumblr.com'],
        'fingerprints': ['there\'s nothing here', 'whatever you were looking for doesn\'t currently exist'],
        'http_status': [404]
    },
    'WordPress.com': {
        'cname_patterns': ['wordpress.com'],
        'fingerprints': ['do you want to register'],
        'http_status': [404]
    },
    'Cargo': {
        'cname_patterns': ['cargocollective.com'],
        'fingerprints': ['404 not found'],
        'http_status': [404]
    },
    'Feedpress': {
        'cname_patterns': ['redirect.feedpress.me'],
        'fingerprints': ['the feed has not been found'],
        'http_status': [404]
    },
    'Ghost': {
        'cname_patterns': ['ghost.io'],
        'fingerprints': ['the thing you were looking for is no longer here'],
        'http_status': [404]
    },
    'Surge.sh': {
        'cname_patterns': ['surge.sh'],
        'fingerprints': ['project not found'],
        'http_status': [404]
    }
}

def check_subdomain_async(subdomain: str, domain: str) -> Dict:
    """Check if subdomain exists and get HTTP status with rate limiting"""
    # Apply rate limiting
    subdomain_limiter.wait_if_needed()
    
    full_domain = f"{subdomain}.{domain}"
    result = {'subdomain': full_domain, 'exists': False, 'status': None}
    
    try:
        # DNS check
        socket.gethostbyname(full_domain)
        result['exists'] = True
        
        # HTTP check with retries and backoff
        max_retries = 2
        for attempt in range(max_retries):
            try:
                headers = {'User-Agent': get_random_user_agent()}
                url = f"https://{full_domain}"
                response = requests.head(url, timeout=3, headers=headers, allow_redirects=True)
                
                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 3))
                    time.sleep(min(retry_after, 10))  # Max 10 seconds
                    continue
                
                result['status'] = response.status_code
                break
                
            except requests.exceptions.SSLError:
                # Try HTTP if HTTPS fails
                try:
                    url = f"http://{full_domain}"
                    response = requests.head(url, timeout=3, headers=headers, allow_redirects=True)
                    
                    if response.status_code == 429:
                        time.sleep(2 ** attempt)
                        continue
                    
                    result['status'] = response.status_code
                    break
                except:
                    result['status'] = 'SSL Error'
                    break
            except:
                if attempt < max_retries - 1:
                    time.sleep(1)
                else:
                    result['status'] = 'Connection Failed'
                break
                
    except socket.gaierror:
        pass
    
    return result

def check_directory_async(base_url: str, path: str) -> Dict:
    """Check if directory exists and get HTTP status with rate limiting"""
    # Apply rate limiting
    directory_limiter.wait_if_needed()
    
    full_url = urljoin(base_url, path)
    result = {'path': path, 'exists': False, 'status': None}
    
    max_retries = 2
    for attempt in range(max_retries):
        try:
            headers = {'User-Agent': get_random_user_agent()}
            response = requests.head(full_url, timeout=3, headers=headers, allow_redirects=True)
            
            # Handle rate limiting
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 3))
                time.sleep(min(retry_after * (attempt + 1), 10))
                continue
            
            # Only consider these status codes as "interesting"
            interesting_codes = [200, 201, 301, 302, 303, 403]
            if response.status_code in interesting_codes:
                result['exists'] = True
                result['status'] = response.status_code
            
            break  # Success, exit retry loop
            
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt) 
            continue
    
    return result

def find_subdomains_parallel(domain: str, max_workers: int = 10) -> List[Dict]:
    """Find subdomains using parallel DNS enumeration with rate limiting"""
    results = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(check_subdomain_async, sub, domain) for sub in SUBDOMAIN_WORDLIST]
        for future in futures:
            result = future.result()
            if result['exists']:
                results.append(result)
    
    return results

def discover_directories_parallel(base_url: str, max_workers: int = 8) -> List[Dict]:
    """Discover directories using parallel requests with rate limiting"""
    results = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(check_directory_async, base_url, path) for path in DIRECTORY_WORDLIST]
        for future in futures:
            result = future.result()
            if result['exists']:
                results.append(result)
    
    return results

def extract_all_js_files(soup, base_url, html_content):
    """Enhanced JS file extraction"""
    js_files = set()
    
    # 1. Script tags with src
    for script in soup.find_all('script', src=True):
        src = script.get('src', '')
        if src:
            if src.startswith('//'):
                src = 'https:' + src
            elif src.startswith('/'):
                src = urljoin(base_url, src)
            elif not src.startswith('http'):
                src = urljoin(base_url, src)
            js_files.add(src)
    
    # 2. Inline script references
    inline_js_pattern = r'["\']([^"\']*\.js[^"\']*)["\']'
    matches = re.findall(inline_js_pattern, html_content)
    for match in matches:
        if match.startswith('http'):
            js_files.add(match)
        elif match.startswith('//'):
            js_files.add('https:' + match)
        elif match.startswith('/'):
            js_files.add(urljoin(base_url, match))
    
    # 3. Webpack/bundler patterns
    webpack_pattern = r'(?:src|href)=["\'](.*?(?:bundle|chunk|vendor|runtime|main|app).*?\.js)["\'"]'
    webpack_matches = re.findall(webpack_pattern, html_content, re.IGNORECASE)
    for match in webpack_matches:
        if match.startswith('http'):
            js_files.add(match)
        elif match.startswith('//'):
            js_files.add('https:' + match)
        elif match.startswith('/'):
            js_files.add(urljoin(base_url, match))
    
    return list(js_files)

def detect_framework_versions(html_content: str, js_files: List[str]) -> Dict:
    """Detect framework versions from HTML and JS files"""
    versions = {}
    html_lower = html_content.lower()
    
    # React version detection
    react_patterns = [
        r'react[/@-](\d+\.\d+\.\d+)',
        r'react-dom[/@-](\d+\.\d+\.\d+)',
        r'"react":"(\d+\.\d+\.\d+)"',
        r'"react-dom":"(\d+\.\d+\.\d+)"'
    ]
    for pattern in react_patterns:
        match = re.search(pattern, html_content, re.IGNORECASE)
        if match:
            versions['React'] = match.group(1)
            break
    
    # Check JS file URLs for React version
    if 'React' not in versions:
        for js_file in js_files:
            match = re.search(r'react[/@-](\d+\.\d+\.\d+)', js_file, re.IGNORECASE)
            if match:
                versions['React'] = match.group(1)
                break
    
    # jQuery version
    jquery_patterns = [
        r'jquery[/-](\d+\.\d+\.\d+)',
        r'"jquery":"(\d+\.\d+\.\d+)"',
        r'jquery\.min\.js\?v=(\d+\.\d+\.\d+)'
    ]
    for pattern in jquery_patterns:
        match = re.search(pattern, html_content, re.IGNORECASE)
        if match:
            versions['jQuery'] = match.group(1)
            break
    
    # Bootstrap version
    bootstrap_patterns = [
        r'bootstrap[/-](\d+\.\d+\.\d+)',
        r'"bootstrap":"(\d+\.\d+\.\d+)"',
        r'bootstrap\.min\.css\?v=(\d+\.\d+\.\d+)'
    ]
    for pattern in bootstrap_patterns:
        match = re.search(pattern, html_content, re.IGNORECASE)
        if match:
            versions['Bootstrap'] = match.group(1)
            break
    
    # Vue.js version
    vue_patterns = [
        r'vue[/@-](\d+\.\d+\.\d+)',
        r'"vue":"(\d+\.\d+\.\d+)"'
    ]
    for pattern in vue_patterns:
        match = re.search(pattern, html_content, re.IGNORECASE)
        if match:
            versions['Vue.js'] = match.group(1)
            break
    
    # Angular version
    angular_patterns = [
        r'angular[/@-](\d+\.\d+\.\d+)',
        r'"@angular/core":"(\d+\.\d+\.\d+)"'
    ]
    for pattern in angular_patterns:
        match = re.search(pattern, html_content, re.IGNORECASE)
        if match:
            versions['Angular'] = match.group(1)
            break
    
    return versions

def analyze_cdn_resources(soup, html_content, base_url):
    """Analyze CDN and external resources"""
    cdn_info = {
        'primary_cdns': set(),
        'third_party_services': set(),
        'discovered_domains': set(),
        'versions': {}
    }
    
    # Extract all external URLs
    for tag in soup.find_all(['script', 'link', 'img'], src=True):
        src = tag.get('src') or tag.get('href', '')
        if src and ('://' in src or src.startswith('//')):
            if src.startswith('//'):
                src = 'https:' + src
            
            parsed = urlparse(src)
            domain = parsed.netloc
            
            # Skip if same domain as base
            base_domain = urlparse(base_url).netloc
            if domain == base_domain:
                continue
            
            cdn_info['discovered_domains'].add(domain)
            
            # Categorize CDNs and services
            if any(x in domain for x in ['cdn', 'cloudfront', 'akamai', 'fastly', 'cloudflare']):
                cdn_info['primary_cdns'].add(domain)
            elif any(x in domain for x in ['google', 'facebook', 'twitter', 'linkedin', 'doubleclick', 'analytics']):
                cdn_info['third_party_services'].add(domain)
            
            # Extract version from path
            version_match = re.search(r'[/-]v?(\d+\.\d+\.\d+)', src)
            if version_match and domain not in cdn_info['versions']:
                cdn_info['versions'][domain] = version_match.group(1)
    
    # Convert sets to lists for JSON serialization
    cdn_info['primary_cdns'] = list(cdn_info['primary_cdns'])
    cdn_info['third_party_services'] = list(cdn_info['third_party_services'])
    cdn_info['discovered_domains'] = list(cdn_info['discovered_domains'])
    
    return cdn_info

def extract_domain_keyword(domain: str) -> str:
    """Extract searchable keyword from domain"""
    # Remove www
    domain = domain.replace('www.', '')
    
    # Remove common subdomains
    common_subdomains = ['api', 'blog', 'shop', 'mail', 'cdn', 'static', 'assets', 'm', 'mobile']
    for sub in common_subdomains:
        if domain.startswith(f"{sub}."):
            domain = domain[len(sub)+1:]
    
    # Remove TLD (.com, .org, etc.)
    parts = domain.split('.')
    if len(parts) > 1:
        # Keep main part, remove TLD
        keyword = parts[0]
    else:
        keyword = domain
    
    return keyword

def search_cves_by_domain(domain: str) -> List[Dict]:
    """Search CVEs based on domain name"""
    keyword = extract_domain_keyword(domain)
    
    print(f"[CVE DOMAIN SEARCH] Searching for: {keyword}")
    
    try:
        url = "https://services.nvd.nist.gov/rest/json/cves/2.0"
        params = {
            'keywordSearch': keyword,
            'resultsPerPage': 20  # Get more results
        }
        
        headers_req = {'User-Agent': 'AI-Crawler-Security-Scanner/1.0'}
        response = requests.get(url, params=params, headers=headers_req, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            cves = []
            
            if 'vulnerabilities' in data and data['vulnerabilities']:
                for vuln in data['vulnerabilities']:
                    cve_item = vuln.get('cve', {})
                    cve_id = cve_item.get('id', 'N/A')
                    
                    # Get description
                    descriptions = cve_item.get('descriptions', [])
                    description = 'No description available'
                    for desc in descriptions:
                        if desc.get('lang') == 'en':
                            description = desc.get('value', '')[:300]
                            break
                    
                    # Get published date
                    published = cve_item.get('published', 'Unknown')
                    if published != 'Unknown':
                        try:
                            published = published.split('T')[0]  # Get just date part
                        except:
                            pass
                    
                    # Get severity
                    metrics = cve_item.get('metrics', {})
                    severity = 'Unknown'
                    score = 0
                    
                    if 'cvssMetricV31' in metrics and metrics['cvssMetricV31']:
                        cvss_data = metrics['cvssMetricV31'][0].get('cvssData', {})
                        severity = cvss_data.get('baseSeverity', 'Unknown')
                        score = cvss_data.get('baseScore', 0)
                    elif 'cvssMetricV2' in metrics and metrics['cvssMetricV2']:
                        score = metrics['cvssMetricV2'][0].get('cvssData', {}).get('baseScore', 0)
                        if score >= 7.0:
                            severity = 'HIGH'
                        elif score >= 4.0:
                            severity = 'MEDIUM'
                        else:
                            severity = 'LOW'
                    
                    cves.append({
                        'id': cve_id,
                        'severity': severity,
                        'score': score,
                        'description': description,
                        'published': published,
                        'link': f"https://nvd.nist.gov/vuln/detail/{cve_id}"
                    })
                
                # Sort by score (highest first), then by date (newest first)
                return sorted(cves, key=lambda x: (x['score'], x['published']), reverse=True)[:15]
            else:
                print(f"[CVE DOMAIN SEARCH] No CVEs found for: {keyword}")
                return []
    except Exception as e:
        print(f"[CVE DOMAIN SEARCH ERROR] {keyword}: {str(e)}")
        return []
    
    return []

def search_cves_enhanced(tech_name: str, version: str = None) -> List[Dict]:
    """Enhanced CVE search with better filtering"""
    try:
        search_keyword = tech_name.lower()
        
        url = "https://services.nvd.nist.gov/rest/json/cves/2.0"
        params = {
            'keywordSearch': f"{search_keyword} {version}" if version else search_keyword,
            'resultsPerPage': 10
        }
        
        headers_req = {'User-Agent': 'AI-Crawler-Security-Scanner/1.0'}
        response = requests.get(url, params=params, headers=headers_req, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            cves = []
            
            if 'vulnerabilities' in data:
                for vuln in data['vulnerabilities'][:5]:
                    cve_item = vuln.get('cve', {})
                    cve_id = cve_item.get('id', 'N/A')
                    
                    # Get description
                    descriptions = cve_item.get('descriptions', [])
                    description = 'No description available'
                    for desc in descriptions:
                        if desc.get('lang') == 'en':
                            description = desc.get('value', '')[:250]
                            break
                    
                    # Get severity
                    metrics = cve_item.get('metrics', {})
                    severity = 'Unknown'
                    score = 0
                    
                    if 'cvssMetricV31' in metrics and metrics['cvssMetricV31']:
                        cvss_data = metrics['cvssMetricV31'][0].get('cvssData', {})
                        severity = cvss_data.get('baseSeverity', 'Unknown')
                        score = cvss_data.get('baseScore', 0)
                    elif 'cvssMetricV2' in metrics and metrics['cvssMetricV2']:
                        score = metrics['cvssMetricV2'][0].get('cvssData', {}).get('baseScore', 0)
                        if score >= 7.0:
                            severity = 'HIGH'
                        elif score >= 4.0:
                            severity = 'MEDIUM'
                        else:
                            severity = 'LOW'
                    
                    cves.append({
                        'id': cve_id,
                        'severity': severity,
                        'score': score,
                        'description': description,
                        'link': f"https://nvd.nist.gov/vuln/detail/{cve_id}"
                    })
            
            return sorted(cves, key=lambda x: x['score'], reverse=True)
    except Exception as e:
        print(f"[CVE SEARCH ERROR] {tech_name}: {str(e)}")
        return []
    
    return []

def check_robots_txt(base_url):
    """Check and parse robots.txt"""
    try:
        robots_url = urljoin(base_url, '/robots.txt')
        r = requests.get(robots_url, timeout=5)
        if r.status_code == 200:
            return {'found': True, 'content': r.text[:1500]}
    except:
        pass
    return {'found': False, 'content': None}


GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

def get_github_headers():
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    else:
        print("[WARNING] No GitHub token found. Using unauthenticated requests (low rate limit).")
    return headers

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def _confidence_badge(level: str) -> str:
    colors = {"High": "#22c55e", "Medium": "#facc15", "Low": "#ef4444"}
    return f"<span style='color:{colors[level]};font-weight:bold'>{level}</span>"

def find_github_repo(html_content: str, soup, domain: str, company_aliases: dict = {}) -> list:
    """
    Finds the most likely GitHub organization for a domain.
    Works with or without a GitHub token, caches results in Redis.
    """
    domain = domain.replace("www.", "").lower().strip().rstrip("/")
    cache_key = f"github:{domain}"
    
    # Check Redis cache
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    results = []
    seen = set()
    
    company = domain.split(".")[0]
    search_terms = {company}

    # Add aliases if provided
    for alias in company_aliases.get(company, []):
        search_terms.add(alias)

    # 1️⃣ Strong signal: GitHub link on website
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "github.com" in href:
            match = re.search(r"github\.com/([^/\s]+)", href)
            if match:
                org = match.group(1)
                url = f"https://github.com/{org}"
                if url not in seen:
                    results.append({
                        "url": url,
                        "confidence": "High",
                        "badge": _confidence_badge("High"),
                        "reason": "GitHub link found on official website"
                    })
                    seen.add(url)

    if results:
        redis_client.setex(cache_key, CACHE_TTL, json.dumps(results))
        return results

    # 2️⃣ GitHub Search API — organization inference
    best_match = None
    best_score = 0
    headers = get_github_headers()

    try:
        for term in search_terms:
            search_url = f"{GITHUB_API}/search/users"
            params = {"q": f"{term} type:org", "per_page": 5}

            r = requests.get(search_url, headers=headers, params=params, timeout=10)
            if r.status_code != 200:
                continue

            for org in r.json().get("items", []):
                org_login = org.get("login")
                if not org_login:
                    continue

                org_url = f"{GITHUB_API}/orgs/{org_login}"
                o = requests.get(org_url, headers=headers, timeout=10)
                if o.status_code != 200:
                    continue

                data = o.json()
                score = 0

                # Name similarity
                score += _similarity(company, org_login) * 50

                # Verified organization
                if data.get("is_verified"):
                    score += 40

                # Website match
                blog = (data.get("blog") or "").lower()
                if company in blog or domain in blog:
                    score += 30

                # Description hint
                description = (data.get("description") or "").lower()
                if company in description:
                    score += 10

                if score > best_score:
                    best_score = score
                    best_match = {
                        "url": f"https://github.com/{org_login}",
                        "confidence": (
                            "High" if score >= 90 else
                            "Medium" if score >= 70 else
                            "Low"
                        ),
                        "badge": _confidence_badge(
                            "High" if score >= 90 else
                            "Medium" if score >= 70 else
                            "Low"
                        ),
                        "reason": "Matched via GitHub Search API",
                        "score": round(score)
                    }
    except Exception as e:
        print(f"[GitHub API ERROR] {str(e)}")

    if best_match:
        results.append(best_match)

    # 3️⃣ Final fallback — heuristic guess
    if not results:
        results.append({
            "url": f"https://github.com/{company}",
            "confidence": "Low",
            "badge": _confidence_badge("Low"),
            "reason": "Heuristic guess based on domain name"
        })

    # Cache results
    redis_client.setex(cache_key, CACHE_TTL, json.dumps(results))
    return results

            
def analyze_security_headers(headers):
    """Analyze security-related headers"""
    security = {}
    
    security_headers = {
        'Strict-Transport-Security': 'HSTS',
        'Content-Security-Policy': 'CSP',
        'X-Frame-Options': 'Clickjacking Protection',
        'X-Content-Type-Options': 'MIME-Type Protection',
        'X-XSS-Protection': 'XSS Protection',
        'Referrer-Policy': 'Referrer Policy'
    }
    
    for header, name in security_headers.items():
        value = headers.get(header, headers.get(header.lower(), None))
        security[name] = '✓ Enabled' if value else '✗ Missing'
    
    return security

def deep_crawl_analysis(url: str, html_content: str, headers: dict):
    """Perform comprehensive deep analysis"""
    
    soup = BeautifulSoup(html_content, 'html.parser')
    domain = urlparse(url).netloc.replace('www.', '')
    
    analysis = {
        "url": url,
        "domain": domain,
        "title": "",
        "basic_tech": {},
        "frameworks": [],
        "framework_versions": {},
        "cloud_hosting": [],
        "subdomains": [],
        "js_files": [],
        "directories": [],
        "cdn_resources": {},
        "robots_txt": {},
        "github_repos": [],
        "security_headers": {},
        "meta_info": {},
        "server_info": {},
        "performance": {},
        "domain_cves": [],
        "framework_cves": {},
        "hidden_parameters": [],
        "subdomain_takeovers": [],
        "s3_buckets": []
    }
    
    # Extract title
    title_tag = soup.find('title')
    if title_tag:
        analysis["title"] = title_tag.get_text().strip()
    
    # Meta tags
    meta_tags = soup.find_all('meta')
    for meta in meta_tags[:8]:
        name = meta.get('name') or meta.get('property', '')
        content = meta.get('content', '')
        if name and content:
            analysis["meta_info"][name] = content[:150]
    
    # Detect HTML version
    doctype = str(soup)[:200].lower()
    if '<!doctype html>' in doctype:
        analysis["basic_tech"]["HTML"] = "HTML5"
    
    # Detect CSS
    stylesheets = soup.find_all('link', rel='stylesheet')
    if stylesheets:
        analysis["basic_tech"]["CSS"] = f"{len(stylesheets)} stylesheet(s)"
    
    # Detect JavaScript
    scripts = soup.find_all('script')
    if scripts:
        analysis["basic_tech"]["JavaScript"] = f"{len(scripts)} script(s)"
    
    html_lower = html_content.lower()
    
    # Frontend Frameworks (basic detection)
    if 'react' in html_lower:
        analysis["frameworks"].append("React")
    if 'vue' in html_lower:
        analysis["frameworks"].append("Vue.js")
    if 'angular' in html_lower:
        analysis["frameworks"].append("Angular")
    if 'jquery' in html_lower:
        analysis["frameworks"].append("jQuery")
    if 'bootstrap' in html_lower:
        analysis["frameworks"].append("Bootstrap")
    
    # Server-side technologies
    if headers.get('x-powered-by'):
        powered = headers.get('x-powered-by')
        analysis["basic_tech"]["Server Technology"] = powered
    
    if 'xmlhttprequest' in html_lower or 'fetch(' in html_lower:
        analysis["basic_tech"]["AJAX"] = "Detected"
    
    if headers.get('server'):
        analysis["server_info"]["Server"] = headers.get('server')
    
    # Extract JS files
    print(f"[DEEP CRAWL] Extracting JavaScript files...")
    analysis["js_files"] = extract_all_js_files(soup, url, html_content)
    
    # Detect framework versions
    print(f"[DEEP CRAWL] Detecting framework versions...")
    analysis["framework_versions"] = detect_framework_versions(html_content, analysis["js_files"])
    
    # Cloud provider detection
    print(f"[DEEP CRAWL] Detecting cloud provider...")
    cloud_providers = []
    if 'amazonaws.com' in html_lower or 'aws' in html_lower:
        cloud_providers.append('Amazon Web Services (AWS)')
    if 'cloudfront' in html_lower:
        cloud_providers.append('AWS CloudFront (CDN)')
    if 'azure' in html_lower:
        cloud_providers.append('Microsoft Azure')
    if 'googleapis.com' in html_lower or 'gstatic.com' in html_lower:
        cloud_providers.append('Google Cloud Platform (GCP)')
    if headers.get('server', '').lower() == 'cloudflare' or 'cf-ray' in headers:
        cloud_providers.append('Cloudflare')
        global directory_limiter
        directory_limiter = RateLimiter(min_delay=1.5, max_delay=3.5)
    
    # Will check S3 buckets later - if found, add AWS
    analysis["cloud_hosting"] = cloud_providers
    
    # Parallel subdomain discovery
    print(f"[DEEP CRAWL] Finding subdomains (parallel)...")
    analysis["subdomains"] = find_subdomains_parallel(domain)
    
    # Parallel directory discovery
    print(f"[DEEP CRAWL] Discovering directories (parallel)...")
    analysis["directories"] = discover_directories_parallel(url)
    
    # CDN analysis
    print(f"[DEEP CRAWL] Analyzing CDN resources...")
    analysis["cdn_resources"] = analyze_cdn_resources(soup, html_content, url)
    
    # Robots.txt
    print(f"[DEEP CRAWL] Checking robots.txt...")
    analysis["robots_txt"] = check_robots_txt(url)
    
    # GitHub repos
    print(f"[DEEP CRAWL] Finding GitHub repositories...")
    analysis["github_repos"] = find_github_repo(html_content, soup, domain)
    
    # Security headers
    print(f"[DEEP CRAWL] Analyzing security headers...")
    analysis["security_headers"] = analyze_security_headers(headers)
    
    # Domain-based CVE search (PRIMARY)
    print(f"[DEEP CRAWL] Searching CVEs for domain: {domain}...")
    analysis["domain_cves"] = search_cves_by_domain(domain)
    
    # Also search CVEs for detected framework versions (SECONDARY)
    print(f"[DEEP CRAWL] Searching CVEs for detected frameworks...")
    for tech, version in analysis["framework_versions"].items():
        print(f"[CVE FRAMEWORK] Searching {tech} {version}...")
        cves = search_cves_enhanced(tech, version)
        if cves:
            analysis["framework_cves"][f"{tech} {version}"] = cves
    
    # Check subdomain takeover vulnerabilities
    print(f"[DEEP CRAWL] Checking subdomain takeover vulnerabilities...")
    takeovers = []
    for subdomain_info in analysis["subdomains"]:
        takeover = check_subdomain_takeover(subdomain_info)
        if takeover:
            takeovers.append(takeover)
    analysis["subdomain_takeovers"] = takeovers
    
    # Find and check S3 buckets
    print(f"[DEEP CRAWL] Discovering AWS S3 buckets...")
    analysis["s3_buckets"] = find_s3_buckets(html_content, soup, domain)
    
    # Update cloud hosting if S3 buckets found
    if analysis["s3_buckets"] and 'Amazon Web Services (AWS)' not in analysis["cloud_hosting"]:
        analysis["cloud_hosting"].insert(0, 'Amazon Web Services (AWS)')
    
    # If no cloud provider detected
    if not analysis["cloud_hosting"]:
        analysis["cloud_hosting"] = ['Unable to detect']
    
    # Performance metrics
    analysis["performance"]["Page Size"] = f"{len(html_content) / 1024:.2f} KB"
    analysis["performance"]["Total Scripts"] = len(scripts)
    analysis["performance"]["Total Stylesheets"] = len(stylesheets)
    analysis["performance"]["Images"] = len(soup.find_all('img'))
    
    return analysis

def get_status_label(status_code):
    """Convert status code to readable label"""
    if status_code == 200:
        return "200 OK"
    elif status_code == 301:
        return "301 Moved"
    elif status_code == 302:
        return "302 Redirect"
    elif status_code == 403:
        return "403 Forbidden"
    elif status_code == 404:
        return "404 Not Found"
    elif status_code == 500:
        return "500 Server Error"
    elif isinstance(status_code, int):
        return f"{status_code}"
    else:
        return str(status_code)

def check_subdomain_takeover(subdomain_info: Dict) -> Dict:
    """Check if subdomain is vulnerable to takeover"""
    subdomain = subdomain_info['subdomain']
    
    try:
        # Get CNAME record
        try:
            answers = dns.resolver.resolve(subdomain, 'CNAME')
            cname = str(answers[0].target).rstrip('.')
        except:
            return None  
        
        # Check if CNAME matches known vulnerable services
        for service, sig in TAKEOVER_SIGNATURES.items():
            if any(pattern in cname.lower() for pattern in sig['cname_patterns']):
                # Try to access the CNAME target
                try:
                    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                    
                    # Try HTTPS first
                    try:
                        response = requests.get(f"https://{subdomain}", headers=headers, timeout=5)
                    except:
                        # Fallback to HTTP
                        response = requests.get(f"http://{subdomain}", headers=headers, timeout=5)
                    
                    response_text = response.text.lower()
                    
                    # Check for vulnerability fingerprints
                    fingerprint_match = any(fp in response_text for fp in sig['fingerprints'])
                    status_match = response.status_code in sig['http_status']
                    
                    if fingerprint_match and status_match:
                        return {
                            'subdomain': subdomain,
                            'cname': cname,
                            'service': service,
                            'status': response.status_code,
                            'risk': 'HIGH',
                            'reason': 'CNAME exists but service not configured'
                        }
                    elif fingerprint_match or status_match:
                        return {
                            'subdomain': subdomain,
                            'cname': cname,
                            'service': service,
                            'status': response.status_code,
                            'risk': 'MEDIUM',
                            'reason': 'Possible misconfiguration detected'
                        }
                except:
                    return {
                        'subdomain': subdomain,
                        'cname': cname,
                        'service': service,
                        'status': 'Timeout/Error',
                        'risk': 'MEDIUM',
                        'reason': 'CNAME exists but target unreachable'
                    }
    except:
        pass
    
    return None

def find_s3_buckets(html_content: str, soup, domain: str) -> List[Dict]:
    """Find and check AWS S3 buckets"""
    buckets = set()
    
    # Pattern 1: Direct S3 URLs in HTML
    s3_patterns = [
        r'https?://([a-z0-9.-]+)\.s3\.amazonaws\.com',
        r'https?://s3\.amazonaws\.com/([a-z0-9.-]+)',
        r'https?://([a-z0-9.-]+)\.s3[.-]([a-z0-9-]+)\.amazonaws\.com',
        r's3://([a-z0-9.-]+)',
    ]
    
    for pattern in s3_patterns:
        matches = re.findall(pattern, html_content, re.IGNORECASE)
        for match in matches:
            if isinstance(match, tuple):
                buckets.add(match[0])
            else:
                buckets.add(match)
    
    # Pattern 2: Common naming conventions based on domain
    domain_name = domain.replace('.com', '').replace('.', '-')
    common_variations = [
        domain_name,
        f"{domain_name}-assets",
        f"{domain_name}-static",
        f"{domain_name}-media",
        f"{domain_name}-backup",
        f"{domain_name}-files",
        f"{domain_name}-public",
        f"{domain_name}-uploads"
    ]
    buckets.update(common_variations)
    
    # Check each bucket
    results = []
    for bucket in list(buckets)[:10]:  # Check max 10 buckets
        bucket_info = check_s3_bucket(bucket)
        if bucket_info:
            results.append(bucket_info)
    
    return results

def check_s3_bucket(bucket_name: str) -> Dict:
    """Check if S3 bucket exists and is publicly accessible"""
    bucket_url = f"https://{bucket_name}.s3.amazonaws.com/"
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(bucket_url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            # Check if we can list contents
            if '<?xml' in response.text and 'ListBucketResult' in response.text:
                # Parse XML to count objects
                try:
                    root = ET.fromstring(response.text)
                    contents = root.findall('.//{http://s3.amazonaws.com/doc/2006-03-01/}Contents')
                    
                    # Get sample files
                    sample_files = []
                    for content in contents[:5]:
                        key = content.find('{http://s3.amazonaws.com/doc/2006-03-01/}Key')
                        if key is not None:
                            sample_files.append(key.text)
                    
                    return {
                        'bucket': bucket_name,
                        'url': bucket_url,
                        'status': 'LISTABLE',
                        'risk': 'CRITICAL',
                        'object_count': len(contents),
                        'sample_files': sample_files,
                        'public': True
                    }
                except:
                    return {
                        'bucket': bucket_name,
                        'url': bucket_url,
                        'status': 'READABLE',
                        'risk': 'HIGH',
                        'public': True
                    }
            else:
                # Bucket exists and responds but listing disabled
                return {
                    'bucket': bucket_name,
                    'url': bucket_url,
                    'status': 'READABLE',
                    'risk': 'MEDIUM',
                    'note': 'Listing disabled but files may be accessible',
                    'public': True
                }
        elif response.status_code == 403:
            # Bucket exists but is private (good!)
            return {
                'bucket': bucket_name,
                'url': bucket_url,
                'status': 'PRIVATE',
                'risk': 'NONE',
                'public': False
            }
        elif response.status_code == 404:
            # Bucket doesn't exist
            return None
    except:
        return None
    
    return None

def format_deep_analysis(analysis: dict) -> str:
    """Format comprehensive analysis results as HTML"""
    
    lines = []
    lines.append('<div style="font-family: monospace; line-height: 1.6; color: #e6eef8;">')
    lines.append("=" * 70)
    lines.append("<br><strong style='font-size: 18px;'>🔍 DEEP WEB CRAWLER - COMPREHENSIVE ANALYSIS REPORT</strong><br>")
    lines.append("=" * 70)
    lines.append(f"<br><br>🌐 <strong>URL:</strong> <a href='{analysis['url']}' target='_blank' style='color: #4b72ff;'>{analysis['url']}</a>")
    lines.append(f"<br>🏷️  <strong>Title:</strong> {analysis['title']}")
    lines.append(f"<br>🔗 <strong>Domain:</strong> {analysis['domain']}")
    
    # Basic Technologies
    lines.append("<br><br><strong>🛠️  CORE TECHNOLOGIES:</strong><br>")
    lines.append("-" * 70 + "<br>")
    for tech, details in analysis['basic_tech'].items():
        lines.append(f"  ✓ {tech}: {details}<br>")
    
    # Frameworks
    if analysis['frameworks']:
        lines.append("<br><strong>📚 FRAMEWORKS & LIBRARIES:</strong><br>")
        lines.append("-" * 70 + "<br>")
        for fw in analysis['frameworks']:
            version = analysis['framework_versions'].get(fw, '')
            if version:
                lines.append(f"  ✓ {fw} {version}<br>")
            else:
                lines.append(f"  ✓ {fw}<br>")
    
    # Cloud Hosting
    lines.append("<br><strong>☁️  CLOUD HOSTING PROVIDER:</strong><br>")
    lines.append("-" * 70 + "<br>")
    for provider in analysis['cloud_hosting']:
        lines.append(f"  ✓ {provider}<br>")
    
    # Subdomains with status codes
    if analysis['subdomains']:
        lines.append(f"<br><strong>🔍 DISCOVERED SUBDOMAINS ({len(analysis['subdomains'])}):</strong><br>")
        lines.append("-" * 70 + "<br>")
        for sub in analysis['subdomains']:
            status_label = get_status_label(sub['status'])
            subdomain_link = f"https://{sub['subdomain']}"
            lines.append(f"  • <a href='{subdomain_link}' target='_blank' style='color: #4b72ff;'>{sub['subdomain']}</a> [{status_label}]<br>")
    
    # Directories with status codes
    if analysis['directories']:
        lines.append(f"<br><strong>📁 DISCOVERED DIRECTORIES ({len(analysis['directories'])}):</strong><br>")
        lines.append("-" * 70 + "<br>")
        for dir_info in analysis['directories']:
            status_label = get_status_label(dir_info['status'])
            dir_url = urljoin(f"https://{analysis['domain']}", dir_info['path'])
            lines.append(f"  • <a href='{dir_url}' target='_blank' style='color: #4b72ff;'>{dir_info['path']}</a> [{status_label}]<br>")
    
    # JavaScript Files
    if analysis['js_files']:
       lines.append(f"<br><strong>📜 JAVASCRIPT FILES ({len(analysis['js_files'])}):</strong><br>")
       lines.append("-" * 70 + "<br>")
       for js in analysis['js_files']:
           lines.append(f"  • <a href='{js}' target='_blank' style='color: #4b72ff;'>{js}</a><br>")
    
    # CDN & External Resources
    if analysis['cdn_resources']:
        cdn = analysis['cdn_resources']
        if cdn['primary_cdns'] or cdn['third_party_services'] or cdn['discovered_domains']:
            lines.append("<br><strong>📦 CDN & EXTERNAL RESOURCES:</strong><br>")
            lines.append("-" * 70 + "<br>")
            
            if cdn['primary_cdns']:
                lines.append("<br>  <strong>Primary CDNs:</strong><br>")
                for cdn_domain in cdn['primary_cdns']:
                    version = cdn['versions'].get(cdn_domain, '')
                    if version:
                        lines.append(f"    • {cdn_domain} (Version: {version})<br>")
                    else:
                        lines.append(f"    • {cdn_domain}<br>")
            
            if cdn['third_party_services']:
                lines.append("<br>  <strong>Third-Party Services:</strong><br>")
                for service in cdn['third_party_services']:
                    lines.append(f"    • {service}<br>")
            
            if cdn['discovered_domains']:
                lines.append(f"<br>  <strong>Additional Domains Discovered ({len(cdn['discovered_domains'])}):</strong><br>")
                for domain in cdn['discovered_domains'][:10]:
                    lines.append(f"    • {domain}<br>")
                if len(cdn['discovered_domains']) > 10:
                    lines.append(f"    ... and {len(cdn['discovered_domains']) - 10} more<br>")
    
    # Robots.txt
    lines.append("<br><strong>🤖 ROBOTS.TXT:</strong><br>")
    lines.append("-" * 70 + "<br>")
    if analysis['robots_txt']['found']:
        lines.append("  ✓ Found!<br>")
        robots_url = urljoin(f"https://{analysis['domain']}", '/robots.txt')
        lines.append(f"  <a href='{robots_url}' target='_blank' style='color: #4b72ff;'>View robots.txt</a><br><br>")
        lines.append("  <strong>Content Preview:</strong><br>")
        for line in analysis['robots_txt']['content'].split('\n')[:15]:
            if line.strip():
                lines.append(f"    {line}<br>")
    else:
        lines.append("  ✗ Not Found<br>")
    
    # GitHub Repos
    if analysis['github_repos']:
        lines.append(f"<br><strong>🐙 GITHUB REPOSITORIES ({len(analysis['github_repos'])}):</strong><br>")
        lines.append("-" * 70 + "<br>")
        if analysis['github_repos']:
           lines.append(f"<br><strong>🐙 GITHUB ORGANIZATION:</strong><br>")
           lines.append("-" * 70 + "<br>")
    
           for repo in analysis['github_repos']:
                lines.append(
                    f"  • <a href='{repo['url']}' target='_blank' style='color:#4b72ff;'>"
                    f"{repo['url']}</a> "
                    f"[Confidence: {repo['badge']}]<br>"
                    f"    <em>Reason:</em> {repo['reason']}<br>"
                )
    
    # Security Headers
    lines.append("<br><strong>🔒 SECURITY HEADERS:</strong><br>")
    lines.append("-" * 70 + "<br>")
    for header, status in analysis['security_headers'].items():
        icon = "✓" if "Enabled" in status else "✗"
        lines.append(f"  {icon} {header}: {status}<br>")
    
    # Domain-based CVE Search (PRIMARY)
    if analysis['domain_cves']:
        domain_keyword = extract_domain_keyword(analysis['domain'])
        lines.append(f"<br><strong>⚠️  CVE VULNERABILITIES (Domain-Based Search):</strong><br>")
        lines.append("-" * 70 + "<br>")
        lines.append(f"  Searching for CVEs related to: '<strong>{domain_keyword}</strong>'<br>")
        lines.append(f"  Found {len(analysis['domain_cves'])} known vulnerabilities:<br><br>")
        
        for cve in analysis['domain_cves']:
            severity_icon = "🔴" if cve['severity'] in ['CRITICAL', 'HIGH'] else "🟡" if cve['severity'] == 'MEDIUM' else "🟢"
            score_text = f" (CVSS: {cve['score']})" if cve['score'] else ""
            lines.append(f"  {severity_icon} <strong>{cve['id']}</strong> - Severity: {cve['severity']}{score_text}<br>")
            lines.append(f"     {cve['description']}<br>")
            if cve['published'] != 'Unknown':
                lines.append(f"     📅 Published: {cve['published']}<br>")
            lines.append(f"     🔗 <a href='{cve['link']}' target='_blank' style='color: #4b72ff;'>{cve['link']}</a><br><br>")
    else:
        domain_keyword = extract_domain_keyword(analysis['domain'])
        lines.append(f"<br><strong>✅ CVE VULNERABILITIES (Domain-Based Search):</strong><br>")
        lines.append("-" * 70 + "<br>")
        lines.append(f"  No known CVEs found for domain: '<strong>{domain_keyword}</strong>'<br>")
    
    # Framework-specific CVEs (SECONDARY - if found)
    if analysis['framework_cves']:
        lines.append(f"<br><strong>⚠️  ADDITIONAL CVEs (Framework-Specific):</strong><br>")
        lines.append("-" * 70 + "<br>")
        for tech, cves in analysis['framework_cves'].items():
            lines.append(f"<br>  <strong>Technology:</strong> {tech}<br>")
            lines.append(f"  Found {len(cves)} vulnerabilities:<br>")
            for cve in cves[:3]:
                severity_icon = "🔴" if cve['severity'] in ['CRITICAL', 'HIGH'] else "🟡" if cve['severity'] == 'MEDIUM' else "🟢"
                lines.append(f"<br>    {severity_icon} <strong>{cve['id']}</strong> - Severity: {cve['severity']}<br>")
                if cve.get('score'):
                    lines.append(f"       CVSS Score: {cve['score']}<br>")
                lines.append(f"       {cve['description'][:200]}...<br>")
                lines.append(f"       🔗 <a href='{cve['link']}' target='_blank' style='color: #4b72ff;'>{cve['link']}</a><br>")
        lines.append("<br>")
    
    # Subdomain Takeover Analysis
    if analysis['subdomain_takeovers']:
        lines.append(f"<br><strong>⚠️  SUBDOMAIN TAKEOVER ANALYSIS:</strong><br>")
        lines.append("-" * 70 + "<br>")
        lines.append("  🔴 <strong>POTENTIAL VULNERABILITIES DETECTED:</strong><br>")
        lines.append("  ⚠️  Note: These are POTENTIAL risks requiring manual verification<br><br>")
        
        high_risk = [t for t in analysis['subdomain_takeovers'] if t['risk'] == 'HIGH']
        medium_risk = [t for t in analysis['subdomain_takeovers'] if t['risk'] == 'MEDIUM']
        
        if high_risk:
            lines.append(f"  🔴 <strong>HIGH RISK ({len(high_risk)}):</strong><br>")
            for takeover in high_risk:
                lines.append(f"<br>    • <strong>{takeover['subdomain']}</strong><br>")
                lines.append(f"      CNAME → {takeover['cname']}<br>")
                lines.append(f"      Service: {takeover['service']}<br>")
                lines.append(f"      Status: {takeover['status']}<br>")
                lines.append(f"      Reason: {takeover['reason']}<br>")
                lines.append(f"      💡 Action: Verify manually - this requires investigation<br>")
        
        if medium_risk:
            lines.append(f"<br>  🟡 <strong>MEDIUM RISK ({len(medium_risk)}):</strong><br>")
            for takeover in medium_risk:
                lines.append(f"<br>    • <strong>{takeover['subdomain']}</strong><br>")
                lines.append(f"      CNAME → {takeover['cname']}<br>")
                lines.append(f"      Service: {takeover['service']}<br>")
                lines.append(f"      Reason: {takeover['reason']}<br>")
        
        lines.append("<br>  ⚠️  <strong>IMPORTANT:</strong> Subdomain takeover detection is probability-based.<br>")
        lines.append("     Always verify findings manually before reporting.<br>")
    else:
        lines.append(f"<br><strong>✅ SUBDOMAIN TAKEOVER ANALYSIS:</strong><br>")
        lines.append("-" * 70 + "<br>")
        lines.append("  No potential subdomain takeover vulnerabilities detected<br>")
        lines.append("  All subdomains appear to be properly configured<br>")
    
    # S3 Bucket Analysis
    if analysis['s3_buckets']:
        public_buckets = [b for b in analysis['s3_buckets'] if b.get('public')]
        private_buckets = [b for b in analysis['s3_buckets'] if not b.get('public')]
        
        if public_buckets or private_buckets:
            lines.append(f"<br><strong>☁️  AWS S3 BUCKET ANALYSIS:</strong><br>")
            lines.append("-" * 70 + "<br>")
        
        if public_buckets:
            lines.append(f"  🔴 <strong>PUBLICLY ACCESSIBLE ({len(public_buckets)}):</strong><br><br>")
            for bucket in public_buckets:
                lines.append(f"    • <strong>{bucket['bucket']}</strong><br>")
                lines.append(f"      Status: {bucket['status']}<br>")
                lines.append(f"      Risk: {bucket['risk']}<br>")
                
                if bucket['status'] == 'LISTABLE' and 'object_count' in bucket:
                    lines.append(f"      Objects: {bucket['object_count']} files found<br>")
                    if bucket.get('sample_files'):
                        lines.append(f"      Sample files:<br>")
                        for file in bucket['sample_files']:
                            sensitive = any(x in file.lower() for x in ['config', 'backup', 'sql', 'db', 'env', 'key', 'secret', 'password'])
                            warning = " ⚠️  <strong>SENSITIVE!</strong>" if sensitive else ""
                            lines.append(f"        - /{file}{warning}<br>")
                elif 'note' in bucket:
                    lines.append(f"      Note: {bucket['note']}<br>")
                
                lines.append(f"      🔗 <a href='{bucket['url']}' target='_blank' style='color: #4b72ff;'>{bucket['url']}</a><br><br>")
        
        if private_buckets:
            lines.append(f"  🟢 <strong>PRIVATE/SECURED ({len(private_buckets)}):</strong><br>")
            for bucket in private_buckets:
                lines.append(f"    • {bucket['bucket']} [{bucket['status']}]<br>")
        
        if public_buckets or private_buckets:
            lines.append(f"<br>  📊 <strong>Summary:</strong><br>")
            lines.append(f"     Total buckets found: {len(analysis['s3_buckets'])}<br>")
            lines.append(f"     Public: {len(public_buckets)}<br>")
            lines.append(f"     Private: {len(private_buckets)}<br>")
    
    # Server Info
    if analysis['server_info']:
        lines.append("<br><strong>🖥️  SERVER INFORMATION:</strong><br>")
        lines.append("-" * 70 + "<br>")
        for key, value in analysis['server_info'].items():
            lines.append(f"  • {key}: {value}<br>")
    
    # Performance
    lines.append("<br><strong>⚡ PERFORMANCE METRICS:</strong><br>")
    lines.append("-" * 70 + "<br>")
    for metric, value in analysis['performance'].items():
        lines.append(f"  • {metric}: {value}<br>")
    
    # Meta Info
    if analysis['meta_info']:
        lines.append("<br><strong>📋 META INFORMATION:</strong><br>")
        lines.append("-" * 70 + "<br>")
        for key, value in list(analysis['meta_info'].items())[:5]:
            lines.append(f"  • {key}: {value[:100]}<br>")
    
    lines.append("<br>" + "=" * 70 + "<br>")
    # Locate this inside format_deep_analysis() in api.py
    lines.append("<strong style='color: #4ade80;'>✅ DEEP ANALYSIS COMPLETE!</strong><br>")
    lines.append("<span style='color: #a1a1aa; font-style: italic;'>🤖 CRAWLER is an AI and can make mistakes</span><br>")
    lines.append("=" * 70)
    lines.append("</div>")
    
    return "".join(lines)


def deep_crawl_analysis_with_progress(task_id: str, url: str, html_content: str, headers: dict, stop_flag: threading.Event):
    """Perform comprehensive deep analysis with progress updates"""
    
    soup = BeautifulSoup(html_content, 'html.parser')
    domain = urlparse(url).netloc.replace('www.', '')
    
    analysis = {
        "url": url,
        "domain": domain,
        "title": "",
        "basic_tech": {},
        "frameworks": [],
        "framework_versions": {},
        "cloud_hosting": [],
        "subdomains": [],
        "js_files": [],
        "directories": [],
        "cdn_resources": {},
        "robots_txt": {},
        "github_repos": [],
        "security_headers": {},
        "meta_info": {},
        "server_info": {},
        "performance": {},
        "domain_cves": [],
        "framework_cves": {},
        "hidden_parameters": [],
        "subdomain_takeovers": [],
        "s3_buckets": []
    }
    
    # Extract title
    title_tag = soup.find('title')
    if title_tag:
        analysis["title"] = title_tag.get_text().strip()
    
    # Meta tags
    meta_tags = soup.find_all('meta')
    for meta in meta_tags[:8]:
        name = meta.get('name') or meta.get('property', '')
        content = meta.get('content', '')
        if name and content:
            analysis["meta_info"][name] = content[:150]
    
    # Basic tech detection
    tasks[task_id]["status"] = f"🔍 Detecting core technologies... (30%)"
    
    doctype = str(soup)[:200].lower()
    if '<!doctype html>' in doctype:
        analysis["basic_tech"]["HTML"] = "HTML5"
    
    stylesheets = soup.find_all('link', rel='stylesheet')
    if stylesheets:
        analysis["basic_tech"]["CSS"] = f"{len(stylesheets)} stylesheet(s)"
    
    scripts = soup.find_all('script')
    if scripts:
        analysis["basic_tech"]["JavaScript"] = f"{len(scripts)} script(s)"
    
    html_lower = html_content.lower()
    
    # Framework detection
    if 'react' in html_lower:
        analysis["frameworks"].append("React")
    if 'vue' in html_lower:
        analysis["frameworks"].append("Vue.js")
    if 'angular' in html_lower:
        analysis["frameworks"].append("Angular")
    if 'jquery' in html_lower:
        analysis["frameworks"].append("jQuery")
    if 'bootstrap' in html_lower:
        analysis["frameworks"].append("Bootstrap")
    
    if headers.get('x-powered-by'):
        powered = headers.get('x-powered-by')
        analysis["basic_tech"]["Server Technology"] = powered
    
    if 'xmlhttprequest' in html_lower or 'fetch(' in html_lower:
        analysis["basic_tech"]["AJAX"] = "Detected"
    
    if headers.get('server'):
        analysis["server_info"]["Server"] = headers.get('server')
    
    if stop_flag.is_set():
        return analysis
    
    # Extract JS files
    tasks[task_id]["status"] = f"🔍 Extracting JavaScript files... (35%)"
    analysis["js_files"] = extract_all_js_files(soup, url, html_content)
    
    # Detect framework versions
    tasks[task_id]["status"] = f"🔍 Detecting framework versions... (38%)"
    analysis["framework_versions"] = detect_framework_versions(html_content, analysis["js_files"])
    
    # Cloud provider detection
    tasks[task_id]["status"] = f"🔍 Detecting cloud provider... (40%)"
    cloud_providers = []
    if 'amazonaws.com' in html_lower or 'aws' in html_lower:
        cloud_providers.append('Amazon Web Services (AWS)')
    if 'cloudfront' in html_lower:
        cloud_providers.append('AWS CloudFront (CDN)')
    if 'azure' in html_lower:
        cloud_providers.append('Microsoft Azure')
    if 'googleapis.com' in html_lower or 'gstatic.com' in html_lower:
        cloud_providers.append('Google Cloud Platform (GCP)')
    if headers.get('server', '').lower() == 'cloudflare' or 'cf-ray' in headers:
        cloud_providers.append('Cloudflare')
    
    analysis["cloud_hosting"] = cloud_providers
    
    if stop_flag.is_set():
        return analysis
    
    # Subdomain discovery
    tasks[task_id]["status"] = f"🔍 Discovering subdomains... (45%)"
    analysis["subdomains"] = find_subdomains_parallel(domain)
    
    if stop_flag.is_set():
        return analysis
    
    # Directory discovery
    tasks[task_id]["status"] = f"🔍 Discovering directories... (55%)"
    analysis["directories"] = discover_directories_parallel(url)
    
    if stop_flag.is_set():
        return analysis
    
    # CDN analysis
    tasks[task_id]["status"] = f"🔍 Analyzing CDN resources... (65%)"
    analysis["cdn_resources"] = analyze_cdn_resources(soup, html_content, url)
    
    # Robots.txt
    tasks[task_id]["status"] = f"🔍 Checking robots.txt... (68%)"
    analysis["robots_txt"] = check_robots_txt(url)
    
    # GitHub repos
    tasks[task_id]["status"] = f"🔍 Finding GitHub repositories... (70%)"
    analysis["github_repos"] = find_github_repo(html_content, soup, domain)
    
    # Security headers
    tasks[task_id]["status"] = f"🔍 Analyzing security headers... (72%)"
    analysis["security_headers"] = analyze_security_headers(headers)
    
    if stop_flag.is_set():
        return analysis
    
    # CVE searches
    tasks[task_id]["status"] = f"🔍 Searching CVEs for domain... (75%)"
    analysis["domain_cves"] = search_cves_by_domain(domain)
    
    tasks[task_id]["status"] = f"🔍 Searching CVEs for frameworks... (78%)"
    for tech, version in analysis["framework_versions"].items():
        cves = search_cves_enhanced(tech, version)
        if cves:
            analysis["framework_cves"][f"{tech} {version}"] = cves
    
    if stop_flag.is_set():
        return analysis
    
    if stop_flag.is_set():
        return analysis
    
    # Subdomain takeover
    tasks[task_id]["status"] = f"🔍 Checking subdomain takeovers... (85%)"
    takeovers = []
    for subdomain_info in analysis["subdomains"]:
        takeover = check_subdomain_takeover(subdomain_info)
        if takeover:
            takeovers.append(takeover)
    analysis["subdomain_takeovers"] = takeovers
    
    # S3 buckets
    tasks[task_id]["status"] = f"🔍 Discovering AWS S3 buckets... (90%)"
    analysis["s3_buckets"] = find_s3_buckets(html_content, soup, domain)
    
    # Update cloud hosting if S3 found
    if analysis["s3_buckets"] and 'Amazon Web Services (AWS)' not in analysis["cloud_hosting"]:
        analysis["cloud_hosting"].insert(0, 'Amazon Web Services (AWS)')
    
    if not analysis["cloud_hosting"]:
        analysis["cloud_hosting"] = ['Unable to detect']
    
    # Performance metrics
    analysis["performance"]["Page Size"] = f"{len(html_content) / 1024:.2f} KB"
    analysis["performance"]["Total Scripts"] = len(scripts)
    analysis["performance"]["Total Stylesheets"] = len(stylesheets)
    analysis["performance"]["Images"] = len(soup.find_all('img'))
    
    return analysis

def do_deep_crawl(task_id: str, url: str, stop_flag: threading.Event):
    tasks[task_id]["status"] = f"🌐 Fetching {url}... (5%)"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    # Fetch URL with error handling
    try:
        r = requests.get(url, timeout=30, headers=headers)
    except requests.exceptions.Timeout:
        tasks[task_id]["status"] = "⏱️ Request timed out"
        tasks[task_id]["result"] = "The website took too long to respond."
        return
    except requests.exceptions.ConnectionError:
        tasks[task_id]["status"] = "🚫 Connection failed"
        tasks[task_id]["result"] = "Could not connect to the website."
        return
    except requests.exceptions.MissingSchema as e:
        tasks[task_id]["status"] = "❌ Invalid URL"
        error_msg = str(e)
        if error_msg.startswith("Invalid URL"):
            tasks[task_id]["result"] = error_msg
        else:
            tasks[task_id]["result"] = f"Invalid URL: {error_msg}"
        return
    except Exception as e:
        tasks[task_id]["status"] = "❌ Fetch Failed"
        tasks[task_id]["result"] = str(e)
        return
    
    # If we get here, the fetch was successful - continue with analysis
    try:
        if stop_flag.is_set():
            return
        
        tasks[task_id]["status"] = f"🔍 Analyzing page structure... (15%)"
        time.sleep(0.3)
        
        if stop_flag.is_set():
            return
        
        # Parse initial data
        soup = BeautifulSoup(r.text, 'html.parser')
        domain = urlparse(url).netloc.replace('www.', '')
        
        tasks[task_id]["status"] = f"🔍 Detecting technologies... (25%)"
        time.sleep(0.3)
        
        if stop_flag.is_set():
            return
        
        tasks[task_id]["status"] = f"🔍 Discovering subdomains... (35%)"
        
        # Perform deep analysis with progress updates
        analysis = deep_crawl_analysis_with_progress(task_id, url, r.text, r.headers, stop_flag)
        
        if stop_flag.is_set():
            return
        
        tasks[task_id]["status"] = f"📝 Formatting results... (95%)"
        formatted_result = format_deep_analysis(analysis)
        
        tasks[task_id]["status"] = f"✅ Deep analysis complete for {url} (100%)\n\nCRAWLER is an AI and can make mistakes"
        tasks[task_id]["result"] = formatted_result
        
    except Exception as e:
        tasks[task_id]["status"] = "❌ Analysis Failed"
        error_msg = str(e)
        tasks[task_id]["result"] = error_msg if not error_msg.startswith("Error:") else error_msg[7:]

class CrawlRequest(BaseModel):
    url: str

class ValidateURLRequest(BaseModel):
    url: str

@app.post("/validate-url")
def validate_url(req: ValidateURLRequest):
    """Quick validation to check if URL is reachable"""
    try:
        parsed = urlparse(req.url)
        domain = parsed.netloc or parsed.path.split('/')[0]
        
        # Try to resolve DNS
        try:
            socket.gethostbyname(domain)
        except socket.gaierror:
            return {
                "valid": False,
                "error": f"Could not resolve domain '{domain}'. Please check the URL and try again."
            }
        
        # Quick HEAD request
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.head(req.url, timeout=5, headers=headers, allow_redirects=True)
            return {"valid": True}
        except requests.exceptions.SSLError:
            return {"valid": True}
        except requests.exceptions.ConnectionError:
            return {
                "valid": False,
                "error": f"Could not connect to '{domain}'. The website may be down or the URL is incorrect."
            }
        except requests.exceptions.Timeout:
            return {
                "valid": False,
                "error": f"Connection to '{domain}' timed out. The website may be slow or unreachable."
            }
        except Exception as e:
            return {"valid": True}
            
    except Exception as e:
        return {"valid": False, "error": f"Invalid URL: {str(e)}"}

@app.post("/crawl")
def crawl_url(req: CrawlRequest, background_tasks: BackgroundTasks):
    task_id = str(time.time())
    stop_flag = threading.Event()
    tasks[task_id] = {"status": f"🚀 Starting comprehensive crawl of {req.url}...", "stop_flag": stop_flag}
    background_tasks.add_task(do_deep_crawl, task_id, req.url, stop_flag)
    return {"task_id": task_id, "status": tasks[task_id]["status"]}

@app.get("/status/{task_id}")
def get_status(task_id: str):
    if task_id not in tasks:
        return JSONResponse(status_code=404, content={"status": "Task not found"})
    return {"status": tasks[task_id]["status"], "result": tasks[task_id].get("result")}

@app.post("/stop/{task_id}")
def stop_crawl(task_id: str):
    if task_id not in tasks:
        return JSONResponse(status_code=404, content={"status": "Task not found"})
    tasks[task_id]["stop_flag"].set()
    tasks[task_id]["status"] = "🛑 Analysis stopped by user"
    return {"status": tasks[task_id]["status"]}
