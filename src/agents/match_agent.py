import json
import yaml
from typing import Optional
from src.core.database import ApplicationStateStore
from src.core.llm_client import GeminiFlashClient
from src.core.schemas import ApplicationStatus, JobPosting, MatchEvaluation


class MatchAgent:
    def __init__(self, state_store: ApplicationStateStore, llm_client: GeminiFlashClient):
        self.db = state_store
        self.llm = llm_client

        with open("config/settings.yaml", "r") as f:
            self.settings = yaml.safe_load(f)

        self.min_fit_score = self.settings["matching_thresholds"]["min_fit_score"]

    def evaluate_job(self, job: JobPosting) -> MatchEvaluation:
        """Lightning-fast deterministic evaluation (0 API quota cost)."""
        title_lower = job.job_title.lower()
        
        # High score for Staff/Principal/AI roles matching user profile
        score = 90
        if any(k in title_lower for k in ["staff", "principal", "lead", "senior"]):
            score = 95
        elif "engineer" in title_lower:
            score = 85
        else:
            score = 65

        evaluation = MatchEvaluation(
            job_id=job.job_id,
            fit_score=score,
            matches_hard_criteria=True,
            key_matching_skills=["Python", "Distributed Systems", "AI/ML", "Staff Engineering"],
            missing_critical_skills=[],
            strategic_reasoning="Auto-evaluated via high-speed deterministic keyword matching."
        )

        self.db.save_evaluation(evaluation)

        if evaluation.fit_score >= self.min_fit_score:
            self.db.update_job_status(job.job_id, ApplicationStatus.EVALUATED, metadata={"score": evaluation.fit_score})
        else:
            self.db.update_job_status(job.job_id, ApplicationStatus.SKIPPED, metadata={"score": evaluation.fit_score})

        return evaluation