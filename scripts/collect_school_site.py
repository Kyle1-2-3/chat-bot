"""Maintenance tool: pip install beautifulsoup4, then run with --output <scratch-dir>.

Raw public pages are for review only. Do not automatically replace the curated knowledge.
"""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlparse, urljoin
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

parser = argparse.ArgumentParser(description='Inventory Brentwood sitemaps and read public information/course pages.')
parser.add_argument('--output', type=Path, required=True, help='Scratch directory; do not commit raw pages')
OUT = parser.parse_args().output
OUT.mkdir(parents=True, exist_ok=True)
BASE = 'https://www.brentwood.ca/'

def fetch(url):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'BrentwoodStudentChatbot/1.0 (public school information)'}), timeout=30) as response:
                return response.geturl(), response.read().decode('utf-8')
        except Exception:
            if attempt == 2: raise
            time.sleep(attempt + 1)

index = ET.fromstring(fetch(BASE + 'sitemap.xml')[1])
maps = [e.text for e in index.findall('.//{*}sitemap/{*}loc')]
inventory = []
for url in maps:
    xml = ET.fromstring(fetch(url)[1])
    rows = [{'url': e.find('{*}loc').text, 'last_modified': e.findtext('{*}lastmod'), 'sitemap': url.rsplit('/',1)[-1]} for e in xml.findall('{*}url')]
    inventory.extend(rows)
    print(url.rsplit('/',1)[-1], len(rows), flush=True)
(OUT / 'inventory.json').write_text(json.dumps(inventory, indent=2))
selected = [r for r in inventory if r['sitemap'] in ('page-sitemap.xml', 'course-sitemap.xml')]

def collect(row):
    path = OUT / (hashlib.sha256(row['url'].encode()).hexdigest()[:16] + '.json')
    if path.exists(): return json.loads(path.read_text())
    try:
        final_url, html = fetch(row['url'])
        soup = BeautifulSoup(html, 'html.parser')
        main = soup.select_one('main')
        title = soup.title.get_text(' ', strip=True) if soup.title else row['url']
        if main is None: raise ValueError('No main content')
        for tag in main.select('script, style, svg, nav, form'):
            tag.decompose()
        links = [{'text': a.get_text(' ', strip=True), 'url': urljoin(final_url, a.get('href', ''))} for a in main.select('a[href]')]
        text = main.get_text('\n', strip=True)
        for marker in ['Happening Around Campus', 'Where Students\nChoose\nTo Be']:
            text = text.split(marker)[0]
        row = {**row, 'final_url': final_url, 'title': title, 'text': text, 'links': links, 'status': 'read'}
    except Exception as exc:
        row = {**row, 'status': 'failed', 'error': str(exc)}
    path.write_text(json.dumps(row, ensure_ascii=False, indent=2))
    return row

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    results = []
    for row in pool.map(collect, selected):
        results.append(row)
        print(row['status'], row['url'], len(row.get('text','')), flush=True)
(OUT / 'pages.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
print('COMPLETE', len(results), flush=True)
