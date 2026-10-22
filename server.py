"""SafeWork 백엔드 — FastAPI REST API 서버 (포트 8100).

화면(frontend/, 포트 5173)과 분리되어 있고, 화면은 이 서버의 API만 호출한다.

  GET  /health                       서버 상태, 사용 중인 LLM
  GET  /manuals                      사내 안전규정 목록 (MCP 서버에서 가져옴)

  [REST — 한 번에 받기]
  POST /jsa                          작업 계획 → 위험성평가표 (승인 대기 상태)
  POST /jsa/{job_id}/review          관리자 승인 또는 반려 (반려하면 의견을 반영해 다시 작성)
  GET  /jsa/{job_id}                 현재 상태 조회

  [SSE 스트리밍 — 진행 과정을 실시간으로 받기]
  GET  /jsa/stream                   작업 계획 → 진행 단계 + AI가 작성 중인 글자 + 평가표
  GET  /jsa/{job_id}/revise/stream   반려 의견 → 다시 작성하는 과정을 같은 방식으로 전송

화면(5173)과 서버(8100)는 포트가 달라 '출처(Origin)'가 다르다. 그래서 브라우저가
응답을 막는 CORS 에러가 나는데, 아래 CORSMiddleware가 허용 헤더를 붙여서 해결한다.
실험: DISABLE_CORS=1 로 서버를 켜면 브라우저 콘솔에서 CORS 에러를 직접 볼 수 있다.
"""
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()   # .env의 LangSmith/OpenAI 설정을 먼저 읽는다

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.graph import build_graph, sources
from agents.llm import backend_name, model_names
from tools.manual_client import ManualClient

OFFLINE = os.environ.get("PUBCHEM_OFFLINE") == "1"   # 1이면 PubChem 대신 로컬 캐시만 사용
MAX_REVISIONS = 3                                       # 반려로 다시 쓰는 최대 횟수

# 평가 한 건씩 저장해 두는 곳 { job_id: {...} } — 메모리라서 서버를 끄면 사라진다
JOBS: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버가 켜질 때 딱 1번: MCP 서버 연결 + 그래프 생성 → 모든 요청이 같이 쓴다
    manual_client = ManualClient()
    await manual_client.start()
    app.state.manuals = manual_client
    app.state.graph = build_graph(manual_client, offline=OFFLINE)
    yield
    await manual_client.stop()


app = FastAPI(title="SafeWork JSA Agent API", lifespan=lifespan)

# CORS: 화면(5173)에서 오는 요청을 허용한다는 헤더(Access-Control-Allow-Origin)를 붙인다
if os.environ.get("DISABLE_CORS") != "1":
    app.add_middleware(CORSMiddleware,
                       allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["GET", "POST"], allow_headers=["*"])


# ── 요청 모양 (Pydantic) ────────────────────────────────────────────────
class JSARequest(BaseModel):
    request: str                     # 작업 계획


class ReviewRequest(BaseModel):
    approved: bool                   # True=승인, False=반려
    comment: str = ""                # 반려 사유 / 승인 의견
    approver: str = "관리자"


# ── 평가 한 건 관리 ─────────────────────────────────────────────────────
def new_job(request: str) -> dict:
    job_id = f"jsa-{uuid.uuid4().hex[:8]}"
    JOBS[job_id] = {"job_id": job_id, "request": request, "version": 1,
                    "status": "running", "history": []}
    return JOBS[job_id]


def get_job(job_id: str) -> dict:
    if job_id not in JOBS:
        raise HTTPException(404, "해당 평가를 찾을 수 없습니다.")
    return JOBS[job_id]


def save_result(job: dict, state: dict):
    """그래프 실행 결과를 화면에 보내기 좋은 모양으로 job에 저장한다."""
    job["steps"] = state.get("steps", [])
    job["analysis"] = state.get("analysis")
    if state.get("status") == "rejected_input":            # 작업 계획이 아니었음
        job["status"] = "rejected_input"
        job["message"] = state.get("message")
        return
    job["status"] = "pending"                              # 관리자 승인 대기
    job["draft"] = state.get("draft")
    job["sources"] = sources(state)


async def run_graph(job: dict, feedback: str = "") -> dict:
    graph_input = {"request": job["request"], "feedback": feedback}
    state = await app.state.graph.ainvoke(graph_input)
    save_result(job, state)
    return job


