INSERT INTO products (name, description, price, product_type, category_id, is_available) VALUES
-- هندسة
('ميكانيكا هندسية 1', 'أساسيات الاستاتيكا والديناميكا', 55.00, 'book',
 (SELECT id FROM categories WHERE name='هندسة' LIMIT 1), 'yes'),
('دوائر كهربائية', 'تحليل الدوائر الكهربائية مع أمثلة محلولة', 60.00, 'book',
 (SELECT id FROM categories WHERE name='هندسة' LIMIT 1), 'yes'),

-- طب
('تشريح الإنسان', 'مرجع مبسط لطلاب الطب والعلوم الصحية', 75.00, 'book',
 (SELECT id FROM categories WHERE name='طب' LIMIT 1), 'yes'),
('علم الأدوية', 'مبادئ فارماكولوجي + أسئلة تدريبية', 80.00, 'book',
 (SELECT id FROM categories WHERE name='طب' LIMIT 1), 'yes'),

-- علوم
('كيمياء عامة', 'مفاهيم الكيمياء الأساسية والتجارب', 50.00, 'book',
 (SELECT id FROM categories WHERE name='علوم' LIMIT 1), 'yes'),
('فيزياء عامة', 'قوانين الفيزياء مع مسائل متنوعة', 48.00, 'book',
 (SELECT id FROM categories WHERE name='علوم' LIMIT 1), 'yes'),

-- آداب
('مدخل إلى علم النفس', 'مبادئ علم النفس ونظرياته', 40.00, 'book',
 (SELECT id FROM categories WHERE name='آداب' LIMIT 1), 'yes'),
('مهارات الكتابة الأكاديمية', 'كتابة أبحاث وتقارير جامعية', 35.00, 'book',
 (SELECT id FROM categories WHERE name='آداب' LIMIT 1), 'yes'),

-- حاسوب
('مقدمة في البرمجة (Python)', 'أساسيات بايثون وتمارين عملية', 58.00, 'book',
 (SELECT id FROM categories WHERE name='حاسوب' LIMIT 1), 'yes'),
('هياكل البيانات', 'Stacks/Queues/Trees مع تطبيقات', 65.00, 'book',
 (SELECT id FROM categories WHERE name='حاسوب' LIMIT 1), 'yes'),

-- إدارة
('مبادئ المحاسبة', 'محاسبة مالية للمبتدئين', 45.00, 'book',
 (SELECT id FROM categories WHERE name='إدارة' LIMIT 1), 'yes'),
('إدارة الأعمال', 'مفاهيم الإدارة والتخطيط والتنظيم', 47.00, 'book',
 (SELECT id FROM categories WHERE name='إدارة' LIMIT 1), 'yes');
SELECT p.id, p.name, p.price, p.product_type, c.name AS category
FROM products p
LEFT JOIN categories c ON p.category_id = c.id
ORDER BY p.id DESC;
