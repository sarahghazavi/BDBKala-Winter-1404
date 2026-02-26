\set ON_ERROR_STOP on
\echo 'Running phase2_part2.sql ...'

BEGIN;

SET search_path TO public;

-- 0) PRE REPORT (we count violations before fixing them)

-- (C1) 0 <= discount <= 1
SELECT 'C1_bad_discount' AS check_name, COUNT(*) AS bad_rows
FROM product
WHERE discount IS NULL OR discount < 0 OR discount > 1;

-- (C1) email format
SELECT 'C1_bad_email' AS check_name, COUNT(*) AS bad_rows
FROM customer
WHERE email IS NOT NULL
  AND btrim(email) <> ''
  AND email !~* '^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$';

-- (C2) ship date must not be before order date
SELECT 'C2_bad_shipdate' AS check_name, COUNT(*) AS bad_rows
FROM shipment s
JOIN "Order" o ON o.shipmentid = s.shipmentid
WHERE s.shipdate IS NOT NULL AND s.shipdate < o.date;

-- (C3) item status must not be null
SELECT 'C3_null_itemstatus' AS check_name, COUNT(*) AS bad_rows
FROM orderitem
WHERE itemstatus IS NULL;

-- (C4) low income small business cannot be critical
SELECT 'C4_bad_priority' AS check_name, COUNT(*) AS bad_rows
FROM "Order" o
JOIN customer c ON c.customerid = o.customerid
WHERE lower(coalesce(o.priority,'')) = 'critical'
  AND lower(coalesce(c.nature,'')) = 'company_buyer'
  AND (
    CASE WHEN c.incomelevel ~ '^[0-9]+(\.[0-9]+)?$'
         THEN c.incomelevel::numeric
         ELSE NULL
    END
  ) < 60000;

-- (C5) large packages must be ground, box packages must be air
SELECT 'C5_bad_pack_method' AS check_name, COUNT(*) AS bad_rows
FROM shipment
WHERE
  (packagetype IN ('Envelope','Bubble') AND packagesize = 'Large' AND shipmethod <> 'Ground')
  OR
  (packagetype = 'Box' AND shipmethod = 'Ground');

-- (C6) wallet debt must not exceed credit limit
SELECT 'C6_bad_wallet_debt' AS check_name, COUNT(*) AS bad_rows
FROM customer
WHERE creditlimit IS NOT NULL
  AND balance < -creditlimit;

-- (C7) branches must have manager, a manager cannot lead more than one branch
SELECT 'C7_duplicate_manager' AS check_name, COUNT(*) AS bad_rows
FROM (
  SELECT managerid
  FROM branch
  GROUP BY managerid
  HAVING COUNT(*) > 1
) t;

-- (C9) return result domain
SELECT 'C9_bad_return_result' AS check_name, COUNT(*) AS bad_rows
FROM returnrequest
WHERE result IS NULL OR lower(result) NOT IN ('pending_review','approved','rejected');

-- (C10) rating must be in {1, 2, 3, 4, 5}
SELECT 'C10_bad_rating' AS check_name, COUNT(*) AS bad_rows
FROM feedback
WHERE rating IS NULL OR rating < 1 OR rating > 5;

-- (C10) comment length must be lower than 800
SELECT 'C10_long_comment' AS check_name, COUNT(*) AS bad_rows
FROM feedback
WHERE length(coalesce(comment,'')) >= 800;



-- 1) NORMALIZE & FIX

-- 1.0) trim common text fields to avoid hidden mismatches
UPDATE shipment
SET packagetype = NULLIF(btrim(packagetype), ''),
    packagesize = NULLIF(btrim(packagesize), ''),
    shipmethod  = NULLIF(btrim(shipmethod),  ''),
    shiptype    = NULLIF(btrim(shiptype),    '');

UPDATE "Order"
SET
  priority = NULLIF(btrim(priority), ''),
  status   = NULLIF(btrim(status), '');

