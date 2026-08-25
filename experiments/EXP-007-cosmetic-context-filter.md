# EXP-007 — 논문 계열이 화장품 논문을 세고 있었나

## Identity and status

- Experiment ID: `EXP-007`
- Type: `OTHER` (measurement + 데이터 정정)
- Status: `COMPLETED`
- Related: `MODELS.md` Model E, 시현님 성분 3소스 대조표
- Owner: hyeonjunni
- Created at: 2026-08-25T14:10+09:00
- Last executed at: 2026-08-25T15:40+09:00

## 이 실험은 사전 등록이 없다

발견이 먼저였다. 팀원이 아데노신 한 행을 물어서 확인하다가 나왔고, 가설을 세우고
잰 것이 아니라 잰 뒤에 문제를 알았다. 그러므로 이 기록은 가설 검정이 아니라 **정정
기록**이다. 사후 서사를 사전 등록처럼 쓰지 않기 위해 여기에 못 박는다.

## Question

`academic.paper_trend` 는 성분명만으로 검색해 만들었다. 그 계열이 실제로 화장품
논문을 세고 있는가.

## Observations

```text
[측정] PubMed 2025년 전체, 'AND (skin OR cosmetic OR dermatology)' 전후
  검색어             원본      필터후    남는 비율
  adenosine        12,017      330      2.7%
  retinol           2,280      159      7.0%
  ascorbic acid     3,307      235      7.1%
  exosome           8,709      665      7.6%
  niacinamide       1,089       92      8.4%
  ceramide          1,535      192     12.5%
  collagen         19,468    3,478     17.9%
  hyaluronic acid   5,337    1,208     22.6%

  아데노신만의 문제가 아니다. 전부다.
```

```text
[측정] 필터가 배수와 순위를 바꾸는가 (17검색어 x 2소스, 2019 vs 최근 12개월)
  PubMed      배수 순위가 바뀐 검색어 16 / 17
  Europe PMC  배수 순위가 바뀐 검색어 11 / 17

  방향이 뒤집힌 것
    niacinamide   PubMed  0.91x (감소) -> 1.16x (증가)
    retinaldehyde PubMed  0.66x (감소) -> 1.00x (보합)

  크게 강해진 것
    polydeoxyribonucleotide  PubMed 1.95x -> 5.86x
    exosome                  PubMed 1.92x -> 4.38x
    madecassoside            PubMed 2.08x -> 4.75x
```

```text
[측정] 소스 간 불일치가 필터로 해소된다
  원본  niacinamide  PubMed 0.91x (감소) vs Europe PMC 2.09x (증가)  — 반대
  필터  niacinamide  PubMed 1.16x (증가) vs Europe PMC 3.34x (증가)  — 같은 방향
```

## Interpretation

```text
[추론] 원본 계열은 화장품 논문을 세지 않았다. 남는 비율이 2.7~22.6% 이므로 대부분이
다른 분야다. 아데노신은 ATP·수용체·신호전달, 엑소좀은 암·약물전달, 콜라겐은 조직공학
쪽 문헌이 분모를 채우고 있었다.

배수도 오염된다. 화장품 맥락의 연구가 전체보다 빨리 크는 성분에서는 원본 배수가 신호를
희석하고(아데노신 1.11 -> 1.27), 느리게 크는 성분에서는 부풀린다.
```

```text
[추론] 내가 앞서 "엑소좀 1.92배는 암·약물전달 연구가 만든 것" 이라고 팀에 말한 것은
틀렸다. 필터 후 배수가 4.38배로 **더 높다** — 화장품 엑소좀 연구가 전체 엑소좀 연구보다
빨리 크고 있다. 근거 없이 방향을 추측했고 측정이 반대로 나왔다.
```

```text
[추론] 소스 간 불일치의 일부는 색인 차이가 아니라 필터 부재였다. niacinamide 에서
PubMed 와 Europe PMC 가 반대 방향이었던 것을 나는 "두 색인이 다른 것을 센다" 로
설명했는데, 화장품 맥락으로 좁히니 둘 다 증가로 모인다. 설명이 틀린 것은 아니지만
그것만으로 돌린 것은 성급했다.
```

```text
[추론] 이 결함은 ratio_usable 로 막히지 않는다. 그 컬럼은 표본이 작은지를 보는데,
여기서는 표본이 커도 다른 것을 세고 있었다. 크기 검사와 대상 검사는 다른 검사다.
```

## Result

- Outcome: **원본 계열은 화장품 결론에 쓸 수 없다.** 필터 계열을 병기하고
  `context_filtered` 컬럼으로 구분한다. 원본을 지우지는 않는다 — 필터가 얼마나
  바꾸는지 보이려면 둘 다 있어야 한다.
- Known limitations:
  - **필터가 거칠다.** MeSH 가 아니라 평문 키워드다. `"Cosmetics"[MeSH]` 나
    `"Skin"[MeSH]` 가 더 정확하지만 확인하지 않았다. 지금 값은 하한도 상한도 아니다.
  - 모든 검색어에 같은 필터를 걸었으므로 **검색어 간 비교는 유지**되지만, 절대량은
    필터의 재현율에 좌우된다.
  - 필터 후 기준선이 작아져 `ratio_usable=False` 가 늘었다. PubMed 에서 PDRN·
    마데카소사이드·센텔라·판테놀·에칠헥실트리아존·레티날데하이드가 표본 부족이다.
  - `Model E`(논문 -> 매출) 는 필터 없는 계열로 측정했다. 다시 돌리지 않았다.

## Next

1. `Model E` 를 필터 계열로 다시 측정한다. 무신호 결론이 유지되는지는 미확인이다.
2. MeSH 기반 필터와 비교해 평문 필터의 재현율을 잰다.
3. 시현님 대조표의 논문 축을 `(skin)` 계열로 교체한다. 순위가 16/17 바뀌므로
   그 표의 성분 분류(카테고리 밖 / 널리 얕게 / 널리 깊게)도 다시 봐야 한다.
