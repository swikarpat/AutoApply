import logging
from typing import Any, Dict, Optional
from rich.console import Console
from rich.panel import Panel

from src.agents.discovery_agent import DiscoveryAgent
from src.agents.form_agent import FormAutomationAgent
from src.agents.match_agent import MatchAgent
from src.core.database import ApplicationStateStore
from src.core.schemas import ApplicationStatus, JobPosting

console = Console()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SupervisorFSM")


class SupervisorFSM:
    def __init__(
        self,
        state_store: ApplicationStateStore,
        discovery_agent: DiscoveryAgent,
        match_agent: MatchAgent,
        form_agent: FormAutomationAgent,
    ):
        self.db = state_store
        self.discovery = discovery_agent
        self.matcher = match_agent
        self.form_engine = form_agent

    async def execute_job_pipeline(self, job_url: str) -> Dict[str, Any]:
        """Runs the linear state machine: DISCOVERY -> MATCH -> FORM_FILL & ATTACH -> HITL -> COMPLETE"""
        
        # 1. State: DISCOVERY
        console.print(Panel(f"[bold cyan]State 1: DISCOVERY[/bold cyan]\nTarget: {job_url}"))
        job: Optional[JobPosting] = await self.discovery.ingest_from_url(job_url)
        if not job:
            return {"status": "FAILED", "reason": "Unable to ingest job posting"}

        # 2. State: EVALUATE & MATCH
        console.print(Panel(f"[bold cyan]State 2: EVALUATION[/bold cyan]\nAnalyzing: {job.job_title} @ {job.company_name}"))
        eval_result = self.matcher.evaluate_job(job)

        console.print(f"[bold yellow]Match Fit Score:[/bold yellow] [bold green]{eval_result.fit_score}/100[/bold green]")
        console.print(f"[bold yellow]Strategic Reasoning:[/bold yellow] {eval_result.strategic_reasoning}")
        console.print(f"[bold yellow]Matching Skills:[/bold yellow] {', '.join(eval_result.key_matching_skills)}")

        if eval_result.fit_score < self.matcher.min_fit_score or not eval_result.matches_hard_criteria:
            console.print(f"[red]Job fit score {eval_result.fit_score} < threshold {self.matcher.min_fit_score}. SKIPPED.[/red]")
            return {"status": "SKIPPED", "job_id": job.job_id, "score": eval_result.fit_score}

        # 3. State: FORM_MAPPING & PDF ATTACHMENT
        console.print(Panel(f"[bold cyan]State 3: FORM AUTOMATION & PDF ATTACH[/bold cyan]\nUploading Master PDF & Mapping Inputs..."))
        page = await self.form_engine.browser.get_page(job_url)
        form_results = await self.form_engine.process_application_form(page, job.job_id, job.job_title, job.company_name)

        if form_results.get("submitted"):
            self.db.update_job_status(job.job_id, ApplicationStatus.SUBMITTED)
            status_return = "SUBMITTED"
        elif form_results.get("status") == "PENDING_HITL":
            self.db.update_job_status(job.job_id, ApplicationStatus.PENDING_HITL)
            status_return = "PENDING_HITL"
        else:
            self.db.update_job_status(job.job_id, ApplicationStatus.FAILED)
            status_return = "FAILED"

        # 4. State: REVIEW & COMPLETION REPORT
        if status_return == "PENDING_HITL":
            console.print(Panel(
                f"[bold magenta]State 4: DRY-RUN REVIEW SCREEN READY[/bold magenta]\n"
                f"• Resume Uploaded: {form_results.get('resume_uploaded', False)}\n"
                f"• Fields Autofilled: {len(form_results.get('fields_filled', []))}\n"
                f"• Follow-Company: [bold green]UNCHECKED GUARANTEE APPLIED[/bold green]\n"
                f"• Review Screenshot: {form_results.get('screenshot_path', 'N/A')}\n\n"
                f"[bold green]Application is filled and paused on the Review screen in the browser for inspection![/bold green]"
            ))
        elif status_return == "SUBMITTED":
            console.print(Panel(
                f"[bold green]State 4: APPLICATION SUBMITTED[/bold green]\n"
                f"• Company: {job.company_name}\n"
                f"• Role: {job.job_title}\n"
                f"• Proof Screenshot: {form_results.get('screenshot_path', 'N/A')}"
            ))

        return {
            "status": status_return,
            "job_id": job.job_id,
            "company": job.company_name,
            "title": job.job_title,
            "fit_score": eval_result.fit_score,
            "form_results": form_results,
            "page": page
        }