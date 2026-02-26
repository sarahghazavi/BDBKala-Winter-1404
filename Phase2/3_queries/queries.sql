\set ON_ERROR_STOP on
\echo 'Running phase2_part3.sql ...'
BEGIN;
SET search_path TO public;

-- Q1) average of benefit margin for subsections using weights based on quantity
--          input: category
--          output: subcategory + avg_margin + revenue/profit
CREATE OR REPLACE FUNCTION q1_avg_profit_margin_by_subcategory(p_category text)
RETURNS TABLE(
  subcategory text,
  avg_margin numeric(10,4),
  total_qty bigint,
  revenue numeric(14,2),
  profit numeric(14,2)
)
LANGUAGE sql STABLE AS $$
  SELECT
    p.subcategory,
    ROUND(
      SUM(oi.quantity * (COALESCE(oi.purchaseprice,0) - COALESCE(p.costprice,0)))
      / NULLIF(SUM(oi.quantity * COALESCE(oi.purchaseprice,0)), 0)
    , 4) AS avg_margin,
    SUM(oi.quantity) AS total_qty,
    ROUND(SUM(oi.quantity * COALESCE(oi.purchaseprice,0)), 2) AS revenue,
    ROUND(SUM(oi.quantity * (COALESCE(oi.purchaseprice,0) - COALESCE(p.costprice,0))), 2) AS profit
  FROM orderitem oi
  JOIN product p ON p.productid = oi.productid
  JOIN "Order" o ON o.orderid = oi.orderid
  WHERE p.category = p_category
    AND oi.itemstatus = 'Received'
  GROUP BY p.subcategory
  ORDER BY avg_margin DESC NULLS LAST, revenue DESC;
$$;


-- Q2) popular products in a time interval (based on average rate)
--          input: start_ts, end_ts
--          output: product names + avg_raring (sorted)
CREATE OR REPLACE FUNCTION q2_favorite_products_in_range(
  p_start timestamp,
  p_end   timestamp
)
RETURNS TABLE(
  product_name text,
  avg_rating numeric,
  rating_count bigint
)
LANGUAGE sql
AS $$
  SELECT
    p.name AS product_name,
    AVG(f.rating)::numeric(4,2) AS avg_rating,
    COUNT(*)::bigint AS rating_count
  FROM feedback f
  JOIN "Order" o  ON o.orderid = f.orderid
  JOIN product p  ON p.productid = f.productid
  WHERE o.date >= p_start
    AND o.date <= p_end
    AND f.ispublic = true
  GROUP BY p.name
  ORDER BY avg_rating DESC, rating_count DESC, product_name;
$$;


-- Q3) new most active customers
--          input: today_date, min_orders, min_amount
--          output: name + number + order counts + sum of shopping
CREATE OR REPLACE FUNCTION q3_new_high_value_customers(
  p_now timestamp,
  p_min_orders int,
  p_min_amount numeric
)
RETURNS TABLE(
  customerid bigint,
  name text,
  phone text,
  total_orders bigint,
  total_purchase numeric
)
LANGUAGE sql
AS $$
  WITH new_customers AS (
    SELECT o.customerid
    FROM "Order" o
    GROUP BY o.customerid
    HAVING MIN(o.date) >= (p_now - interval '1 month')
  ),
  recent_orders AS (
    SELECT o.orderid, o.customerid
    FROM "Order" o
    WHERE o.date >= (p_now - interval '1 month')
  ),
  recent_order_amounts AS (
    SELECT
      ro.customerid,
      ro.orderid,
      COALESCE(SUM(oi.quantity * oi.purchaseprice), 0)::numeric AS order_amount
    FROM recent_orders ro
    LEFT JOIN orderitem oi ON oi.orderid = ro.orderid
    GROUP BY ro.customerid, ro.orderid
  ),
  recent_customer_agg AS (
    SELECT
      roa.customerid,
      COUNT(DISTINCT roa.orderid) AS total_orders,
      COALESCE(SUM(roa.order_amount), 0) AS total_purchase
    FROM recent_order_amounts roa
    GROUP BY roa.customerid
  )
  SELECT
    c.customerid,
    c.name,
    c.phone,
    a.total_orders,
    a.total_purchase
  FROM new_customers nc
  JOIN customer c ON c.customerid = nc.customerid
  JOIN recent_customer_agg a ON a.customerid = c.customerid
  WHERE a.total_orders >= p_min_orders
    AND a.total_purchase >= p_min_amount
  ORDER BY a.total_purchase DESC, a.total_orders DESC;
$$;


