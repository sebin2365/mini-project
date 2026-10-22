"""가짜 LLM + 로컬 캐시로 전체 흐름을 자동 점검한다. 인터넷·Ollama가 없어도 된다.
  분석 → 물질조회 → 규정조회 → 작성 → 검수 → (서버) 승인 대기 → 반려 → 재작성 → 승인

실행:  LLM_BACKEND=fake PUBCHEM_OFFLINE=1 .venv/bin/python3 -m tests.test_smoke
"""
import os

os.environ.setdefault("LLM_BACKEND", "fake")
os.environ.setdefault("PUBCHEM_OFFLINE", "1")

from fastapi.testclient import TestClient   # noqa: E402

from server import app   # noqa: E402

CASES = [
    # (작업 계획, 꼭 찾아야 하는 작업 유형, 꼭 찾아야 하는 규정)
    ("내일 T-201 톨루엔 저장탱크 안에 들어가서 용접 보수 작업. 작업자 2명",
     {"밀폐공간 작업", "화기작업"}, {"SAFE-04", "SAFE-05", "SAFE-07"}),
    ("3층 배관 랙에서 사다리 타고 올라가 밸브 교체", {"고소작업"}, {"SAFE-08"}),
    ("염산 드럼을 소분 용기로 옮겨 담는 작업", {"화학물질 취급"}, {"SAFE-06"}),
]

ok, total = 0, 0


def check(name, cond):
    global ok, total
    total += 1
    ok += bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}")


with TestClient(app) as client:   # with 블록: 서버 lifespan(MCP 연결)이 실행된다
    check("GET /health", client.get("/health").json()["status"] == "ok")
    r = client.get("/health", headers={"Origin": "http://localhost:5173"})
    check("CORS: 5173 허용 헤더", r.headers.get("access-control-allow-origin") == "http://localhost:5173")

    for req, types, manuals in CASES:
        job = client.post("/jsa", json={"request": req}).json()
        name = f"[{req[:20]}]"
        check(f"{name} 작업 유형 {types}", types <= set(job["analysis"]["work_types"]))
        found = {s.split()[2] for s in job["sources"] if s.startswith("사내 규정")}
        check(f"{name} 규정 {manuals}", manuals <= found)
        check(f"{name} 승인 대기", job["status"] == "pending")
        check(f"{name} 위험도 계산됨", all(r["level"] in ("상", "중", "하") for r in job["draft"]["rows"]))

    # SSE 스트리밍
    text = client.get("/jsa/stream", params={"request": CASES[0][0]}).text
    check("SSE: step 이벤트가 옴", '"type": "step"' in text)
    check("SSE: token(작성 중인 글자) 이벤트가 옴", '"type": "token"' in text)
    check("SSE: result 이벤트가 옴", '"type": "result"' in text and "[DONE]" in text)
    jid = text.split('"job_id": "')[1].split('"')[0]
    text = client.get(f"/jsa/{jid}/revise/stream", params={"comment": "감시인 추가"}).text
    check("SSE 반려: 다시 작성된 v2가 옴", '"version": 2' in text and "감시인 추가" in text)

    # 반려 → 다시 작성 → 승인
    job = client.post("/jsa", json={"request": CASES[0][0]}).json()
    jid = job["job_id"]
    job = client.post(f"/jsa/{jid}/review", json={"approved": False, "comment": "화재감시자 추가"}).json()
    check("반려 후 v2로 다시 작성",
          job["version"] == 2 and job["status"] == "pending" and "화재감시자" in str(job["draft"]))
    job = client.post(f"/jsa/{jid}/review", json={"approved": True, "comment": "OK"}).json()
    check("승인 후 확정", job["status"] == "approved")
    check("확정된 평가는 다시 검토 불가",
          client.post(f"/jsa/{jid}/review", json={"approved": True}).status_code == 400)

    # 작업 계획이 아닌 입력
    job = client.post("/jsa", json={"request": "점심 메뉴 추천해줘"}).json()
    check("작업 계획이 아니면 안내 후 종료", job["status"] == "rejected_input")
    check("없는 평가 번호는 404", client.get("/jsa/없는번호").status_code == 404)

print(f"\n{ok}/{total} 통과")
raise SystemExit(0 if ok == total else 1)
