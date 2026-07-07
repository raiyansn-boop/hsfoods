from fastapi import APIRouter, HTTPException

from .. import db
from ..models import ProductCreate, ProductUpdate

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("")
def list_products():
    conn = db.get_conn()
    try:
        rows = conn.execute("SELECT * FROM products").fetchall()
        return [db.product_to_dict(r) for r in rows]
    finally:
        conn.close()


@router.post("", status_code=201)
def create_product(body: ProductCreate):
    conn = db.get_conn()
    try:
        pid = db.new_id("prod")
        db.ensure_category(conn, body.category)
        conn.execute(
            "INSERT INTO products (id, name, price, unit, stock, emoji, category, active, cost) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (pid, body.name, body.price, body.unit, body.stock, body.emoji, body.category, body.cost),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        return db.product_to_dict(row)
    finally:
        conn.close()


@router.patch("/{product_id}")
def update_product(product_id: str, body: ProductUpdate):
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        updates = body.model_dump(exclude_none=True)
        if "active" in updates:
            updates["active"] = 1 if updates["active"] else 0
        if "category" in updates:
            db.ensure_category(conn, updates["category"])
        if updates:
            cols = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE products SET {cols} WHERE id = ?", (*updates.values(), product_id))
            conn.commit()
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return db.product_to_dict(row)
    finally:
        conn.close()


@router.delete("/{product_id}")
def delete_product(product_id: str):
    conn = db.get_conn()
    try:
        cur = conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True}
    finally:
        conn.close()