-- Q4) relations between products in orders
--          input: category, min_support
--          output: all categories in the same order of input category + number of shared orders
CREATE OR REPLACE FUNCTION q4_category_dependency(p_category text, p_min_support int)
RETURNS TABLE(
  other_category text,
  support_orders bigint
)
LANGUAGE sql STABLE AS $$
  WITH orders_with_cat AS (
    SELECT DISTINCT oi.orderid
    FROM orderitem oi
    JOIN product p ON p.productid = oi.productid
    WHERE p.category = p_category
      AND oi.itemstatus = 'Received'
  ),
  other_cats AS (
    SELECT DISTINCT ow.orderid, p2.category AS other_category
    FROM orders_with_cat ow
    JOIN orderitem oi2 ON oi2.orderid = ow.orderid
    JOIN product p2 ON p2.productid = oi2.productid
    WHERE p2.category IS NOT NULL
      AND p2.category <> p_category
  )
  SELECT
    other_category,
    COUNT(DISTINCT orderid) AS support_orders
  FROM other_cats
  GROUP BY other_category
  HAVING COUNT(DISTINCT orderid) >= p_min_support
  ORDER BY support_orders DESC, other_category;
$$;


-- Q5) delayed orders
--          input: -
--          output: id of orders:
--                              A) shiptype = same-day but shipdate != order.date
--                              B) shiptype = ordinary but shipdate - order.date > 2 days
CREATE OR REPLACE VIEW q5_late_shipments AS
SELECT
  o.orderid,
  s.shiptype,
  o.date AS order_date,
  s.shipdate
FROM "Order" o
JOIN shipment s ON s.shipmentid = o.shipmentid
WHERE s.shipdate IS NOT NULL
  AND o.date IS NOT NULL
  AND (
    (lower(btrim(coalesce(s.shiptype,''))) IN ('same-day','sameday','same day')
      AND s.shipdate::date <> o.date::date)
    OR
    (lower(btrim(coalesce(s.shiptype,''))) NOT IN ('same-day','sameday','same day')
      AND s.shipdate > o.date + interval '2 days')
  );


-- Q6) amount of taxes payed by a customer
--          input: customerid
--          output: sum of taxes
CREATE OR REPLACE FUNCTION q6_tax_paid_by_customer(p_customerid bigint, p_tax_rate numeric DEFAULT 0.09)
RETURNS numeric(14,2)
LANGUAGE sql STABLE AS $$
  SELECT
    ROUND(
      SUM(
        CASE
          WHEN lower(coalesce(c.taxstatus,'')) IN ('exempt','no','false','0','none') THEN 0
          WHEN lower(coalesce(p.taxstatus,'')) IN ('taxable','taxed','vat','yes','true','1')
            THEN (COALESCE(oi.purchaseprice,0) * oi.quantity) * p_tax_rate
          ELSE 0
        END
      )
    , 2)
  FROM "Order" o
  JOIN customer c ON c.customerid = o.customerid
  JOIN orderitem oi ON oi.orderid = o.orderid
  JOIN product p ON p.productid = oi.productid
  WHERE o.customerid = p_customerid;
$$;


-- Q7) shared customers between branches
--          input: branch1, branch2
--          output: customer name + number of orders in each branch + name of most used branch
CREATE OR REPLACE FUNCTION q7_common_customers_between_branches(p_b1 bigint, p_b2 bigint)
RETURNS TABLE(
  customer_name text,
  orders_in_b1 bigint,
  orders_in_b2 bigint,
  more_orders_branch text
)
LANGUAGE sql STABLE AS $$
  WITH cnt AS (
    SELECT
      o.customerid,
      SUM(CASE WHEN o.branchid = p_b1 THEN 1 ELSE 0 END) AS c1,
      SUM(CASE WHEN o.branchid = p_b2 THEN 1 ELSE 0 END) AS c2
    FROM "Order" o
    WHERE o.branchid IN (p_b1, p_b2)
    GROUP BY o.customerid
    HAVING SUM(CASE WHEN o.branchid = p_b1 THEN 1 ELSE 0 END) > 0
       AND SUM(CASE WHEN o.branchid = p_b2 THEN 1 ELSE 0 END) > 0
  )
  SELECT
    c.name,
    cnt.c1,
    cnt.c2,
    CASE
      WHEN cnt.c1 > cnt.c2 THEN b1.name
      WHEN cnt.c2 > cnt.c1 THEN b2.name
      ELSE 'Equal'
    END
  FROM cnt
  JOIN customer c ON c.customerid = cnt.customerid
  JOIN branch b1 ON b1.branchid = p_b1
  JOIN branch b2 ON b2.branchid = p_b2
  ORDER BY GREATEST(cnt.c1, cnt.c2) DESC, c.name;
