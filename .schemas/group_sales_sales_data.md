# BigQuery Schema - Group Sales Data

## Tables

### sales_data

**Description**: Core sales transaction records with group and region information.

#### Columns

- `transaction_id` | STRING | Unique identifier for each transaction
- `group_id` | STRING | Identifier for the sales group
- `region` | STRING | Geographic region of the sale
- `amount` | FLOAT64 | Sale amount in dollars
- `quantity` | INTEGER | Number of items sold
- `sale_date` | DATE | Date of the transaction
- `created_at` | TIMESTAMP | Record creation timestamp
- `updated_at` | TIMESTAMP | Record last update timestamp
- `status` | STRING | Transaction status (COMPLETED, PENDING, CANCELLED)
- `category` | STRING | Product category
- `salesperson_id` | STRING | ID of the salesperson
- `customer_id` | STRING | ID of the customer

## Metadata

- **Dataset**: group_sales
- **Table**: sales_data
- **Row Count**: 1,000,000+
- **Update Frequency**: Daily
- **Created**: 2024-01-01
- **Last Updated**: 2024-12-31

## Indexes

- Clustered by: `group_id`, `sale_date`
- Partitioned by: `sale_date`

## Typical Queries

**Get sales by group for a date range:**
```sql
SELECT group_id, SUM(amount) as total_sales, COUNT(*) as transaction_count
FROM group_sales.sales_data
WHERE sale_date BETWEEN '2024-01-01' AND '2024-12-31'
GROUP BY group_id
ORDER BY total_sales DESC
```

**Get top performers by region:**
```sql
SELECT region, salesperson_id, SUM(amount) as total_sales
FROM group_sales.sales_data
WHERE status = 'COMPLETED'
GROUP BY region, salesperson_id
ORDER BY region, total_sales DESC
```
