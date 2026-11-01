# Benchmark results

Median of 7 `EXPLAIN (ANALYZE, BUFFERS)` runs after one warm-up run. Buffers = 8 kB pages touched.

| Query | Index | Before: plan | Before (ms) | After: plan | After (ms) | Speedup | Buffers before → after |
|---|---|---|---:|---|---:|---:|---:|
| Orders of one customer | `idx_orders_customer_id` | Seq Scan on orders | 4.505 | Bitmap Heap Scan on orders, Bitmap Index Scan using idx_orders_customer_id | 0.062 | 72.7× | 812 → 12 |
| get_customer_orders() (orders + items + products) | `idx_orders_customer_id` | Seq Scan on orders, Index Scan using order_items_pkey on order_items, Index Scan using products_pkey on products | 4.383 | Bitmap Heap Scan on orders, Bitmap Index Scan using idx_orders_customer_id, Index Scan using order_items_pkey on order_items, Index Scan using products_pkey on products | 0.178 | 24.6× | 924 → 124 |
| metadata @> {"brand": "Voltix", "warranty_months": 36} | `idx_products_metadata_gin` | Seq Scan on products | 3.795 | Bitmap Heap Scan on products, Bitmap Index Scan using idx_products_metadata_gin | 0.446 | 8.5× | 488 → 134 |
| metadata @> {"colors": ["red"], "sizes": ["XS"], "material": "leather"} | `idx_products_metadata_gin` | Seq Scan on products | 4.074 | Bitmap Heap Scan on products, Bitmap Index Scan using idx_products_metadata_gin | 0.531 | 7.7× | 488 → 112 |
| metadata ? 'warranty_months' (low selectivity, ~17% of rows) | `idx_products_metadata_gin` | Seq Scan on products | 2.558 | Bitmap Heap Scan on products, Bitmap Index Scan using idx_products_metadata_gin | 1.354 | 1.9× | 488 → 492 |

Index sizes: `idx_orders_customer_id` 920 kB, `idx_products_metadata_gin` 688 kB

## Orders of one customer

```sql
SELECT order_id, order_date, status FROM orders WHERE customer_id = %s ORDER BY order_date DESC
```

**Before**

```
Sort  (cost=2062.17..2062.19 rows=10 width=25) (actual time=4.460..4.461 rows=10 loops=1)
  Sort Key: order_date DESC
  Sort Method: quicksort  Memory: 25kB
  Buffers: shared hit=812
  ->  Seq Scan on orders  (cost=0.00..2062.00 rows=10 width=25) (actual time=0.034..4.436 rows=10 loops=1)
        Filter: (customer_id = 5000)
        Rows Removed by Filter: 99990
        Buffers: shared hit=812
Planning Time: 0.056 ms
Execution Time: 4.495 ms
```

**After**

```
Sort  (cost=41.33..41.36 rows=10 width=25) (actual time=0.024..0.025 rows=10 loops=1)
  Sort Key: order_date DESC
  Sort Method: quicksort  Memory: 25kB
  Buffers: shared hit=12
  ->  Bitmap Heap Scan on orders  (cost=4.37..41.17 rows=10 width=25) (actual time=0.009..0.016 rows=10 loops=1)
        Recheck Cond: (customer_id = 5000)
        Heap Blocks: exact=10
        Buffers: shared hit=12
        ->  Bitmap Index Scan on idx_orders_customer_id  (cost=0.00..4.37 rows=10 width=0) (actual time=0.006..0.006 rows=10 loops=1)
              Index Cond: (customer_id = 5000)
              Buffers: shared hit=2
Planning Time: 0.030 ms
Execution Time: 0.062 ms
```

## get_customer_orders() (orders + items + products)

```sql
SELECT o.order_id, o.order_date, o.status, oi.product_id, p.name, oi.quantity, oi.unit_price FROM orders o JOIN order_items oi USING (order_id) JOIN products p USING (product_id) WHERE o.customer_id = %s ORDER BY o.order_date DESC, o.order_id DESC
```

**Before**

```
Sort  (cost=2190.45..2190.51 rows=25 width=57) (actual time=4.466..4.468 rows=24 loops=1)
  Sort Key: o.order_date DESC, o.order_id DESC
  Sort Method: quicksort  Memory: 27kB
  Buffers: shared hit=924
  ->  Nested Loop  (cost=0.71..2189.87 rows=25 width=57) (actual time=0.048..4.451 rows=24 loops=1)
        Buffers: shared hit=924
        ->  Nested Loop  (cost=0.42..2182.03 rows=25 width=43) (actual time=0.042..4.398 rows=24 loops=1)
              Buffers: shared hit=852
              ->  Seq Scan on orders o  (cost=0.00..2062.00 rows=10 width=25) (actual time=0.030..4.346 rows=10 loops=1)
                    Filter: (customer_id = 5000)
                    Rows Removed by Filter: 99990
                    Buffers: shared hit=812
              ->  Index Scan using order_items_pkey on order_items oi  (cost=0.42..11.97 rows=3 width=26) (actual time=0.004..0.004 rows=2 loops=10)
                    Index Cond: (order_id = o.order_id)
                    Buffers: shared hit=40
        ->  Index Scan using products_pkey on products p  (cost=0.29..0.31 rows=1 width=22) (actual time=0.002..0.002 rows=1 loops=24)
              Index Cond: (product_id = oi.product_id)
              Buffers: shared hit=72
Planning:
  Buffers: shared hit=34
Planning Time: 0.579 ms
Execution Time: 4.535 ms
```

**After**