$$;


-- Q8) rate of wallet acceptence seperated by gender and income in a year
--          input: -
--          output: year, gender, incomelevel, avg_turnover
--                                                  avg_turnover = SUM (ABS(withdraw) + ABS(deposit))
CREATE OR REPLACE FUNCTION q8_wallet_turnover_by_year()
RETURNS TABLE(
  year int,
  gender text,
  incomelevel text,
  avg_turnover numeric(14,2)
)
LANGUAGE sql STABLE AS $$
  WITH per_customer_year AS (
    SELECT
      c.customerid,
      EXTRACT(YEAR FROM wt.date)::int AS year,
      SUM(ABS(wt.amount)) AS turnover
    FROM customer c
    JOIN wallettransaction wt ON wt.walletid = c.walletid
    GROUP BY c.customerid, EXTRACT(YEAR FROM wt.date)
  )
  SELECT
    p.year,
    c.gender,
    c.incomelevel,
    ROUND(AVG(p.turnover)::numeric, 2) AS avg_turnover
  FROM per_customer_year p
  JOIN customer c ON c.customerid = p.customerid
  GROUP BY p.year, c.gender, c.incomelevel
  ORDER BY p.year, c.gender, c.incomelevel;
$$;


-- Q9) amount of BNPL credit
--          input: customerid, purchase_amount
--          output: debt, creditlimit, can_use_bnpl
CREATE OR REPLACE FUNCTION q9_bnpl_credit_decision(p_customerid bigint, p_amount numeric)
RETURNS TABLE(
  current_debt numeric(14,2),
  credit_limit numeric(14,2),
  can_use_bnpl boolean,
  available_credit numeric(14,2)
)
LANGUAGE sql STABLE AS $$
  SELECT
    ROUND(GREATEST(0, -COALESCE(c.balance,0)), 2) AS current_debt,
    c.creditlimit AS credit_limit,
    CASE
      WHEN c.creditlimit IS NULL THEN false
      WHEN (COALESCE(c.balance,0) - COALESCE(p_amount,0)) >= -c.creditlimit THEN true
      ELSE false
    END AS can_use_bnpl,
    CASE
      WHEN c.creditlimit IS NULL THEN NULL
      ELSE ROUND(c.creditlimit - GREATEST(0, -COALESCE(c.balance,0)), 2)
    END AS available_credit
  FROM customer c
  WHERE c.customerid = p_customerid;
$$;


-- Q10) popularity (avg of rates) of a category's products
--          input: category
--          output: product_name, avg_rating
CREATE OR REPLACE FUNCTION q10_popularity_in_category(p_category text)
RETURNS TABLE(
  product_name text,
  avg_rating numeric(4,2),
  rating_count bigint
)
LANGUAGE sql STABLE AS $$
  SELECT
    p.name,
    ROUND(AVG(f.rating)::numeric, 2) AS avg_rating,
    COUNT(f.rating) AS rating_count
  FROM product p
  JOIN feedback f ON f.productid = p.productid
  WHERE p.category = p_category
  GROUP BY p.name
  ORDER BY avg_rating DESC, rating_count DESC, p.name;
$$;


