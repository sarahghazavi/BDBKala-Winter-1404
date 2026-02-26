CREATE TABLE Manager (
  ManagerID   BIGINT PRIMARY KEY,
  name        TEXT NOT NULL
);

CREATE TABLE Branch (
  BranchID     BIGINT PRIMARY KEY,
  ManagerID    BIGINT NOT NULL,
  name         TEXT NOT NULL,
  phone        TEXT,
  address      TEXT,
  totalSales   NUMERIC(14,2) DEFAULT 0,

  CONSTRAINT fk_branch_manager
    FOREIGN KEY (ManagerID) REFERENCES Manager(ManagerID)
);

CREATE TABLE shipment (
  ShipmentID     BIGINT PRIMARY KEY,
  postalCode     TEXT,
  DestCity       TEXT,
  DestRegion     TEXT,
  ShippingCost   NUMERIC(12,2) DEFAULT 0,
  PackageState   TEXT,
  PackageSize    TEXT,
  PackageType    TEXT,
  ShipDate       TIMESTAMP,
  ShipMethod     TEXT,
  ShipType       TEXT,
  Address        TEXT
);

CREATE TABLE Customer (
  customerID      BIGINT PRIMARY KEY,
  walletID        BIGINT UNIQUE,
  balance         NUMERIC(14,2) DEFAULT 0,
  name            TEXT NOT NULL,
  age             INT,
  gender          TEXT,
  phone           TEXT,
  email           TEXT,
  incomeLevel     TEXT,
  creditLimit     NUMERIC(14,2),
  MemberShipTier  TEXT,
  totalPoints     INT DEFAULT 0,
  taxStatus       TEXT,
  nature          TEXT,
  relationStatus  TEXT
);

CREATE TABLE WalletTransaction (
  TransactionID BIGINT PRIMARY KEY,
  WalletID      BIGINT NOT NULL,
  amount        NUMERIC(14,2) NOT NULL,
  date          TIMESTAMP NOT NULL,
  type          TEXT NOT NULL,

  CONSTRAINT fk_wallettransaction_wallet
    FOREIGN KEY (WalletID) REFERENCES Customer(walletID)
);

CREATE TABLE Supplier (
  supplierID BIGINT PRIMARY KEY,
  name       TEXT NOT NULL,
  phone      TEXT,
  address    TEXT
);


CREATE TABLE Product (
  productID        BIGINT PRIMARY KEY,      -- inferred PK
  name             TEXT NOT NULL,
  category         TEXT,
  subcategory      TEXT,
  taxStatus        TEXT,
  CostPrice        NUMERIC(14,2),
  Specifications   JSONB,
  discount         NUMERIC(6,2) DEFAULT 0
);

CREATE TABLE "Order" (
  OrderID          BIGINT PRIMARY KEY,
  CustomerID       BIGINT NOT NULL,
  ShipmentID       BIGINT NOT NULL,
  BranchID         BIGINT NOT NULL,
  status           TEXT,
  priority         TEXT,
  date             TIMESTAMP NOT NULL,
  loyalityDiscount NUMERIC(6,2) DEFAULT 0,
  earned_points    INT DEFAULT 0,

  CONSTRAINT fk_order_customer
    FOREIGN KEY (CustomerID) REFERENCES Customer(customerID),

  CONSTRAINT fk_order_shipment
    FOREIGN KEY (ShipmentID) REFERENCES shipment(ShipmentID),

  CONSTRAINT fk_order_branch
    FOREIGN KEY (BranchID) REFERENCES Branch(BranchID)
);

CREATE TABLE Repayment (
  repaymentID  BIGINT PRIMARY KEY,
  orderID      BIGINT NOT NULL,
  amount       NUMERIC(14,2) NOT NULL,
  date         TIMESTAMP NOT NULL,
  method       TEXT,

  CONSTRAINT fk_repayment_order
    FOREIGN KEY (orderID) REFERENCES "Order"(OrderID)
);


CREATE TABLE Supplies (
  branchID     BIGINT NOT NULL,
  supplierID   BIGINT NOT NULL,
  productID    BIGINT NOT NULL,
  supplyPrice  NUMERIC(14,2),
  supplyTime   TIMESTAMP,

  PRIMARY KEY (branchID, supplierID, productID),

  CONSTRAINT fk_supplies_branch
    FOREIGN KEY (branchID) REFERENCES Branch(BranchID),

  CONSTRAINT fk_supplies_supplier
    FOREIGN KEY (supplierID) REFERENCES Supplier(supplierID),

  CONSTRAINT fk_supplies_product
    FOREIGN KEY (productID) REFERENCES Product(productID)
);

CREATE TABLE Stocks (
  branchID   BIGINT NOT NULL,
  productID  BIGINT NOT NULL,
  salePrice  NUMERIC(14,2),
  Quantity   INT DEFAULT 0,

  PRIMARY KEY (branchID, productID),

  CONSTRAINT fk_stocks_branch
    FOREIGN KEY (branchID) REFERENCES Branch(BranchID),

  CONSTRAINT fk_stocks_product
    FOREIGN KEY (productID) REFERENCES Product(productID)
);

CREATE TABLE orderItem (
  orderID        BIGINT NOT NULL,
  productID      BIGINT NOT NULL,
  itemStatus     TEXT,
  Quantity       INT NOT NULL DEFAULT 1,
  PurchasePrice  NUMERIC(14,2),
  paymentMethod  TEXT,

  PRIMARY KEY (orderID, productID),

  CONSTRAINT fk_orderitem_order
    FOREIGN KEY (orderID) REFERENCES "Order"(OrderID),

  CONSTRAINT fk_orderitem_product
    FOREIGN KEY (productID) REFERENCES Product(productID)
);


CREATE TABLE returnRequest (
  returnID      BIGINT PRIMARY KEY,
  orderID       BIGINT NOT NULL,
  productID     BIGINT NOT NULL,
  decisionDate  TIMESTAMP,
  result        TEXT,
  reason        TEXT,
  requestDate   TIMESTAMP NOT NULL,

  CONSTRAINT fk_return_order
    FOREIGN KEY (orderID) REFERENCES "Order"(OrderID),

  CONSTRAINT fk_return_product
    FOREIGN KEY (productID) REFERENCES Product(productID)
);

CREATE TABLE Feedback (
  feedbackID    BIGINT PRIMARY KEY,   -- inferred PK (was missing ..)
  orderID       BIGINT NOT NULL,
  productID     BIGINT NOT NULL,
  rating        INT,
  comment       TEXT,
  isPublic      BOOLEAN DEFAULT TRUE,
  imageString   TEXT,

  CONSTRAINT fk_feedback_order
    FOREIGN KEY (orderID) REFERENCES "Order"(OrderID),

  CONSTRAINT fk_feedback_product
    FOREIGN KEY (productID) REFERENCES Product(productID)
);



SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_type = 'BASE TABLE'
  AND table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY table_schema, table_name;