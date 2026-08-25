"""COSMAI 질의 GUI — Claude 가 계산하지 않고, 조회한 숫자를 읽는다.

## 왜 벡터 DB 가 아닌가

우리 데이터는 대부분 숫자 표다 — 월별 논문 수, 시간별 순위, 가격, 판매량. 벡터 검색은
비슷해 보이는 텍스트 조각을 가져올 뿐 세지 않는다. "레티놀 논문 늘었어?" 에 대해 레티놀이
언급된 조각을 반환하는 것과 실제로 세는 것은 다르고, 후자만 답이다.

그래서 질문마다 쿼리를 고정해 도구로 노출한다. Claude 는 **어느 도구를 부를지** 만 정하고
숫자는 Postgres 가 만든다. 자유 SQL 생성도 아니다 — 생성된 SQL 은 검증할 수 없고,
읽기 전용 계정이어도 틀린 조인은 틀린 답을 낸다.

리뷰 본문만 텍스트라서 거기만 검색을 쓴다. 15,817행이라 ILIKE 로 충분하다.

## 모든 응답에 근거가 붙는다

도구는 행만 주지 않고 `provenance` 를 함께 준다 — 어느 테이블, 몇 행, 언제 조회, 무슨 한계.
시스템 프롬프트가 그것을 답변에 싣도록 강제한다. 이 프로젝트는 감사를 두 번 맞으면서
"근거보다 자신감이 앞서는" 실패를 계속 잡아냈고, 그 교훈이 화면에 보이는 형태다.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg
from anthropic import Anthropic, beta_tool

DSN = os.environ.get(
    "COSMAI_DSN", "postgresql://trend_radar:trend_radar@localhost:5432/cosmai_integrated")
MODEL = os.environ.get("COSMAI_MODEL", "claude-sonnet-5")
PORT = int(os.environ.get("COSMAI_PORT", "8800"))
MAX_ROWS = 40


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    """읽기 전용 조회. 트랜잭션을 read only 로 못박아 도구가 쓰기를 할 수 없게 한다."""
    with psycopg.connect(DSN) as connection, connection.cursor() as cursor:
        cursor.execute("set transaction read only")
        cursor.execute(sql, params)
        columns = [d.name for d in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchmany(MAX_ROWS)]


def _pack(rows: list[dict], table: str, note: str = "") -> str:
    """행 + 출처. Claude 가 답변에 그대로 실을 수 있는 형태로 준다."""
    payload = {
        "rows": rows,
        "provenance": {"table": table, "returned": len(rows),
                       "queried_at": datetime.now().isoformat(timespec="seconds")},
    }
    if note:
        payload["provenance"]["caveat"] = note
    return json.dumps(payload, ensure_ascii=False, default=str)


# ---------------------------------------------------------------- 도구 8개

@beta_tool
def paper_trend(query: str, source: str = "pubmed", months: int = 24) -> str:
    """성분·주제별 월간 논문 수를 반환한다. 학계동향 축의 원자료.

    Args:
        query: 검색어. 수집된 값은 cosmetic, retinol, niacinamide, hyaluronic acid,
            ceramide, collagen, ascorbic acid, salicylic acid, centella asiatica,
            panthenol, tranexamic acid, polydeoxyribonucleotide 뿐이다.
        source: pubmed 또는 europepmc. 두 소스의 절대값은 서로 비교·합산할 수 없다.
        months: 최근 몇 개월. 최대 92.
    """
    rows = _rows(
        "select period, count from academic.paper_trend"
        " where source = %s and query = %s order by period desc limit %s",
        (source, query, min(months, 92)))
    return _pack(list(reversed(rows)), "academic.paper_trend",
                 "소스가 다르면 세는 대상이 다르다. PubMed 는 MeSH 확장 주제매칭, "
                 "Europe PMC 는 프리프린트·특허 포함 생명과학 색인. 절대값 비교·합산 금지. "
                 "최근 2~3개월은 색인 지연으로 과소집계이므로 하락으로 읽지 말 것. "
                 "**PubMed 는 1월이 나머지 달의 1.65~2.40배다** — 측정한 10개 검색어 전부에서, "
                 "예외 없이. 모든 성분이 같은 방향으로 튀므로 성분 얘기가 아니라 연초 게재일 "
                 "몰림에 따른 색인 아티팩트다(Europe PMC 는 1.16배로 훨씬 약하다). 1월 봉우리를 "
                 "관심 폭증으로 읽지 말 것. 연 단위 비교는 1월을 양쪽이 한 번씩 포함하므로 "
                 "안전하지만, 월별 추세나 3개월 이동평균은 12~2월 구간이 부풀려진다.")


@beta_tool
def paper_growth(source: str = "pubmed") -> str:
    """수집된 모든 검색어의 2019년 대비 최근 12개월 증가 배수. 어느 성분이 뜨는지.

    Args:
        source: pubmed 또는 europepmc.
    """
    rows = _rows(
        "select query,"
        " round(avg(count) filter (where period between date '2019-01-01'"
        "   and date '2019-12-01')::numeric, 1) as avg_2019,"
        " round(avg(count) filter (where period between date '2025-07-01'"
        "   and date '2026-06-01')::numeric, 1) as avg_recent"
        " from academic.paper_trend where source = %s group by query"
        " order by 3 desc nulls last", (source,))
    for row in rows:
        early, recent = row.get("avg_2019"), row.get("avg_recent")
        row["growth"] = round(float(recent) / float(early), 2) if early and recent else None
    return _pack(rows, "academic.paper_trend",
                 "배수는 같은 소스 안에서만 비교 가능하다. 두 소스에서 방향이 엇갈리는 "
                 "검색어는 색인 차이를 뜻하므로 한쪽만 보고 결론 내지 말 것.")


@beta_tool
def top_products(source: str = "oliveyoung", board: str = "", limit: int = 15) -> str:
    """가장 최근 순위 스냅샷의 상위 제품.

    한 소스는 보드를 여러 개 가진다(연령별·피부별·카테고리별·세일 등). board 를 비우면
    여러 보드가 섞여 나오므로 "통합 N위" 가 아니다. 순위를 순위로 읽으려면 보드를 지정하라.
    어떤 보드가 있는지는 board="?" 로 물으면 목록만 돌려준다.

    Args:
        source: oliveyoung, daisomall, glowpick, hwahae 중 하나.
        board: 보드 이름. 비우면 섞인다. "?" 면 사용 가능한 보드 목록만 반환한다.
        limit: 몇 개. 최대 40.
    """
    if board == "?":
        rows = _rows(
            "select board, count(distinct category_key) as categories,"
            " max(rank) as deepest, count(*) as rows"
            " from rank_snapshot where source = %s and captured_at ="
            " (select max(captured_at) from rank_snapshot where source = %s)"
            " group by board order by rows desc", (source, source))
        return _pack(rows, "rank_snapshot",
                     "보드마다 관측 깊이가 다르다. 보드를 지정하지 않고 뽑은 상위 N개는 "
                     "여러 보드가 섞인 것이지 통합 순위가 아니다.")

    want = min(limit, MAX_ROWS)
    # distinct on 은 지금 아무것도 지우지 않는다 — 173,007행에서 완전 중복 0건을
    # 측정했고 shk 원본도 같다. 그래도 두는 이유는 두 가지다. 하나, 같은 순위에 두
    # 행이 생기면 limit 이 조용히 진짜 순위를 밀어낸다. 둘, 결과가 결정적이 된다.
    where = " and board = %s" if board else ""
    args: tuple = (source, source) + ((board,) if board else ())
    rows = _rows(
        "select distinct on (rank, product_key)"
        " rank, product_name, brand, price, discount_rate, review_count,"
        " review_rating, rank_delta, is_new, board, category_name, captured_at"
        " from rank_snapshot where source = %s and captured_at ="
        " (select max(captured_at) from rank_snapshot where source = %s)" + where +
        " order by rank, product_key, captured_at desc limit %s", args + (want,))

    # 관측 깊이. 얕은 스냅샷에 없는 제품을 그대로 읽으면 "이탈"이나 "급락"이 된다 —
    # 유튜브 파트에서 채널당 상한 10편이 트렌드로 보였던 것과 같은 종류다. 걸러내는
    # 대신 깊이를 답변에 실어, 관측하지 않은 순위를 말할 수 없게 한다.
    depth = _rows(
        "select max(rank) as deepest, count(distinct board) as boards"
        " from rank_snapshot where source = %s and captured_at ="
        " (select max(captured_at) from rank_snapshot where source = %s)" + where, args)
    deepest = (depth[0]["deepest"] if depth else None) or 0
    boards = (depth[0]["boards"] if depth else None) or 0

    note = ("hwahae 는 robots 제한으로 각 보드의 50~100행 중 약 10행만 보인다 — "
            "관측된 순위 분포의 꼬리가 인위적으로 짧다. "
            "다변형 리스팅의 순위는 리스팅의 순위이지 그 안 개별 변형의 순위가 아니다. "
            f"이 스냅샷이 관측한 최하위 순위는 {deepest}위다.")
    if not board and boards > 1:
        note += (f" **board 를 지정하지 않아 {boards}개 보드가 섞여 있다.** 반환된 행은"
                 " 통합 순위가 아니라 보드마다 1위부터 다시 시작하는 순위들이므로,"
                 " 'N위' 라고 말하려면 board 를 지정해 다시 물어야 한다."
                 ' 보드 목록은 board="?" 로 확인한다.')
    if deepest and deepest < want:
        note += (f" 요청한 {want}위까지 관측되지 않았으므로 그 아래를 '이탈'이나 "
                 "'순위 없음'으로 읽어서는 안 된다.")
    return _pack(rows, "rank_snapshot", note)


@beta_tool
def price_history(name_contains: str, days: int = 30) -> str:
    """제품명으로 찾아 최근 가격·할인율 변화를 반환한다.

    Args:
        name_contains: 제품명 일부. 한국어 그대로.
        days: 최근 며칠. 최대 90.
    """
    rows = _rows(
        "select p.name, pp.captured_at, pp.price, pp.discount_rate"
        " from price_point pp join product p"
        "   on p.source = pp.source and p.product_key = pp.product_key"
        " where p.name ilike %s"
        "   and pp.captured_at > now() - (%s || ' days')::interval"
        " order by pp.captured_at desc limit %s",
        (f"%{name_contains}%", min(days, 90), MAX_ROWS))
    return _pack(rows, "price_point join product",
                 "수집 시작이 2026-08-20 이라 그 이전 가격은 존재하지 않는다.")


@beta_tool
def new_products(days: int = 14, source: str = "") -> str:
    """최근 새로 등장한 제품.

    Args:
        days: 최근 며칠. 최대 90.
        source: 비우면 전체. daisomall, glowpick 에만 데이터가 있다.
    """
    clause = " and source = %s" if source else ""
    params: tuple = (min(days, 90),) + ((source,) if source else ())
    rows = _rows(
        "select source, name, brand, listed_at, captured_at from new_product"
        " where captured_at > now() - (%s || ' days')::interval" + clause +
        " order by captured_at desc limit 40", params)
    return _pack(rows, "new_product",
                 "oliveyoung 과 hwahae 는 이 lane 이 비어 있다. 신제품 0건은 "
                 "'신제품이 없다' 가 아니라 '그 소스는 신제품을 수집하지 않는다' 일 수 있다.")


@beta_tool
def review_topics(name_contains: str) -> str:
    """제품에 대해 사람들이 실제로 언급한 토픽과 그 감성. 이미 추출되어 있다.

    Args:
        name_contains: 제품명 일부.
    """
    rows = _rows(
        "select p.name, rt.topic_name, rt.is_positive, rt.share_pct,"
        " rt.review_count, rt.sentence"
        " from review_topic rt join product p"
        "   on p.source = rt.source and p.product_key = rt.product_key"
        " where p.name ilike %s order by rt.share_pct desc nulls last limit %s",
        (f"%{name_contains}%", MAX_ROWS))
    return _pack(rows, "review_topic join product",
                 "리뷰는 상위 랭크 제품 위주로만 수집된다. 인기 제품을 설명할 뿐 "
                 "시장 전체를 설명하지 않는다.")


@beta_tool
def search_reviews(keyword: str, limit: int = 12) -> str:
    """리뷰 본문에서 키워드를 찾는다. 이 도구만 자유 텍스트를 다룬다.

    Args:
        keyword: 찾을 말. 한국어 그대로.
        limit: 몇 건. 최대 40.
    """
    rows = _rows(
        "select p.name, r.rating, r.written_at, left(r.body, 300) as body"
        " from review r join product p"
        "   on p.source = r.source and p.product_key = r.product_key"
        " where r.body ilike %s order by r.written_at desc nulls last limit %s",
        (f"%{keyword}%", min(limit, MAX_ROWS)))
    return _pack(rows, "review join product",
                 "본문 300자까지만 반환한다. 리뷰 수집은 상위 랭크 제품 편향이 있다.")


@beta_tool
def data_status() -> str:
    """지금 무슨 데이터를 얼마나 가지고 있는지. 없는 것도 말한다."""
    rows = _rows(
        "select 'product' as t, count(*) as n, min(first_seen_at)::date as lo,"
        " max(last_seen_at)::date as hi from product"
        " union all select 'rank_snapshot', count(*), min(captured_at)::date,"
        " max(captured_at)::date from rank_snapshot"
        " union all select 'price_point', count(*), min(captured_at)::date,"
        " max(captured_at)::date from price_point"
        " union all select 'review', count(*), min(written_at)::date,"
        " max(written_at)::date from review"
        " union all select 'new_product', count(*), min(captured_at)::date,"
        " max(captured_at)::date from new_product"
        " union all select 'academic.paper_trend', count(*), min(period),"
        " max(period) from academic.paper_trend"
        " union all select 'entity.sku', count(*), null, null from entity.sku"
        " union all select 'entity.listing', count(*), null, null from entity.listing")
    return _pack(rows, "여러 테이블",
                 "네이버와 SNS 는 수집기가 없어 0건이다. entity.product_line 은 "
                 "의도적으로 비어 있다 — 매처 정밀도가 상위 구간 38.2% 라 라인 ID 를 "
                 "부여하면 서로 다른 제품이 되돌릴 수 없게 합쳐진다.")


TOOLS = [paper_trend, paper_growth, top_products, price_history,
         new_products, review_topics, search_reviews, data_status]

SYSTEM = """당신은 COSMAI 화장품 트렌드 데이터에 답하는 도우미다. 한국어로 답한다.