UPDATE orderitem
SET itemstatus = NULLIF(btrim(itemstatus), '');

UPDATE customer
SET email = NULLIF(btrim(email), '');

UPDATE orderitem
SET quantity = 1
WHERE quantity IS NULL OR quantity <= 0;

-- 1.1) discount: null -> 0 (clamp to [0,1])
UPDATE product
SET discount = GREATEST(0, LEAST(COALESCE(discount,0), 1))
WHERE discount IS NULL OR discount < 0 OR discount > 1;

-- 1.2) invalid emails -> null
UPDATE customer
SET email = NULL
WHERE email IS NOT NULL
  AND email !~* '^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$';

-- 1.3) shipdate < order.date => set shipdate = order.date
UPDATE shipment s
SET shipdate = o.date
FROM "Order" o
WHERE o.shipmentid = s.shipmentid
  AND s.shipdate IS NOT NULL
  AND s.shipdate < o.date;

-- 1.4) orderitem.itemstatus: null -> 'Pending Payment' (earliest stage)
UPDATE orderitem
SET itemstatus = 'Pending Payment'
WHERE itemstatus IS NULL;

-- 1.4b) normalize itemstatus to the 4 stage domain (Pending Payment -> Stocking -> Shipped -> Received)
--       unknown => Stocking
UPDATE orderitem
SET itemstatus = CASE lower(itemstatus)
  WHEN 'pending payment' THEN 'Pending Payment'
  WHEN 'pending_payment' THEN 'Pending Payment'
  WHEN 'waiting payment' THEN 'Pending Payment'
  WHEN 'awaiting payment' THEN 'Pending Payment'

  WHEN 'stocking' THEN 'Stocking'
  WHEN 'processing' THEN 'Stocking'
  WHEN 'in process' THEN 'Stocking'
  WHEN 'unknown' THEN 'Stocking'

  WHEN 'shipped' THEN 'Shipped'
  WHEN 'sent' THEN 'Shipped'

  WHEN 'received' THEN 'Received'
  WHEN 'delivered' THEN 'Received'
  ELSE itemstatus
END;

-- remaining unexpected value => Stocking
UPDATE orderitem
SET itemstatus = 'Stocking'
WHERE itemstatus NOT IN ('Pending Payment','Stocking','Shipped','Received');

-- 1.4c) normalize "Order".status to the 4 stage domain too
UPDATE "Order"
SET status = CASE lower(status)
  WHEN 'pending payment' THEN 'Pending Payment'
  WHEN 'pending_payment' THEN 'Pending Payment'
  WHEN 'pending' THEN 'Pending Payment'
  WHEN 'waiting payment' THEN 'Pending Payment'
  WHEN 'awaiting payment' THEN 'Pending Payment'

  WHEN 'stocking' THEN 'Stocking'
  WHEN 'processing' THEN 'Stocking'
  WHEN 'in process' THEN 'Stocking'
  WHEN 'unknown' THEN 'Stocking'

  WHEN 'shipped' THEN 'Shipped'
  WHEN 'sent' THEN 'Shipped'

  WHEN 'received' THEN 'Received'
  WHEN 'delivered' THEN 'Received'
  ELSE status
END;

UPDATE "Order"
SET status = 'Pending Payment'
WHERE status IS NULL
   OR status NOT IN ('Pending Payment','Stocking','Shipped','Received');

-- 1.5) priority: if null => low
UPDATE "Order"
SET priority = 'Low'
WHERE priority IS NULL;

-- normalize priority to canonical case insensitive set
UPDATE "Order"
SET priority = CASE lower(priority)
  WHEN 'low' THEN 'Low'
  WHEN 'medium' THEN 'Medium'
  WHEN 'high' THEN 'High'
  WHEN 'urgent' THEN 'Urgent'
  WHEN 'critical' THEN 'Critical'
  ELSE priority
