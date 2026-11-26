import sys
from pathlib import Path
repo_root = str(Path(__file__).resolve().parent.parent)
backend_root = str(Path(__file__).resolve().parent)
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

import logging
from backend.app.services.speaker_outreach_service import SpeakerOutreachService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("live_outreach_dispatcher")

def main():
    logger.info("🚀 Starting live outreach dispatch for verified qualified leads...")
    svc = SpeakerOutreachService()
    try:
        res = svc.run_outreach_send_pass(force=True, dry_run_override=False)
        logger.info(f"✅ Outreach dispatch completed: {res}")
        print("\n" + "=" * 60)
        print("LIVE OUTREACH DISPATCH SUMMARY")
        print("=" * 60)
        print(f"Status: {res.get('status')}")
        print(f"Sent Count: {res.get('sent_count')}")
        print(f"Skipped Count: {res.get('skipped_count')}")
        print("=" * 60)
    finally:
        svc.close()

if __name__ == "__main__":
    main()
