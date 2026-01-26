
USE bzulib;

CREATE TABLE IF NOT EXISTS branches (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
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

INSERT INTO branches (name,address,phone,manager_name,open_time,close_time,is_active,monthly_sales,staff_count) VALUES
('الفرع الرئيسي (الحرم الجامعي)','المكتبة المركزية، جامعة بيرزيت','022942000','محمد أحمد','08:00','20:00',1,5200,15),
('فرع كلية الهندسة','مبنى كلية الهندسة، جامعة بيرزيت','022942100','سارة خليل','09:00','19:00',1,3800,10);