END;

-- unknown priority => low
UPDATE "Order"
SET priority = 'Low'
WHERE priority NOT IN ('Low','Medium','High','Urgent','Critical');

-- 1.6) downgrade critical -> urgent for low income company buyer
UPDATE "Order" o
SET priority = 'Urgent'
FROM customer c
WHERE c.customerid = o.customerid
  AND o.priority = 'Critical'
  AND lower(coalesce(c.nature,'')) = 'company_buyer'
  AND (
    CASE WHEN c.incomelevel ~ '^[0-9]+(\.[0-9]+)?$'
         THEN c.incomelevel::numeric
         ELSE NULL
    END
  ) < 60000;

-- 1.7) creditlimit null -> 0
UPDATE customer
SET creditlimit = 0
WHERE creditlimit IS NULL;

-- 1.8) clamp debt: balance < -creditlimit => balance = -creditlimit
UPDATE customer
SET balance = -creditlimit
WHERE balance < -creditlimit;

-- 1.9) returnrequest.result: null -> pending_review
UPDATE returnrequest
SET result = 'pending_review'
WHERE result IS NULL;

UPDATE returnrequest
SET result = CASE lower(result)
  WHEN 'pending_review' THEN 'pending_review'
  WHEN 'pending review' THEN 'pending_review'

  WHEN 'approved' THEN 'approved'
  WHEN 'accept' THEN 'approved'
  WHEN 'accepted' THEN 'approved'

  WHEN 'rejected' THEN 'rejected'
  WHEN 'reject' THEN 'rejected'
  ELSE result
END;

UPDATE returnrequest
SET result = 'pending_review'
WHERE lower(result) NOT IN ('pending_review','approved','rejected');

-- 1.10) feedback.rating clamp 1..5, null -> 1
UPDATE feedback
SET rating = GREATEST(1, LEAST(COALESCE(rating,1), 5))
WHERE rating IS NULL OR rating < 1 OR rating > 5;

-- 1.11) feedback.comment truncate to < 800
UPDATE feedback
SET comment = left(comment, 799)
WHERE length(coalesce(comment,'')) >= 800;


-- 1.12) packaging & shipping rules
--       envelope/bubble + large => must be ground
UPDATE shipment
SET shipmethod = 'Ground'
WHERE packagetype IN ('Envelope','Bubble')
  AND packagesize = 'Large'
  AND shipmethod <> 'Ground';

--       box => must be air
UPDATE shipment
SET shipmethod = CASE
  WHEN packagesize = 'Large' THEN 'Air (Freight)'
  ELSE 'Air (Post)'
END
WHERE packagetype = 'Box'
  AND shipmethod = 'Ground';


-- 1.13) duplicate managers: create new managers for extra branches
DO $$
DECLARE
  max_id bigint;
  r record;
BEGIN
  SELECT COALESCE(MAX(managerid),0) INTO max_id FROM manager;

  FOR r IN
    SELECT b.branchid, b.managerid, m.name,
           ROW_NUMBER() OVER (PARTITION BY b.managerid ORDER BY b.branchid) AS rn
    FROM branch b
    JOIN manager m ON m.managerid = b.managerid
    WHERE b.managerid IN (
      SELECT managerid
      FROM branch
      GROUP BY managerid
      HAVING COUNT(*) > 1
    )
    ORDER BY b.managerid, b.branchid
  LOOP
    IF r.rn > 1 THEN
      max_id := max_id + 1;

      INSERT INTO manager(managerid, name)
      VALUES (max_id, r.name || ' (auto)')
      ON CONFLICT (managerid) DO NOTHING;

      UPDATE branch
      SET managerid = max_id
      WHERE branchid = r.branchid;
    END IF;
  END LOOP;
END $$;


-- 2) ASSERT FIXES (abort cleanly if still inconsistent)

