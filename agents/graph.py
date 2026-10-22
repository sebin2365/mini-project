"""SafeWork 멀티 에이전트 — LangGraph로 '누가 언제 일하는지'를 그린 흐름도.

  작업 계획 → analyze ──(작업 계획 아님)──▶ 끝 (안내 메시지)
                 │
                 ▼
             chem_agent (PubChem) → rule_agent (MCP) → writer → validator ──(통과)──▶ 끝
                                                         ▲          │
                                                         └(형식 미달)┘

- analyze    : 작업 분석 에이전트 — 작업 유형(밀폐공간/화기/고소/화학물질)과 물질을 뽑는다
- chem_agent : 물질조회 에이전트 — PubChem REST API (외부 API 도구)
- rule_agent : 규정조회 에이전트 — 직접 만든 MCP 서버의 search_manuals 도구
- writer     : 평가표 작성 에이전트 — 조사 결과만 근거로 JSON 평가표 작성
- validator  : 코드 검수 — 위험도 계산, 근거 없는 규정번호 삭제, 형식 미달이면 재작성

관리자 승인/반려는 그래프 밖(server.py)에서 처리한다.
반려되면 반려 의견(feedback)을 넣어서 그래프를 처음부터 한 번 더 실행한다.
"""
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from agents.llm import get_llm
from agents.prompts import (ANALYZE_SYSTEM, WORK_TYPES, WRITER_SYSTEM, risk_level,
                            writer_user_message)
from agents.schemas import JSADraft, WorkAnalysis, parse_json_as
from tools.pubchem import find_known_chemicals, korean_name, lookup_chemical

MAX_FORMAT_RETRY = 1     # 형식 미달 시 다시 쓰는 횟수
MAX_CHEMICALS = 3


# ── 상태(State): 에이전트들이 함께 보는 메모장 ──────────────────────────
class JSAState(TypedDict, total=False):
    request: str              # 사용자가 입력한 작업 계획
    feedback: str             # 관리자 반려 의견 (다시 작성할 때만 들어옴)
    steps: list               # 화면에 보여줄 진행 단계
    analysis: dict            # 작업 분석 결과
    chem_results: list        # 물질조회 결과
    manual_results: list      # 규정조회 결과
    draft: dict               # 작성된 평가표
    format_feedback: str      # 코드 검수 의견
    format_retries: int
    status: str               # rejected_input(작업 계획 아님) / done
    message: str              # 작업 계획이 아닐 때 안내 메시지


def add_step(state: JSAState, node: str, label: str, detail: str = "") -> list:
    """지금까지의 진행 기록 뒤에 한 줄을 붙인다."""
    return state.get("steps", []) + [{"node": node, "label": label, "detail": detail}]


# ── 조사 결과를 writer가 읽을 글로 정리 ─────────────────────────────────
def format_context(state: JSAState) -> str:
    parts = ["### 물질 정보"]
    chems = state.get("chem_results", [])
    if not chems:
        parts.append("- 해당 없음")
    for c in chems:
        if not c["found"]:
            parts.append(f"- {c['name_en']}: 정보를 찾지 못함")
            continue
        parts.append(f"- {c['name_ko']} ({c['name_en']}) — 신호어: {c['signal'] or '정보 없음'}, "
                     f"인화점: {c['flash_point'] or '정보 없음'}")
        parts += [f"  - {h}" for h in c["hazards"][:6]]
    parts.append("\n### 사내 안전 규정")
    for m in state.get("manual_results", []):
        parts.append(f"[{m['id']} {m['title']}]\n{m['content']}")
    return "\n".join(parts)


def sources(state: JSAState) -> list[str]:
    """평가표 아래에 보여줄 출처 목록."""
    out = []
    for c in state.get("chem_results", []):
        if c["found"]:
            out.append(f"{c['name_ko']}: {c['source']}" + (f" — {c['url']}" if c["url"] else ""))
    for m in state.get("manual_results", []):
        out.append(f"사내 규정 {m['id']} {m['title']} (MCP: safety-manuals)")
    return out


