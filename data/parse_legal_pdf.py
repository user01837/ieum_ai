# -*- coding: utf-8 -*-
"""
법령 PDF에서 추출한 텍스트를 "조문 단위"로 청크 분할하는 파서.

법령 조문은 "제N조(제목)" 또는 "제N조의M(제목)" 형식으로 시작하는 게 규칙적이라,
이 패턴을 기준으로 텍스트를 잘라서 각 조문을 독립된 청크로 만든다.
조문 단위로 쪼개야 나중에 "재산세 납부시기가 뭐예요?" 같은 질문에 대해
관련 조문 1~2개만 정확히 검색되지, 법 전체가 통째로 걸리는 걸 막을 수 있다.

사용 방법:
    from parse_legal_pdf import parse_legal_articles
    with open("민원처리법.txt", encoding="utf-8") as f:
        text = f.read()
    articles = parse_legal_articles(text, law_title="민원 처리에 관한 법률")
"""
import re


# 조문 시작 패턴: "제1조(목적)", "제7조의2(민원의 날)" 등
ARTICLE_PATTERN = re.compile(r"제(\d+)조(?:의(\d+))?\(([^)]+)\)")

# 부칙 시작 패턴 (부칙은 조문 번호가 본문과 별개로 다시 1부터 시작되므로 별도 처리)
# 반드시 re.MULTILINE으로 컴파일해야 "^"가 각 줄의 시작에 매치됨 (문서 전체 시작이 아니라)
BUCHIL_PATTERN = re.compile(r"^\s*부칙\s*<", re.MULTILINE)

# 장/절 제목 라인 (예: "제2장 민원의 처리", "제1절 민원의 신청 및 접수 등")
# 조문 내용이 아니라 목차성 헤더라 조문 청크 안에 섞이면 안 됨 - 파싱 전에 통째로 제거
CHAPTER_SECTION_LINE = re.compile(r"^\s*제\d+(?:장|절)\s+.+$", re.MULTILINE)


def _strip_chapter_section_headers(text: str) -> str:
    return CHAPTER_SECTION_LINE.sub("", text)


def parse_legal_articles(text: str, law_title: str) -> list[dict]:
    """
    법령 전문 텍스트를 조문 단위 청크로 분할.

    Returns:
        [
            {
                "law_title": "민원 처리에 관한 법률",
                "article_no": "1",        # 조 번호 (문자열, "7의2" 형태도 있음)
                "article_title": "목적",   # 조문 제목
                "content": "이 법은 민원 처리에 관한...",  # 조문 본문 (다음 조 시작 전까지)
                "is_buchil": False,        # 부칙 여부
            },
            ...
        ]
    """
    text = _strip_chapter_section_headers(text)

    # 부칙 이전/이후로 먼저 분리 (부칙은 조번호가 리셋되므로 섞이면 안 됨)
    buchil_match = BUCHIL_PATTERN.search(text)
    if buchil_match:
        main_text = text[: buchil_match.start()]
        buchil_text = text[buchil_match.start() :]
    else:
        main_text = text
        buchil_text = ""

    articles = []

    def _extract(section_text: str, is_buchil: bool):
        matches = list(ARTICLE_PATTERN.finditer(section_text))
        for i, m in enumerate(matches):
            article_main = m.group(1)
            article_sub = m.group(2)
            article_title = m.group(3)
            article_no = f"{article_main}의{article_sub}" if article_sub else article_main

            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(section_text)
            content = section_text[start:end].strip()

            articles.append({
                "law_title": law_title,
                "article_no": article_no,
                "article_title": article_title,
                "content": content,
                "is_buchil": is_buchil,
            })

    _extract(main_text, is_buchil=False)
    _extract(buchil_text, is_buchil=True)

    # 같은 (article_no, is_buchil) 조합이 여러 번 나오는 경우 처리
    # (법령 PDF 특성상 "현재 버전 + 개정 예정 버전"이 둘 다 실리는 경우가 있음)
    # → 마지막에 등장한 버전(대체로 최신 개정 반영본)만 남기고, 중복 있었던 조문은 로그로 안내
    seen = {}
    order = []
    duplicated_keys = set()
    for a in articles:
        key = (a["article_no"], a["is_buchil"])
        if key in seen:
            duplicated_keys.add(key)
        else:
            order.append(key)
        seen[key] = a  # 나중 것으로 덮어씀 (마지막 등장 버전 채택)

    if duplicated_keys:
        print(f"  ⚠ 중복 조문 {len(duplicated_keys)}건 발견 - 마지막 등장 버전만 채택함 (수동 검토 권장):")
        for no, is_b in sorted(duplicated_keys):
            tag = "[부칙] " if is_b else ""
            print(f"     {tag}제{no}조")

    return [seen[key] for key in order]


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "민원처리법_샘플.txt"
    with open(path, encoding="utf-8") as f:
        text = f.read()

    articles = parse_legal_articles(text, law_title="민원 처리에 관한 법률")

    print(f"총 {len(articles)}개 조문 추출됨\n")
    for a in articles:
        tag = "[부칙] " if a["is_buchil"] else ""
        no_display = f"제{a['article_no']}조" if "의" not in a["article_no"] else f"제{a['article_no'].split('의')[0]}조의{a['article_no'].split('의')[1]}"
        print(f"{tag}{no_display}({a['article_title']})")
        print(f"  내용: {a['content'][:80]}...")
        print()