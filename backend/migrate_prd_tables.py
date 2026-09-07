"""기존 PRD 마크다운의 표(POL·NFR·DEC·AT)를 컬렉션 행으로 옮긴다. docs/PLAN-collections.md §7 · 1.10

    docker compose exec -T backend python migrate_prd_tables.py <slug>          # DRY RUN: 무엇을 옮길지만 출력
    docker compose exec -T backend python migrate_prd_tables.py <slug> --apply  # 실제 삽입
    docker compose exec -T backend python migrate_prd_tables.py <slug> --undo   # 이 스크립트가 넣은 행(legacy_id 보유)만 삭제

- 헤더 첫 셀이 ID 인 마크다운 표만 본다. 행의 ID 접두어로 대상 컬렉션을 정한다.
- 원래 ID(POL-07)는 props.legacy_id 에 보존하고 새 번호(seq)를 발급한다.
- 원문 md 는 지우지 않는다. 대신 legacy 섹션 제목을 "기존 PRD (표는 컬렉션으로 옮겨짐)" 로 바꾼다.
- 같은 컬렉션에 legacy_id 행이 이미 있으면 그 표는 건너뛴다(두 번 실행해도 중복되지 않게).
- init_db 에서 부르지 않는다. 실행 전 화면에서 버전을 하나 저장해 두는 것을 권한다.
"""
import json
import re
import sys

import main

# 첫 열 ID 접두어 → (컬렉션 key, 표 열 순서대로 대응되는 속성 key, 고정 속성)
TARGETS = {
    "POL": ("policies", ["policy"], {}),
    "NFR": ("nfr", ["area", "requirement"], {}),
    "DEC": ("decisions", ["topic", "default"], {"status": "미결정"}),
    "AT": ("tests", ["scenario", "expected"], {}),
}
ID_RE = re.compile(r"^([A-Z]+)-\d+$")
SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}")
LEGACY_TITLE = "기존 PRD"
LEGACY_TITLE_DONE = "기존 PRD (표는 컬렉션으로 옮겨짐)"


def split_row(line: str) -> list[str]:
    """'| a | b |' → ['a', 'b']. 셀 안에 \\| 는 없다고 본다(실측)."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_tables(md: str) -> list[tuple[list[str], list[list[str]]]]:
    """마크다운 표 블록들 중 헤더 첫 셀이 ID 인 것만 (header, rows) 로."""
    lines, out, i = md.splitlines(), [], 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) and SEP_RE.match(lines[i + 1]):
            header, rows, i = split_row(lines[i]), [], i + 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            if header and header[0].upper() == "ID":
                out.append((header, rows))
        else:
            i += 1
    return out


def plan(md: str) -> dict[str, list[dict]]:
    """접두어별로 옮길 행을 모은다. {컬렉션 key: [props, …]}"""
    result: dict[str, list[dict]] = {}
    for _header, rows in parse_tables(md):
        for r in rows:
            m = ID_RE.match(r[0]) if r else None
            if not m or m.group(1) not in TARGETS:
                continue
            key, cols, fixed = TARGETS[m.group(1)]
            props = {c: (r[k + 1] if k + 1 < len(r) else "") for k, c in enumerate(cols)}
            props.update(fixed)
            props["legacy_id"] = r[0]
            result.setdefault(key, []).append(props)
    return result


def apply(cur, pid: int, planned: dict[str, list[dict]]) -> dict[str, int]:
    made = {}
    for key, rows in planned.items():
        cid = main.add_collection(cur, pid, key, builtin=True)
        if cid is None:                       # 이미 있는 표면 그 id 를 쓴다
            cur.execute("SELECT id FROM collections WHERE project_id = %s AND key = %s", (pid, key))
            cid = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM items WHERE collection_id = %s AND props ? 'legacy_id'", (cid,))
        if cur.fetchone()[0]:
            print(f"  {key}: 이미 옮긴 행이 있어 건너뜀")
            continue
        for props in rows:
            main.add_item(cur, pid, cid, props)
        made[key] = len(rows)
    cur.execute("""UPDATE items SET props = props || %s::jsonb
                   WHERE project_id = %s AND props->>'title' = %s""",
                (json.dumps({"title": LEGACY_TITLE_DONE}, ensure_ascii=False), pid, LEGACY_TITLE))
    return made


def undo(cur, pid: int) -> int:
    cur.execute("DELETE FROM items WHERE project_id = %s AND props ? 'legacy_id'", (pid,))
    n = cur.rowcount
    # 비어 버린 대상 표는 함께 지운다 (사용자가 따로 넣은 행이 있으면 남긴다)
    cur.execute("""DELETE FROM collections c WHERE c.project_id = %s AND c.key = ANY(%s)
                   AND NOT EXISTS (SELECT 1 FROM items i WHERE i.collection_id = c.id)""",
                (pid, [t[0] for t in TARGETS.values()]))
    cur.execute("""UPDATE items SET props = props || %s::jsonb
                   WHERE project_id = %s AND props->>'title' = %s""",
                (json.dumps({"title": LEGACY_TITLE}, ensure_ascii=False), pid, LEGACY_TITLE_DONE))
    return n


def main_cli(argv: list[str]) -> int:
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 1
    slug, mode = argv[0], ("--apply" if "--apply" in argv else "--undo" if "--undo" in argv else "dry")
    with main.pool.connection() as conn, conn.cursor() as cur:
        pid, _owner, _token = main.find_project(cur, slug)
        cur.execute("SELECT prd FROM projects WHERE id = %s", (pid,))
        md = cur.fetchone()[0] or ""
        if mode == "--undo":
            print(f"삭제한 행: {undo(cur, pid)}")
            return 0
        planned = plan(md)
        if not planned:
            print("옮길 표가 없습니다 (헤더 첫 셀이 ID 이고 행 ID 가 POL-/NFR-/DEC-/AT- 인 표를 찾습니다)")
            return 0
        for key, rows in planned.items():
            sample = {k: (v[:40] + "…" if len(v) > 40 else v) for k, v in rows[0].items()}
            print(f"{key:<10} {len(rows):>3}행   예) {json.dumps(sample, ensure_ascii=False)}")
        if mode != "--apply":
            print("\nDRY RUN — 실제로 넣으려면 --apply")
            return 0
        made = apply(cur, pid, planned)
        print("삽입:", made or "없음(모두 건너뜀)")
    return 0


if __name__ == "__main__":
    sys.exit(main_cli(sys.argv[1:]))