def check_pending(job: dict):
    if job["status"] != "pending":
        raise HTTPException(400, "승인 대기 중인 평가가 아닙니다.")


def reject(job: dict, comment: str) -> str | None:
    """반려 기록을 남기고 버전을 올린다. 반려 한도를 넘으면 종료하고 None."""
    job["history"].append({"version": job["version"], "approved": False, "comment": comment})
    if job["version"] > MAX_REVISIONS:
        job["status"] = "closed"
        return None
    job["version"] += 1
    return comment or "보완이 필요합니다."


# ── REST: 한 번에 받기 ──────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "llm_backend": backend_name(), "models": model_names(),
            "pubchem": "offline(로컬 캐시)" if OFFLINE else "online"}


@app.get("/manuals")
async def manuals():
    return await app.state.manuals.list()


@app.post("/jsa")
async def create_jsa(req: JSARequest):
    return await run_graph(new_job(req.request))


@app.post("/jsa/{job_id}/review")
async def review_jsa(job_id: str, req: ReviewRequest):
    job = get_job(job_id)
    check_pending(job)
    if req.approved:                                       # 승인 → 확정
        job["history"].append({"version": job["version"], "approved": True, "comment": req.comment})
        job["status"] = "approved"
        job["approval"] = {"approver": req.approver, "comment": req.comment,
                           "at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        return job
    feedback = reject(job, req.comment)                    # 반려 → 의견을 넣어 다시 실행
    if feedback is None:
        return job
    return await run_graph(job, feedback=feedback)


# ── SSE: 진행 과정을 실시간으로 받기 ────────────────────────────────────
def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def stream_graph(job: dict, feedback: str = ""):
    """이벤트 종류
      start  : 시작                    {"type":"start","job_id"}
      step   : 에이전트 한 단계가 끝남  {"type":"step","node","label","detail"}
      token  : AI가 평가표를 쓰는 중인 글자 {"type":"token","text"}
      result : 완성된 평가표            {"type":"result", ...job}
      error  : 오류                    {"type":"error","message"}
    마지막에 data: [DONE] 을 보낸다.
    """
    yield sse({"type": "start", "job_id": job["job_id"]})
    try:
        state = {}
        # stream_mode를 두 개 주면 (종류, 내용) 짝으로 나온다
        #   "updates"  : 노드 하나가 끝날 때마다 그 노드가 바꾼 값
        #   "messages" : LLM이 글자를 만들어 내는 대로 조금씩
        async for mode, payload in app.state.graph.astream(
                {"request": job["request"], "feedback": feedback},
                stream_mode=["updates", "messages"]):
            if mode == "messages":
                chunk, meta = payload
                if meta["langgraph_node"] == "writer" and chunk.content:   # 평가표 작성 글자만
                    yield sse({"type": "token", "text": chunk.content})
                continue
            for node, delta in payload.items():
                state.update(delta)
                if delta.get("steps"):
                    yield sse({"type": "step", **delta["steps"][-1]})     # 방금 추가된 진행 단계
        save_result(job, state)
        yield sse({"type": "result", **job})
    except Exception as e:   # 내부 오류를 그대로 보여주지 않고, 사용자용 메시지로 바꾼다
        print(f"[ERROR] {type(e).__name__}: {e}")
        job["status"] = "error"
        yield sse({"type": "error", "message": "평가표를 만드는 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요."})
    yield "data: [DONE]\n\n"


def stream_response(gen):
    return StreamingResponse(gen, media_type="text/event-stream")


@app.get("/jsa/stream")
async def create_jsa_stream(request: str):
    return stream_response(stream_graph(new_job(request)))


@app.get("/jsa/{job_id}/revise/stream")
async def revise_jsa_stream(job_id: str, comment: str = ""):
    job = get_job(job_id)
    check_pending(job)
    feedback = reject(job, comment)
    if feedback is None:                                   # 반려 한도 초과 → 결과만 보내고 끝
        async def closed():
            yield sse({"type": "result", **job})
            yield "data: [DONE]\n\n"
        return stream_response(closed())
    return stream_response(stream_graph(job, feedback))


# ※ 주소 모양이 /jsa/stream 과 겹치므로, {job_id} 주소는 맨 마지막에 등록해야 한다
@app.get("/jsa/{job_id}")
async def get_jsa(job_id: str):
    return get_job(job_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8100)))
