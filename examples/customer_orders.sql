SELECT
    c.customer_id,
    c.signup_date,
    c.segment,
    o.order_id,
    o.net_revenue
FROM customers AS c
LEFT JOIN orders AS o
    ON c.customer_id = o.customer_id
WHERE c.signup_date >= '2026-01-01';