DO $$
DECLARE n int;
BEGIN
  SELECT COUNT(*) INTO n
  FROM shipment
  WHERE
    (packagetype IN ('Envelope','Bubble') AND packagesize='Large' AND shipmethod <> 'Ground')
    OR
    (packagetype='Box' AND shipmethod='Ground');

  IF n > 0 THEN
    RAISE EXCEPTION 'C5 still violated after fixes: % shipment rows', n;
  END IF;
END $$;


-- 3) CONSTRAINTS + TRIGGERS

-- ---------- (C1) discount & email ----------
ALTER TABLE product DROP CONSTRAINT IF EXISTS ck_product_discount_0_1;
ALTER TABLE product
  ADD CONSTRAINT ck_product_discount_0_1
  CHECK (discount >= 0 AND discount <= 1);

ALTER TABLE customer DROP CONSTRAINT IF EXISTS ck_customer_email_format;
ALTER TABLE customer
  ADD CONSTRAINT ck_customer_email_format
  CHECK (email IS NULL OR email ~* '^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$');


-- ---------- (C2) Order.date = insertion time + immutable ----------
ALTER TABLE "Order" ALTER COLUMN date SET DEFAULT now();

DROP FUNCTION IF EXISTS trg_order_force_now() CASCADE;
CREATE FUNCTION trg_order_force_now()
RETURNS trigger AS $$
BEGIN
  NEW.date := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS t_order_force_now ON "Order";
CREATE TRIGGER t_order_force_now
BEFORE INSERT ON "Order"
FOR EACH ROW EXECUTE FUNCTION trg_order_force_now();

DROP FUNCTION IF EXISTS trg_order_date_immutable() CASCADE;
CREATE FUNCTION trg_order_date_immutable()
RETURNS trigger AS $$
BEGIN
  IF NEW.date IS DISTINCT FROM OLD.date THEN
    RAISE EXCEPTION '"Order".date is immutable';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS t_order_date_immutable ON "Order";
CREATE TRIGGER t_order_date_immutable
BEFORE UPDATE ON "Order"
FOR EACH ROW EXECUTE FUNCTION trg_order_date_immutable();


-- shipdate must not be before order date (checked from both sides)
DROP FUNCTION IF EXISTS trg_order_shipdate_check() CASCADE;
CREATE FUNCTION trg_order_shipdate_check()
RETURNS trigger AS $$
DECLARE sd timestamp;
BEGIN
  SELECT shipdate INTO sd FROM shipment WHERE shipmentid = NEW.shipmentid;
  IF sd IS NOT NULL AND sd < NEW.date THEN
    RAISE EXCEPTION 'shipdate (%) < order.date (%)', sd, NEW.date;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS t_order_shipdate_check ON "Order";
CREATE TRIGGER t_order_shipdate_check
BEFORE INSERT OR UPDATE ON "Order"
FOR EACH ROW EXECUTE FUNCTION trg_order_shipdate_check();

DROP FUNCTION IF EXISTS trg_shipment_vs_order_date_check() CASCADE;
CREATE FUNCTION trg_shipment_vs_order_date_check()
RETURNS trigger AS $$
DECLARE od timestamp;
BEGIN
  IF NEW.shipdate IS NULL THEN
    RETURN NEW;
  END IF;

  SELECT o.date INTO od
  FROM "Order" o
  WHERE o.shipmentid = NEW.shipmentid
  ORDER BY o.date DESC
  LIMIT 1;

  IF od IS NOT NULL AND NEW.shipdate < od THEN
    RAISE EXCEPTION 'shipdate (%) < order.date (%)', NEW.shipdate, od;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS t_shipment_vs_order_date_check ON shipment;
CREATE TRIGGER t_shipment_vs_order_date_check
BEFORE INSERT OR UPDATE ON shipment
FOR EACH ROW EXECUTE FUNCTION trg_shipment_vs_order_date_check();


