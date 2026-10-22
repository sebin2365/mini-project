#!/usr/bin/env bash
# 화면(Vue) 켜기 — 포트 5173. 백엔드(8100)와 '다른 출처'라서 CORS 설정이 필요한 구조다.
#   bash sh/run_frontend.sh
# 종료: Ctrl+C
set -euo pipefail
cd "$(dirname "$0")/.."

curl -s --max-time 2 http://127.0.0.1:8100/health >/dev/null 2>&1 \
    || echo "⚠️  백엔드(8100)가 아직 꺼져 있어요. 다른 탭에서 bash sh/run_backend.sh 를 먼저 켜세요."

lsof -ti:5173 | xargs kill -9 2>/dev/null || true
echo "화면을 켭니다 → 브라우저에서 http://localhost:5173 을 여세요"
python3 -m http.server 5173 --bind 127.0.0.1 --directory frontend
