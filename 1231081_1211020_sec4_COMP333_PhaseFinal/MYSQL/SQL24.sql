SELECT
  o.id          AS order_id,
  u.full_name   AS customer_name,
  u.email       AS customer_email,
  o.status,
  o.total_price,
  o.order_date,
  o.notes
FROM orders o
JOIN users u ON u.id = o.user_id
ORDER BY o.order_date DESC, o.id DESC;
