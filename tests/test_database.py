import os
import hashlib
from src.core.schemas import ApplicationStatus, JobPosting, MatchEvaluation
from src.core.database import ApplicationStateStore


def test_state_store_lifecycle(tmp_path):
    db_file = os.path.join(tmp_path, "test_applications.db")
    store = ApplicationStateStore(db_path=db_file)

    # 1. Create unique job hash
    url = "https://jobs.lever.co/paloaltonetworks/staff-ai-engineer-123"
    job_hash = hashlib.sha256(url.encode()).hexdigest()[:16]

    job = JobPosting(
        job_id=job_hash,
        platform="lever",
        company_name="Palo Alto Networks",
        job_title="Staff AI Software Engineer",
        location="Santa Clara, CA",
        job_url=url,
        raw_description="Looking for Staff AI Engineer with Python, Go, and LLM Orchestration...",
        is_remote=True
    )

    # 2. Test Upsert
    assert store.upsert_job(job) is True

    # 3. Test Query by Status
    discovered_jobs = store.get_jobs_by_status(ApplicationStatus.DISCOVERED)
    assert len(discovered_jobs) == 1
    assert discovered_jobs[0]["company_name"] == "Palo Alto Networks"

    # 4. Test Match Evaluation Save & Status Transition
    evaluation = MatchEvaluation(
        job_id=job_hash,
        fit_score=92,
        matches_hard_criteria=True,
        key_matching_skills=["Python", "Go", "LLM Orchestration", "Zero-Trust"],
        missing_critical_skills=["C++"],
        strategic_reasoning="Strong alignment with candidate's Staff AI background at Capital One."
    )
    store.save_evaluation(evaluation)
    store.update_job_status(job_hash, ApplicationStatus.EVALUATED, metadata={"score": 92})

    # 5. Verify Status Mutation
    evaluated_jobs = store.get_jobs_by_status(ApplicationStatus.EVALUATED)
    assert len(evaluated_jobs) == 1
    assert evaluated_jobs[0]["job_id"] == job_hash
    assert store.get_job_status(job_hash) == ApplicationStatus.EVALUATED
    assert store.get_job_status("non_existent_job_id") is None