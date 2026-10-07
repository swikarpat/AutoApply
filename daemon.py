"""
AutoApply: Background Daemon & Stream Runner (Alias for main.py stream)
"""
import asyncio
from main import command_stream

if __name__ == "__main__":
    asyncio.run(command_stream(headless=False))