-- ---------- (C3) orderitem.itemstatus domain + non-decreasing transition ----------
ALTER TABLE orderitem ALTER COLUMN itemstatus SET NOT NULL;

ALTER TABLE orderitem DROP CONSTRAINT IF EXISTS ck_orderitem_itemstatus_domain;
ALTER TABLE orderitem
  ADD CONSTRAINT ck_orderitem_itemstatus_domain
  CHECK (itemstatus IN ('Pending Payment','Stocking','Shipped','Received'));

DROP FUNCTION IF EXISTS trg_orderitem_status_transition() CASCADE;
CREATE FUNCTION trg_orderitem_status_transition()
RETURNS trigger AS $$
DECLARE old_rank int; new_rank int;
BEGIN
  old_rank := CASE OLD.itemstatus
    WHEN 'Pending Payment' THEN 1
    WHEN 'Stocking' THEN 2
    WHEN 'Shipped' THEN 3
    WHEN 'Received' THEN 4
    ELSE 0 END;

  new_rank := CASE NEW.itemstatus
    WHEN 'Pending Payment' THEN 1
    WHEN 'Stocking' THEN 2
    WHEN 'Shipped' THEN 3
    WHEN 'Received' THEN 4
    ELSE 0 END;

  IF new_rank = 0 THEN
    RAISE EXCEPTION 'invalid itemstatus=%', NEW.itemstatus;
  END IF;

  IF new_rank < old_rank THEN
    RAISE EXCEPTION 'itemstatus cannot go backwards (% -> %)', OLD.itemstatus, NEW.itemstatus;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS t_orderitem_status_transition ON orderitem;
CREATE TRIGGER t_orderitem_status_transition
BEFORE UPDATE ON orderitem
FOR EACH ROW EXECUTE FUNCTION trg_orderitem_status_transition();

-- ---------- (C3b) "Order".status domain + non-decreasing transition ----------
ALTER TABLE "Order" ALTER COLUMN status SET DEFAULT 'Pending Payment';
ALTER TABLE "Order" ALTER COLUMN status SET NOT NULL;

ALTER TABLE "Order" DROP CONSTRAINT IF EXISTS ck_order_status_domain;
ALTER TABLE "Order"
  ADD CONSTRAINT ck_order_status_domain
  CHECK (status IN ('Pending Payment','Stocking','Shipped','Received'));

DROP FUNCTION IF EXISTS trg_order_status_transition() CASCADE;
CREATE FUNCTION trg_order_status_transition()
RETURNS trigger AS $$
DECLARE old_rank int; new_rank int;
BEGIN
  old_rank := CASE OLD.status
    WHEN 'Pending Payment' THEN 1
    WHEN 'Stocking' THEN 2
    WHEN 'Shipped' THEN 3
    WHEN 'Received' THEN 4
    ELSE 0 END;

  new_rank := CASE NEW.status
    WHEN 'Pending Payment' THEN 1
    WHEN 'Stocking' THEN 2
    WHEN 'Shipped' THEN 3
    WHEN 'Received' THEN 4
    ELSE 0 END;

  IF new_rank = 0 THEN
    RAISE EXCEPTION 'invalid "Order".status=%', NEW.status;
  END IF;

  IF new_rank < old_rank THEN
    RAISE EXCEPTION '"Order".status cannot go backwards (% -> %)', OLD.status, NEW.status;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS t_order_status_transition ON "Order";
CREATE TRIGGER t_order_status_transition
BEFORE UPDATE OF status ON "Order"
FOR EACH ROW EXECUTE FUNCTION trg_order_status_transition();


