SELECT
  o.id, o.status, o.total_price, o.order_date, o.notes
FROM orders o
WHERE o.user_id = 1
ORDER BY o.order_date DESC, o.id DESC;
