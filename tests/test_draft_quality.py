"""
/api/draft (답변 초안 생성, Llama3.1) 품질 확인용 테스트 스크립트

분류기 테스트(test_classifier_accuracy.py)와 달리, 이건 "정답 O/X"를 자동 채점하는 게
아니라 실제 생성된 답변 초안을 눈으로 확인하기 위한 스크립트입니다.
(자동 정량 평가는 다음 단계인 RAGAS 실증에서 진행)

사용법:
    1) ieum_ai 서버 + Ollama 켜두기
       uvicorn app.main:app --reload --port 8100

    2) 같은 폴더에 ragas_goldset_40.json 두고 실행
       python test_draft_quality.py

    3) 결과는 화면 출력 + draft_test_results.md 파일로 저장됨 (나란히 비교하기 편하게 마크다운)
"""
import argparse
import json
import sys

import requests

# 도메인 -> department_code 임시 매핑 (seed_complaints.py 기준, 부서 마스터 확정 전 값)
# 주택·건축/교통처럼 코드가 2개로 나뉜 도메인은 건수가 더 많은 쪽을 대표값으로 사용.
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
    """
    /api/draft 호출. 실패 시 (None, None) 반환.
    """
    import time
    start = time.time()
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
        elapsed = time.time() - start
        res.raise_for_status()
        body = res.json()
        print(f"  (소요시간: {elapsed:.1f}초)")
        return body.get("draft"), body.get("referenced_cases", [])
    except Exception as e:
        elapsed = time.time() - start
        print(f"  [경고] 호출 실패 ({elapsed:.1f}초 경과): {e}")
        return None, None


def main():
    parser = argparse.ArgumentParser(description="/api/draft 품질 확인 스크립트")
    parser.add_argument("--goldset", default="ragas_goldset_40.json")
    parser.add_argument("--base-url", default="http://localhost:8100")
    parser.add_argument("--limit", type=int, default=None, help="테스트할 건수 제한 (예: 8 = 도메인별 1건씩만)")
    args = parser.parse_args()

    try:
        goldset = load_goldset(args.goldset)
    except FileNotFoundError:
        print(f"골드셋 파일을 찾을 수 없습니다: {args.goldset}")
        sys.exit(1)

    if args.limit:
        goldset = goldset[: args.limit]

    print(f"총 {len(goldset)}건 테스트 시작 (서버: {args.base_url})\n")

    md_lines = ["# /api/draft 품질 확인 결과\n"]
    failed = 0
    zero_reference = 0

    for item in goldset:
        no = item["no"]
        domain = item["domain"]
        question = item["question"]
        ground_truth = item["ground_truth"]
        dept_code = DOMAIN_TO_DEPT_CODE.get(domain)

        print(f"[{no:2d}] ({domain}) {question[:40]}...")

        if not dept_code:
            print(f"  [경고] 매핑되는 department_code 없음 (domain={domain}) - 건너뜀")
            continue

        draft, referenced = call_draft(args.base_url, question, dept_code, domain)

        if draft is None:
            failed += 1
            continue

        if not referenced:
            zero_reference += 1
            print(f"  [주의] 유사사례 0건 검색됨 - department_code({dept_code}) 매핑 확인 필요")

        print(f"  → 생성된 초안: {draft[:80]}...")

        md_lines.append(f"## [{no}] {domain} - {question}\n")
        md_lines.append(f"**참고 사례 수**: {len(referenced) if referenced else 0}건 (department_code={dept_code})\n")
        md_lines.append(f"**생성된 답변 초안**:\n> {draft}\n")
        md_lines.append(f"**RAGAS 골드셋 ground_truth (참고용)**:\n> {ground_truth}\n")
        md_lines.append("---\n")

    print("\n" + "=" * 70)
    print(f"완료: {len(goldset)}건 중 호출실패 {failed}건, 유사사례 0건 검색된 케이스 {zero_reference}건")
    print("=" * 70)

    out_path = "draft_test_results.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"\n상세 결과(생성 초안 vs ground_truth 나란히 비교) 저장됨: {out_path}")
    print("이 파일 열어서 눈으로 훑어보면서 공문서체 톤/근거 활용 여부/환각 여부 확인하시면 됩니다.")


if __name__ == "__main__":
    main()
