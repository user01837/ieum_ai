# -*- coding: utf-8 -*-
"""
가드레일 임계값 캘리브레이션 스크립트.

40건 골드셋 각각에 대해 실제 top-1 유사도(similarity)를 구하고,
이미 저장된 ragas_results.csv의 context_precision과 나란히 놓아서
"유사도가 몇 % 이상일 때 실제로 관련성 높은 검색이 이루어지는지" 확인합니다.

실행 위치: ieum_ai/tests 폴더
사전 조건: FastAPI 서버(포트 8100) 실행 중, ragas_results.csv가 같은 폴더에 있어야 함
"""
import json
import csv
import requests

BASE_URL = "http://localhost:8100"

DOMAIN_TO_DEPT_CODE = {
    "교통": "TRAF", "주택·건축": "URBAN", "환경": "ENV", "복지": "WELF",
    "안전": "SAFETY", "경제·산업": "ECON", "문화·체육·관광": "CULT", "행정·일반": "GEN",
}

with open("ragas_goldset_40.json", encoding="utf-8") as f:
    goldset = json.load(f)

# ragas_results.csv에서 no별 context_precision, faithfulness 읽기
precision_map = {}
faithfulness_map = {}
with open("ragas_results.csv", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        no = int(row["no"])
        precision_map[no] = float(row["context_precision"])
        faithfulness_map[no] = float(row["faithfulness"])

print(f"{'no':>3} {'도메인':<10} {'top1_유사도':>10} {'precision':>10} {'faithfulness':>12}")
print("-" * 55)

rows = []
for item in goldset:
    no = item["no"]
    domain = item["domain"]
    question = item["question"]
    dept_code = DOMAIN_TO_DEPT_CODE.get(domain)

    try:
        res = requests.post(
            f"{BASE_URL}/api/draft",
            json={"complaint_text": question, "department_code": dept_code, "domain_code": domain},
            timeout=120.0,
        )
        res.raise_for_status()
        referenced = res.json().get("referenced_cases", [])
        top1_sim = referenced[0]["similarity"] if referenced else 0.0
    except Exception as e:
        print(f"  [경고] {no}번 호출 실패: {e}")
        top1_sim = None

    precision = precision_map.get(no)
    faith = faithfulness_map.get(no)
    rows.append((no, domain, top1_sim, precision, faith))
    print(f"{no:>3} {domain:<10} {top1_sim!s:>10} {precision!s:>10} {faith!s:>12}")

# 유사도 구간별 평균 precision/faithfulness 집계 (10% 단위)
print("\n" + "=" * 55)
print("유사도 구간별 평균 (10%p 단위)")
buckets = {}
for no, domain, sim, prec, faith in rows:
    if sim is None:
        continue
    bucket = int(sim // 10) * 10
    buckets.setdefault(bucket, []).append((prec, faith))

for bucket in sorted(buckets.keys()):
    items = buckets[bucket]
    avg_prec = sum(p for p, f in items) / len(items)
    avg_faith = sum(f for p, f in items) / len(items)
    print(f"  {bucket:>3}~{bucket+9}%  (n={len(items):2d})  평균 precision={avg_prec:.3f}  평균 faithfulness={avg_faith:.3f}")

print("\n※ precision/faithfulness가 뚜렷이 낮아지기 시작하는 구간의 하한값을")
print("   가드레일 임계값 후보로 삼으세요 (예: 40%대부터 낮으면 40을 컷오프로).")
