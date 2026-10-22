"""규정조회 에이전트가 쓰는 도구 ② — 직접 만든 MCP 서버 "safety-manuals".

data/manuals/*.md(실습용 가상 사내 안전규정 8종)를 MCP 방식으로 꺼내 준다.
  - Tool     search_manuals(query, top_k) : 질문과 관련 있는 규정을 점수순으로 찾기
  - Tool     list_manuals()               : 규정 목록
  - Resource manual://{manual_id}          : 규정 원문 전체

에이전트 서버(server.py)가 이 파일을 별도 프로세스(stdio)로 띄워서 연결한다.
단독 테스트:  python mcp_server/safety_server.py  (실행 후 Ctrl+C로 종료)
"""
import re
from pathlib import Path

from fastmcp import FastMCP

MANUAL_DIR = Path(__file__).resolve().parent.parent / "data" / "manuals"

mcp = FastMCP("safety-manuals")


def _load_manuals() -> list[dict]:
    manuals = []
    for path in sorted(MANUAL_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta, body = {}, text
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
        if m:
            body = m.group(2)
            for line in m.group(1).splitlines():
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip()
        keywords = [k.strip() for k in meta.get("keywords", "").strip("[]").split(",") if k.strip()]
        manuals.append({"id": meta.get("id", path.stem), "title": meta.get("title", path.stem),
                        "keywords": keywords, "body": body.strip(), "file": path.name})
    return manuals


MANUALS = _load_manuals()


def _score(manual: dict, query: str) -> int:
    """아주 단순한 키워드 점수: 키워드가 질문에 들어 있으면 +3, 질문 단어가 본문에 있으면 +1.
    (개선 아이디어: 임베딩 기반 의미 검색(RAG)으로 바꾸기)"""
    q = query.lower()
    score = sum(3 for k in manual["keywords"] if k.lower() in q)
    words = {w for w in re.findall(r"[가-힣A-Za-z]{2,}", q)}
    body = manual["body"].lower()
    score += sum(1 for w in words if w in body)
    return score


@mcp.tool
def search_manuals(query: str, top_k: int = 3) -> list[dict]:
    """질문과 관련 있는 사내 안전규정을 찾아 점수가 높은 순서로 돌려준다."""
    ranked = sorted(((_score(m, query), m) for m in MANUALS), key=lambda x: -x[0])
    results = []
    for score, m in ranked[:top_k]:
        if score <= 0:
            continue
        results.append({"id": m["id"], "title": m["title"], "score": score,
                        "content": m["body"][:1200]})
    return results


@mcp.tool
def list_manuals() -> list[dict]:
    """등록된 사내 안전규정 목록."""
    return [{"id": m["id"], "title": m["title"], "keywords": m["keywords"]} for m in MANUALS]


@mcp.resource("manual://{manual_id}")
def get_manual(manual_id: str) -> str:
    """규정 원문 전체 (예: manual://SAFE-01)."""
    for m in MANUALS:
        if m["id"] == manual_id:
            return m["body"]
    return f"{manual_id} 규정을 찾을 수 없습니다."


if __name__ == "__main__":
    mcp.run(show_banner=False)   # 기본: stdio 방식
