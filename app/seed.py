"""Seed HSFOODS with a starter fruit catalogue.

Run with:  python -m app.seed
"""
from . import db

# name, unit, price, stock, emoji, category, cost, bonus_type, bonus_value, cap
# category is the top-level product group (Fruits, Vegetables, Dairy, Juices, ...)
PRODUCTS = [
    ("Alphonso Mango", "kg", 399, 50, "🥭", "Fruits", 240, "percent", 5, 30),
    ("Shimla Apple", "kg", 180, 120, "🍎", "Fruits", 110, "percent", 5, 0),
    ("Banana Elaichi", "dozen", 60, 200, "🍌", "Fruits", 38, "flat", 3, 0),
    ("Green Kiwi", "box", 150, 40, "🥝", "Fruits", 95, "percent", 6, 0),
    ("Kinnow Orange", "kg", 90, 80, "🍊", "Fruits", 58, "percent", 5, 0),
    ("Red Grapes", "kg", 130, 60, "🍇", "Fruits", 80, "percent", 5, 0),
    ("Strawberries", "box", 199, 35, "🍓", "Fruits", 140, "percent", 6, 25),
    ("Watermelon", "pc", 70, 45, "🍉", "Fruits", 50, "percent", 4, 0),
    ("Pomegranate", "kg", 160, 55, "🫐", "Fruits", 105, "percent", 5, 0),
    ("Sweet Lime", "kg", 75, 90, "🍋", "Fruits", 68, "percent", 5, 0),  # thin margin → margin guard
]


def run() -> None:
    db.init_db()
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM products")
        for name, unit, price, stock, emoji, category, cost, btype, bval, cap in PRODUCTS:
            conn.execute(
                "INSERT INTO products "
                "(id, name, price, unit, stock, emoji, category, active, cost, ref_bonus_type, ref_bonus_value, ref_cap) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
                (db.new_id("prod"), name, price, unit, stock, emoji, category, cost, btype, bval, cap),
            )
        conn.commit()
        print(f"✅ Seeded {len(PRODUCTS)} products into HSFOODS.")
        print("   Run: uvicorn app.main:app --port 4000  ->  http://localhost:4000")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