-- Q11) best providers
--          input: -
--          output: best providers, for each branch:
--                                                A) provides at least half of branch's products (considering quantity)
--                                                B) has an average of supplytime less than everybody else
CREATE OR REPLACE FUNCTION q11_best_suppliers()
RETURNS TABLE(
  branchid bigint,
  branch_name text,
  supplierid bigint,
  supplier_name text,
  supplied_qty bigint,
  supplied_share numeric(6,3),
  supplier_avg_supplytime timestamp,
  branch_avg_supplytime timestamp,
  qualifies_by text
)
LANGUAGE sql STABLE AS $$
  WITH sold AS (
    SELECT o.branchid, oi.productid, SUM(oi.quantity) AS qty_sold
    FROM "Order" o
    JOIN orderitem oi ON oi.orderid = o.orderid
    WHERE oi.itemstatus = 'Received'
    GROUP BY o.branchid, oi.productid
  ),
  branch_total AS (
    SELECT branchid, SUM(qty_sold) AS total_qty
    FROM sold
    GROUP BY branchid
  ),
  chosen_supplier AS (
    SELECT branchid, productid, supplierid
    FROM (
      SELECT s.*,
             ROW_NUMBER() OVER (
               PARTITION BY s.branchid, s.productid
               ORDER BY s.supplyprice NULLS LAST, s.supplierid
             ) AS rn
      FROM supplies s
    ) x
    WHERE rn = 1
  ),
  supplier_sales AS (
    SELECT cs.branchid, cs.supplierid, SUM(s.qty_sold) AS qty_supplied
    FROM sold s
    JOIN chosen_supplier cs
      ON cs.branchid = s.branchid AND cs.productid = s.productid
    GROUP BY cs.branchid, cs.supplierid
  ),
  supplier_time AS (
    SELECT
      branchid,
      supplierid,
      (timestamp '2020-01-01' +
        make_interval(secs => AVG(EXTRACT(EPOCH FROM (supplytime - timestamp '2020-01-01'))))
      ) AS avg_time
    FROM supplies
    WHERE supplytime IS NOT NULL
    GROUP BY branchid, supplierid
  ),
  branch_time AS (
    SELECT
      branchid,
      (timestamp '2020-01-01' +
        make_interval(secs => AVG(EXTRACT(EPOCH FROM (supplytime - timestamp '2020-01-01'))))
      ) AS avg_time
    FROM supplies
    WHERE supplytime IS NOT NULL
    GROUP BY branchid
  ),
  fastest_time_per_branch AS (
    SELECT branchid, MIN(avg_time) AS min_avg_time
    FROM supplier_time
    GROUP BY branchid
  )
  SELECT
    b.branchid,
    b.name AS branch_name,
    sup.supplierid,
    sup.name AS supplier_name,
    ss.qty_supplied::bigint AS supplied_qty,
    ROUND((ss.qty_supplied::numeric / NULLIF(bt.total_qty,0)), 3) AS supplied_share,
    st.avg_time AS supplier_avg_supplytime,
    bt2.avg_time AS branch_avg_supplytime,
    CASE
      WHEN (ss.qty_supplied::numeric >= 0.5 * bt.total_qty::numeric)
           AND (st.avg_time = f.min_avg_time) THEN 'both'
      WHEN (ss.qty_supplied::numeric >= 0.5 * bt.total_qty::numeric) THEN 'half_sales'
      WHEN (st.avg_time = f.min_avg_time) THEN 'fastest'
      ELSE 'none'
    END AS qualifies_by
  FROM supplier_sales ss
  JOIN branch b ON b.branchid = ss.branchid
  JOIN supplier sup ON sup.supplierid = ss.supplierid
  JOIN branch_total bt ON bt.branchid = ss.branchid
  LEFT JOIN supplier_time st
    ON st.branchid = ss.branchid AND st.supplierid = ss.supplierid
  LEFT JOIN branch_time bt2
    ON bt2.branchid = ss.branchid
  LEFT JOIN fastest_time_per_branch f
    ON f.branchid = ss.branchid
  WHERE
    (ss.qty_supplied::numeric >= 0.5 * bt.total_qty::numeric)
    OR (st.avg_time = f.min_avg_time)
  ORDER BY b.branchid, supplied_share DESC, sup.name;
$$;


