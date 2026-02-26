\set ON_ERROR_STOP off

SELECT MIN(productid)  AS p1 FROM product;
SELECT MIN(customerid) AS c1 FROM customer;
SELECT MIN(branchid)   AS b1 FROM branch;
SELECT MIN(shipmentid) AS s1 FROM shipment;

-- 1) C1: product.discount out of range
BEGIN;
SAVEPOINT sp1;
UPDATE product SET discount = 2 WHERE productid = (SELECT MIN(productid) FROM product);
ROLLBACK TO sp1;
COMMIT;

-- 2) C1: bad email
BEGIN;
SAVEPOINT sp2;
UPDATE customer SET email = 'not-an-email' WHERE customerid = (SELECT MIN(customerid) FROM customer);
ROLLBACK TO sp2;
COMMIT;

-- 3) C3: orderitem status backward
BEGIN;
SAVEPOINT sp3;
UPDATE orderitem
SET itemstatus = 'Received'
WHERE orderid = (SELECT MIN(orderid) FROM orderitem);

-- now try to go backwards => should fail
UPDATE orderitem
SET itemstatus = 'Stocking'
WHERE orderid = (SELECT MIN(orderid) FROM orderitem);
ROLLBACK TO sp3;
COMMIT;

-- 4) C5: invalid packaging rule
BEGIN;
SAVEPOINT sp4;
UPDATE shipment
SET packagetype='Envelope', packagesize='Large', shipmethod='Air (Post)'
WHERE shipmentid = (SELECT MIN(shipmentid) FROM shipment);
ROLLBACK TO sp4;
COMMIT;

-- 5) C6: wallet debt below -creditlimit
BEGIN;
SAVEPOINT sp5;
UPDATE customer
SET creditlimit = 100, balance = -200
WHERE customerid = (SELECT MIN(customerid) FROM customer);
ROLLBACK TO sp5;
COMMIT;

-- 6) C7: one manager for two branches
BEGIN;
SAVEPOINT sp6;
UPDATE branch
SET managerid = (SELECT MIN(managerid) FROM manager)
WHERE branchid IN (SELECT branchid FROM branch ORDER BY branchid LIMIT 2);
ROLLBACK TO sp6;
COMMIT;

-- 7) C9: final return result cannot change
BEGIN;
SAVEPOINT sp7;
UPDATE returnrequest
SET result='approved'
WHERE returnid = (SELECT MIN(returnid) FROM returnrequest);

-- should fail
UPDATE returnrequest
SET result='rejected'
WHERE returnid = (SELECT MIN(returnid) FROM returnrequest);
ROLLBACK TO sp7;
COMMIT;