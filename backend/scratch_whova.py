import requests
import re
import json

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

whova_url = 'https://whova.com/embedded/speakers/moHHtsILJDkAoZkDQbVKyZqiSRnMXDKopQ8Tl8K54FI%3D/?view=preview'
res = requests.get(whova_url, headers=headers, timeout=15)

print("Searching for URLs and tokens in Whova page...")
for m in re.finditer(r'https?://[^\s"\'<>]+', res.text):
    u = m.group(0)
    if 'api' in u or 'speaker' in u or 'whova' in u:
        if not u.endswith('.js') and not u.endswith('.css'):
            print(f"URL: {u}")

# Look for variable assignments
for line in res.text.split('\n'):
    if any(k in line.lower() for k in ['event_id', 'eventid', 'speaker_data', 'event_name', 'view_type']):
        print(f"Var line: {line.strip()[:150]}")
