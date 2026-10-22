#!/usr/bin/env bash
# 도구만 따로 시험해 보기 (서버·LLM 없이)
#   bash sh/test_tools.sh            # 톨루엔 조회 + 규정 검색
#   bash sh/test_tools.sh benzene    # 다른 물질
set -euo pipefail
cd "$(dirname "$0")/.."
CHEM="${1:-toluene}"

echo "── ① PubChem 도구: $CHEM ──"
./.venv/bin/python3 -m tools.pubchem "$CHEM"

echo
echo "── ② MCP 서버 도구: search_manuals('염산 취급') ──"
./.venv/bin/python3 - <<'EOF'
import asyncio
from tools.manual_client import ManualClient

async def main():
    c = ManualClient()
    await c.start()
    for m in await c.search("염산 취급"):
        print(f"  {m['id']} {m['title']} (점수 {m['score']})")
    await c.stop()

asyncio.run(main())
EOF
