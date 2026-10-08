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
from src.core.schemas import ApplicationStatus, JobPosting
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


async def command_apply_single(url: str, headless: bool = False):
    """Executes the 100% autonomous pipeline for a single target job posting URL."""
    settings, _ = load_configurations()
    store = ApplicationStateStore()
    llm_client = GeminiFlashClient(model_name=settings.get("llm_routing", {}).get("model", "gemini-2.5-flash"))

    is_headless = headless or settings.get("automation_safety", {}).get("headless_browser", True)
    browser_tool = StealthBrowserTool(
        headless=is_headless,
        user_data_dir=settings.get("automation_safety", {}).get("user_data_dir", "data/browser_profile")
    )
    await browser_tool.initialize()

    discovery_agent = DiscoveryAgent(store, browser_tool, llm_client)
    match_agent = MatchAgent(store, llm_client)
    form_agent = FormAutomationAgent(browser_tool, llm_client, auto_submit=True)
    fsm = SupervisorFSM(store, discovery_agent, match_agent, form_agent)

    try:
        result = await fsm.execute_job_pipeline(url)
        console.print(f"\n[bold green]Pipeline Execution Result:[/bold green] {result['status']}")
    finally:
        await browser_tool.close()


async def command_stream(headless: bool = False):
    """Executes the high-speed autonomous stream applier queue matching search criteria in settings.yaml."""
    settings, truth = load_configurations()
    store = ApplicationStateStore()
    llm_client = GeminiFlashClient(model_name=settings.get("llm_routing", {}).get("model", "gemini-2.5-flash"))

    is_headless = headless or settings.get("automation_safety", {}).get("headless_browser", True)
    user_data_dir = settings.get("automation_safety", {}).get("user_data_dir", "data/browser_profile")
    browser = StealthBrowserTool(headless=is_headless, user_data_dir=user_data_dir)
    await browser.initialize()

    discovery_agent = DiscoveryAgent(store, browser, llm_client)
    form_agent = FormAutomationAgent(browser, llm_client, auto_submit=True)

    try:
        page = await browser.get_page("https://www.linkedin.com/jobs/")
        await asyncio.sleep(1.5)

        # Login verification
        if any(k in page.url for k in ["login", "signup", "checkpoint", "authwall"]):
            console.print(Panel(
                "[bold yellow]ACTION REQUIRED: Please log in to LinkedIn on the browser.[/bold yellow]\n"
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
        exclude_ca = job_cfg.get("exclude_california", True)

        ca_indicators = [
            "california", ", ca", "ca,", "ca ", "(ca)", "san francisco", "bay area", 
            "los angeles", "san jose", "san diego", "sunnyvale", 
            "mountain view", "palo alto", "menlo park", "cupertino", 
            "fremont", "oakland", "santa clara", "irvine"
        ]
        excluded_staffing_agencies = [
            "cybercoders", "insight global", "teksystems", "apex systems", "robert half",
            "kforce", "jobot", "motion recruitment", "beacon hill", "hays", "randstad",
            "adecco", "manpower", "aerotek", "collabera", "kelly services", "judge group"
        ]

        boolean_query = " OR ".join([f'"{t}"' for t in titles])
        import urllib.parse
        base_params = {
            "keywords": boolean_query,
            "location": location,
            "f_AL": "true",  # Easy Apply only
            "sortBy": "DD" if recent_first else "R"
        }
        if time_range:
            base_params["f_TPR"] = time_range

        max_apps = settings.get("automation_safety", {}).get("max_applications_per_run", 30)
        applied_count = 0
        max_search_pages = 10

        console.print(Panel(
            f"[bold cyan]Target Roles:[/bold cyan] {', '.join(titles)}\n"
            f"[bold cyan]Location:[/bold cyan] {location} | [bold cyan]Recency:[/bold cyan] Newest First ({time_range})\n"
            f"[bold cyan]Company Filter:[/bold cyan] >= 5,000 Employees | [bold cyan]Headless Mode:[/bold cyan] {is_headless}\n"
            f"[bold cyan]Auto-Submit:[/bold cyan] {auto_submit_flag} (Zero manual confirmation needed)",
            title="AutoApply High-Speed Stream Engine ⚡",
            expand=False
        ))

        for page_idx in range(1, max_search_pages + 1):
            if applied_count >= max_apps:
                console.print(f"[yellow]Reached application cap of {max_apps} for this run.[/yellow]")
                break

            params = dict(base_params)
            if page_idx > 1:
                params["start"] = (page_idx - 1) * 25

            search_url = f"https://www.linkedin.com/jobs/search/?{urllib.parse.urlencode(params)}"
            console.print(f"\n[bold magenta]─── Search Page {page_idx}/{max_search_pages} ───[/bold magenta] [dim]{search_url}[/dim]")

            await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(2.0)

            # High-speed DOM evaluation: extract all cards metadata in ONE shot
            cards_meta = await page.evaluate("""() => {
                const cards = Array.from(document.querySelectorAll(
                    'li[data-occludable-job-id], li.jobs-search-results__list-item, div.job-card-container, div[data-job-id]'
                ));
                return cards.map((c, i) => {
                    const jobId = c.getAttribute('data-job-id') || c.getAttribute('data-occludable-job-id') || '';
                    const titleEl = c.querySelector('.job-card-list__title, .job-card-container__link, a[data-control-id]');
                    const compEl = c.querySelector('.job-card-container__primary-description, .artdeco-entity-lockup__subtitle, .job-card-container__company-name');
                    const locEl = c.querySelector('.job-card-container__metadata-item, .job-card-container__metadata-wrapper');
                    const text = (c.innerText || '').toLowerCase();
                    return {
                        index: i,
                        jobId: jobId,
                        title: titleEl ? titleEl.innerText.trim() : '',
                        company: compEl ? compEl.innerText.trim() : '',
                        location: locEl ? locEl.innerText.trim() : '',
                        hasEasyApply: text.includes('easy apply'),
                        isApplied: text.includes('applied'),
                        rawText: text
                    };
                });
            }""")

            total_cards = len(cards_meta)
            if total_cards == 0:
                console.print("[dim]No more job cards found on this page. Ending stream search.[/dim]")
                break

            card_locators = page.locator(
                'li[data-occludable-job-id], '
                'li.jobs-search-results__list-item, '
                'div.job-card-container, '
                'div[data-job-id]'
            )

            console.print(f"[bold cyan]Discovered {total_cards} job cards on Page {page_idx}. Running instant pre-filter...[/bold cyan]")

            for meta in cards_meta:
                if applied_count >= max_apps:
                    break

                idx = meta["index"]
                job_id = meta["jobId"] or f"stream_{page_idx}_{idx+1}"
                card_title = meta["title"] or "Job Posting"
                company_name = meta["company"] or "Enterprise Employer"
                card_loc = meta["location"] or ""
                card_text = meta["rawText"]

                # 1. Instant SQLite status check
                existing_status = store.get_job_status(job_id)
                if existing_status in [ApplicationStatus.SUBMITTED, ApplicationStatus.SKIPPED]:
                    console.print(f"  [dim]• [{idx+1}/{total_cards}] Skipping '{card_title[:40]}' ({company_name}): Already in DB ({existing_status})[/dim]")
                    continue

                # 2. Instant Applied badge check
                if meta["isApplied"]:
                    store.update_job_status(job_id, ApplicationStatus.SKIPPED, metadata={"reason": "Already applied on LinkedIn"})
                    console.print(f"  [dim]• [{idx+1}/{total_cards}] Skipping '{card_title[:40]}': Marked Applied on LinkedIn[/dim]")
                    continue

                # 3. Instant Easy Apply badge check
                if not meta["hasEasyApply"]:
                    store.update_job_status(job_id, ApplicationStatus.SKIPPED, metadata={"reason": "No Easy Apply badge"})
                    continue

                # 4. Instant California Region filter (0ms delay)
                if exclude_ca:
                    if any(ind in card_loc.lower() for ind in ca_indicators) or any(ind in card_text for ind in ca_indicators):
                        store.update_job_status(job_id, ApplicationStatus.SKIPPED, metadata={"reason": "Excluded Region: CA"})
                        console.print(f"  [dim]• [{idx+1}/{total_cards}] Skipping '{card_title[:40]}': Excluded CA region[/dim]")
                        continue

                # 5. Instant Staffing Agency filter (0ms delay)
                comp_lower = company_name.lower()
                if any(agency in comp_lower for agency in excluded_staffing_agencies):
                    store.update_job_status(job_id, ApplicationStatus.SKIPPED, metadata={"reason": f"Excluded Staffing Agency: {company_name}"})
                    console.print(f"  [dim]• [{idx+1}/{total_cards}] Skipping '{card_title[:40]}': Excluded Staffing Agency ({company_name})[/dim]")
                    continue

                # Candidate passed pre-filter! Click card to inspect details & verify >= 5,000 employees
                console.print(f"\n[bold yellow]🔍 Candidate Job [{idx+1}/{total_cards}]:[/bold yellow] [bold white]{card_title}[/bold white] at [cyan]{company_name}[/cyan]")
                
                try:
                    card = card_locators.nth(idx)
                    if not await card.is_visible():
                        await card.scroll_into_view_if_needed()
                        await asyncio.sleep(0.2)

                    await card.click()
                    await asyncio.sleep(0.4)  # Fast details pane update wait

                    job_posting = JobPosting(
                        job_id=job_id,
                        platform="linkedin",
                        company_name=company_name,
                        job_title=card_title,
                        location=card_loc or location,
                        job_url=f"https://www.linkedin.com/jobs/view/{job_id}/",
                        raw_description=card_title,
                        status=ApplicationStatus.DISCOVERED,
                    )
                    store.upsert_job(job_posting)

                    # Strict enterprise size (>= 5,000 employees) & eligibility verification
                    eligible, reason = await discovery_agent.evaluate_job_eligibility(page, settings)
                    if not eligible:
                        console.print(f"  [yellow]↳ Filtered Out: {reason}. Skipping.[/yellow]")
                        store.update_job_status(job_id, ApplicationStatus.SKIPPED, metadata={"reason": reason})
                        continue

                    console.print(f"  [green]↳ ✓ Eligible Employer ({reason})! Executing autonomous Easy Apply...[/green]")
                    store.update_job_status(job_id, ApplicationStatus.FORM_MAPPED)

                    # Execute 100% autonomous Easy Apply
                    res = await form_agent.process_linkedin_application(page, job_id, card_title, company_name)
                    if res.get("submitted"):
                        applied_count += 1
                        store.update_job_status(job_id, ApplicationStatus.SUBMITTED, metadata=res)
                        console.print(f"[bold green]  🎉 SUBMITTED SUCCESSFULLY! (Total Applied: {applied_count}/{max_apps})[/bold green]")
                    else:
                        store.update_job_status(job_id, ApplicationStatus.FAILED, metadata=res)
                        console.print(f"  [dim]  Application ended with status: {res.get('status')}[/dim]")

                    await asyncio.sleep(settings.get("automation_safety", {}).get("delay_between_jobs_seconds", 1.0))
                except Exception as e:
                    console.print(f"  [red]Error processing card {idx+1}: {e}[/red]")
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

    run_parser = subparsers.add_parser("run", help="Alias for stream")
    run_parser.add_argument("--headless", action="store_true", help="Run in headless browser mode")

    # Command: apply
    apply_parser = subparsers.add_parser("apply", help="Apply to a specific LinkedIn Easy Apply URL")
    apply_parser.add_argument("--url", type=str, required=True, help="Job posting URL")
    apply_parser.add_argument("--headless", action="store_true", help="Run in headless browser mode")

    # Command: stats
    subparsers.add_parser("stats", help="Display local application metrics and history")

    # Command: login
    subparsers.add_parser("login", help="Open browser to log in to LinkedIn and save session")

    args = parser.parse_args()

    if not args.command or args.command in ["stream", "run"]:
        headless = getattr(args, "headless", False)
        asyncio.run(command_stream(headless=headless))
    elif args.command == "apply":
        asyncio.run(command_apply_single(url=args.url, headless=args.headless))
    elif args.command == "stats":
        asyncio.run(command_stats())
    elif args.command == "login":
        asyncio.run(command_login())


if __name__ == "__main__":
    main()