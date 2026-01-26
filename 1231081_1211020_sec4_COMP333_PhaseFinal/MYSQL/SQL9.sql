SELECT
  o.id AS order_id,
  u.full_name,
  o.status,
  o.order_date,
  o.total_price
FROM orders o
JOIN users u ON u.id = o.user_id
ORDER BY o.order_date DESC;
