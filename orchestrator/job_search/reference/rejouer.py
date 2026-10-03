"""CLI — rejoue le jeu de référence sur un modèle nommé (TCK-221, EXE-107).

Usage:
    python -m orchestrator.job_search.reference.rejouer --model llama3
    python -m orchestrator.job_search.reference.rejouer --model gemma4:12b
"""

import argparse
import os
from pathlib import Path

from orchestrator.job_search.matching.profile import load_profile
from orchestrator.job_search.paths import ALIAS_PATH, PROFILE_PATH
from orchestrator.job_search.reference.dataset import JEU_PATH, load_jeu
from orchestrator.job_search.reference.replay import replay_jeu
from orchestrator.job_search.scoring.aliases import load_alias_table
from orchestrator.job_search.scoring.extractor import OllamaUnavailable


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rejoue le jeu de référence sur un modèle"
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--profile", default=str(PROFILE_PATH))
    parser.add_argument("--jeu", default=str(JEU_PATH))
    parser.add_argument(
        "--host", default=os.getenv("OLLAMA_HOST", "http://localhost:11434")
    )
    args = parser.parse_args()

    profile, _ = load_profile(args.profile)
    alias_table = load_alias_table(ALIAS_PATH)
    entries = load_jeu(Path(args.jeu))

    try:
        result = replay_jeu(
            entries,
            args.model,
            profile=profile,
            alias_table=alias_table,
            host=args.host,
        )
    except OllamaUnavailable as exc:
        print(f"[reference] {exc}")
        return

    print(f"[reference] {result.n_skipped_non_relu} entrée(s) non relue(s) sautée(s)")
    print(result.report_text)
    print(f"[reference] rapport → {result.report_path}")


if __name__ == "__main__":
    main()
