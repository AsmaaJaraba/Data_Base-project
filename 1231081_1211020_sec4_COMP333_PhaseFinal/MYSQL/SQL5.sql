SELECT
  SUM(oi.quantity * oi.unit_price) AS cart_total
FROM order_items oi
WHERE oi.order_id = (
  SELECT id
  FROM orders
  WHERE user_id = 2 AND status = 'pending'
  ORDER BY id DESC
  LIMIT 1
);
