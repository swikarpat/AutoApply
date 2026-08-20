import json
import yaml
import pytest
from src.core.llm_client import GeminiFlashClient


@pytest.mark.asyncio
def test_gemini_flash_evaluation_and_tailoring():
    client = GeminiFlashClient(model_name="gemini-2.5-flash")

    # 1. Load Configurations & Master Resume
    with open("config/truth_matrix.yaml", "r") as f:
        truth_matrix = yaml.safe_load(f)
    with open("data/master_resume.json", "r") as f:
        master_resume = json.load(f)

    job_description = """
    Palo Alto Networks is hiring a Sr Staff Software Engineer (AI) for Prisma Access.
    Key responsibilities:
    - Build scalable backend services in Python / Go.
    - LLM orchestration pipelines and structured output generation.
    - Design guardrails, zero-trust token vaults, and RAG pipelines using vector search.
    - Optimize latency for sub-50ms p99 performance.
    """

    # 2. Test Match Evaluation (Flash)
    evaluation = client.evaluate_job_match(
        job_id="test_panw_001",
        job_title="Sr Staff Software Engineer (AI)",
        company="Palo Alto Networks",
        description=job_description,
        candidate_summary=master_resume["basics"]["summary"],
        truth_matrix=truth_matrix
    )

    assert evaluation.fit_score >= 75
    assert evaluation.matches_hard_criteria is True
    assert len(evaluation.key_matching_skills) > 0
    print(f"\n[Gemini Flash] Fit Score: {evaluation.fit_score}% | Reasoning: {evaluation.strategic_reasoning}")

    # 3. Test Resume Tailoring (Flash)
    tailored = client.tailor_resume_content(
        job_id="test_panw_001",
        job_title="Sr Staff Software Engineer (AI)",
        company="Palo Alto Networks",
        description=job_description,
        master_resume=master_resume
    )

    assert len(tailored.selected_experiences) > 0
    assert "Palo Alto Networks" in tailored.executive_summary or "Prisma Access" in tailored.executive_summary or "Staff" in tailored.executive_summary
    print(f"\n[Gemini Flash] Tailored Summary: {tailored.executive_summary[:150]}...")