#!/usr/bin/env bash
# 맨 처음 한 번만: 가상환경(.venv) 만들기 + 패키지 설치 + .env 만들기
#   bash sh/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PY=python3
command -v python3.11 >/dev/null 2>&1 && PY=python3.11   # 3.11이 있으면 우선 사용

if [ ! -x ".venv/bin/python3" ]; then
    echo "가상환경(.venv)을 만듭니다... ($($PY --version))"
    $PY -m venv .venv
fi

echo "패키지 설치 중 (1~3분)..."
./.venv/bin/python3 -m pip install --upgrade pip --quiet
./.venv/bin/python3 -m pip install -r requirements.txt --quiet
./.venv/bin/python3 -c "import fastapi, langgraph, langchain_ollama, langchain_openai, fastmcp, mcp; print('  ✓ 패키지 설치 확인')"

if [ ! -f .env ]; then
    cp .env.example .env
    echo "  ✓ .env 파일을 만들었습니다 — 필요하면 열어서 키를 채우세요:  open -e .env"
fi

cat <<EOF

준비 완료! 다음 순서로 실행하세요.
  bash sh/run_backend.sh fake      ← AI 없이 연결만 확인 (가장 빠름)
  bash sh/run_backend.sh ollama    ← 로컬 AI (개발용, 무료)
  bash sh/run_backend.sh openai    ← OpenAI (발표용, 과금)
  그다음 새 터미널 탭에서: bash sh/run_frontend.sh  → 브라우저 http://localhost:5173
EOF
