"""`pull-from-shk.sh` 가 받아 둔 CSV 를 cosmai_integrated 에 적재한다.

지난번 적재는 임시로 했고 스크립트가 남지 않았다. 그래서 사본이 어떤 동결 시점의
무엇인지 나중에 확인할 방법이 없었다. 여기서 그걸 고친다.

## 한 트랜잭션으로 한다

truncate 와 copy 를 한 트랜잭션에 넣는다. 중간에 한 테이블이라도 실패하면 전부
되돌아가므로, 반쯤 적재된 DB 라는 상태가 존재하지 않는다. 질의 GUI 가 이 DB 를 보고
있어서 더 중요하다 — truncate 는 ACCESS EXCLUSIVE 잠금을 잡으므로 읽는 쪽은 빈
테이블을 보는 게 아니라 잠깐 기다렸다가 새 데이터를 본다.

## public 만 건드린다

`entity.*` 와 `academic.*` 는 파생 스키마라 여기서 손대지 않는다. 다만 `entity` 는
`product` 에서 유도된 것이라 적재 후 `classify_rows.py --apply` 를 다시 돌려야 맞는다.
그 사실을 마지막에 출력한다 — 잊으면 조용히 낡은 채로 남는다.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# 적재 순서는 상관없다 — 이 사본에는 테이블 간 FK 가 없다. shk 원본의 순서를 따른다.
TABLES = ["rank_snapshot", "price_point", "product", "new_product", "review",
          "review_topic", "review_answer", "review_stats", "review_summary",
          "run", "run_source", "fetch_log"]


def csv_records(path: Path) -> int:
    """행이 아니라 레코드를 센다. 리뷰 본문에 줄바꿈이 들어 있다."""
    with path.open(encoding="utf-8", newline="") as handle:
        return max(0, sum(1 for _ in csv.reader(handle)) - 1)


def header_of(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return next(csv.reader(handle))


def load(dsn: str, source_dir: Path) -> int:
    import psycopg

    freeze = (source_dir / "FREEZE.txt").read_text(encoding="utf-8").strip()
    print(f"[측정] 동결 시각 {freeze} UTC")

    expected = {}
    for table in TABLES:
        path = source_dir / f"{table}.csv"
        if not path.is_file():
            raise SystemExit(f"[실패] {path} 가 없다. pull-from-shk.sh 를 먼저 돌려라")
        expected[table] = csv_records(path)

    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(f"truncate {', '.join(TABLES)}")
        for table in TABLES:
            path = source_dir / f"{table}.csv"
            columns = ", ".join(f'"{c}"' for c in header_of(path))
            statement = (f"copy {table} ({columns}) from stdin"
                         " with (format csv, header true)")
            with cursor.copy(statement) as copy, path.open("rb") as handle:
                while chunk := handle.read(1 << 20):
                    copy.write(chunk)

        # 커밋 전에 센다. 어긋나면 아무것도 남기지 않고 끝낸다.
        bad = []
        for table in TABLES:
            cursor.execute(f"select count(*) from {table}")
            got = cursor.fetchone()[0]
            mark = "OK" if got == expected[table] else "** 불일치 **"
            if got != expected[table]:
                bad.append(f"{table}: {got} != {expected[table]}")
            print(f"  {table:<16}{got:>8}  {mark}")
        if bad:
            raise SystemExit("[실패] 행 수가 어긋난다, 롤백한다:\n  " + "\n  ".join(bad))

    print(f"\n[측정] 12개 테이블 적재 완료, 동결 {freeze} UTC")
    print("[다음] entity.* 는 product 에서 유도된 것이라 아직 낡았다. "
          "classify_rows.py --apply 를 다시 돌려야 한다.")
    return 0


def _self_check() -> None:
    """CSV 레코드 계수가 줄바꿈 든 본문에서도 맞는지. DB 는 건드리지 않는다."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "t.csv"
        path.write_text('a,b\n1,"두 줄\n짜리 본문"\n2,평범\n', encoding="utf-8")
        assert csv_records(path) == 2, csv_records(path)
        assert header_of(path) == ["a", "b"]
    print("self-check OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn")
    parser.add_argument("--dir", default="shk-pull")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0
    if not args.dsn:
        parser.error("--dsn 또는 --self-check")
    return load(args.dsn, Path(args.dir))


if __name__ == "__main__":
    sys.exit(main())
