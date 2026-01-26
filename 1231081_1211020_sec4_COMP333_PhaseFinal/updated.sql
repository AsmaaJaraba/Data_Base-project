DROP DATABASE IF EXISTS bzulib;
CREATE DATABASE IF NOT EXISTS bzulib;
USE bzulib;

CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  full_name VARCHAR(120) NOT NULL,
  email VARCHAR(120) NOT NULL UNIQUE,
  password VARCHAR(255) NOT NULL,
  role ENUM('student','admin') NOT NULL DEFAULT 'student',
  status ENUM('active','blocked') NOT NULL DEFAULT 'active',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categories (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(80) NOT NULL UNIQUE
);


CREATE TABLE IF NOT EXISTS branches (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  city VARCHAR(80),              
  address VARCHAR(255),
  phone VARCHAR(50),
  manager_name VARCHAR(120),
  open_time TIME,
  close_time TIME,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  monthly_sales DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  staff_count INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(200) NOT NULL,
  description TEXT,
  price DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  product_type ENUM('stationery','service','book','ebook') NOT NULL DEFAULT 'stationery',
  category_id INT NULL,
  image_filename VARCHAR(255),
  is_available ENUM('yes','no') NOT NULL DEFAULT 'yes',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

  stock INT NOT NULL DEFAULT 0,
  min_stock INT NOT NULL DEFAULT 10,
  last_restock DATETIME NULL,

  CONSTRAINT fk_products_category
    FOREIGN KEY (category_id) REFERENCES categories(id)
    ON UPDATE CASCADE
    ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS orders (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  order_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status ENUM('pending','processing','completed','canceled') NOT NULL DEFAULT 'pending',
  total_price DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  notes TEXT,

  CONSTRAINT fk_orders_user
    FOREIGN KEY (user_id) REFERENCES users(id)
    ON UPDATE CASCADE
    ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS order_items (
  order_id INT NOT NULL,
  product_id INT NOT NULL,
  quantity INT NOT NULL DEFAULT 1,
  unit_price DECIMAL(10,2) NOT NULL DEFAULT 0.00,

  PRIMARY KEY (order_id, product_id),

  CONSTRAINT fk_order_items_order
    FOREIGN KEY (order_id) REFERENCES orders(id)
    ON UPDATE CASCADE
    ON DELETE CASCADE,

  CONSTRAINT fk_order_items_product
    FOREIGN KEY (product_id) REFERENCES products(id)
    ON UPDATE CASCADE
    ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS favorites (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  product_id INT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

  UNIQUE KEY uniq_user_product (user_id, product_id),

  CONSTRAINT fk_favorites_user
    FOREIGN KEY (user_id) REFERENCES users(id)
    ON UPDATE CASCADE
    ON DELETE CASCADE,

  CONSTRAINT fk_favorites_product
    FOREIGN KEY (product_id) REFERENCES products(id)
    ON UPDATE CASCADE
    ON DELETE CASCADE
);

INSERT INTO users (full_name, email, password, role, status) VALUES
('Admin User',   'admin@bzu.ps',   '123', 'admin',   'active'),
('Ahmed Student','student@bzu.ps', '123', 'student', 'active');

INSERT INTO branches
(name, city, address, phone, manager_name, open_time, close_time, is_active, monthly_sales, staff_count) VALUES
('الفرع الرئيسي (الحرم الجامعي)', 'بيرزيت', 'المكتبة المركزية، جامعة بيرزيت', '022942000', 'محمد أحمد', '08:00:00', '20:00:00', 1, 5200, 15),
('فرع كلية الهندسة', 'بيرزيت', 'مبنى كلية الهندسة، جامعة بيرزيت', '022942100', 'سارة خليل', '09:00:00', '19:00:00', 1, 3800, 10);