-- ---------- (C4) priority rule (company_buyer + low income cannot be critical) ----------
DROP FUNCTION IF EXISTS trg_order_priority_check() CASCADE;
CREATE FUNCTION trg_order_priority_check()
RETURNS trigger AS $$
DECLARE n text; inc_num numeric; p text;
BEGIN
  SELECT nature,
         CASE WHEN incomelevel ~ '^[0-9]+(\.[0-9]+)?$'
              THEN incomelevel::numeric
              ELSE NULL
         END
  INTO n, inc_num
  FROM customer
  WHERE customerid = NEW.customerid;

  p := lower(coalesce(NEW.priority,''));

  IF lower(coalesce(n,'')) = 'company_buyer'
     AND inc_num IS NOT NULL
     AND inc_num < 60000
     AND p = 'critical' THEN
    RAISE EXCEPTION 'low-income company_buyer cannot have Critical priority';
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS t_order_priority_check ON "Order";
CREATE TRIGGER t_order_priority_check
BEFORE INSERT OR UPDATE ON "Order"
FOR EACH ROW EXECUTE FUNCTION trg_order_priority_check();

-- ---------- (C4b) Order.priority domain ----------
ALTER TABLE "Order" ALTER COLUMN priority SET DEFAULT 'Low';
ALTER TABLE "Order" ALTER COLUMN priority SET NOT NULL;

ALTER TABLE "Order" DROP CONSTRAINT IF EXISTS ck_order_priority_domain;
ALTER TABLE "Order"
  ADD CONSTRAINT ck_order_priority_domain
  CHECK (lower(priority) IN ('low','medium','high','urgent','critical'));


-- ---------- (C5) shipment domains + packaging/method rule ----------
ALTER TABLE shipment DROP CONSTRAINT IF EXISTS ck_shipment_shipmethod_domain;
ALTER TABLE shipment
  ADD CONSTRAINT ck_shipment_shipmethod_domain
  CHECK (shipmethod IS NULL OR shipmethod IN ('Ground','Air (Post)','Air (Freight)'));

ALTER TABLE shipment DROP CONSTRAINT IF EXISTS ck_shipment_packagetype_domain;
ALTER TABLE shipment
  ADD CONSTRAINT ck_shipment_packagetype_domain
  CHECK (packagetype IS NULL OR packagetype IN ('Box','Bubble','Envelope'));

ALTER TABLE shipment DROP CONSTRAINT IF EXISTS ck_shipment_packagesize_domain;
ALTER TABLE shipment
  ADD CONSTRAINT ck_shipment_packagesize_domain
  CHECK (packagesize IS NULL OR packagesize IN ('Envelope','Small','Medium','Large'));

ALTER TABLE shipment DROP CONSTRAINT IF EXISTS ck_shipment_pack_method;
ALTER TABLE shipment
  ADD CONSTRAINT ck_shipment_pack_method
  CHECK (
    NOT (packagetype IN ('Envelope','Bubble') AND packagesize='Large' AND shipmethod <> 'Ground')
    AND
    NOT (packagetype='Box' AND shipmethod='Ground')
  );


-- ---------- (C6) wallet debt <= credit limit ----------
ALTER TABLE customer ALTER COLUMN creditlimit SET DEFAULT 0;

ALTER TABLE customer DROP CONSTRAINT IF EXISTS ck_customer_creditlimit_nonneg;
ALTER TABLE customer
  ADD CONSTRAINT ck_customer_creditlimit_nonneg
  CHECK (creditlimit >= 0);

ALTER TABLE customer DROP CONSTRAINT IF EXISTS ck_customer_balance_vs_creditlimit;
ALTER TABLE customer
  ADD CONSTRAINT ck_customer_balance_vs_creditlimit
  CHECK (balance >= -creditlimit);


-- ---------- (C7) each manager leads at most one branch ----------
ALTER TABLE branch DROP CONSTRAINT IF EXISTS uq_branch_managerid;
ALTER TABLE branch
  ADD CONSTRAINT uq_branch_managerid UNIQUE (managerid);