## 절대 규칙

1. **숫자를 직접 만들지 마라.** 모든 수치는 도구 호출 결과에서만 나온다. 추세·평균·비율을
   머릿속으로 계산하지 말고, 도구가 준 값을 읽어라. 도구에 없는 숫자는 "측정하지 않았다"
   라고 말하라.
2. **모든 답에 근거를 붙여라.** 도구 결과의 provenance 를 답변 끝에 그대로 싣는다 —
   어느 테이블, 몇 행, 무슨 한계. 한계(caveat)를 생략하지 마라. 그것이 이 시스템의 핵심이다.
3. **모르면 모른다고 하라.** 데이터가 없으면 없다고 말한다. 그럴듯한 추측은 이 프로젝트가
   가장 경계하는 실패다.
4. 도구로 답할 수 없는 질문이면 data_status 를 불러 무엇이 있고 없는지 보여주고,
   답할 수 없는 이유를 말하라.

## 알아 둘 것

- 수집은 2026-08-20 에 시작했다. 그 이전의 순위·가격·리뷰·신제품은 존재하지 않는다.
  논문(2019-01~)과 판매량(2019-01~2025-06)만 과거가 있다.
- 네 소스뿐이다: oliveyoung, daisomall, glowpick, hwahae. 네이버·SNS·유튜브는 없다.
- 수집기 고장과 시장 침체는 데이터에서 똑같이 0으로 보인다. 0을 발견하면 그 가능성을 말하라.
- 논문 소스 둘(PubMed / Europe PMC)의 절대값은 절대 합치거나 비교하지 마라. 세는 대상이 다르다.
"""


# ---------------------------------------------------------------- 예산 하드스톱
#
# 이 앱은 tailnet 에 공개돼 있고 질문 한 번이 API 호출을 여러 번 만든다(도구 왕복마다
# 대화 전체가 다시 올라간다). 상한이 없으면 데모 중 누가 반복 질문하는 것만으로 청구가
# 열려 있다.
#
# 설계는 `cosmai` 의 analysis/polarity/pricing.py 를 그대로 따른다. 팀에 패턴이 둘이면
# 안 되고, 그 설계가 맞다:
#   - 차단은 호출 *전*이다. 호출 후에 세면 이미 나간 돈은 돌아오지 않는다.
#   - reserve() 가 한 트랜잭션에서 잠그고·읽고·견적 행을 쓰고 커밋한다. 그 뒤 응답이
#     오지 않아도(타임아웃·예외) 예약분은 원장에 남는다.
#   - settle() 은 그 행을 실측으로 **덮어쓴다**. 새 행을 더하면 이중 계상이 된다.
#   - 잠금이 없으면 두 요청이 같은 잔액을 읽고 둘 다 통과한다. ThreadingHTTPServer 라
#     동시 요청이 실제로 생긴다.
#
# 단가는 `cosmai` analysis/polarity/pricing.py 에서 가져왔다(석현님이 2026-08-24 에
# claude-api 스킬을 읽어 기록한 값). 내가 독립적으로 확인하지 못했으므로 새로 만들지
# 않는다 — 팀이 서로 다른 두 숫자를 갖는 것보다 같은 숫자를 갖는 편이 낫다.
BUDGET_USD = Decimal(os.environ.get("COSMAI_BUDGET_USD", "10.00"))
PRICE_IN = Decimal("3.00") / 1_000_000    # claude-sonnet-5, $/토큰
PRICE_OUT = Decimal("15.00") / 1_000_000
PRICE_CACHE_READ = PRICE_IN / 10
PRICE_CACHE_WRITE = PRICE_IN * Decimal("1.25")

# 요청 하나의 비관적 견적. 실제로는 이보다 훨씬 싸지만, 견적이 낮으면 상한을 넘긴 뒤에야
# 막힌다. 넘치게 잡고 settle 에서 되돌린다.
ESTIMATE_USD = Decimal("0.15")

LEDGER_DDL = """
create schema if not exists app;
create table if not exists app.llm_usage (
    id            bigserial primary key,
    called_at     timestamptz not null default now(),
    model         text not null,
    purpose       text not null,
    input_tokens  int not null default 0,
    output_tokens int not null default 0,
    cache_read    int not null default 0,
    cache_write   int not null default 0,
    usd           numeric not null default 0,
    settled       boolean not null default false
);
create index if not exists llm_usage_called_at_idx on app.llm_usage (called_at);
"""

LOCK_KEY = 0x0C05_A1_01   # 이 원장 전용. 다른 무엇과도 겹치지 않게 상수로 고정한다.


class BudgetExceeded(RuntimeError):
    """하드스톱. 이 예외가 던져진 시점에 그 호출은 아직 나가지 않았다."""


def cost_of(input_tokens: int, output_tokens: int, cache_read: int, cache_write: int) -> Decimal:
    return (PRICE_IN * input_tokens + PRICE_OUT * output_tokens
            + PRICE_CACHE_READ * cache_read + PRICE_CACHE_WRITE * cache_write)


def reserve(purpose: str) -> int:
    """잠그고·읽고·견적을 남긴다. 상한을 넘으면 호출 전에 막는다."""
    import psycopg

    with psycopg.connect(DSN) as connection, connection.cursor() as cursor:
        cursor.execute(LEDGER_DDL)
        cursor.execute("select pg_advisory_xact_lock(%s)", (LOCK_KEY,))
        cursor.execute("select coalesce(sum(usd), 0) from app.llm_usage")
        spent = Decimal(cursor.fetchone()[0])
        if spent + ESTIMATE_USD > BUDGET_USD:
            raise BudgetExceeded(
                f"예산 하드스톱: 누적 ${spent:.4f} + 견적 ${ESTIMATE_USD} > 상한 ${BUDGET_USD}. "
                "호출하지 않았습니다. COSMAI_BUDGET_USD 로 상한을 올릴 수 있습니다.")
        cursor.execute(
            "insert into app.llm_usage (model, purpose, usd) values (%s, %s, %s) returning id",
            (MODEL, purpose, ESTIMATE_USD))
        return cursor.fetchone()[0]


def settle(row_id: int, totals: dict[str, int]) -> None:
    """견적 행을 실측으로 덮어쓴다. 더하지 않는다 — 더하면 이중 계상이다."""
    import psycopg

    usd = cost_of(totals["input"], totals["output"], totals["cache_read"], totals["cache_write"])
    with psycopg.connect(DSN) as connection, connection.cursor() as cursor:
        cursor.execute(
            "update app.llm_usage set input_tokens = %s, output_tokens = %s,"
            " cache_read = %s, cache_write = %s, usd = %s, settled = true where id = %s",
            (totals["input"], totals["output"], totals["cache_read"],
             totals["cache_write"], usd, row_id))


def ask(question: str) -> str:
    row_id = reserve("gui:ask")           # 넘치면 여기서 끝난다. API 는 아직 안 불렀다.
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    try:
        client = Anthropic()
        runner = client.beta.messages.tool_runner(
            model=MODEL,
            max_tokens=8000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},  # 도구 고르기는 어려운 판단이 아니다. 속도 우선.
            tools=TOOLS,
            messages=[{"role": "user", "content": question}],
        )
        last = None
        for message in runner:
            last = message
            # 도구 왕복마다 대화 전체가 다시 올라가므로 usage 는 메시지마다 누적한다.
            usage = getattr(message, "usage", None)
            if usage is not None:
                totals["input"] += getattr(usage, "input_tokens", 0) or 0
                totals["output"] += getattr(usage, "output_tokens", 0) or 0
                totals["cache_read"] += getattr(usage, "cache_read_input_tokens", 0) or 0
                totals["cache_write"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
    finally:
        # 예외가 나도 정산한다. 안 하면 견적이 원장에 남아 잔액을 과하게 깎는다.
        settle(row_id, totals)

    if last is None:
        return "응답이 없습니다."
    return "\n".join(b.text for b in last.content if b.type == "text").strip() or "(빈 응답)"


PAGE = """<!doctype html><html lang=ko><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>COSMAI</title><style>
*{box-sizing:border-box}
body{margin:0;font:15px/1.7 -apple-system,'Segoe UI','Malgun Gothic',sans-serif;
background:#f6f6f4;color:#1a1a18}
header{padding:18px 20px;background:#fff;border-bottom:1px solid #e2e2dd}
h1{margin:0;font-size:17px;letter-spacing:-.2px}
header p{margin:4px 0 0;font-size:12.5px;color:#8a8a80}
main{max-width:780px;margin:0 auto;padding:20px}
.msg{margin:0 0 14px;padding:13px 16px;border-radius:10px;white-space:pre-wrap;
word-break:break-word}
.q{background:#1a1a18;color:#fff;margin-left:auto;max-width:80%}
.a{background:#fff;border:1px solid #e2e2dd}
.err{background:#fff4f4;border:1px solid #f0c9c9;color:#a33}
form{display:flex;gap:8px;position:sticky;bottom:0;padding:14px 0;background:#f6f6f4}
input{flex:1;padding:12px 14px;border:1px solid #d5d5cd;border-radius:9px;font:inherit;
background:#fff}
button{padding:12px 20px;border:0;border-radius:9px;background:#1a1a18;color:#fff;
font:inherit;cursor:pointer}
button:disabled{opacity:.4;cursor:default}
.ex{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:16px}
.ex b{padding:6px 11px;background:#fff;border:1px solid #e2e2dd;border-radius:20px;
font-weight:400;font-size:13px;cursor:pointer;color:#55554e}
</style>
<header><h1>COSMAI 데이터 질의</h1>
<p>숫자는 Postgres 가 만들고 모델은 읽기만 합니다. 모든 답에 출처와 한계가 붙습니다.</p></header>
<main>
<div class=ex>
<b>지금 데이터 뭐가 있어?</b><b>어떤 성분 논문이 제일 빨리 늘어?</b>
<b>올리브영 지금 1위가 뭐야?</b><b>PDRN 논문 추세 보여줘</b>
<b>세라마이드 리뷰에서 사람들이 뭐라고 해?</b>
</div>
<div id=log></div>
<form id=f><input id=q autocomplete=off placeholder="질문을 입력하세요" required>
<button id=b>질문</button></form>
</main><script>
const log=document.getElementById('log'),f=document.getElementById('f'),
      q=document.getElementById('q'),b=document.getElementById('b');
document.querySelectorAll('.ex b').forEach(e=>e.onclick=()=>{q.value=e.textContent;f.requestSubmit()});
function add(t,c){const d=document.createElement('div');d.className='msg '+c;d.textContent=t;
log.append(d);d.scrollIntoView({block:'end'});return d}
f.onsubmit=async e=>{e.preventDefault();const text=q.value.trim();if(!text)return;
 q.value='';b.disabled=true;add(text,'q');const w=add('조회 중...','a');
 try{const r=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({q:text})});const j=await r.json();
  w.textContent=j.answer||j.error;if(j.error)w.className='msg err';}
 catch(err){w.textContent=String(err);w.className='msg err';}
 finally{b.disabled=false;q.focus();}};
</script></html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if self.path != "/ask":
            self._send(404, b"not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            question = json.loads(self.rfile.read(length))["q"]
            body = json.dumps({"answer": ask(question)}, ensure_ascii=False)
        except Exception as exc:                    # 데모 서버다. 죽지 않고 이유를 보여준다.
            traceback.print_exc()
            body = json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
        self._send(200, body.encode("utf-8"), "application/json; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


SAMPLE_ARGS = {
    "paper_trend": {"query": "retinol"},
    "paper_growth": {},
    "top_products": {"source": "oliveyoung", "board": "?", "limit": 3},
    "price_history": {"name_contains": "세럼", "days": 30},
    "new_products": {"days": 30},
    "review_topics": {"name_contains": "세럼"},
    "search_reviews": {"keyword": "보습", "limit": 3},
    "data_status": {},
}


def _check_budget_math() -> None:
    """단가 계산과 하드스톱 산술. API 도 DB 도 건드리지 않는다."""
    # 100만 입력 토큰 = $3.00, 100만 출력 = $15.00
    assert cost_of(1_000_000, 0, 0, 0) == Decimal("3.00")
    assert cost_of(0, 1_000_000, 0, 0) == Decimal("15.00")
    # 캐시 읽기는 입력의 1/10, 캐시 쓰기는 1.25배
    assert cost_of(0, 0, 1_000_000, 0) == Decimal("0.30")
    assert cost_of(0, 0, 0, 1_000_000) == Decimal("3.75")
    # 견적이 상한보다 크면 첫 요청부터 막혀야 한다 — 상한을 0 으로 두면 그렇게 된다
    assert ESTIMATE_USD > 0 and BUDGET_USD > 0
    assert Decimal("9.90") + ESTIMATE_USD > Decimal("10.00"), "상한 근처에서 막히지 않는다"
    print(f"  예산 산술 OK   상한 ${BUDGET_USD}  요청당 견적 ${ESTIMATE_USD}")


def _self_check() -> None:
    """도구가 실제로 도는지. Claude 는 부르지 않는다 — 토큰을 쓰지 않고 배선만 본다."""
    _check_budget_math()
    # @beta_tool 은 함수를 BetaFunctionTool 로 감싼다 — 원래 함수는 .func, 이름은 .name.
    for tool in TOOLS:
        name = tool.name
        payload = json.loads(tool.func(**SAMPLE_ARGS[name]))
        assert "rows" in payload and payload["provenance"]["table"], name
        assert payload["provenance"].get("caveat"), f"{name}: 한계 표기가 없다"
        print(f"  {name:<16} {payload['provenance']['returned']:>3}행")
    print("self-check OK")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
        raise SystemExit(0)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        key = Path(os.environ.get("COSMAI_KEY_FILE", "anthropic.key"))
        if key.is_file():
            text = key.read_text(encoding="utf-8").strip()
            # 파일이 KEY=값 형태일 수도, 키만 있을 수도 있다.
            os.environ["ANTHROPIC_API_KEY"] = text.split("=", 1)[1] if "=" in text else text
    print(f"COSMAI on :{PORT}  model={MODEL}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
