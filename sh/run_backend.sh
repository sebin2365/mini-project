#!/usr/bin/env bash
# 백엔드 API 서버(포트 8100) 켜기
#   bash sh/run_backend.sh ollama    로컬 Ollama (기본값, 무료)
#   bash sh/run_backend.sh openai    OpenAI API (과금)
#   bash sh/run_backend.sh fake      가짜 LLM — 화면·서버 연결 확인용
# 종료: Ctrl+C
set -euo pipefail
cd "$(dirname "$0")/.."

[ -x ".venv/bin/python3" ] || { echo "먼저 bash sh/setup.sh 를 실행하세요."; exit 1; }
[ -f .env ] || cp .env.example .env
set -a; source .env; set +a

export LLM_BACKEND="${1:-ollama}"

if [ "$LLM_BACKEND" = "ollama" ]; then
    ANALYZER="${OLLAMA_ANALYZER_MODEL:-qwen3:0.6b}"
    WRITER="${OLLAMA_WRITER_MODEL:-qwen3:8b}"
    if ! curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        echo "Ollama가 꺼져 있어 켭니다..."
        nohup ollama serve > /tmp/safework_ollama.log 2>&1 &
        sleep 3
    fi
    for m in "$ANALYZER" "$WRITER"; do
        ollama list | grep "^${m}" >/dev/null || {
            echo "모델 $m 이 없습니다 → 받는 중 (처음 한 번, 몇 분 걸릴 수 있어요)"
            ollama pull "$m"; }
    done
    echo "모델: 분석=$ANALYZER / 작성=$WRITER"
fi

if [ "$LLM_BACKEND" = "openai" ]; then
    if [ -z "${OPENAI_API_KEY:-}" ] || [ "$OPENAI_API_KEY" = "sk-..." ]; then
        echo "ERROR: .env 에 OPENAI_API_KEY를 채워주세요."; exit 1
    fi
    read -r -p "⚠️  OpenAI는 요청마다 요금이 나옵니다. 계속할까요? [y/N] " OK
    [[ "$OK" =~ ^[yY] ]] || exit 1
fi

lsof -ti:8100 | xargs kill -9 2>/dev/null || true   # 이전에 켜둔 서버 정리
echo
echo "백엔드를 켭니다 → http://localhost:8100  (LLM_BACKEND=$LLM_BACKEND)"
echo "API 문서(자동 생성): http://localhost:8100/docs"
echo "이 창은 켜 둔 채로, 새 탭에서 bash sh/run_frontend.sh 를 실행하세요."
echo
./.venv/bin/python3 server.py
