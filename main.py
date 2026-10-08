import argparse
import asyncio
import os
import sys
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from src.agents.discovery_agent import DiscoveryAgent
from src.agents.form_agent import FormAutomationAgent
from src.agents.match_agent import MatchAgent
from src.core.database import ApplicationStateStore
from src.core.fsm import SupervisorFSM
from src.core.llm_client import GeminiFlashClient
from src.core.schemas import ApplicationStatus
from src.mcp.tools.browser import StealthBrowserTool

console = Console()


def load_configurations():
    with open("config/settings.yaml", "r") as f:
        settings = yaml.safe_load(f)
    with open("config/truth_matrix.yaml", "r") as f:
        truth = yaml.safe_load(f)
    return settings, truth


async def command_login():
    """Opens a persistent browser session so the user can log in to LinkedIn once."""
    settings, _ = load_configurations()
    user_data_dir = settings.get("automation_safety", {}).get("user_data_dir", "data/browser_profile")
    
    console.print(Panel(
        "[bold cyan]AutoApply: LinkedIn Session Manager[/bold cyan]\n\n"
        f"1. A browser window will open using profile: [yellow]{user_data_dir}[/yellow]\n"
        "2. Log in with your LinkedIn credentials (complete any 2FA/CAPTCHA if prompted).\n"
        "3. Once logged in to your feed, press Enter here to save your session.",
        title="Session Setup",
        expand=False
    ))

    browser = StealthBrowserTool(headless=False, user_data_dir=user_data_dir)
    await browser.initialize()
    try:
        page = await browser.get_page("https://www.linkedin.com/login")
        console.input("\n[bold yellow]Press Enter once you are logged in to your LinkedIn feed...[/bold yellow]")
        current_url = page.url
        if "feed" in current_url or "jobs" in current_url:
            console.print("[bold green]✓ Verified active session! Session stored for future runs.[/bold green]")
        else:
            console.print(f"[yellow]Current URL: {current_url}. Profile saved in {user_data_dir}.[/yellow]")
    finally:
        await browser.close()


async def command_stats():
    """Displays summary metrics from the local SQLite store."""
    store = ApplicationStateStore()
    with store._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, count(*) FROM jobs GROUP BY status ORDER BY count(*) DESC;")
        status_counts = cursor.fetchall()

        cursor.execute(
            """
            SELECT company_name, job_title, status, updated_at 
            FROM jobs 
            ORDER BY updated_at DESC 
            LIMIT 10;
            """
        )
        recent_jobs = cursor.fetchall()

    table = Table(title="AutoApply: Application Status Summary", show_header=True, header_style="bold cyan")
    table.add_column("Status", style="green", width=25)
    table.add_column("Count", style="bold yellow", width=10)

    total = 0
    for row in status_counts:
        table.add_row(row["status"], str(row["count(*)"]))
        total += row["count(*)"]

    table.add_section()
    table.add_row("[bold white]Total Tracked[/bold white]", f"[bold green]{total}[/bold green]")
    console.print(table)

    if recent_jobs:
        recent_table = Table(title="Recent Activity (Last 10 Roles)", show_header=True, header_style="bold magenta")
        recent_table.add_column("Company", style="cyan", width=24)
        recent_table.add_column("Role Title", style="white", width=40)
        recent_table.add_column("Status", style="yellow", width=18)
        recent_table.add_column("Last Updated", style="dim", width=22)

        for job in recent_jobs:
            recent_table.add_row(
                job["company_name"][:22],
                job["job_title"][:38],
                job["status"],
                job["updated_at"][:19].replace("T", " ")
            )
        console.print(recent_table)


