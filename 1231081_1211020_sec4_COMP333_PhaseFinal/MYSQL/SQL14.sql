SELECT
  p.id,
  p.name,
  p.stock,
  p.min_stock
FROM products p
GROUP BY p.id, p.name, p.stock, p.min_stock
HAVING p.stock <= p.min_stock
ORDER BY p.stock ASC;
