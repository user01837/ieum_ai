"""
data/seed_tasks.py에 있는 합성 사업 120건을 ChromaDB(tasks 컬렉션)에 일괄 색인하는 스크립트.
실행 방법 (ieum_ai 폴더 루트에서, conda activate ieum_ai 상태로):
    python data/seed_tasks_ingest.py
이미 같은 (lead_department_code, task_id) 조합이 있으면 덮어씁니다(upsert).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.vectorstore.task_chroma_client import add_tasks_batch
from data.seed_tasks import TASKS


def main():
    print(f"총 {len(TASKS)}건 색인을 시작합니다...")
    add_tasks_batch(TASKS)

    from collections import Counter
    counts = Counter(t["lead_department_code"] for t in TASKS)
    print("\n주관부서별 색인 건수:")
    for dept, cnt in sorted(counts.items()):
        print(f"  {dept}: {cnt}건")
    print(f"\n완료! 총 {len(TASKS)}건이 ChromaDB(tasks 컬렉션)에 색인되었습니다.")
    print("확인하려면 서버 실행 후 /api/similar-tasks 로 검색해보세요.")


if __name__ == "__main__":
    main()