async def command_apply_single(url: str, headless: bool = False, dry_run: bool = False):
    """Executes the pipeline for a single target job posting URL."""
    settings, _ = load_configurations()
    store = ApplicationStateStore()
    llm_client = GeminiFlashClient(model_name=settings.get("llm_routing", {}).get("model", "gemini-2.5-flash"))

    browser_tool = StealthBrowserTool(
        headless=headless,
        user_data_dir=settings.get("automation_safety", {}).get("user_data_dir", "data/browser_profile")
    )
    await browser_tool.initialize()

    discovery_agent = DiscoveryAgent(store, browser_tool, llm_client)
    match_agent = MatchAgent(store, llm_client)
    auto_submit_flag = False if dry_run else settings.get("automation_safety", {}).get("auto_submit", True)
    form_agent = FormAutomationAgent(browser_tool, llm_client, auto_submit=auto_submit_flag)
    fsm = SupervisorFSM(store, discovery_agent, match_agent, form_agent)

    try:
        result = await fsm.execute_job_pipeline(url)
        console.print(f"\n[bold green]Pipeline Execution Result:[/bold green] {result['status']}")

        if result.get("status") == "PENDING_HITL":
            page = result.get("page")
            console.print(Panel(
                "[bold green]✓ ALL APPLICATION STEPS COMPLETED & REVIEW SCREEN REACHED[/bold green]\n\n"
                "• All input fields autofilled from Truth Matrix\n"
                "• Master Resume PDF attached\n"
                "• Follow-Company checkbox verified: [bold yellow]UNCHECKED[/bold yellow]\n\n"
                "[dim]The browser window remains open so you can inspect the application.[/dim]",
                title="Dry-Run Inspection Ready",
                expand=False
            ))
            if Confirm.ask("\n[bold cyan]Would you like to SUBMIT this application now?[/bold cyan]", default=False):
                if page:
                    submit_btn = page.locator('button[aria-label="Submit application"], button:has-text("Submit application")').first
                    if await submit_btn.is_visible():
                        modal = page.locator('div[role="dialog"]').first
                        await form_agent.uncheck_follow_company(page, modal)
                        await submit_btn.click(force=True)
                        await asyncio.sleep(2.5)
                        store.update_job_status(result["job_id"], ApplicationStatus.SUBMITTED)
                        console.print("[bold green]✓ Successfully submitted application via confirmation![/bold green]")
                        done_btn = page.locator('button:has-text("Done"), button[aria-label="Dismiss"]').first
                        if await done_btn.is_visible():
                            await done_btn.click(force=True)
            else:
                console.print("[yellow]Dry-run review finished. Dismissing modal safely...[/yellow]")
                if page:
                    await form_agent._dismiss_modal(page)
    finally:
        await browser_tool.close()


