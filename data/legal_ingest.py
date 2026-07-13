# -*- coding: utf-8 -*-
"""
법령 PDF 색인 스크립트 (법률챗봇용, 기존 seed_ingest.py와 별도).

사용법 (ieum_ai 루트에서, conda activate ieum_ai 상태로):
    python data/legal_ingest.py "민원_처리에_관한_법률.pdf" "민원 처리에 관한 법률"
    python data/legal_ingest.py "지방세법.pdf" "지방세법"

동작:
    1) PDF에서 텍스트 추출 (pypdf)
    2) 조문("제N조(제목)") 단위로 청크 분할 (parse_legal_pdf.py 재사용)
    3) ko-sbert-nli로 임베딩 → ChromaDB "legal_documents" 컬렉션에 색인
       (민원 코퍼스가 있는 "complaints" 컬렉션과는 완전히 별개)
    4) LEGAL_DOCUMENT 테이블에 넣을 INSERT문을 화면에 출력
       (ieum_ai에서 직접 MySQL에 쓰지 않고, 백엔드 담당자가 실행하도록 SQL만 생성 -
        기존 프로젝트 관례상 AI 서버가 DB에 직접 쓰지 않는 방식과 일관성 유지)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pypdf import PdfReader
from app.embeddings.embedder import embed_texts
from app.core.config import settings
import chromadb

from parse_legal_pdf import parse_legal_articles  # 같은 data/ 폴더에 위치

LEGAL_COLLECTION_NAME = "legal_documents"


def extract_pdf_text(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    pages_text = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages_text)


def get_legal_collection():
    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    return client.get_or_create_collection(
        name=LEGAL_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def ingest_law_pdf(pdf_path: str, law_title: str):
    print(f"[1/4] PDF 텍스트 추출 중... ({pdf_path})")
    text = extract_pdf_text(pdf_path)

    print("[2/4] 조문 단위 청크 분할 중...")
    articles = parse_legal_articles(text, law_title=law_title)
    print(f"      → {len(articles)}개 조문 추출됨")

    print("[3/4] 임베딩 및 ChromaDB 색인 중...")
    texts = [f"{law_title} 제{a['article_no']}조({a['article_title']})\n{a['content']}" for a in articles]
    vectors = embed_texts(texts)

    collection = get_legal_collection()
    ids = [f"{law_title}_{'buchil_' if a['is_buchil'] else ''}{a['article_no']}" for a in articles]
    collection.upsert(
        ids=ids,
        embeddings=vectors,
        documents=texts,
        metadatas=[{
            "law_title": a["law_title"],
            "article_no": a["article_no"],
            "article_title": a["article_title"],
            "is_buchil": a["is_buchil"],
        } for a in articles],
    )
    print(f"      → {len(articles)}개 조문 색인 완료")

    print("[4/4] LEGAL_DOCUMENT 등록용 SQL (백엔드 담당자에게 전달, 직접 실행은 안 함):\n")
    file_name = os.path.basename(pdf_path)
    print(
        "INSERT INTO LEGAL_DOCUMENT (title, file_url, source_type, uploaded_at) VALUES\n"
        f"('{law_title}', '{file_name}', '01', NOW());"
    )


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python data/legal_ingest.py <PDF경로> <법령명>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    law_title = sys.argv[2]
    ingest_law_pdf(pdf_path, law_title)
