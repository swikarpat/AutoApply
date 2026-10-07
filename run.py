import argparse
import asyncio
from rich.console import Console
from rich.prompt import Confirm

from src.agents.discovery_agent import DiscoveryAgent
from src.agents.form_agent import FormAutomationAgent
from src.agents.match_agent import MatchAgent
from src.core.database import ApplicationStateStore
from src.core.fsm import SupervisorFSM
from src.core.llm_client import GeminiFlashClient
from src.mcp.tools.browser import StealthBrowserTool

console = Console()


async def main():
    parser = argparse.ArgumentParser(description="AutoApply: Autonomous LinkedIn Job Application Engine")
    parser.add_argument("--url", type=str, help="Direct URL to a job posting (LinkedIn Easy Apply)")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (default: False)")
    args = parser.parse_args()

    # 1. Initialize Subsystems
    console.print("[bold green]Initializing Agentic Career OS Subsystems...[/bold green]")
    store = ApplicationStateStore()
    llm_client = GeminiFlashClient(model_name="gemini-2.5-flash")
    
    browser_tool = StealthBrowserTool(headless=args.headless)
    await browser_tool.initialize()

    discovery_agent = DiscoveryAgent(store, browser_tool, llm_client)
    match_agent = MatchAgent(store, llm_client)
    form_agent = FormAutomationAgent(browser_tool, llm_client)

    fsm = SupervisorFSM(store, discovery_agent, match_agent, form_agent)

    # 2. Target URL
    target_url = args.url
    if not target_url:
        target_url = console.input("\n[bold yellow]Enter Job Posting URL to process:[/bold yellow] ").strip()

    if not target_url:
        console.print("[red]No URL provided. Exiting.[/red]")
        await browser_tool.close()
        return

    # 3. Execute State Machine
    try:
        result = await fsm.execute_job_pipeline(target_url)
        console.print(f"\n[bold green]Pipeline Execution Result:[/bold green] {result['status']}")

        # 4. Interactive HITL Confirmation
        if result.get("status") == "PENDING_HITL":
            if Confirm.ask("\n[bold cyan]Would you like to keep the browser open to inspect the review page?[/bold cyan]"):
                console.print("[yellow]Browser kept open. Press Ctrl+C in terminal when finished.[/yellow]")
                while True:
                    await asyncio.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down browser...[/yellow]")
    finally:
        await browser_tool.close()


if __name__ == "__main__":
    asyncio.run(main())