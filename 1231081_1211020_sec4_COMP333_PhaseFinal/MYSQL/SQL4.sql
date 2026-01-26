SELECT
  p.name,
  oi.quantity,
  oi.unit_price
FROM order_items oi
JOIN products p ON p.id = oi.product_id
WHERE oi.order_id = 18;
