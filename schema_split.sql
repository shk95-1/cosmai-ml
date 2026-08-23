-- 세 표현을 분리한다 — SKU, 리스팅, 제품 라인.
--
-- `public.product` 는 건드리지 않는다. 수집기와 shk 통합 DB 가 쓰는 테이블이고, 여기서
-- 만드는 것은 그 위에 얹는 파생 표현이다. 되돌리려면 `drop schema entity cascade` 하나면 된다.
--
-- 자연키를 그대로 쓴다. (source, product_key) 는 `product` 에 이미 있고 유일하므로 대리키를
-- 새로 만들 이유가 없다. 대리키가 필요한 것은 어느 소스에도 존재하지 않는 product_line 뿐이다.

create schema if not exists entity;

-- 한 행이 SKU 인지 리스팅인지는 이름이 결정한다 (`classify_rows.row_kind`).
-- 두 테이블은 `product` 를 분할한다 — 합이 원본 행 수와 같아야 하고, --apply 가 확인한다.

create table if not exists entity.sku (
    source          text not null,
    product_key     text not null,
    name            text not null,
    product_line_id bigint,          -- 항상 null 이다. 아래 product_line 주석 참조.
    primary key (source, product_key)
);

create table if not exists entity.listing (
    source      text not null,
    product_key text not null,
    name        text not null,
    primary key (source, product_key)
);

-- 리스팅이 이름 안에 열거한 변형들. 소스 안에서 닫히는 정보라 엔티티 해소가 필요 없다.
create table if not exists entity.listing_variant (
    source      text not null,
    product_key text not null,
    position    int  not null,
    variant     text not null,
    primary key (source, product_key, position),
    foreign key (source, product_key)
        references entity.listing (source, product_key) on delete cascade
);

-- 포함 관계. `EXP-005` 가 동일성 라벨에 뭉개 넣었던 바로 그 관계이며, 여기서 분리된다.
-- 포함은 추이적이지 않다: L 이 A 와 B 를 담아도 A 와 B 는 같은 제품이 아니다. 별도 테이블로
-- 두는 이유가 그것이다 — 동일성 그래프에 간선을 주지 않는다.
--
-- provenance 는 이 행이 어디서 왔는지다. 지금 채워지는 것은 전부 모델 라벨이고 사람 검증이
-- 0건이므로, 출처를 컬럼으로 강제해 두지 않으면 나중에 정답과 구분할 수 없게 된다.
create table if not exists entity.listing_contains (
    listing_source text not null,
    listing_key    text not null,
    sku_source     text not null,
    sku_key        text not null,
    provenance     text not null,
    primary key (listing_source, listing_key, sku_source, sku_key),
    foreign key (listing_source, listing_key)
        references entity.listing (source, product_key) on delete cascade,
    foreign key (sku_source, sku_key)
        references entity.sku (source, product_key) on delete cascade,
    check (not (listing_source = sku_source and listing_key = sku_key))
);

-- 제품 라인. **비어 있다, 의도적으로.**
--
-- 라인 ID 를 부여하려면 소스 간 엔티티 해소가 필요한데, 측정된 정밀도는 sku x sku 최상위
-- 구간에서 38.2% 다 (`EXP-006`). 그 매처로 ID 를 붙이면 서로 다른 제품이 한 ID 아래 합쳐지고,
-- 합쳐진 뒤에는 어느 행이 잘못 합쳐졌는지 알 수 없다. 되돌릴 수 없는 손상이다.
--
-- 그래서 테이블과 `sku.product_line_id` 컬럼은 만들되 채우지 않는다. 다운스트림은 이 컬럼에
-- 기대어 작성할 수 있고, 채우는 것은 매처가 운용 가능한 정밀도에 도달한 뒤의 일이다.
-- 지금 비어 있다는 사실 자체가 측정 결과다.
create table if not exists entity.product_line (
    id    bigserial primary key,
    brand text,
    name  text not null
);

do $$ begin
    alter table entity.sku
        add constraint sku_product_line_fk
        foreign key (product_line_id) references entity.product_line (id);
exception when duplicate_object then null; end $$;

create index if not exists listing_contains_sku_idx
    on entity.listing_contains (sku_source, sku_key);
