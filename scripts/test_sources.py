import requests
from bs4 import BeautifulSoup
import json

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

urls = {
    '10times': 'https://10times.com/usa',
    'Eventbrite': 'https://www.eventbrite.com/d/united-states/conferences/',
    'Meetup': 'https://www.meetup.com/find/?keywords=conference&location=us--ny--new-york',
    'Cvent': 'https://www.cvent.com/en/event-management-software',
    'EventsInAmerica': 'https://eventsinamerica.com',
    'Luma': 'https://lu.ma/tech'
}

for name, url in urls.items():
    try:
        r = requests.get(url, headers=headers, timeout=12)
        print(f"[{name}] Status: {r.status_code}, Length: {len(r.text)}")
    except Exception as e:
        print(f"[{name}] Error: {e}")
