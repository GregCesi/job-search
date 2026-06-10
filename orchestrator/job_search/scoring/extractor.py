"""
Extraction LLM des faits intrinsèques d'une offre (architecture.md §4).

Un seul appel par offre, à l'ingestion. Résultat persisté sur `offers`.
Jamais recalculé sauf si l'offre change.
"""
import json
import os
import warnings
from datetime import datetime, timezone

import ollama
from dotenv import load_dotenv

from orchestrator.job_search.scoring.tracing import TRACE_PATH, LLMTrace, _write_trace
from orchestrator.job_search.sources.base import (
    ExtractedFacts,
    JobOffer,
    RoleLevel,
    SeniorityLevel,
    TechRequirement,
)

load_dotenv()

_DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
_DEFAULT_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

_SYSTEM_PROMPT = """\
You are a technical job offer analyzer. Extract facts from the job offer — no scoring, no opinion.
Reply with a single valid JSON object, nothing else:
{
  "seniority_required": "<junior|intermediate|senior|lead>",
  "techs_required": [
    {"name": "<tech>", "importance": "<core|required|nice_to_have>"},
    ...
  ],
  "domain": "<ai_engineering|data_engineering|data_science|backend|devops|fullstack|embedded|other>",
  "role_level": "<ic|lead|manager>"
}

Rules:
- seniority_required: junior=0-2 yrs, intermediate=2-5 yrs, senior=5-10 yrs, lead=tech lead or 10+ yrs or management.
- techs_required: specific technology names only. Include implicit ones \
(e.g. "RAG architectures" → "rag", "orchestration de flux" → "airflow"). All lowercase.
  importance values:
    core         = central to the role — explicitly required, mentioned multiple times, or the main stack
    required     = needed but secondary — must have, but not the focus
    nice_to_have = optional — "idéalement", "un plus", "apprécié", bonus
- domain: single best fit from the allowed values only.
- role_level:
    ic      = individual contributor — no team management
    lead    = tech lead / squad lead — technical leadership of a team, but may have no reports
    manager = people management — hiring, reviews, headcount responsibility
"""

_FEW_SHOT = """\
Example 1 — IC role, mixed importance:
Title: Développeur IA / LLM (H/F)
Description: Vous concevez des architectures RAG en production avec LangGraph et FastAPI. \
Stack cœur : Python, LangChain, LangGraph, PostgreSQL, Docker. \
Maîtrise de Python et LangChain exigée. Git souhaité. Kubernetes serait un plus.
Experience hint: Souhaitée
→ {"seniority_required": "intermediate", "techs_required": [{"name": "python", "importance": "core"}, {"name": "rag", "importance": "core"}, {"name": "langchain", "importance": "core"}, {"name": "langgraph", "importance": "required"}, {"name": "fastapi", "importance": "required"}, {"name": "postgresql", "importance": "required"}, {"name": "docker", "importance": "required"}, {"name": "git", "importance": "required"}, {"name": "kubernetes", "importance": "nice_to_have"}], "domain": "ai_engineering", "role_level": "ic"}

Example 2 — Tech lead role:
Title: Tech Lead Data / ML (H/F)
Description: Vous pilotez une équipe de 5 data engineers. Référent technique sur notre stack Spark/Databricks. \
Recrutement et montée en compétences de l'équipe. Expertise Python et Spark indispensable. SQL, Airflow requis. Kafka apprécié.
Experience hint: Exigée
→ {"seniority_required": "lead", "techs_required": [{"name": "python", "importance": "core"}, {"name": "spark", "importance": "core"}, {"name": "databricks", "importance": "required"}, {"name": "sql", "importance": "required"}, {"name": "airflow", "importance": "required"}, {"name": "kafka", "importance": "nice_to_have"}], "domain": "data_engineering", "role_level": "lead"}

Example 3 — Backend IC, legacy stack:
Title: Développeur Java Backend (H/F)
Description: Développement de microservices Java/Spring Boot, exposition REST, intégration PostgreSQL. \
Docker et CI/CD Jenkins sont utilisés. Angular côté client (équipe frontend dédiée, vous n'y touchez pas). \
Kafka ou RabbitMQ serait un plus.
Experience hint: Souhaitée
→ {"seniority_required": "intermediate", "techs_required": [{"name": "java", "importance": "core"}, {"name": "spring", "importance": "core"}, {"name": "postgresql", "importance": "required"}, {"name": "docker", "importance": "required"}, {"name": "jenkins", "importance": "required"}, {"name": "kafka", "importance": "nice_to_have"}, {"name": "rabbitmq", "importance": "nice_to_have"}], "domain": "backend", "role_level": "ic"}
"""

_SENIORITY_VALID = {s.value for s in SeniorityLevel}
_ROLE_VALID = {r.value for r in RoleLevel}
_IMPORTANCE_VALID = {"core", "required", "nice_to_have"}
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
        role_level=RoleLevel.ic,
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

    _last_raw = ""
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
            _last_raw = resp.message.content
            raw = resp.message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            if raw.startswith("→"):
                raw = raw.lstrip("→").strip()
            data = json.loads(raw)

            seniority_raw = str(data.get("seniority_required", "")).lower()
            seniority = (
                SeniorityLevel(seniority_raw)
                if seniority_raw in _SENIORITY_VALID
                else SeniorityLevel.intermediate
            )

            raw_techs = data.get("techs_required", [])
            techs: list[TechRequirement] = []
            for item in raw_techs:
                if isinstance(item, str):
                    # Model ignored the new format — degrade gracefully
                    name = item.lower().strip()
                    if name:
                        techs.append(TechRequirement(name=name, importance="required"))
                elif isinstance(item, dict):
                    name = str(item.get("name", "")).lower().strip()
                    importance = str(item.get("importance", "")).lower()
                    if name:
                        techs.append(TechRequirement(
                            name=name,
                            importance=importance if importance in _IMPORTANCE_VALID else "required",
                        ))

            domain_raw = str(data.get("domain", "")).lower()
            domain = domain_raw if domain_raw in _DOMAIN_VALID else "other"

            role_raw = str(data.get("role_level", "ic")).lower()
            role_level = (
                RoleLevel(role_raw) if role_raw in _ROLE_VALID else RoleLevel.ic
            )

            facts = ExtractedFacts(
                seniority_required=seniority,
                techs_required=techs,
                domain=domain,
                role_level=role_level,
            )
            _write_trace(LLMTrace(
                offer_id=offer.source_id,
                model=model,
                temperature=0.1,
                prompt_system=_SYSTEM_PROMPT,
                prompt_user=user_prompt,
                raw_response=_last_raw,
                parsed_facts=facts.model_dump(),
                parse_failed=False,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ), TRACE_PATH)
            return facts
        except Exception as exc:
            if attempt == retries:
                warnings.warn(
                    f"[extractor] parse failed on offer '{offer.source_id}': {exc}"
                )

    fallback = _fallback()
    _write_trace(LLMTrace(
        offer_id=offer.source_id,
        model=model,
        temperature=0.1,
        prompt_system=_SYSTEM_PROMPT,
        prompt_user=user_prompt,
        raw_response=_last_raw,
        parsed_facts=fallback.model_dump(),
        parse_failed=True,
        timestamp=datetime.now(timezone.utc).isoformat(),
    ), TRACE_PATH)
    return fallback
