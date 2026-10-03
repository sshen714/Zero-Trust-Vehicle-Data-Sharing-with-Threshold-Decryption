-- Run against the existing MySQL database with an account that has ALTER permission.
ALTER TABLE users
MODIFY COLUMN role ENUM(
    'owner', 'visitor', 'vendor', 'supervisor_a', 'supervisor_b', 'admin',
    'researcher', 'police'
) NOT NULL;
