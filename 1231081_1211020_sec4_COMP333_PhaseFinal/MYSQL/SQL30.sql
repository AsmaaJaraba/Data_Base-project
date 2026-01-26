USE bzulib;
SELECT DATABASE();
SELECT * FROM products;

SELECT * FROM orders;
USE bzulib;
SELECT email, role, status FROM users WHERE email='student@bzu.ps';
SELECT id, full_name, email, password, role, status FROM users;

