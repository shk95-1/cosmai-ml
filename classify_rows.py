"""무엇이 한 행인가 — SKU 인가 리스팅인가.

`EXP-004`/`EXP-005` 가 뭉갠 것은 세 가지다: 팔리는 물건 하나(SKU), 그 물건이 속한 제품
라인, 그리고 여러 SKU 를 한 페이지에 묶어 파는 리스팅. `product` 테이블은 이 셋을 구분
하지 않고 한 테이블에 담는다. oliveyoung 행의 3분의 1 가까이가 리스팅인데도 그렇다.

여기서 만드는 것은 엔티티 ID 가 아니다. 아직 엔티티가 풀리지 않았는데 ID 를 붙이면 풀리지
않은 것에 이름만 주는 꼴이다. 만드는 것은 그 앞 단계 두 가지다.

  row_kind(name)     이 행이 SKU 인가 리스팅인가
  variants_of(name)  리스팅이면 그 안에 열거된 변형들

이 둘이 있으면 매칭이 서로 다른 질문으로 갈라진다. SKU 대 SKU 는 동일성 질문이고, SKU 대
리스팅은 동일성이 아니라 포함 질문이며, 후자를 동일성으로 라벨링한 것이 `EXP-005` 가
`INCONCLUSIVE` 로 끝난 이유다.

`match_products.py` 의 `_PROMO` 는 이 표기들을 정규화 단계에서 지운다. 같은 지식을 반대로
쓴다 — 지우는 대신 읽는다.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

# 여러 SKU 를 한 행에 묶었다고 이름이 스스로 말하는 표기.
# 감사 F8 이 원래 정규식의 누락을 지적해 보수적으로 넓힌 것을 반영한다 — 역순 `단품/기획`,
# 공백 있는 `택 1`, 한국어 색상/호수 표기. 여전히 하한이다: 표기 없이 여러 변형을 파는
# 리스팅은 이름만으로 알 수 없다.
_LISTING = re.compile(
    r"[0-9]+\s*종"
    r"|[0-9]+\s*[Cc]olors?"
    r"|[0-9]+\s*가지"
    r"|[0-9]+\s*호"
    r"|기획\s*/\s*단품"
    r"|단품\s*/\s*기획"
    r"|기획\s*/\s*본품"
    r"|본품\s*/\s*기획"
    r"|택\s*[0-9]"
)

# 괄호를 열고 변형을 늘어놓는 형태. 구분자는 슬래시일 수도 쉼표일 수도 있다 —
# "(에센스/톤업)", "(어성초/수분초/마데카소사이드)", "(PDRN, 콜라겐, 세라놀, 비타, 씨켈프)".
#
# 닫는 괄호까지로 끊지 않고 뒤를 끝까지 본다. 실제 데이터에 "(블레미쉬(광채), 가지(보습),
# 티트리(진정)" 처럼 중첩되고 닫히지도 않은 것이 있어서, 균형 잡힌 괄호를 가정하면 놓친다.
# self-check 가 처음 실패한 케이스가 정확히 이것이었다.
#
# 두 항목은 열거로 보지 않는다. "(에센스/톤업)" 같은 것은 제형·용도 표기와 구별되지 않고,
# 세 항목부터는 사실상 선택지 목록이다.
_GROUP_OPEN = re.compile(r"[\(（]")
_MIN_ITEMS = 3


def variants_of(name: str) -> list[str]:
    """리스팅이 이름 안에 열거한 변형들. 열거가 없으면 빈 목록."""
    if not isinstance(name, str):
        return []
    for opening in _GROUP_OPEN.finditer(name):
        tail = re.split(r"[\)）]\s*$", name[opening.end():])[0]
        items = [part.strip(" ()（）") for part in re.split(r"[/,]", tail)]
        items = [item for item in items if item]
        if len(items) >= _MIN_ITEMS:
            return items
    return []


def row_kind(name: str) -> str:
    """`sku` 또는 `listing`.

    이름이 스스로 여러 변형을 판다고 말할 때만 리스팅이다. 말하지 않는 리스팅은 SKU 로
    분류되며, 그것이 이 함수의 알려진 한계다 — 거짓 음성은 있고 거짓 양성은 드물다.
    """
    if not isinstance(name, str):
        return "sku"
    if _LISTING.search(name) or variants_of(name):
        return "listing"
    return "sku"


def _self_check() -> None:
    listings = [
        "[NEW] 투에이엔 듀얼치크 20 colors (기획/단품)",
        "[72관왕/1위] 린제이 모델링 팩 (컵팩)  7종 택1",
        "바이오힐보 프로바이오덤 콜라겐 선크림 2종 (에센스/톤업)",
        "[10매/5종] 아비브 껌딱지 시트 마스크 스티커 10매 (어성초/수분초/마데카소사이드/콜라겐밀크/비타)",
        "파파레서피 효소 파우더 클렌저 50g (블레미쉬(광채), 가지(보습), 티트리(진정)",
    ]
    skus = [
        "다이브인 저분자 히알루론산 세럼",
        "[올영 어워즈 1등 크림] 에스트라 아토베리어365 크림 80ml",
        # 기획 구성이지만 파는 물건은 하나다 — 리스팅이 아니라 번들 SKU 다.
        "[NEW] 토리든 다이브인 저분자 히알루론산 세럼 50ml 기획 (+멀티 패드 10매)",
        "헤라 블랙 쿠션 파운데이션 리필 15g",
    ]
    for name in listings:
        assert row_kind(name) == "listing", f"listing 으로 잡혀야 함: {name}"
    for name in skus:
        assert row_kind(name) == "sku", f"sku 로 잡혀야 함: {name}"

    # 파파레서피 행은 슬래시 열거가 괄호 중첩 안에 있어 균형 잡힌 괄호를 가정하면 놓치지만
    # `50g (` 뒤 세 항목을 다른 경로로 잡는다. 실제로 무엇이 잡았는지 확인한다.
    assert variants_of("바이오힐보 콜라겐 선크림 2종 (에센스/톤업)") == []  # 두 항목은 열거 아님
    assert len(variants_of("아비브 스티커 (어성초/수분초/마데카소사이드/콜라겐밀크/비타)")) == 5
    print("self-check OK")


def _load_product(cursor) -> list[tuple[str, str, str]]:
    cursor.execute("select source, product_key, name from product")
    return cursor.fetchall()


def apply_schema(connection, label_csv: str | None) -> None:
    """DDL 을 적용하고 `product` 를 sku / listing 으로 분할한다.

    멱등이다. 파생 테이블만 지우고 다시 채우므로 몇 번 돌려도 같은 상태가 된다.
    `product` 는 읽기만 한다.
    """
    ddl = (Path(__file__).resolve().parent / "schema_split.sql").read_text(encoding="utf-8")
    with connection.cursor() as cursor:
        cursor.execute(ddl)
        rows = _load_product(cursor)

        # 파생 테이블이므로 매번 새로 만든다. cascade 로 variant / contains 도 함께 간다.
        cursor.execute("truncate entity.sku, entity.listing cascade")

        skus, listings, variants = [], [], []
        for source, key, name in rows:
            if row_kind(name) == "listing":
                listings.append((source, key, name))
                for index, variant in enumerate(variants_of(name)):
                    variants.append((source, key, index, variant))
            else:
                skus.append((source, key, name))

        cursor.executemany(
            "insert into entity.sku (source, product_key, name) values (%s, %s, %s)", skus)
        cursor.executemany(
            "insert into entity.listing (source, product_key, name) values (%s, %s, %s)",
            listings)
        cursor.executemany(
            "insert into entity.listing_variant (source, product_key, position, variant)"
            " values (%s, %s, %s, %s)", variants)

        contained = _seed_contains(cursor, label_csv) if label_csv else 0
        _check_invariants(cursor, len(rows))

    connection.commit()
    print(f"[측정] sku {len(skus)}  listing {len(listings)}  "
          f"listing_variant {len(variants)}  listing_contains {contained}")
    print("[측정] entity.product_line 0행, entity.sku.product_line_id 전부 null — 의도적이다.")


def _seed_contains(cursor, label_csv: str) -> int:
    """`EXP-005` 라인 라벨에서 포함 관계만 뽑아 넣는다.

    라인 라벨은 동일성과 포함을 한 컬럼에 합쳐 놓았다. 한쪽이 리스팅이고 다른 쪽이 SKU 인
    `y` 쌍은 포함 주장이지 동일성 주장이 아니므로, 여기로 옮기면 동일성 그래프에서 빠진다.
    이것이 `EXP-005` 를 `INCONCLUSIVE` 로 만든 오염을 실제로 걷어내는 조작이다.

    provenance 를 붙이는 이유: 이 라벨은 모델이 만들었고 사람 검증이 0건이다.
    """
    import csv

    seeded = []
    with open(label_csv, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("is_same_product") != "y":
                continue
            a = (row["source_a"], row["key_a"], row["name_a"])
            b = (row["source_b"], row["key_b"], row["name_b"])
            kinds = (row_kind(a[2]), row_kind(b[2]))
            if kinds == ("listing", "sku"):
                seeded.append((a[0], a[1], b[0], b[1]))
            elif kinds == ("sku", "listing"):
                seeded.append((b[0], b[1], a[0], a[1]))

    cursor.executemany(
        "insert into entity.listing_contains"
        " (listing_source, listing_key, sku_source, sku_key, provenance)"
        " values (%s, %s, %s, %s, 'exp005-line-label-model-generated')"
        " on conflict do nothing", seeded)
    return cursor.rowcount if cursor.rowcount >= 0 else len(seeded)


def _check_invariants(cursor, product_rows: int) -> None:
    """분할이 실제로 분할인지 확인한다. 틀리면 커밋하지 않는다."""
    cursor.execute("select (select count(*) from entity.sku),"
                   " (select count(*) from entity.listing)")
    skus, listings = cursor.fetchone()
    if skus + listings != product_rows:
        raise SystemExit(f"[실패] 분할이 원본과 다르다: {skus}+{listings} != {product_rows}")

    cursor.execute("select count(*) from entity.sku s"
                   " join entity.listing l using (source, product_key)")
    if cursor.fetchone()[0]:
        raise SystemExit("[실패] 양쪽에 동시에 있는 행이 있다")

    cursor.execute("select count(*) from entity.sku where product_line_id is not null")
    if cursor.fetchone()[0]:
        raise SystemExit("[실패] product_line_id 가 채워졌다 — 매처 정밀도가 이를 허락하지 않는다")

    print(f"[측정] 불변식 통과 — sku {skus} + listing {listings} = product {product_rows}, "
          "교집합 0, product_line_id 전부 null")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn")
    parser.add_argument("--apply", action="store_true",
                        help="DDL 적용 후 product 를 sku/listing 으로 분할해 채운다")
    parser.add_argument("--labels", help="--apply 와 함께: listing_contains 를 채울 라인 라벨 CSV")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0
    if not args.dsn:
        parser.error("--dsn 또는 --self-check")

    import psycopg

    with psycopg.connect(args.dsn) as connection:
        if args.apply:
            apply_schema(connection, args.labels)
            return 0
        with connection.cursor() as cursor:
            rows = _load_product(cursor)

    kinds = Counter()
    per_source: dict[str, Counter] = {}
    variant_counts = []
    for source, _key, name in rows:
        kind = row_kind(name)
        kinds[kind] += 1
        per_source.setdefault(source, Counter())[kind] += 1
        if kind == "listing":
            found = variants_of(name)
            if found:
                variant_counts.append(len(found))

    print(f"[측정] product 행 {len(rows)}개")
    print(f"  sku {kinds['sku']}   listing {kinds['listing']} "
          f"({kinds['listing'] / len(rows):.1%})")
    print()
    print(f"{'소스':<12}{'행':>7}{'sku':>7}{'listing':>9}{'listing 비율':>13}")
    for source in sorted(per_source, key=lambda s: -sum(per_source[s].values())):
        counter = per_source[source]
        total = sum(counter.values())
        print(f"{source:<12}{total:>7}{counter['sku']:>7}{counter['listing']:>9}"
              f"{counter['listing'] / total:>12.1%}")

    if variant_counts:
        print(f"\n[측정] 변형을 이름에 열거한 리스팅 {len(variant_counts)}건, "
              f"평균 {sum(variant_counts) / len(variant_counts):.1f}개 열거")

    print("\n[측정 아님] 이름이 스스로 말하지 않는 리스팅은 sku 로 분류된다. 이 수치는 하한이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