async def command_stream(headless: bool = False, dry_run: bool = False):
    """Executes the autonomous stream applier queue matching search criteria in settings.yaml."""
    settings, truth = load_configurations()
    store = ApplicationStateStore()
    llm_client = GeminiFlashClient(model_name=settings.get("llm_routing", {}).get("model", "gemini-2.5-flash"))

    user_data_dir = settings.get("automation_safety", {}).get("user_data_dir", "data/browser_profile")
    browser = StealthBrowserTool(headless=headless, user_data_dir=user_data_dir)
    await browser.initialize()

    discovery_agent = DiscoveryAgent(store, browser, llm_client)
    auto_submit_flag = False if dry_run else settings.get("automation_safety", {}).get("auto_submit", True)
    form_agent = FormAutomationAgent(browser, llm_client, auto_submit=auto_submit_flag)

    try:
        page = await browser.get_page("https://www.linkedin.com/jobs/")
        await asyncio.sleep(2.0)

        # Login verification
        if any(k in page.url for k in ["login", "signup", "checkpoint", "authwall"]):
            console.print(Panel(
                "[bold yellow]ACTION REQUIRED: Please log in to LinkedIn on the open browser window.[/bold yellow]\n"
                "[dim]Session will be saved for subsequent automated runs.[/dim]"
            ))
            while any(k in page.url for k in ["login", "signup", "checkpoint", "authwall"]):
                await asyncio.sleep(1.5)
            console.print("[bold green]Login verified! Continuing automation...[/bold green]\n")

        # Search query preparation
        job_cfg = settings.get("job_search", {})
        titles = job_cfg.get("target_titles", ["Staff Software Engineer"])
        location = job_cfg.get("target_location", "United States")
        recent_first = job_cfg.get("sort_by_recent_first", True)
        time_range = job_cfg.get("time_posted_range", "r86400")

        boolean_query = " OR ".join([f'"{t}"' for t in titles])
        import urllib.parse
        params = {
            "keywords": boolean_query,
            "location": location,
            "f_AL": "true",  # Easy Apply only
            "sortBy": "DD" if recent_first else "R"
        }
        if time_range:
            params["f_TPR"] = time_range

        search_url = f"https://www.linkedin.com/jobs/search/?{urllib.parse.urlencode(params)}"
        console.print(Panel(
            f"[bold cyan]Target Roles:[/bold cyan] {', '.join(titles)}\n"
            f"[bold cyan]Location:[/bold cyan] {location} | [bold cyan]Recency:[/bold cyan] Newest First ({time_range})\n"
            f"[bold cyan]Search URL:[/bold cyan] [link={search_url}]{search_url}[/link]",
            title="AutoApply Stream Engine",
            expand=False
        ))

        await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(2.5)

        card_locators = page.locator(
            'li[data-occludable-job-id], '
            'li.jobs-search-results__list-item, '
            'div.job-card-container, '
            'div[data-job-id]'
        )
        total_cards = await card_locators.count()
        console.print(f"[bold cyan]Discovered {total_cards} job cards in active stream.[/bold cyan]\n")

        max_apps = settings.get("automation_safety", {}).get("max_applications_per_run", 30)
        applied_count = 0

        for idx in range(total_cards):
            if applied_count >= max_apps:
                console.print(f"[yellow]Reached application cap of {max_apps} for this run.[/yellow]")
                break

            card = card_locators.nth(idx)
            try:
                if not await card.is_visible():
                    await card.scroll_into_view_if_needed()
                    await asyncio.sleep(0.3)

                card_text = (await card.inner_text()).split("\n")
                card_title = card_text[0].strip() if card_text else "Job Posting"
                console.print(f"[bold yellow][{idx+1}/{total_cards}] Inspecting:[/bold yellow] {card_title[:55]}")

                await card.click()
                await asyncio.sleep(1.2)

                # Pre-screen eligibility (e.g. California exclusion, company size, public status)
                eligible, reason = await discovery_agent.evaluate_job_eligibility(page, settings)
                if not eligible:
                    console.print(f"  [yellow]Filtered Out: {reason}. Skipping.[/yellow]")
                    continue

                console.print(f"  [green]Eligible ({reason}). Traversing Easy Apply...[/green]")

                # Process Easy Apply on the active card
                job_id = f"stream_{idx+1}"
                res = await form_agent.process_linkedin_application(page, job_id, card_title, "Target Company")
                if res.get("submitted"):
                    applied_count += 1
                    console.print(f"[bold green]✓ SUBMITTED SUCCESSFULLY! (Total: {applied_count}/{max_apps})[/bold green]")
                else:
                    console.print(f"  [dim]Result status: {res.get('status')}[/dim]")

                await asyncio.sleep(settings.get("automation_safety", {}).get("delay_between_jobs_seconds", 3.0))
            except Exception as e:
                console.print(f"  [red]Error on card {idx+1}: {e}[/red]")
                continue

        console.print(f"\n[bold green]AutoApply stream session finished. Submitted: {applied_count}[/bold green]")
    finally:
        await browser.close()


def main():
    parser = argparse.ArgumentParser(
        description="AutoApply: Autonomous AI-Powered LinkedIn Job Application Engine ⚡",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: stream (or run)
    stream_parser = subparsers.add_parser("stream", help="Run continuous stream search and Easy Apply queue")
    stream_parser.add_argument("--headless", action="store_true", help="Run in headless browser mode")
    stream_parser.add_argument("--dry-run", action="store_true", help="Pause on Review screen for human verification without submitting")

    run_parser = subparsers.add_parser("run", help="Alias for stream")
    run_parser.add_argument("--headless", action="store_true", help="Run in headless browser mode")
    run_parser.add_argument("--dry-run", action="store_true", help="Pause on Review screen for human verification without submitting")

    # Command: apply
    apply_parser = subparsers.add_parser("apply", help="Apply to a specific LinkedIn Easy Apply URL")
    apply_parser.add_argument("--url", type=str, required=True, help="Job posting URL")
    apply_parser.add_argument("--headless", action="store_true", help="Run in headless browser mode")
    apply_parser.add_argument("--dry-run", action="store_true", help="Pause on Review screen for human verification without submitting")

    # Command: stats
    subparsers.add_parser("stats", help="Display local application metrics and history")

    # Command: login
    subparsers.add_parser("login", help="Open browser to log in to LinkedIn and save session")

    args = parser.parse_args()

    if not args.command or args.command in ["stream", "run"]:
        headless = getattr(args, "headless", False)
        dry_run = getattr(args, "dry_run", False)
        asyncio.run(command_stream(headless=headless, dry_run=dry_run))
    elif args.command == "apply":
        asyncio.run(command_apply_single(url=args.url, headless=args.headless, dry_run=args.dry_run))
    elif args.command == "stats":
        asyncio.run(command_stats())
    elif args.command == "login":
        asyncio.run(command_login())


if __name__ == "__main__":
    main()