CREATE OR REPLACE FUNCTION q12_real_customer_value(p_tax_rate numeric DEFAULT 0.09)
RETURNS TABLE(
  customerid bigint,
  customer_name text,
  gross_paid numeric(14,2),
  refunds numeric(14,2),
  tax_paid numeric(14,2),
  real_value numeric(14,2)
)
LANGUAGE sql STABLE AS $$
  WITH
  -- 1) payments done for orders (normal + BNPL installments, etc.)
  rep_paid AS (
    SELECT o.customerid,
           SUM(r.amount) AS paid_amount
    FROM repayment r
    JOIN "Order" o ON o.orderid = r.orderid
    WHERE r.amount > 0
      AND lower(coalesce(r.method,'')) NOT IN ('refund','return','chargeback')
    GROUP BY o.customerid
  ),

  -- 2) refunds that are recorded in repayment
  rep_refund AS (
    SELECT o.customerid,
           SUM(r.amount) AS refund_amount
    FROM repayment r
    JOIN "Order" o ON o.orderid = r.orderid
    WHERE r.amount > 0
      AND lower(coalesce(r.method,'')) IN ('refund','return','chargeback')
    GROUP BY o.customerid
  ),

  -- 3) wallet spending (money leaving wallet due to purchase/payment)
  wallet_spent AS (
    SELECT c.customerid,
           SUM(wt.amount) AS wallet_out
    FROM wallettransaction wt
    JOIN customer c ON c.walletid = wt.walletid
    WHERE wt.amount > 0
      AND lower(wt.type) IN ('withdraw','payment','purchase','debit')
    GROUP BY c.customerid
  ),

  -- 4) wallet refunds (money returning to wallet due to return/refund)
  wallet_refund AS (
    SELECT c.customerid,
           SUM(wt.amount) AS wallet_in
    FROM wallettransaction wt
    JOIN customer c ON c.walletid = wt.walletid
    WHERE wt.amount > 0
      AND lower(wt.type) IN ('refund','return','chargeback','credit')
    GROUP BY c.customerid
  ),

  -- 5) tax paid (computed from purchased items + tax status flags)
  tax AS (
    SELECT
      o.customerid,
      SUM(
        CASE
          WHEN lower(coalesce(c.taxstatus,'')) IN ('exempt','no','false','0','none') THEN 0
          WHEN lower(coalesce(p.taxstatus,'')) IN ('taxable','taxed','vat','yes','true','1')
            THEN (COALESCE(oi.purchaseprice,0) * oi.quantity) * p_tax_rate
          ELSE 0
        END
      ) AS tax_paid
    FROM "Order" o
    JOIN customer c ON c.customerid = o.customerid
    JOIN orderitem oi ON oi.orderid = o.orderid
    JOIN product p ON p.productid = oi.productid
    GROUP BY o.customerid
  )

  SELECT
    c.customerid,
    c.name AS customer_name,
    ROUND(COALESCE(rp.paid_amount,0) + COALESCE(ws.wallet_out,0), 2) AS gross_paid,
    ROUND(COALESCE(rr.refund_amount,0) + COALESCE(wr.wallet_in,0), 2) AS refunds,
    ROUND(COALESCE(t.tax_paid,0), 2) AS tax_paid,
    ROUND(
      (COALESCE(rp.paid_amount,0) + COALESCE(ws.wallet_out,0))
      - (COALESCE(rr.refund_amount,0) + COALESCE(wr.wallet_in,0))
      + COALESCE(t.tax_paid,0)
    , 2) AS real_value
  FROM customer c
  LEFT JOIN rep_paid     rp ON rp.customerid = c.customerid
  LEFT JOIN rep_refund   rr ON rr.customerid = c.customerid
  LEFT JOIN wallet_spent ws ON ws.customerid = c.customerid
  LEFT JOIN wallet_refund wr ON wr.customerid = c.customerid
  LEFT JOIN tax           t ON t.customerid  = c.customerid
  ORDER BY real_value DESC, customer_name;
$$;


-- Q13) available values for a product's specifications
--          input: key, category, subcategory
--          output: list of available values (distinct)
CREATE OR REPLACE FUNCTION q13_possible_spec_values(
  p_category text,
  p_subcategory text,
  p_key text DEFAULT NULL
)
RETURNS TABLE(value text)
LANGUAGE sql
AS $$
  WITH filtered AS (
    SELECT specifications
    FROM product
    WHERE lower(category) = lower(p_category)
      AND lower(subcategory) = lower(p_subcategory)
      AND specifications IS NOT NULL
      AND specifications <> '{}'::jsonb
  ),
  chosen AS (
    SELECT COALESCE(
      p_key,
      (
        SELECT k FROM (
          SELECT k, COUNT(*) AS cnt
          FROM filtered f
          CROSS JOIN LATERAL jsonb_object_keys(f.specifications) k
          GROUP BY k
          ORDER BY cnt DESC, k
          LIMIT 1
        ) s
      )
    ) AS key_to_use
  ),
  vals AS (
    SELECT f.specifications -> c.key_to_use AS v
    FROM filtered f
    CROSS JOIN chosen c
    WHERE c.key_to_use IS NOT NULL
      AND f.specifications ? c.key_to_use
  )
  SELECT DISTINCT
    CASE
      WHEN jsonb_typeof(v) = 'string' THEN v #>> '{}'
      WHEN jsonb_typeof(v) IN ('number','boolean') THEN v::text
      ELSE v::text
    END
  FROM vals
  WHERE jsonb_typeof(v) <> 'array'

  UNION

  SELECT DISTINCT jsonb_array_elements_text(v)
  FROM vals
  WHERE jsonb_typeof(v) = 'array'
  ORDER BY 1;
$$;


-- Performance
-- EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM q2_favorite_products_in_range('2020-01-01','2020-02-01');
-- EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM q4_category_dependency('Electronics', 50);

CREATE INDEX IF NOT EXISTS ix_order_date ON "Order"(date);
-- index for join/group feedback on (orderid,productid) -> Q2
CREATE INDEX IF NOT EXISTS ix_feedback_order_product ON feedback(orderid, productid);

-- index for filtering category/subcategory on products -> Q1,Q4,Q10,Q13
CREATE INDEX IF NOT EXISTS ix_product_category_subcat ON product(category, subcategory, productid);

ANALYZE;

COMMIT;
\echo 'phase2_part3.sql done.'