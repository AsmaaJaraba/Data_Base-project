SHOW DATABASES;
USE bzulib;
SELECT id, full_name, email, password, role, status FROM users;
INSERT INTO users (full_name, email, password, role, status) VALUES
('Admin User',   'admin@bzu.ps',   '123', 'admin',   'active'),

('Ahmed Student','student@bzu.ps', '123', 'student', 'active');


