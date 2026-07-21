"""
data/seed_task_categories.py에 있는 부서 내 세부업무(TASK) 데이터를
ChromaDB(task_categories 컬렉션)에 일괄 색인하는 스크립트.
실행 방법 (ieum_ai 폴더 루트에서):
    python data/seed_task_categories_ingest.py
이미 같은 (department_code, task_id) 조합이 있으면 덮어씁니다(upsert).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.vectorstore.chroma_client import add_task
from data.seed_task_categories import TASKS


def main():
    print(f"총 {len(TASKS)}건 색인을 시작합니다...")
    for t in TASKS:
        add_task(t["task_id"], t["name"], t["department_code"], t["description"])

    from collections import Counter
    counts = Counter(t["department_code"] for t in TASKS)
    print("\n부서별 색인 건수:")
    for dept, cnt in sorted(counts.items()):
        print(f"  {dept}: {cnt}건")
    print(f"\n완료! 총 {len(TASKS)}건이 ChromaDB(task_categories 컬렉션)에 색인되었습니다.")
    print("확인하려면 서버 실행 후 /api/classify-task 로 검색해보세요.")


if __name__ == "__main__":
    main()
