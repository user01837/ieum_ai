"""
분류기(/api/classify) 자동 정확도 테스트 스크립트

사용법:
    1) ieum_ai 서버를 먼저 켜둔다.
       uvicorn app.main:app --reload --port 8100
       (Ollama도 당연히 켜져 있어야 함: ollama list 로 handover-classifier 확인)

    2) 이 스크립트와 ragas_goldset_40.json을 같은 폴더에 두고 실행.
       python test_classifier_accuracy.py

    3) 다른 경로/포트를 쓴다면:
       python test_classifier_accuracy.py --goldset ./ragas_goldset_40.json --base-url http://localhost:8100
"""
import argparse
import json
import sys
from collections import defaultdict

import requests

DOMAIN_CATEGORIES = [
    "교통", "주택·건축", "환경", "복지",
    "안전", "경제·산업", "문화·체육·관광", "행정·일반",
]


def load_goldset(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # question, domain 필드만 쓰지만 나머지도 결과 리포트에 같이 남겨둠
    return data


def call_classify(base_url: str, text: str, timeout: float = 15.0) -> str | None:
    """
    /api/classify 엔드포인트 호출. 실패 시 None 반환(에러 메시지는 호출부에서 출력).
    """
    try:
        res = requests.post(
            f"{base_url}/api/classify",
            json={"text": text},
            timeout=timeout,
        )
        res.raise_for_status()
        return res.json()["domain_code"]
    except Exception as e:
        print(f"  [경고] 호출 실패: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="분류기 골드셋 자동 정확도 테스트")
    parser.add_argument("--goldset", default="ragas_goldset_40.json", help="골드셋 JSON 경로")
    parser.add_argument("--base-url", default="http://localhost:8100", help="ieum_ai 서버 base URL")
    args = parser.parse_args()

    try:
        goldset = load_goldset(args.goldset)
    except FileNotFoundError:
        print(f"골드셋 파일을 찾을 수 없습니다: {args.goldset}")
        sys.exit(1)

    print(f"총 {len(goldset)}건 테스트 시작 (서버: {args.base_url})\n")

    results = []  # (no, domain(정답), question, 예측, 정오)
    confusion = defaultdict(lambda: defaultdict(int))  # confusion[정답][예측] = count
    per_domain_total = defaultdict(int)
    per_domain_correct = defaultdict(int)
    failed_calls = 0

    for item in goldset:
        no = item["no"]
        expected = item["domain"]
        question = item["question"]

        predicted = call_classify(args.base_url, question)

        if predicted is None:
            failed_calls += 1
            results.append((no, expected, question, "호출실패", False))
            continue

        is_correct = predicted == expected
        results.append((no, expected, question, predicted, is_correct))
        confusion[expected][predicted] += 1
        per_domain_total[expected] += 1
        if is_correct:
            per_domain_correct[expected] += 1

        mark = "✅" if is_correct else "❌"
        print(f"[{no:2d}] {mark} 정답:{expected:10s} 예측:{predicted:10s} | {question[:40]}")

    print("\n" + "=" * 70)
    print("도메인별 정확도")
    print("=" * 70)
    total_correct = sum(per_domain_correct.values())
    total_evaluated = sum(per_domain_total.values())
    for domain in DOMAIN_CATEGORIES:
        total = per_domain_total.get(domain, 0)
        correct = per_domain_correct.get(domain, 0)
        acc = (correct / total * 100) if total else 0.0
        print(f"  {domain:10s} : {correct}/{total}  ({acc:5.1f}%)")

    overall_acc = (total_correct / total_evaluated * 100) if total_evaluated else 0.0
    print("-" * 70)
    print(f"  {'전체':10s} : {total_correct}/{total_evaluated}  ({overall_acc:5.1f}%)")
    if failed_calls:
        print(f"  (호출 실패로 제외된 건수: {failed_calls}건 — 서버/Ollama 상태 확인 필요)")

    print("\n" + "=" * 70)
    print("혼동 행렬 (정답 도메인 -> 실제 예측된 도메인들)")
    print("=" * 70)
    for domain in DOMAIN_CATEGORIES:
        preds = confusion.get(domain, {})
        wrong_preds = {k: v for k, v in preds.items() if k != domain}
        if wrong_preds:
            detail = ", ".join(f"{k}:{v}건" for k, v in sorted(wrong_preds.items(), key=lambda x: -x[1]))
            print(f"  {domain:10s} -> 오답: {detail}")

    # 결과를 JSON으로도 저장 (다음 세션/재파인튜닝 검토용)
    out_path = "classifier_test_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "overall_accuracy": overall_acc,
                "per_domain": {
                    d: {
                        "correct": per_domain_correct.get(d, 0),
                        "total": per_domain_total.get(d, 0),
                    }
                    for d in DOMAIN_CATEGORIES
                },
                "details": [
                    {"no": no, "expected": exp, "question": q, "predicted": pred, "correct": ok}
                    for no, exp, q, pred, ok in results
                ],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\n상세 결과 저장됨: {out_path}")


if __name__ == "__main__":
    main()