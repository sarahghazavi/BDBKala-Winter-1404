CREATE OR REPLACE VIEW vw_customer_loyalty_marketing AS
SELECT
    c.customerid,
    c.name AS customer_name,
    c.email,
    c.phone,

    -- total amount spent by customer
    COALESCE(SUM(oi.quantity * COALESCE(oi.purchaseprice, 0)), 0)::numeric(14,2) AS total_spent,

    -- computed loyalty points (example rule: 1 point per 10 currency units)
    FLOOR(
        COALESCE(SUM(oi.quantity * COALESCE(oi.purchaseprice, 0)), 0) / 10
    )::int AS loyalty_points_calculated,

    -- stored loyalty info from customer table
    c.totalpoints AS loyalty_points_stored,
    c.membershiptier
FROM customer c
LEFT JOIN "Order" o
    ON o.customerid = c.customerid
LEFT JOIN orderitem oi
    ON oi.orderid = o.orderid
GROUP BY
    c.customerid, c.name, c.email, c.phone, c.totalpoints, c.membershiptier;
