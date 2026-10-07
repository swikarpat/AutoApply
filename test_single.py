"""
AutoApply: Test Single Job Posting (Alias for main.py apply)
"""
import asyncio
import sys
from main import command_apply_single

if __name__ == "__main__":
    target_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.linkedin.com/jobs/view/4429707612/"
    asyncio.run(command_apply_single(url=target_url, headless=False))