# ── 그래프 만들기 ───────────────────────────────────────────────────────
def build_graph(manual_client, offline: bool = False):
    analyzer_llm = get_llm("analyzer")
    writer_llm = get_llm("writer")

    # 1) 작업 분석 에이전트 ----------------------------------------------
    async def analyze(state: JSAState):
        req = state["request"]
        resp = await analyzer_llm.ainvoke([SystemMessage(ANALYZE_SYSTEM), HumanMessage(req)])
        a = parse_json_as(resp.content, WorkAnalysis)

        # 작은 AI는 자주 놓치므로, 키워드로 한 번 더 확인한다 (코드 안전망)
        kw_types = [t for t, words in WORK_TYPES.items() if any(w in req for w in words)]
        types = list(dict.fromkeys([t for t in a.work_types if t in WORK_TYPES] + kw_types))
        chems = list(dict.fromkeys(find_known_chemicals(req) + [c.lower() for c in a.chemicals]))
        chems = chems[:MAX_CHEMICALS]
        if chems and "화학물질 취급" not in types:
            types.append("화학물질 취급")

        analysis = {**a.model_dump(), "work_types": types, "chemicals": chems,
                    "summary": a.summary or req[:60]}
        if not types:   # 작업 유형을 하나도 못 찾으면 작업 계획이 아니라고 본다
            return {"analysis": analysis, "status": "rejected_input",
                    "message": "작업 계획을 입력해 주세요. 예) '내일 T-201 탱크 안에서 용접 보수 작업, 2명'",
                    "steps": add_step(state, "analyze", "작업 분석", "작업 계획이 아님 → 안내 후 종료")}
        detail = f"유형: {', '.join(types)}" + (f" / 물질: {', '.join(chems)}" if chems else "")
        return {"analysis": analysis, "format_retries": 0,
                "steps": add_step(state, "analyze", "작업 분석", detail)}

    def after_analyze(state: JSAState):
        if state.get("status") == "rejected_input":
            return END
        return "chem_agent"

    # 2) 물질조회 에이전트 (외부 API) -------------------------------------
    async def chem_agent(state: JSAState):
        results = []
        for name in state["analysis"]["chemicals"]:
            results.append(await lookup_chemical(name, offline=offline))

        names = []
        for r in results:
            if not r["found"]:
                names.append(f"{r['name_en']}(못 찾음)")
            elif r["source"].startswith("PubChem"):
                names.append(f"{r['name_ko']}(PubChem)")
            else:
                names.append(f"{r['name_ko']}(로컬 캐시)")
        return {"chem_results": results,
                "steps": add_step(state, "chem_agent", "물질 정보 조회 (PubChem)",
                                  ", ".join(names) or "해당 물질 없음")}

    # 3) 규정조회 에이전트 (MCP) -----------------------------------------
    async def rule_agent(state: JSAState):
        a = state["analysis"]
        names_ko = " ".join(korean_name(c) for c in a["chemicals"])
        # 작업 유형마다 1개씩 + 작업 계획 전체로 2개 + 보호구 1개 → 여러 번 검색해서 합친다
        # (검색어, 가져올 개수, 최소 점수) — 점수가 낮으면 관련 없는 규정이라 버린다
        queries = [(f"{names_ko} 취급" if t == "화학물질 취급" else t, 1, 1) for t in a["work_types"]]
        queries += [(f"{state['request']} {names_ko}", 2, 3), ("보호구", 1, 1)]
        found = {}
        for q, k, min_score in queries:
            for m in await manual_client.search(q, top_k=k):
                if m["score"] >= min_score:
                    found[m["id"]] = m      # 같은 규정이 여러 번 나와도 한 번만
        manuals = sorted(found.values(), key=lambda m: m["id"])[:6]
        return {"manual_results": manuals,
                "steps": add_step(state, "rule_agent", "사내 안전규정 조회 (MCP)",
                                  ", ".join(m["id"] for m in manuals) or "관련 규정 없음")}

    # 4) 평가표 작성 에이전트 ---------------------------------------------
    async def writer(state: JSAState):
        feedback = "\n".join(f for f in [state.get("feedback"), state.get("format_feedback")] if f)
        user = writer_user_message(state["request"], state["analysis"], format_context(state), feedback)
        resp = await writer_llm.ainvoke([SystemMessage(WRITER_SYSTEM), HumanMessage(user)])
        draft = parse_json_as(resp.content, JSADraft)
        label = "위험성평가표 작성" + (" — 형식 보완" if state.get("format_feedback") else "")
        return {"draft": draft.model_dump(),
                "steps": add_step(state, "writer", label, f"{len(draft.rows)}개 항목")}

    # 5) 코드 검수 --------------------------------------------------------
    async def validator(state: JSAState):
        draft = JSADraft.model_validate(state["draft"])
        allowed = {m["id"] for m in state.get("manual_results", [])}
        removed = 0
        for row in draft.rows:
            row.score, row.level = risk_level(row.likelihood, row.severity)   # 위험도는 코드가 계산
            before = len(row.basis)
            row.basis = [b for b in row.basis if b in allowed]                 # 조회 안 한 규정번호는 삭제
            removed += before - len(row.basis)

        problems = []
        if len(draft.rows) < 2:
            problems.append("평가 항목이 2개 미만입니다. 작업 단계별로 3~6개 작성하세요.")
        if any(not r.controls for r in draft.rows):
            problems.append("안전 대책(controls)이 비어 있는 항목이 있습니다.")
        if not draft.ppe:
            problems.append("필요한 보호구(ppe) 목록이 비어 있습니다.")

        if problems and state["format_retries"] < MAX_FORMAT_RETRY:
            return {"format_feedback": " ".join(problems),
                    "format_retries": state["format_retries"] + 1,
                    "steps": add_step(state, "validator", "자동 검수 — 보완 요청", " ".join(problems))}
        detail = "위험도 계산 완료"
        if removed:
            detail += f", 근거 없는 규정번호 {removed}개 삭제"
        if problems:
            detail += " (일부 미흡, 관리자 확인 필요)"
        return {"draft": draft.model_dump(), "format_feedback": "", "status": "done",
                "steps": add_step(state, "validator", "자동 검수 — 통과", detail)}

    def after_validate(state: JSAState):
        return "writer" if state.get("format_feedback") else END

    g = StateGraph(JSAState)
    g.add_node("analyze", analyze)
    g.add_node("chem_agent", chem_agent)
    g.add_node("rule_agent", rule_agent)
    g.add_node("writer", writer)
    g.add_node("validator", validator)

    g.add_edge(START, "analyze")
    g.add_conditional_edges("analyze", after_analyze, ["chem_agent", END])
    g.add_edge("chem_agent", "rule_agent")
    g.add_edge("rule_agent", "writer")
    g.add_edge("writer", "validator")
    g.add_conditional_edges("validator", after_validate, ["writer", END])
    return g.compile()
