\echo '=== Phase2 / Part3 Tests ==='
\set ON_ERROR_STOP on
BEGIN;
SET search_path TO public;

-- -------------------------
-- Q1) avg profit margin by subcategory (input: category)
-- -------------------------
\echo '--- Q1: q1_avg_profit_margin_by_subcategory(category) ---'
SELECT category AS cat
FROM product
WHERE category IS NOT NULL AND btrim(category) <> ''
LIMIT 1
\gset

SELECT * FROM q1_avg_profit_margin_by_subcategory(:'cat')
LIMIT 20;

-- -------------------------
-- Q2) favorite products in range (input: start_ts, end_ts)
-- -------------------------
\echo '--- Q2: q2_favorite_products_in_range(start, end) ---'
WITH best_month AS (
  SELECT date_trunc('month', o.date)::timestamp AS start_d,
         COUNT(*) AS fb_cnt
  FROM feedback f
  JOIN "Order" o ON o.orderid = f.orderid
  WHERE COALESCE(f.ispublic, true) = true
  GROUP BY 1
  ORDER BY fb_cnt DESC, start_d
  LIMIT 1
)
SELECT start_d AS q2_start, (start_d + interval '1 month')::timestamp AS q2_end, fb_cnt
FROM best_month
\gset

SELECT *
FROM q2_favorite_products_in_range(
  (:'q2_start')::timestamp,
  (:'q2_end')::timestamp
)
LIMIT 20;

-- -------------------------
-- Q3) new high value customers (input: today, min_orders, min_amount)
-- -------------------------
\echo '--- Q3: q3_new_high_value_customers(today, min_orders, min_amount) ---'
SELECT * FROM q3_new_high_value_customers(now()::timestamp, 1::int, 1::numeric);

-- SELECT * FROM q3_new_high_value_customers(current_date, 3, 500) LIMIT 20;

-- -------------------------
-- Q4) product dependency (input: threshold_count, min_confidence)
-- -------------------------
\echo '--- Q4: q4_category_dependency(threshold, min_conf) ---'
SELECT * FROM q4_category_dependency('Clothing'::text, 3::int)
LIMIT 30;

-- -------------------------
-- Q5) late shipments (VIEW)
-- -------------------------
\echo '--- Q5: q5_late_shipments (VIEW) ---'
SELECT * FROM q5_late_shipments
LIMIT 30;

-- -------------------------
-- Q6) total tax paid by customer (input: customerid)
-- -------------------------
\echo '--- Q6: q6_tax_paid_by_customer(customerid) ---'
SELECT o.customerid AS cid
FROM "Order" o
JOIN orderitem oi ON oi.orderid = o.orderid
WHERE oi.itemstatus = 'Received'
LIMIT 1
\gset

SELECT * FROM q6_tax_paid_by_customer(:cid);

-- -------------------------
-- Q7) shared customers between two branches (input: branch1, branch2)
-- -------------------------
\echo '--- Q7: q7_common_customers_between_branches(branch1, branch2) ---'
WITH best_pair AS (
  SELECT o1.branchid AS b1, o2.branchid AS b2,
         COUNT(DISTINCT o1.customerid) AS shared_cnt
  FROM "Order" o1
  JOIN "Order" o2
    ON o1.customerid = o2.customerid
   AND o1.branchid < o2.branchid
  GROUP BY o1.branchid, o2.branchid
  ORDER BY shared_cnt DESC
  LIMIT 1
)
SELECT b1, b2 FROM best_pair
\gset

SELECT * FROM q7_common_customers_between_branches(:b1, :b2)
LIMIT 50;

-- -------------------------
-- Q8) wallet adoption rate per year (no input)
-- -------------------------
\echo '--- Q8: q8_wallet_turnover_by_year() ---'
SELECT * FROM q8_wallet_turnover_by_year()
ORDER BY year
LIMIT 50;

-- -------------------------
-- Q9) BNPL ability (input: customerid, amount)
-- -------------------------
\echo '--- Q9: q9_bnpl_credit_decisionl(customerid, amount) ---'
SELECT customerid AS cid9,
       GREATEST(1, COALESCE(creditlimit,0) / 2) AS amt9
FROM customer
ORDER BY creditlimit DESC NULLS LAST
LIMIT 1
\gset

SELECT * FROM q9_bnpl_credit_decision(:cid9, (:'amt9')::numeric);

-- -------------------------
-- Q10) popular subcategories by discount (input: category)
-- -------------------------
\echo '--- Q10: q10_popularity_in_category(category) ---'
SELECT category AS cat10
FROM product
WHERE category IS NOT NULL AND btrim(category) <> ''
LIMIT 1
\gset

SELECT * FROM q10_popularity_in_category(:'cat10')
LIMIT 20;

-- -------------------------
-- Q11) best suppliers (no input)
-- -------------------------
\echo '--- Q11: q11_best_suppliers() ---'
SELECT * FROM q11_best_suppliers()
LIMIT 30;

-- -------------------------
-- Q12) real customer value (optional input tax_rate)
-- -------------------------
\echo '--- Q12: q12_real_customer_value(tax_rate=0.09 default) ---'
SELECT * FROM q12_real_customer_value()
LIMIT 30;

-- -------------------------
-- Q13) possible values for product attributes (input: category, subcategory, key (optional))
-- -------------------------
\echo '--- Q13: q13_possible_spec_values(category, subcategory, key) ---'
SELECT category AS cat13, subcategory AS sub13
FROM product
WHERE specifications IS NOT NULL
  AND specifications <> '{}'::jsonb
  AND category IS NOT NULL
  AND subcategory IS NOT NULL
GROUP BY category, subcategory
ORDER BY COUNT(*) DESC, category, subcategory
LIMIT 1
\gset
WITH keys AS (
  SELECT k, COUNT(*) AS cnt
  FROM product p
  CROSS JOIN LATERAL jsonb_object_keys(p.specifications) k
  WHERE specifications IS NOT NULL
    AND specifications <> '{}'::jsonb
    AND lower(p.category) = lower(:'cat13')
    AND lower(p.subcategory) = lower(:'sub13')
  GROUP BY k
)
SELECT k AS key13, cnt AS keycnt
FROM keys
ORDER BY keycnt DESC, k
LIMIT 1
\gset

SELECT *
FROM q13_possible_spec_values(:'cat13', :'sub13', :'key13')
LIMIT 30;

\echo '=== Done. Rolling back (no changes persisted). ==='
ROLLBACK;