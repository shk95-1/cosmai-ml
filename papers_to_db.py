"""월별 논문 수를 모아 DB 에 넣는다 — 학계동향 라벨축의 원자료.

네 수집 소스(oliveyoung/daisomall/glowpick/hwahae) 어디에도 논문은 없다. shk 통합 DB 가
노출하는 13개 테이블에도 학술 테이블 자체가 없다. 그래서 여기서 만든다.

**세 소스의 수치는 서로 더하거나 이어붙일 수 없다.** PubMed 는 MeSH 로 확장된 주제 매칭이라
'cosmetic' 이라는 단어가 없는 논문까지 닿고, Europe PMC 는 생명과학 색인에 프리프린트와
특허를 포함하며, Crossref 는 서지 필드만 본다. 2019-01 'cosmetic' 이 각각 1205 / 843 / 208
이었던 것은 논문 수에 대한 이견이 아니라 세 개의 다른 질문이다. 그래서 primary key 에
source 가 들어간다 — 한 테이블에 있어도 한 계열이 아니다.

색인 지연 때문에 최근 2~3개월은 항상 과소집계된다. 하락으로 읽으면 안 된다.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

DDL = """
create schema if not exists academic;

create table if not exists academic.paper_trend (
    source       text not null,
    query        text not null,
    period       date not null,
    count        int  not null check (count >= 0),
    collected_at timestamptz not null default now(),
    primary key (source, query, period)
);

comment on table academic.paper_trend is
  '월별 논문 수. source 가 다르면 다른 질문이므로 계열을 섞지 말 것. 최근 2~3개월은 색인 지연으로 과소집계.';
"""


def read_counts(path: Path) -> list[tuple[str, int]]:
    """`papers trend --csv` 산출물. period,count 두 컬럼."""
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "period" not in rows[0] or "count" not in rows[0]:
        raise SystemExit(f"{path}: period,count 컬럼이 아니다")
    return [(r["period"], int(r["count"])) for r in rows]


def period_to_date(period: str) -> date:
    """'2019-01' 또는 '2019' -> 월 첫날. 연 단위는 1월로 접는다."""
    parts = period.strip().split("-")
    year = int(parts[0])
    month = int(parts[1]) if len(parts) > 1 else 1
    return date(year, month, 1)


def load(dsn: str, files: list[tuple[str, str, Path]]) -> None:
    import psycopg

    # 아직 오지 않은 달은 0 으로 채워져 나온다. 그대로 넣으면 계열 끝이 붕괴처럼 보이는데
    # 붕괴가 아니라 미래다. 넣지 않고, 몇 개를 버렸는지 말한다.
    horizon = date.today().replace(day=1)

    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(DDL)
        total, dropped = 0, 0
        for source, query, path in files:
            rows = [(source, query, period_to_date(p), c) for p, c in read_counts(path)]
            before = len(rows)
            rows = [r for r in rows if r[2] <= horizon]
            dropped += before - len(rows)
            cursor.executemany(
                "insert into academic.paper_trend (source, query, period, count)"
                " values (%s, %s, %s, %s)"
                " on conflict (source, query, period) do update"
                " set count = excluded.count, collected_at = now()", rows)
            # 이전 실행이 심어 놓은 미래 월을 치운다. 넣지 않는 것만으로는 이미 들어간
            # 행이 남고, 그것이 계열 끝의 0 이 된다.
            cursor.execute(
                "delete from academic.paper_trend"
                " where source = %s and query = %s and period > %s",
                (source, query, horizon))
            total += len(rows)
            print(f"[측정] {source:<11} {query:<28} {len(rows):>4}개월")
        cursor.execute("select source, count(distinct query), count(*), min(period), max(period)"
                       " from academic.paper_trend group by source order by source")
        print()
        for source, queries, months, lo, hi in cursor.fetchall():
            print(f"[측정] {source:<11} 검색어 {queries:>3}  행 {months:>5}  {lo} ~ {hi}")
    # psycopg3 의 with 블록이 정상 종료 시 커밋한다. 여기서 또 부르면 닫힌 연결을 만진다.
    print()
    print(f"[측정] 적재 {total}행, 미래 월 {dropped}행 제외 ({horizon} 이후)")
    print("[측정 아님] 소스가 다르면 계열도 다르다. 합산·접합 금지.")


def _self_check() -> None:
    assert period_to_date("2019-01") == date(2019, 1, 1)
    assert period_to_date("2026-12") == date(2026, 12, 1)
    assert period_to_date("2020") == date(2020, 1, 1)
    print("self-check OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn")
    parser.add_argument("--file", action="append", default=[],
                        metavar="SOURCE:QUERY:PATH",
                        help="예: pubmed:cosmetic:papers_pubmed_2019_2026.csv")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0
    if not args.dsn or not args.file:
        parser.error("--dsn 과 --file, 또는 --self-check")

    files = []
    for spec in args.file:
        source, query, path = spec.split(":", 2)
        files.append((source, query, Path(path)))
    load(args.dsn, files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
