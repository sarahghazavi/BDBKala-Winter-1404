CREATE OR REPLACE VIEW vw_branch_customers AS
SELECT DISTINCT
    b.branchid,
    b.name AS branch_name,
    c.customerid,
    c.name AS customer_name,
    c.age,
    c.gender,
    c.phone,
    c.email,
    c.incomelevel,
    c.creditlimit,
    c.membershiptier,
    c.totalpoints,
    c.taxstatus,
    c.nature,
    c.relationstatus
FROM "Order" o
JOIN branch b
    ON b.branchid = o.branchid
JOIN customer c
    ON c.customerid = o.customerid;
