"""Evaluate retrieval quality and, optionally, grounded answer quality."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from vector import retrieve


def _groups_covered(text: str, groups: list[list[str]]) -> tuple[int, int]:
    normalized = text.casefold()
    return sum(any(term.casefold() in normalized for term in group) for group in groups), len(groups)


def _load_cases(path: Path) -> list[dict]:
    cases = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {line_number}: {exc}") from exc
        if not isinstance(case.get("question"), str) or not case["question"].strip():
            raise ValueError(f"Case on line {line_number} needs a non-empty question.")
        for key in ("expected_sources", "retrieval_terms", "answer_terms"):
            if key in case and not isinstance(case[key], list):
                raise ValueError(f"Case on line {line_number}: {key} must be a list.")
        if not all(isinstance(item, str) and item for item in case.get("expected_sources", [])):
            raise ValueError(f"Case on line {line_number}: expected_sources must contain non-empty strings.")
        for key in ("retrieval_terms", "answer_terms"):
            groups = case.get(key, [])
            if not all(isinstance(group, list) and group and all(isinstance(term, str) and term for term in group) for group in groups):
                raise ValueError(f"Case on line {line_number}: {key} must contain lists of alternative phrases.")
        cases.append(case)
    if not cases:
        raise ValueError("No evaluation cases found.")
    return cases


def evaluate(cases: list[dict], top_k: int, include_answers: bool) -> dict:
    answer_runner = citation_checker = None
    if include_answers:
        from main import _valid_citations, run_agent_turn

        answer_runner = run_agent_turn
        citation_checker = _valid_citations

    results = []
    for case in cases:
        question = case["question"].strip()
        workspace = str(case.get("workspace", "general"))
        expected_sources = [str(item).casefold() for item in case.get("expected_sources", [])]
        documents = retrieve(question, workspace, limit=top_k)
        names = [str((doc.metadata or {}).get("source_name", "")).casefold() for doc in documents]
        source_ranks = [index for index, name in enumerate(names, 1) if any(expected in name for expected in expected_sources)]
        source_hit = bool(source_ranks) if expected_sources else None
        retrieved_text = "\n".join(doc.page_content for doc in documents)
        retrieval_groups = case.get("retrieval_terms", [])
        retrieval_hits, retrieval_total = _groups_covered(retrieved_text, retrieval_groups)
        evidence_ranks = [
            index for index, doc in enumerate(documents, 1)
            if retrieval_groups and all(any(term.casefold() in doc.page_content.casefold() for term in group) for group in retrieval_groups)
        ]
        result = {
            "question": question,
            "workspace": workspace,
            "retrieved_sources": list(dict.fromkeys((doc.metadata or {}).get("source_name", "unknown") for doc in documents)),
            "source_hit": source_hit,
            "source_reciprocal_rank": round(1 / source_ranks[0], 3) if source_ranks else 0.0 if expected_sources else None,
            "evidence_reciprocal_rank": round(1 / evidence_ranks[0], 3) if evidence_ranks else 0.0 if retrieval_groups else None,
            "retrieval_fact_coverage": round(retrieval_hits / retrieval_total, 3) if retrieval_total else None,
        }
        if include_answers and answer_runner and citation_checker:
            answer, labels, _message = answer_runner(question, workspace, "answer", [], retrieval_limit=top_k)
            citations_valid, citation_note = citation_checker(answer, labels)
            answer_hits, answer_total = _groups_covered(answer, case.get("answer_terms", []))
            result.update({
                "answer_fact_coverage": round(answer_hits / answer_total, 3) if answer_total else None,
                "citations_valid": citations_valid,
                "citation_note": citation_note,
            })
        results.append(result)

    source_cases = [item for item in results if item["source_hit"] is not None]
    evidence_cases = [item for item in results if item["evidence_reciprocal_rank"] is not None]
    retrieval_case_passes = [
        item for item in results
        if item["source_hit"] is not False and (item["retrieval_fact_coverage"] is None or item["retrieval_fact_coverage"] == 1)
    ]
    summary = {
        "case_count": len(results),
        "top_k": top_k,
        "source_recall_at_k": round(sum(item["source_hit"] is True for item in source_cases) / len(source_cases), 3) if source_cases else None,
        "source_mrr": round(sum(item["source_reciprocal_rank"] or 0 for item in source_cases) / len(source_cases), 3) if source_cases else None,
        "evidence_mrr": round(sum(item["evidence_reciprocal_rank"] or 0 for item in evidence_cases) / len(evidence_cases), 3) if evidence_cases else None,
        "retrieval_case_pass_rate": round(len(retrieval_case_passes) / len(results), 3),
        "results": results,
    }
    if include_answers:
        summary["citation_valid_rate"] = round(sum(item["citations_valid"] for item in results) / len(results), 3)
        answer_scores = [item["answer_fact_coverage"] for item in results if item["answer_fact_coverage"] is not None]
        summary["mean_answer_fact_coverage"] = round(sum(answer_scores) / len(answer_scores), 3) if answer_scores else None
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("eval_cases.jsonl"), help="JSONL cases file")
    parser.add_argument("--top-k", type=int, default=5, help="number of retrieved passages to score (1-20)")
    parser.add_argument("--answers", action="store_true", help="also call Ollama and check answer facts and citations")
    args = parser.parse_args()
    if not 1 <= args.top_k <= 20:
        parser.error("--top-k must be between 1 and 20")
    try:
        summary = evaluate(_load_cases(args.cases), args.top_k, args.answers)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"Evaluation could not run: {exc}\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if not any(item["retrieved_sources"] for item in summary["results"]):
        print("No indexed passages found. Start the assistant and index the sample corpus with /add realistic_restaurant_reviews.csv.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
