"""
seed_complaints.py에 있는 합성 민원을 ChromaDB에 일괄 색인하는 스크립트.
실행 방법 (ieum_ai 폴더 루트에서, conda activate ieum_ai 상태로):
    python data/seed_ingest.py
실행하면 ko-sbert-nli로 임베딩 후 ChromaDB(로컬 디스크, CHROMA_PERSIST_DIR)에 저장됩니다.
이미 같은 complaint_id가 있으면 덮어씁니다(upsert).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.vectorstore.chroma_client import add_complaints_batch
from data.seed_complaints import COMPLAINTS
def main():
    print(f"총 {len(COMPLAINTS)}건 색인을 시작합니다...")
    # add_complaints_batch가 기대하는 키 이름에 맞춰 변환
    items = [
        {
            "complaint_id": c["complaint_id"],
            "title": c["title"],
            "content": c["content"],
            "department_code": c["department_code"],
            "domain_code": c["domain_code"],
            "status_code": c["status_code"],
            "answer": c.get("answer", ""),
        }
        for c in COMPLAINTS
    ]
    add_complaints_batch(items)
    # 도메인별 건수 출력
    from collections import Counter
    counts = Counter(c["domain_code"] for c in COMPLAINTS)
    print("\n도메인별 색인 건수:")
    for domain, cnt in sorted(counts.items()):
        print(f"  {domain}: {cnt}건")
    print(f"\n완료! 총 {len(COMPLAINTS)}건이 ChromaDB에 색인되었습니다.")
    print("확인하려면 서버 실행 후 /api/similar-cases 로 검색해보세요.")
if __name__ == "__main__":
    main()
