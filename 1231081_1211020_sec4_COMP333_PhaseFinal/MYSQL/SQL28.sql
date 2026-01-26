USE bzulib;
SELECT id, full_name, email 
FROM users
WHERE email IN (
  'admin_one@bzu.ps',
  'admin_two@bzu.ps',
  'admin_three@bzu.ps'
);

DELETE FROM users
WHERE email IN (
  'admin1@bzu.ps',
  'admin2@bzu.ps',
  'admin3@bzu.ps'
);
