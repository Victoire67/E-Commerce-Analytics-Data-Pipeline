-- =============================================================================
-- Small, hand-written sample dataset (run after 01_schema.sql on empty tables).
-- For the large benchmark dataset use: poetry run python scripts/seed_data.py
--
--   docker exec -i ecommerce-postgres psql -U ecommerce_user -d ecommerce < sql/03_sample_data.sql
-- =============================================================================

BEGIN;

INSERT INTO categories (name, description) VALUES
    ('Clothing',       'Apparel and footwear'),
    ('Electronics',    'Gadgets and accessories'),
    ('Home & Kitchen', 'Kitchenware and home decor'),
    ('Books',          'Printed and digital books');

INSERT INTO customers (first_name, last_name, email, phone, country) VALUES
    ('Amina',   'Uwase',     'amina.uwase@example.com',     '+250 788 000 001', 'Rwanda'),
    ('Jean',    'Mugisha',   'jean.mugisha@example.com',    '+250 788 000 002', 'Rwanda'),
    ('Grace',   'Hopper',    'grace.hopper@example.com',    '+1 555 0100',      'United States'),
    ('Kofi',    'Mensah',    'kofi.mensah@example.com',     '+233 20 000 0004', 'Ghana'),
    ('Lena',    'Schmidt',   'lena.schmidt@example.com',    '+49 30 000005',    'Germany'),
    ('Carlos',  'Ruiz',      'carlos.ruiz@example.com',     '+34 600 000 006',  'Spain');

-- Category ids follow insertion order above: 1 Clothing, 2 Electronics, 3 Home & Kitchen, 4 Books.
INSERT INTO products (sku, name, category_id, price, stock_quantity, metadata) VALUES
    ('CLO-00001', 'Classic T-Shirt',      1,  19.99, 120,
        '{"colors": ["black", "white", "red"], "sizes": ["S", "M", "L", "XL"], "material": "cotton"}'),
    ('CLO-00002', 'Urban Hoodie',         1,  49.90,  60,
        '{"colors": ["grey", "navy"], "sizes": ["M", "L", "XL"], "material": "polyester"}'),
    ('CLO-00003', 'Retro Sneakers',       1,  89.00,  35,
        '{"colors": ["white"], "sizes": ["S", "M", "L"], "material": "leather"}'),
    ('ELE-00004', 'Pro Headphones',       2, 149.00,  40,
        '{"brand": "Voltix", "warranty_months": 24, "specs": {"wireless": true, "battery_hours": 30}, "colors": ["black"]}'),
    ('ELE-00005', 'Smart Watch',          2, 229.99,  25,
        '{"brand": "Helio", "warranty_months": 12, "specs": {"wireless": true, "battery_hours": 48}, "colors": ["black", "blue"]}'),
    ('HOM-00006', 'Eco Mug',              3,   8.50, 300,
        '{"brand": "Acorn", "colors": ["white", "green"], "eco_friendly": true}'),
    ('HOM-00007', 'Deluxe Blender',       3,  79.00,  15,
        '{"brand": "Orbis", "colors": ["red"], "eco_friendly": false}'),
    ('BOO-00008', 'Essential SQL Guide',  4,  34.00,  80,
        '{"author": "E. F. Codd", "pages": 412, "format": "paperback", "language": "en"}');

INSERT INTO orders (customer_id, order_date, status) VALUES
    (1, now() - interval '30 days', 'delivered'),
    (1, now() - interval '3 days',  'shipped'),
    (2, now() - interval '12 days', 'delivered'),
    (3, now() - interval '1 day',   'paid'),
    (4, now() - interval '40 days', 'cancelled'),
    (5, now() - interval '6 hours', 'pending');

-- unit_price = the product price when the order was placed.
INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
    (1, 1, 2,  19.99),
    (1, 6, 1,   8.50),
    (2, 4, 1, 149.00),
    (3, 2, 1,  49.90),
    (3, 8, 2,  34.00),
    (4, 5, 1, 229.99),
    (4, 1, 1,  19.99),
    (5, 7, 1,  79.00),
    (6, 3, 1,  89.00),
    (6, 6, 4,   8.50);

COMMIT;
