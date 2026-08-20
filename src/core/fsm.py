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

        self.db.update_job_status(job.job_id, ApplicationStatus.PENDING_HITL)

        # 4. State: HUMAN-IN-THE-LOOP (HITL) GATE
        console.print(Panel(
            f"[bold magenta]State 4: HUMAN-IN-THE-LOOP (HITL) GATE[/bold magenta]\n"
            f"• Resume Uploaded: {form_results['resume_uploaded']}\n"
            f"• Fields Autofilled: {len(form_results['fields_filled'])}\n"
            f"• Review Screenshot: {form_results['screenshot_path']}\n\n"
            f"[bold green]Application is filled and ready for review in the active browser![/bold green]"
        ))

        return {
            "status": "PENDING_HITL",
            "job_id": job.job_id,
            "company": job.company_name,
            "title": job.job_title,
            "fit_score": eval_result.fit_score,
            "form_results": form_results
        }