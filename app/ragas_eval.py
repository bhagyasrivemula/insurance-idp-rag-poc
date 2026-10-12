"""
RAGAS evaluation of the whole question-answering pipeline.

For every question in data/eval/testset.json the real bot runs end to end
(guardrails -> retrieval -> generation), and RAGAS scores the result with an
LLM judge (EVAL_MODEL):

    faithfulness               - are the answer's claims supported by the retrieved excerpts?
                                 (low = hallucination)
    answer_relevancy           - does the answer address the question?
    context_precision          - are the relevant excerpts ranked near the top?
    context_recall             - do the excerpts contain everything the reference answer needs?
    factual_correctness        - does the answer agree with the reference answer?

All scores are 0-1, higher is better. Results are saved to data/eval/ragas_report.json
(shown in the Knowledge base tab) and data/eval/ragas_results.csv.

Run:  python -m app.ragas_eval            (all questions)
      python -m app.ragas_eval --limit 5  (quick check)
"""
from __future__ import annotations

import argparse
import json
import math
import warnings
from datetime import datetime, timezone

from app import bot, config

warnings.filterwarnings("ignore", category=DeprecationWarning)

METRIC_INFO = {
    "faithfulness": "Answer is supported by the retrieved excerpts (no hallucination)",
    "answer_relevancy": "Answer addresses the question that was asked",
    "llm_context_precision_with_reference": "Relevant excerpts are ranked at the top",
    "context_recall": "Excerpts contain everything needed for the reference answer",
    "factual_correctness(mode=f1)": "Answer agrees with the reference answer",
}


def _clean(value):
    """NaN (metric could not be computed) -> None, floats rounded."""
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, 3)
    return value


def run(limit: int | None = None) -> dict:
    # Imported here so the rest of the app never needs RAGAS / LangChain at runtime.
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import EvaluationDataset, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (FactualCorrectness, Faithfulness, LLMContextPrecisionWithReference,
                               LLMContextRecall, ResponseRelevancy)

    testset = json.loads(config.RAGAS_TESTSET.read_text(encoding="utf-8"))[:limit]

    # ---- 1. Run the real assistant on every question ----
    samples, extras = [], []
    for n, item in enumerate(testset, 1):
        result = bot.answer(item["question"], item.get("persona", "buyer"))
        print(f"[{n}/{len(testset)}] {item['question'][:70]}  ->  {len(result['contexts'])} excerpts")
        samples.append({
            "user_input": item["question"],
            "response": result["answer"],
            "retrieved_contexts": result["contexts"] or ["(no excerpts retrieved)"],
            "reference": item["reference"],
        })
        extras.append({"guardrails": [c for c in result["checks"] if c["status"] != "pass"]})

    # ---- 2. Score with RAGAS (LLM-as-judge) ----
    judge = LangchainLLMWrapper(ChatOpenAI(model=config.EVAL_MODEL, temperature=0, api_key=config.OPENAI_API_KEY))
    embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model=config.EMBED_MODEL, api_key=config.OPENAI_API_KEY))
    metrics = [Faithfulness(), ResponseRelevancy(), LLMContextPrecisionWithReference(),
               LLMContextRecall(), FactualCorrectness()]
    print(f"\nScoring {len(samples)} answers with RAGAS ({config.EVAL_MODEL} as judge)...")
    result = evaluate(dataset=EvaluationDataset.from_list(samples), metrics=metrics,
                      llm=judge, embeddings=embeddings, experiment_name="insureassist")
    df = result.to_pandas()

    # ---- 3. Report ----
    metric_cols = [c for c in METRIC_INFO if c in df.columns]
    rows = []
    for i, row in df.iterrows():
        rows.append({
            "question": row["user_input"], "answer": row["response"], "reference": row["reference"],
            "excerpts": len(samples[i]["retrieved_contexts"]),
            **{m: _clean(row[m]) for m in metric_cols}, **extras[i],
        })
    scores = {m: _clean(float(df[m].mean(skipna=True))) for m in metric_cols}
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "questions": len(rows), "chat_model": config.CHAT_MODEL, "judge_model": config.EVAL_MODEL,
        "embed_model": config.EMBED_MODEL, "chunking": "semantic",
        "scores": scores, "metric_info": {m: METRIC_INFO[m] for m in metric_cols}, "rows": rows,
    }
    config.EVAL_DIR.mkdir(parents=True, exist_ok=True)
    config.RAGAS_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    df.to_csv(config.EVAL_DIR / "ragas_results.csv", index=False)

    print("\nRAGAS scores (0-1, higher is better)")
    for m, v in scores.items():
        print(f"  {m:40s} {v if v is not None else 'n/a'}")
    print(f"\nSaved {config.RAGAS_REPORT}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate the assistant with RAGAS.")
    parser.add_argument("--limit", type=int, help="only evaluate the first N questions")
    run(parser.parse_args().limit)