-- ---------- (C8) deleting a branch must not delete its orders
DROP FUNCTION IF EXISTS trg_branch_delete_preserve_orders() CASCADE;
CREATE FUNCTION trg_branch_delete_preserve_orders()
RETURNS trigger AS $$
BEGIN
  -- we ensure tombstone manager/branch exist
  INSERT INTO manager(managerid, name)
  VALUES (-1, 'DELETED MANAGER')
  ON CONFLICT (managerid) DO NOTHING;

  INSERT INTO branch(branchid, managerid, name, phone, address, totalsales)
  VALUES (-1, -1, 'DELETED BRANCH', NULL, NULL, 0)
  ON CONFLICT (branchid) DO NOTHING;

  -- we anonymize customers who have orders in this branch and nowhere else
  UPDATE customer c
  SET phone = NULL,
      email = NULL,
      gender = NULL,
      age = NULL,
      incomelevel = NULL,
      taxstatus = NULL,
      nature = NULL,
      relationstatus = NULL,
      name = 'DELETED_' || c.customerid
  WHERE EXISTS (
      SELECT 1 FROM "Order" o
      WHERE o.customerid = c.customerid
        AND o.branchid = OLD.branchid
    )
    AND NOT EXISTS (
      SELECT 1 FROM "Order" o2
      WHERE o2.customerid = c.customerid
        AND o2.branchid <> OLD.branchid
    );

  -- we preserve orders and move them to tombstone branch
  UPDATE "Order"
  SET branchid = -1
  WHERE branchid = OLD.branchid;

  -- we remove branch inventory rows
  DELETE FROM stocks   WHERE branchid = OLD.branchid;
  DELETE FROM supplies WHERE branchid = OLD.branchid;

  RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS t_branch_delete_preserve_orders ON branch;
CREATE TRIGGER t_branch_delete_preserve_orders
BEFORE DELETE ON branch
FOR EACH ROW EXECUTE FUNCTION trg_branch_delete_preserve_orders();


-- ---------- (C9) returnrequest result transitions ----------
ALTER TABLE returnrequest ALTER COLUMN result SET DEFAULT 'pending_review';
ALTER TABLE returnrequest ALTER COLUMN result SET NOT NULL;

ALTER TABLE returnrequest DROP CONSTRAINT IF EXISTS ck_returnrequest_result_domain;
ALTER TABLE returnrequest
  ADD CONSTRAINT ck_returnrequest_result_domain
  CHECK (lower(result) IN ('pending_review','approved','rejected'));

DROP FUNCTION IF EXISTS trg_returnrequest_transition() CASCADE;
CREATE FUNCTION trg_returnrequest_transition()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF lower(OLD.result) IN ('approved','rejected')
       AND lower(NEW.result) <> lower(OLD.result) THEN
      RAISE EXCEPTION 'final return status cannot change (% -> %)', OLD.result, NEW.result;
    END IF;
  END IF;

  IF lower(NEW.result) = 'pending_review' THEN
    NEW.decisiondate := NULL;
  ELSE
    IF NEW.decisiondate IS NULL THEN
      NEW.decisiondate := now();
    END IF;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS t_returnrequest_transition ON returnrequest;
CREATE TRIGGER t_returnrequest_transition
BEFORE INSERT OR UPDATE ON returnrequest
FOR EACH ROW EXECUTE FUNCTION trg_returnrequest_transition();


-- ---------- (C10) feedback rating + comment length ----------
ALTER TABLE feedback ALTER COLUMN rating SET NOT NULL;

ALTER TABLE feedback DROP CONSTRAINT IF EXISTS ck_feedback_rating_1_5;
ALTER TABLE feedback
  ADD CONSTRAINT ck_feedback_rating_1_5
  CHECK (rating BETWEEN 1 AND 5);

ALTER TABLE feedback DROP CONSTRAINT IF EXISTS ck_feedback_comment_len;
ALTER TABLE feedback
  ADD CONSTRAINT ck_feedback_comment_len
  CHECK (length(coalesce(comment,'')) < 800);


-- EXTRA CONSTRAINTS (additional rules)

