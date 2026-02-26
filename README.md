# BDBKala - Relational Database System

**Design and Implementation of a Multi-Branch E-Commerce Database (PostgreSQL)**

> Developed by *Sara Ghazavi*
> Sharif University of Technology – Winter 1404

---

## 📝 Description

This project was developed as part of the *Database Design* course at Sharif University of Technology. It implements the complete migration of an e-commerce platform from CSV-based storage to a fully structured relational database system.

The system models a multi-branch online retail platform supporting order management, warehouse operations, shipping, loyalty programs, wallet transactions, BNPL credit, supplier management, return processing, and flexible product specifications.

The project covers the full database lifecycle, including conceptual modeling, relational schema design, SQL implementation, data integrity enforcement, performance optimization, and analytical query development.

---

## 🏗 Phase 1 - Data Modeling & Schema Design

### ✔ Conceptual Design
- Complete **EER diagram (Chen notation)**
- Iterative refinement for new business requirements
- Modeling of:
  - Orders and order items
  - Customers
  - Branches and branch managers
  - Suppliers and supply relationships
  - Wallet system
  - BNPL credit system
  - Loyalty program
  - Return processing
  - Product specifications using JSON

### ✔ Logical Design
- Fully normalized relational schema
- Primary and foreign key constraints
- Associative entities for many-to-many relationships
- Multi-branch architecture support
- JSON fields for dynamic product attributes

### ✔ DDL Implementation
- PostgreSQL SQL scripts
- Schema creation and table definitions
- Referential integrity enforcement
- Structured migration-ready design

---

## 🗄 Phase 2 - Data, Constraints & Operations

### ✔ Data Import & Generation
- CSV-to-table migration
- Synthetic data generation where required
- Wallet transaction history reconstruction logic

### ✔ Integrity Constraints

Implemented using:
- CHECK constraints
- FOREIGN KEY constraints
- TRIGGERS
- Transaction-safe logic

Examples include:
- Discount validation
- Valid order status transitions
- Wallet credit limit enforcement
- Branch-manager consistency rules
- Shipping method restrictions
- Return state progression validation

---

## 🔍 Advanced SQL Queries

Many operational and analytical queries were implemented, including:

- Weighted profit margin per subcategory
- Product popularity ranking within time intervals
- High-value new customer detection
- Product association analysis
- Delayed shipment identification
- Tax aggregation per customer
- BNPL credit eligibility evaluation
- Supplier optimization per branch
- Customer lifetime value calculation
- JSON-based product attribute extraction

---

## ⚡ Performance Optimization

- Query execution plan analysis using `EXPLAIN`
- Index design based on workload observation
- Performance comparison before and after indexing
- Optimization of computationally heavy analytical queries

---

## 👁 Views & Materialized Views

Designed views for:

- Pending warehouse orders
- Daily sales and profit summary (Materialized View)
- Branch-level customer access control
- Loyalty statistics overview
- Return management monitoring

---

## 🛠 Technical Stack

- **DBMS:** PostgreSQL  
- **Language:** SQL (DDL, DML, Triggers, Views, Indexes)  
- **Advanced Features Used:**
  - Triggers
  - Functions & Procedures
  - JSON data types
  - Indexing strategies
  - Materialized Views
  - Execution plan analysis

---

## 📚 Learning Outcomes

- Advanced relational database design
- Constraint enforcement at database level
- Business rule implementation using triggers
- Performance-aware SQL development
- Modeling complex real-world transactional systems

---

## 👩‍💻 Author

**Sara Ghazavi**
Sharif University of Technology
Course: Database Design – Winter 1404