```
Sort  (cost=169.61..169.68 rows=25 width=57) (actual time=0.131..0.132 rows=24 loops=1)
  Sort Key: o.order_date DESC, o.order_id DESC
  Sort Method: quicksort  Memory: 27kB
  Buffers: shared hit=124
  ->  Nested Loop  (cost=5.08..169.03 rows=25 width=57) (actual time=0.027..0.119 rows=24 loops=1)
        Buffers: shared hit=124
        ->  Nested Loop  (cost=4.79..161.19 rows=25 width=43) (actual time=0.020..0.073 rows=24 loops=1)
              Buffers: shared hit=52
              ->  Bitmap Heap Scan on orders o  (cost=4.37..41.17 rows=10 width=25) (actual time=0.010..0.019 rows=10 loops=1)
                    Recheck Cond: (customer_id = 5000)
                    Heap Blocks: exact=10
                    Buffers: shared hit=12
                    ->  Bitmap Index Scan on idx_orders_customer_id  (cost=0.00..4.37 rows=10 width=0) (actual time=0.006..0.006 rows=10 loops=1)
                          Index Cond: (customer_id = 5000)
                          Buffers: shared hit=2
              ->  Index Scan using order_items_pkey on order_items oi  (cost=0.42..11.97 rows=3 width=26) (actual time=0.004..0.005 rows=2 loops=10)
                    Index Cond: (order_id = o.order_id)
                    Buffers: shared hit=40
        ->  Index Scan using products_pkey on products p  (cost=0.29..0.31 rows=1 width=22) (actual time=0.002..0.002 rows=1 loops=24)
              Index Cond: (product_id = oi.product_id)
              Buffers: shared hit=72
Planning:
  Buffers: shared hit=34
Planning Time: 0.437 ms
Execution Time: 0.189 ms
```

## metadata @> {"brand": "Voltix", "warranty_months": 36}

```sql
SELECT product_id, sku, name FROM products WHERE metadata @> %s
```

**Before**

```
Seq Scan on products  (cost=0.00..738.00 rows=2 width=32) (actual time=0.042..3.649 rows=128 loops=1)
  Filter: (metadata @> '{"brand": "Voltix", "warranty_months": 36}'::jsonb)
  Rows Removed by Filter: 19872
  Buffers: shared hit=488
Planning Time: 0.114 ms
Execution Time: 3.661 ms
```

**After**

```
Bitmap Heap Scan on products  (cost=38.90..46.54 rows=2 width=32) (actual time=0.321..0.437 rows=128 loops=1)
  Recheck Cond: (metadata @> '{"brand": "Voltix", "warranty_months": 36}'::jsonb)
  Rows Removed by Index Recheck: 9
  Heap Blocks: exact=120
  Buffers: shared hit=134
  ->  Bitmap Index Scan on idx_products_metadata_gin  (cost=0.00..38.90 rows=2 width=0) (actual time=0.304..0.305 rows=137 loops=1)
        Index Cond: (metadata @> '{"brand": "Voltix", "warranty_months": 36}'::jsonb)
        Buffers: shared hit=14
Planning:
  Buffers: shared hit=1
Planning Time: 0.136 ms
Execution Time: 0.505 ms
```

## metadata @> {"colors": ["red"], "sizes": ["XS"], "material": "leather"}

```sql
SELECT product_id, sku, name FROM products WHERE metadata @> %s
```

**Before**

```
Seq Scan on products  (cost=0.00..738.00 rows=167 width=32) (actual time=0.008..4.112 rows=94 loops=1)
  Filter: (metadata @> '{"sizes": ["XS"], "colors": ["red"], "material": "leather"}'::jsonb)
  Rows Removed by Filter: 19906
  Buffers: shared hit=488
Planning Time: 0.125 ms
Execution Time: 4.123 ms
```

**After**

```
Bitmap Heap Scan on products  (cost=57.16..399.02 rows=167 width=32) (actual time=0.340..0.423 rows=94 loops=1)
  Recheck Cond: (metadata @> '{"sizes": ["XS"], "colors": ["red"], "material": "leather"}'::jsonb)
  Heap Blocks: exact=90
  Buffers: shared hit=112
  ->  Bitmap Index Scan on idx_products_metadata_gin  (cost=0.00..57.12 rows=167 width=0) (actual time=0.329..0.329 rows=94 loops=1)
        Index Cond: (metadata @> '{"sizes": ["XS"], "colors": ["red"], "material": "leather"}'::jsonb)
        Buffers: shared hit=22
Planning:
  Buffers: shared hit=1
Planning Time: 0.107 ms
Execution Time: 0.500 ms
```

## metadata ? 'warranty_months' (low selectivity, ~17% of rows)

```sql
SELECT product_id, sku, name FROM products WHERE metadata ? %s
```

**Before**

```
Seq Scan on products  (cost=0.00..738.00 rows=3347 width=32) (actual time=0.006..2.435 rows=3338 loops=1)
  Filter: (metadata ? 'warranty_months'::text)
  Rows Removed by Filter: 16662
  Buffers: shared hit=488
Planning Time: 0.102 ms
Execution Time: 2.539 ms
```

**After**

```
Bitmap Heap Scan on products  (cost=34.52..564.35 rows=3347 width=32) (actual time=0.279..1.275 rows=3338 loops=1)
  Recheck Cond: (metadata ? 'warranty_months'::text)
  Heap Blocks: exact=488
  Buffers: shared hit=492
  ->  Bitmap Index Scan on idx_products_metadata_gin  (cost=0.00..33.68 rows=3347 width=0) (actual time=0.235..0.236 rows=3338 loops=1)
        Index Cond: (metadata ? 'warranty_months'::text)
        Buffers: shared hit=4
Planning:
  Buffers: shared hit=1
Planning Time: 0.102 ms
Execution Time: 1.401 ms
```
