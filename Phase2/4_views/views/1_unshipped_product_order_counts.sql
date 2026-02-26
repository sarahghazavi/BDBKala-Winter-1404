CREATE OR REPLACE VIEW vw_unshipped_product_order_counts AS
SELECT
    p.productid,
    p.name AS product_name,
    COUNT(DISTINCT o.orderid) AS unshipped_order_count
FROM "Order" o
JOIN orderitem oi
    ON o.orderid = oi.orderid
JOIN product p
    ON oi.productid = p.productid
WHERE o.status IN ('Stocking', 'Pending Payment')
GROUP BY p.productid, p.name;
