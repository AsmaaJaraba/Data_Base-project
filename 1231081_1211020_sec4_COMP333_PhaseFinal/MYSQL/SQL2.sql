SELECT name, SUM(monthly_sales) AS total_sales
FROM branches
GROUP BY name
HAVING total_sales > 3000
ORDER BY total_sales DESC;
