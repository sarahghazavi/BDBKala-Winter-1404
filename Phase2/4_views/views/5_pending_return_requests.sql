CREATE OR REPLACE VIEW vw_pending_return_requests AS
SELECT
    rr.returnid,
    rr.orderid,
    rr.productid,
    p.name AS product_name,

    rr.requestdate,
    rr.decisiondate,
    rr.result,
    rr.reason,

    o.date     AS order_date,
    o.status   AS order_status,
    o.priority AS order_priority,
    o.branchid
FROM returnrequest rr
JOIN "Order" o
    ON o.orderid = rr.orderid
JOIN product p
    ON p.productid = rr.productid
WHERE rr.result IS NULL
   OR rr.decisiondate IS NULL;
