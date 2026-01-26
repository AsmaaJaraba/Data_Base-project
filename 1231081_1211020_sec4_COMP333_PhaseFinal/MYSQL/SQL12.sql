SELECT
  SUM(stock * price) AS inventory_value
FROM products
WHERE is_available = 'yes';
