import asyncio
from playwright.async_api import async_playwright

async def get_speakers():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        url = 'https://whova.com/embedded/speakers/moHHtsILJDkAoZkDQbVKyZqiSRnMXDKopQ8Tl8K54FI%3D/?view=preview'
        print(f"Loading {url}...")
        await page.goto(url, wait_until='networkidle', timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Grab text of speaker elements
        text = await page.content()
        print(f"Loaded HTML length: {len(text)}")
        
        # Extract speaker names, titles, companies
        cards = await page.query_selector_all('.card, [class*="speaker"], [class*="name"]')
        print(f"Found elements: {len(cards)}")
        
        # Extract all visible text
        body_text = await page.inner_text('body')
        lines = [line.strip() for line in body_text.split('\n') if line.strip()]
        print(f"First 40 lines of extracted page text:")
        for line in lines[:40]:
            print("  *", line)
            
        await browser.close()

asyncio.run(get_speakers())
