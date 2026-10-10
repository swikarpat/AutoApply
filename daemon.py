"""
AutoApply: Background Daemon & Stream Runner (Alias for main.py stream)
"""
import asyncio
import sys
from main import command_stream

if __name__ == "__main__":
    loc = None
    if "--ca" in sys.argv or "--california" in sys.argv:
        loc = "California"
    elif "--location" in sys.argv:
        idx = sys.argv.index("--location")
        if idx + 1 < len(sys.argv):
            loc = sys.argv[idx + 1]
    elif "-l" in sys.argv:
        idx = sys.argv.index("-l")
        if idx + 1 < len(sys.argv):
            loc = sys.argv[idx + 1]
    asyncio.run(command_stream(location=loc))