SELECT product_type, COUNT(*) AS low_stock_count
FROM products
WHERE stock <= min_stock
GROUP BY product_type
HAVING COUNT(*) > 0
ORDER BY low_stock_count DESC;
