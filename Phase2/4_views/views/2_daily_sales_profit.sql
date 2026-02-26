CREATE MATERIALIZED VIEW mv_daily_sales_profit AS
SELECT
    DATE(o.date) AS sales_day,
    SUM(oi.quantity * COALESCE(oi.purchaseprice, 0))::numeric(14,2) AS total_sales,
    SUM(
        oi.quantity * (
            COALESCE(oi.purchaseprice, 0) - COALESCE(p.costprice, 0)
        )
    )::numeric(14,2) AS total_profit
FROM "Order" o
JOIN orderitem oi
    ON oi.orderid = o.orderid
JOIN product p
    ON p.productid = oi.productid
GROUP BY DATE(o.date)
ORDER BY sales_day;


CREATE UNIQUE INDEX mv_daily_sales_profit_day_idx
ON mv_daily_sales_profit (sales_day);