-- quantity must be positive
ALTER TABLE orderitem DROP CONSTRAINT IF EXISTS ck_orderitem_quantity_positive;
ALTER TABLE orderitem
  ADD CONSTRAINT ck_orderitem_quantity_positive
  CHECK (quantity > 0);

-- non-negative costs
ALTER TABLE product DROP CONSTRAINT IF EXISTS ck_product_costprice_nonneg;
ALTER TABLE product
  ADD CONSTRAINT ck_product_costprice_nonneg
  CHECK (costprice IS NULL OR costprice >= 0);

ALTER TABLE shipment DROP CONSTRAINT IF EXISTS ck_shipment_shippingcost_nonneg;
ALTER TABLE shipment
  ADD CONSTRAINT ck_shipment_shippingcost_nonneg
  CHECK (shippingcost >= 0);


COMMIT;


-- POST-REPORT (we count violations after fixing them)
SELECT 'POST_C1_bad_discount' AS check_name, COUNT(*) AS bad_rows
FROM product
WHERE discount IS NULL OR discount < 0 OR discount > 1;

SELECT 'POST_C1_bad_email' AS check_name, COUNT(*) AS bad_rows
FROM customer
WHERE email IS NOT NULL
  AND btrim(email) <> ''
  AND email !~* '^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$';

SELECT 'POST_C2_bad_shipdate' AS check_name, COUNT(*) AS bad_rows
FROM shipment s
JOIN "Order" o ON o.shipmentid = s.shipmentid
WHERE s.shipdate IS NOT NULL AND s.shipdate < o.date;

SELECT 'POST_C3_null_itemstatus' AS check_name, COUNT(*) AS bad_rows
FROM orderitem
WHERE itemstatus IS NULL;

-- (NEW) Order.status check
SELECT 'POST_C3b_bad_order_status' AS check_name, COUNT(*) AS bad_rows
FROM "Order"
WHERE status IS NULL OR status NOT IN ('Pending Payment','Stocking','Shipped','Received');

SELECT 'POST_C4_bad_priority' AS check_name, COUNT(*) AS bad_rows
FROM "Order" o
JOIN customer c ON c.customerid = o.customerid
WHERE lower(coalesce(o.priority,'')) = 'critical'
  AND lower(coalesce(c.nature,'')) = 'company_buyer'
  AND (
    CASE WHEN c.incomelevel ~ '^[0-9]+(\.[0-9]+)?$'
         THEN c.incomelevel::numeric
         ELSE NULL
    END
  ) < 60000;

SELECT 'POST_C5_bad_pack_method' AS check_name, COUNT(*) AS bad_rows
FROM shipment
WHERE
  (packagetype IN ('Envelope','Bubble') AND packagesize = 'Large' AND shipmethod <> 'Ground')
  OR
  (packagetype = 'Box' AND shipmethod = 'Ground');

SELECT 'POST_C6_bad_wallet_debt' AS check_name, COUNT(*) AS bad_rows
FROM customer
WHERE creditlimit IS NOT NULL
  AND balance < -creditlimit;

SELECT 'POST_C7_duplicate_manager' AS check_name, COUNT(*) AS bad_rows
FROM (
  SELECT managerid
  FROM branch
  GROUP BY managerid
  HAVING COUNT(*) > 1
) t;

SELECT 'POST_C9_bad_return_result' AS check_name, COUNT(*) AS bad_rows
FROM returnrequest
WHERE result IS NULL OR lower(result) NOT IN ('pending_review','approved','rejected');

SELECT 'POST_C10_bad_rating' AS check_name, COUNT(*) AS bad_rows
FROM feedback
WHERE rating IS NULL OR rating < 1 OR rating > 5;

SELECT 'POST_C10_long_comment' AS check_name, COUNT(*) AS bad_rows
FROM feedback
WHERE length(coalesce(comment,'')) >= 800;