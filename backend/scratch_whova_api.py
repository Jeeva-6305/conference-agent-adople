import requests
import re

bundle_url = 'https://d16w97s1o4b4t8.cloudfront.net/static-p/frontend/webpack/speaker_webpage.8e9d499f813377d4ee5f.xems-webpack.bundle.js'
res = requests.get(bundle_url)

# Find function calls or URLs around speaker
idx = 0
while True:
    pos = res.text.lower().find('speaker', idx)
    if pos == -1:
        break
    snippet = res.text[max(0, pos-100):min(len(res.text), pos+150)]
    if any(k in snippet for k in ['url', 'get(', 'post(', 'http', '/apis/']):
        print(f"Snippet: {snippet.strip()}")
    idx = pos + 7
    if idx > pos + 100000:
        break
