USE bzulib;
SELECT
  o.id AS order_id,
  SUM(oi.quantity * oi.unit_price) AS total
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
GROUP BY o.id
HAVING total > 100
ORDER BY total DESC;
