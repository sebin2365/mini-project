"""물질조회 에이전트가 쓰는 도구 ① — PubChem REST API (외부 공개 API, API 키 필요 없음).

PubChem은 미국 국립보건원(NIH)이 운영하는 무료 화학물질 데이터베이스다.
  1) 물질 이름 → CID(물질 번호), 분자식
  2) CID → GHS 위험 문구(H코드), 신호어(위험/경고)

인터넷이 안 되거나 PubChem이 응답하지 않으면 data/chemicals_local.json(실습용 로컬
캐시)으로 대신 답한다. 결과에는 어디서 가져왔는지(source)를 항상 남긴다.
"""
import json
import re
from pathlib import Path

import httpx

from tools.ghs_ko import H_CODE_KO, describe

BASE = "https://pubchem.ncbi.nlm.nih.gov/rest"
TIMEOUT = 10.0
DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "chemicals_local.json"

LOCAL = json.loads(DATA_FILE.read_text(encoding="utf-8"))["chemicals"]


# ── 한글 물질명 → 영어 물질명 ────────────────────────────────────────────
def find_known_chemicals(text: str) -> list[str]:
    """작업 계획 속에서 로컬 사전에 있는 물질명(한글/영어)을 찾아 영어 이름 목록으로 돌려준다.
    LLM이 물질명을 놓치거나 잘못 번역할 때를 대비한 안전망이다."""
    found = []
    lower = text.lower()
    for chem in LOCAL:
        names = chem["names_ko"] + [chem["name_en"]]
        if any(n.lower() in lower for n in names):
            found.append(chem["name_en"])
    return found


def korean_name(name_en: str) -> str:
    for chem in LOCAL:
        if chem["name_en"] == name_en.lower():
            return chem["names_ko"][0]
    return name_en


# ── 조회 ────────────────────────────────────────────────────────────────
async def from_pubchem(name_en: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # ① 이름 → CID, 분자식
        r = await client.get(f"{BASE}/pug/compound/name/{name_en}/property/MolecularFormula/JSON")
        r.raise_for_status()   # 없는 물질이면 404 → 에러 → 로컬 캐시로
        props = r.json()["PropertyTable"]["Properties"][0]
        cid = props["CID"]

        # ② CID → GHS 분류. 응답 JSON이 아주 깊게 중첩되어 있어서,
        #    글자 그대로 놓고 'H225' 같은 코드만 정규식으로 뽑는다.
        r = await client.get(f"{BASE}/pug_view/data/compound/{cid}/JSON",
                             params={"heading": "GHS Classification"})
        r.raise_for_status()
        text = r.text

    codes = list(dict.fromkeys(re.findall(r"\b(H\d{3})\b", text)))   # 중복 제거, 순서 유지
    hazards = [describe(c) for c in codes if c in H_CODE_KO]         # 한글표에 있는 것만
    signal = "위험" if '"Danger"' in text else ("경고" if '"Warning"' in text else None)
    return {"found": True, "name_en": name_en, "name_ko": korean_name(name_en),
            "formula": props.get("MolecularFormula"), "signal": signal,
            "hazards": hazards, "flash_point": None,
            "source": f"PubChem (CID {cid})",
            "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"}


def from_local(name_en: str) -> dict:
    for chem in LOCAL:
        if chem["name_en"] == name_en:
            return {"found": True, "name_en": name_en, "name_ko": chem["names_ko"][0],
                    "formula": chem["formula"], "signal": chem["signal"],
                    "hazards": [describe(c) for c in chem["hazards"]],
                    "flash_point": chem["flash_point"],
                    "source": "로컬 캐시(data/chemicals_local.json)", "url": None}
    return {"found": False, "name_en": name_en, "source": "PubChem·로컬 캐시 모두 없음"}


async def lookup_chemical(name_en: str, offline: bool = False) -> dict:
    """물질 1개 조회. PubChem 먼저, 실패하면 로컬 캐시."""
    name_en = name_en.strip().lower()
    if not offline:
        try:
            return await from_pubchem(name_en)
        except Exception as e:   # 네트워크 오류, 404, 응답 형식 오류 → 로컬 캐시로
            print(f"[PubChem] {name_en} 조회 실패 → 로컬 캐시 사용 ({type(e).__name__})")
    return from_local(name_en)


if __name__ == "__main__":
    # 단독 테스트:  python -m tools.pubchem toluene
    import asyncio
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "toluene"
    print(json.dumps(asyncio.run(lookup_chemical(name)), ensure_ascii=False, indent=2))
