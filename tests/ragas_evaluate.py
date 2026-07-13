"""
RAGAS 정량 평가 스크립트 (Faithfulness / Context Precision / Context Recall)
-- ragas>=0.4 collections API 기준 --

사용법:
    1) ieum_ai 서버 + Ollama 켜두기
    2) OpenAI API 키 설정 (judge용, 결제 발생)
       PowerShell: $env:OPENAI_API_KEY = "sk-..."
    3) 패키지 설치 (이미 하셨다면 생략)
       python -m pip install ragas openai langchain-openai
    4) 실행
       python ragas_evaluate.py --limit 8   # 먼저 소규모로
       python ragas_evaluate.py             # 전체 40건

    결과: 화면에 지표별 평균 점수 출력 + ragas_results.csv 저장 (건별 상세 점수 + 판단 이유)
"""
import argparse
import asyncio
import csv
import json
import os
import sys

import requests

DOMAIN_TO_DEPT_CODE = {
    "교통": "TRAF",
    "주택·건축": "URBAN",
    "환경": "ENV",
    "복지": "WELF",
    "안전": "SAFETY",
    "경제·산업": "ECON",
    "문화·체육·관광": "CULT",
    "행정·일반": "GEN",
}


def load_goldset(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def call_draft(base_url: str, complaint_text: str, department_code: str, domain_code: str, timeout: float = 120.0):
    try:
        res = requests.post(
            f"{base_url}/api/draft",
            json={
                "complaint_text": complaint_text,
                "department_code": department_code,
                "domain_code": domain_code,
            },
            timeout=timeout,
        )
        res.raise_for_status()
        body = res.json()
        return body.get("draft"), body.get("referenced_cases", [])
    except Exception as e:
        print(f"  [경고] /api/draft 호출 실패: {e}")
        return None, None


def collect_samples(goldset: list[dict], base_url: str, limit: int | None):
    items = goldset[:limit] if limit else goldset
    samples = []

    for item in items:
        no = item["no"]
        domain = item["domain"]
        question = item["question"]
        ground_truth = item["ground_truth"]
        dept_code = DOMAIN_TO_DEPT_CODE.get(domain)

        print(f"[{no:2d}] ({domain}) draft 생성 중... {question[:40]}")

        if not dept_code:
            print("  [경고] department_code 매핑 없음 - 건너뜀")
            continue

        draft, referenced = call_draft(base_url, question, dept_code, domain)
        if draft is None:
            continue

        retrieved_contexts = [c["document"] for c in referenced] if referenced else []
        if not retrieved_contexts:
            print("  [주의] 검색된 유사사례 0건 - RAGAS 지표가 왜곡될 수 있음")

        samples.append(
            {
                "no": no,
                "domain": domain,
                "user_input": question,
                "response": draft,
                "retrieved_contexts": retrieved_contexts,
                "reference": ground_truth,
            }
        )

    return samples


async def score_all(samples: list[dict]):
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import Faithfulness, ContextPrecision, ContextRecall

    if not os.environ.get("OPENAI_API_KEY"):
        print("환경변수 OPENAI_API_KEY가 설정되어 있지 않습니다.")
        print('PowerShell: $env:OPENAI_API_KEY = "sk-..."')
        sys.exit(1)

    client = AsyncOpenAI()
    llm = llm_factory("gpt-4o-mini", client=client)

    faithfulness = Faithfulness(llm=llm)
    context_precision = ContextPrecision(llm=llm)
    context_recall = ContextRecall(llm=llm)

    results = []
    total = len(samples)

    for i, s in enumerate(samples, 1):
        print(f"[{i}/{total}] RAGAS 채점 중 (no={s['no']}, {s['domain']})...")

        try:
            f_result = await faithfulness.ascore(
                user_input=s["user_input"],
                response=s["response"],
                retrieved_contexts=s["retrieved_contexts"],
            )
            cp_result = await context_precision.ascore(
                user_input=s["user_input"],
                retrieved_contexts=s["retrieved_contexts"],
                reference=s["reference"],
            )
            cr_result = await context_recall.ascore(
                user_input=s["user_input"],
                retrieved_contexts=s["retrieved_contexts"],
                reference=s["reference"],
            )

            results.append(
                {
                    "no": s["no"],
                    "domain": s["domain"],
                    "question": s["user_input"],
                    "faithfulness": f_result.value,
                    "context_precision": cp_result.value,
                    "context_recall": cr_result.value,
                    "faithfulness_reason": getattr(f_result, "reason", ""),
                }
            )
        except Exception as e:
            print(f"  [경고] 채점 실패 (no={s['no']}): {e}")

    return results


def main():
    parser = argparse.ArgumentParser(description="RAGAS 정량 평가 스크립트 (ragas>=0.4)")
    parser.add_argument("--goldset", default="ragas_goldset_40.json")
    parser.add_argument("--base-url", default="http://localhost:8100")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", default="ragas_results.csv")
    args = parser.parse_args()

    try:
        goldset = load_goldset(args.goldset)
    except FileNotFoundError:
        print(f"골드셋 파일을 찾을 수 없습니다: {args.goldset}")
        sys.exit(1)

    samples = collect_samples(goldset, args.base_url, args.limit)
    if not samples:
        print("평가할 샘플이 없습니다 (전부 호출 실패 또는 매핑 누락).")
        sys.exit(1)

    print(f"\nRAGAS 평가 시작 ({len(samples)}건, judge=gpt-4o-mini)... 몇 분 걸릴 수 있습니다.\n")
    results = asyncio.run(score_all(samples))

    if not results:
        print("채점된 결과가 없습니다.")
        sys.exit(1)

    n = len(results)
    avg_faith = sum(r["faithfulness"] for r in results) / n
    avg_cp = sum(r["context_precision"] for r in results) / n
    avg_cr = sum(r["context_recall"] for r in results) / n

    print("=" * 70)
    print(f"RAGAS 평가 결과 (전체 평균, n={n})")
    print("=" * 70)
    print(f"  Faithfulness      : {avg_faith:.3f}")
    print(f"  Context Precision : {avg_cp:.3f}")
    print(f"  Context Recall    : {avg_cr:.3f}")

    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["no", "domain", "question", "faithfulness", "context_precision", "context_recall", "faithfulness_reason"],
        )
        writer.writeheader()
        writer.writerows(results)

    print(f"\n건별 상세 점수 저장됨: {args.out}")
    print("faithfulness/context_precision/context_recall 낮은 순으로 정렬해서 어떤 케이스가 문제인지 확인하세요.")


if __name__ == "__main__":
    main()