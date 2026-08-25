"""`academic.paper_trend` 를 CSV 로 내보낸다 — 통합 DB 쓰기 권한을 기다리지 않기 위해.

논문 축은 시현님 성분별 3소스 대조표(논문 수 x 처방 채택률 x 담론 언급)에서 비어 있던
칸이다. 통합 DB 에 넣으려면 shk 님 승인과 계정이 필요한데 둘 다 시간이 걸린다. 그동안
데이터가 내 DGX 에만 있으면 아무도 못 쓴다.

그래서 저장소에 CSV 로 둔다. 팀 전원이 org read 권한을 가지므로 clone 하면 바로 쓴다.
나중에 통합 DB 로 옮겨도 이 파일은 그대로 재현 가능한 스냅샷으로 남는다.

두 파일을 낸다.

  paper_trend.csv    긴 형태. source,query,period,count — 계열 그대로.
  paper_growth.csv   넓은 형태. 성분별 2019 대비 최근 12개월 배수. 대조표에 바로 붙는다.

**source 를 컬럼으로 남긴다.** PubMed 와 Europe PMC 는 세는 대상이 달라 합치거나
이어붙일 수 없다. 넓은 형태에서도 소스별로 행을 나누는 이유다.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

LONG = ("select source, query, period, count from academic.paper_trend"
        " order by source, query, period")

WIDE = ("select source, query,"
        " round(avg(count) filter (where period between date '2019-01-01'"
        "   and date '2019-12-01')::numeric, 2) as avg_2019,"
        " round(avg(count) filter (where period between date '2025-07-01'"
        "   and date '2026-06-01')::numeric, 2) as avg_recent,"
        " min(period) as first_month, max(period) as last_month,"
        " count(*) as months"
        " from academic.paper_trend group by source, query"
        " order by source, 4 desc nulls last")

HEADER = """# academic.paper_trend — 화장품 성분·주제별 월간 논문 수
#
# 소스가 다르면 세는 대상이 다르다. 절대값을 합치거나 이어붙이지 말 것.
#   PubMed      MeSH 확장 주제매칭. 'cosmetic' 이라는 단어가 없는 논문까지 닿는다.
#   Europe PMC  생명과학 색인. 프리프린트와 특허를 포함한다.
# 2019-01 'cosmetic' 이 각각 1205 / 843 인 것은 이견이 아니라 두 개의 다른 질문이다.
#
# 최근 2~3개월은 색인 지연으로 항상 과소집계된다. 하락으로 읽지 말 것.
# 절대 건수가 한 자릿수인 검색어(ethylhexyl triazone 등)는 배수를 쓰면 안 된다 —
# 연 논문 두세 편 차이가 3배로 보인다.
#
# PubMed 1월은 나머지 달의 1.65~2.40배다. 측정한 10개 검색어 전부에서 예외 없이 그렇고,
# Europe PMC 는 1.16배로 훨씬 약하다. 모든 성분이 같은 방향으로 튀므로 성분 얘기가 아니라
# 연초 게재일 몰림에 따른 색인 아티팩트다. 연 단위 비교(paper_growth)는 1월을 양쪽이 한
# 번씩 포함하므로 안전하고, 월별 계열(paper_trend)을 그리면 매년 1월에 봉우리가 선다.
"""


def write(path: Path, rows: list[dict], comment: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(comment)
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"[측정] {path.name:<20}{len(rows):>6}행")


def export(dsn: str, out: Path) -> None:
    import psycopg

    out.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute("set transaction read only")
        for query, name in ((LONG, "paper_trend.csv"), (WIDE, "paper_growth.csv")):
            cursor.execute(query)
            columns = [d.name for d in cursor.description]
            rows = [dict(zip(columns, r)) for r in cursor.fetchall()]
            if not rows:
                raise SystemExit(f"[실패] {name}: 행이 없다")
            if name == "paper_growth.csv":
                for row in rows:
                    early, recent = row["avg_2019"], row["avg_recent"]
                    row["growth"] = (round(float(recent) / float(early), 2)
                                     if early and recent else None)
                    # 배수를 쓸 수 있는지 여기서 판정해 둔다. 읽는 쪽이 매번 판단하게
                    # 두면 언젠가 월 0.2편짜리 3.67배가 표에 실린다.
                    row["ratio_usable"] = bool(early and float(early) >= 5)
            write(out / name, rows, HEADER)

    print(f"\n[측정 아님] 소스별로 계열이 다르다. paper_growth 의 배수는 같은 source "
          "안에서만 비교 가능하고, ratio_usable=False 인 행은 배수를 인용하지 말 것.")


def _self_check() -> None:
    """배수 판정 규칙만 검사한다. DB 는 건드리지 않는다."""
    cases = [(881.4, 978.7, True), (0.2, 0.9, False), (2.2, 4.5, False), (7.9, 19.4, True)]
    for early, _recent, usable in cases:
        assert bool(early and early >= 5) is usable, early
    print("self-check OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn")
    parser.add_argument("--out", default="datasets/papers")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0
    if not args.dsn:
        parser.error("--dsn 또는 --self-check")
    export(args.dsn, Path(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
