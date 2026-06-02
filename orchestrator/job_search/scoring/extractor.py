"""
Extraction LLM des faits intrinsèques d'une offre (architecture.md §4).

Un seul appel par offre, à l'ingestion. Résultat persisté sur `offers`.
Jamais recalculé sauf si l'offre change.
"""
import json
import os
import warnings

import ollama
from dotenv import load_dotenv

from orchestrator.job_search.sources.base import ExtractedFacts, JobOffer, SeniorityLevel

load_dotenv()

_DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
_DEFAULT_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

_SYSTEM_PROMPT = """\
You are a technical job offer analyzer. Extract facts from the job offer — no scoring, no opinion.
Reply with a single valid JSON object, nothing else:
{
  "seniority_required": "<junior|intermediate|senior|lead>",
  "techs_required": ["<tech1>", "<tech2>", ...],
  "domain": "<ai_engineering|data_engineering|data_science|backend|devops|fullstack|embedded|other>"
}

Rules:
- seniority_required: junior=0-2 yrs, intermediate=2-5 yrs, senior=5-10 yrs, lead=tech lead or 10+ yrs or management.
- techs_required: specific technology names and frameworks only. Include implicit ones \
(e.g. "RAG architectures" → "rag", "orchestration de flux" → "airflow"). All lowercase.
- domain: single best fit from the allowed values only.
"""

_FEW_SHOT = """\
Example 1:
Title: Senior ML Engineer
Description: Building RAG pipelines with LangChain, fine-tuning LLMs with PyTorch, production deployment on Kubernetes.
Experience hint: Exigée
→ {"seniority_required": "senior", "techs_required": ["python", "langchain", "rag", "llm", "pytorch", "kubernetes"], "domain": "ai_engineering"}

Example 2:
Title: Data Engineer
Description: Développement de pipelines ETL sur Databricks, SQL, Spark, orchestration Airflow, intégration Salesforce.
Experience hint: Souhaitée
→ {"seniority_required": "intermediate", "techs_required": ["python", "databricks", "sql", "spark", "airflow"], "domain": "data_engineering"}

Example 3:
Title: Développeur IA / LLM (H/F)
Description: Vous concevez des architectures RAG en production, fine-tunez des modèles open-source, et intégrez des agents LangGraph dans une API FastAPI. Stack : Python, LangChain, LangGraph, PostgreSQL, Docker. Compétences : Python confirmé, Git, REST API.
Experience hint: Souhaitée
→ {"seniority_required": "intermediate", "techs_required": ["python", "rag", "langchain", "langgraph", "fastapi", "postgresql", "docker", "git"], "domain": "ai_engineering"}
"""

_SENIORITY_VALID = {s.value for s in SeniorityLevel}
_DOMAIN_VALID = {
    "ai_engineering", "data_engineering", "data_science",
    "backend", "devops", "fullstack", "embedded", "other",
}
_EXPERIENCE_HINT = {"D": "Débutant accepté", "S": "Souhaitée", "E": "Exigée"}


def _fallback() -> ExtractedFacts:
    return ExtractedFacts(
        seniority_required=SeniorityLevel.intermediate,
        techs_required=[],
        domain="other",
        parse_failed=True,
    )


def extract_facts(
    offer: JobOffer,
    model: str = _DEFAULT_MODEL,
    host: str = _DEFAULT_HOST,
    retries: int = 2,
) -> ExtractedFacts:
    """Extract intrinsic facts from a job offer. Never raises — returns parse_failed on error."""
    client = ollama.Client(host=host)

    hints: list[str] = []
    if offer.experience_required:
        hints.append(f"Experience hint: {_EXPERIENCE_HINT.get(offer.experience_required, offer.experience_required)}")
    if offer.rome_label:
        hints.append(f"ROME classification: {offer.rome_label}")
    if offer.alternance:
        hints.append("Note: this is an apprenticeship offer (alternance).")

    user_prompt = (
        f"{_FEW_SHOT}\n"
        f"Title: {offer.title}\n"
        f"Description: {offer.description[:1500]}\n"
        + ("\n".join(hints) + "\n" if hints else "")
        + "Extract facts now:"
    )

    for attempt in range(retries + 1):
        try:
            resp = client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                options={"temperature": 0.1},
            )
            raw = resp.message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            # Le modèle peut préfixer avec "→ " en imitant les few-shots
            if raw.startswith("→"):
                raw = raw.lstrip("→").strip()
            data = json.loads(raw)

            seniority_raw = str(data.get("seniority_required", "")).lower()
            seniority = (
                SeniorityLevel(seniority_raw)
                if seniority_raw in _SENIORITY_VALID
                else SeniorityLevel.intermediate
            )

            techs = [str(t).lower().strip() for t in data.get("techs_required", []) if t]

            domain_raw = str(data.get("domain", "")).lower()
            domain = domain_raw if domain_raw in _DOMAIN_VALID else "other"

            return ExtractedFacts(
                seniority_required=seniority,
                techs_required=techs,
                domain=domain,
            )
        except Exception as exc:
            if attempt == retries:
                warnings.warn(
                    f"[extractor] parse failed on offer '{offer.source_id}': {exc}"
                )

    return _fallback()
