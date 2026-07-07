"""Category management — add, delete, activate/deactivate product groups.

Deactivating a category hides all its products from the bot menu without
touching the products themselves.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db

router = APIRouter(prefix="/api/categories", tags=["categories"])


class CategoryCreate(BaseModel):
    name: str


class CategoryUpdate(BaseModel):
    active: bool | None = None
    name: str | None = None


@router.get("")
def list_categories():
    conn = db.get_conn()
    try:
        rows = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
        counts = {
            r["category"]: r["n"]
            for r in conn.execute(
                "SELECT category, COUNT(*) AS n FROM products GROUP BY category"
            ).fetchall()
        }
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "active": bool(r["active"]),
                "productCount": counts.get(r["name"], 0),
            }
            for r in rows
        ]
    finally:
        conn.close()


@router.post("", status_code=201)
def create_category(body: CategoryCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    conn = db.get_conn()
    try:
        if conn.execute("SELECT 1 FROM categories WHERE name = ?", (name,)).fetchone():
            raise HTTPException(status_code=409, detail=f"category '{name}' already exists")
        db.ensure_category(conn, name)
        conn.commit()
        row = conn.execute("SELECT * FROM categories WHERE name = ?", (name,)).fetchone()
        return {"id": row["id"], "name": row["name"], "active": True, "productCount": 0}
    finally:
        conn.close()


@router.patch("/{category_id}")
def update_category(category_id: str, body: CategoryUpdate):
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        if body.active is not None:
            conn.execute(
                "UPDATE categories SET active = ? WHERE id = ?",
                (1 if body.active else 0, category_id),
            )
        if body.name is not None:
            new_name = body.name.strip()
            if not new_name:
                raise HTTPException(status_code=400, detail="name cannot be empty")
            clash = conn.execute(
                "SELECT 1 FROM categories WHERE name = ? AND id != ?", (new_name, category_id)
            ).fetchone()
            if clash:
                raise HTTPException(status_code=409, detail=f"category '{new_name}' already exists")
            # rename ripples to the products carrying the old name
            conn.execute("UPDATE products SET category = ? WHERE category = ?", (new_name, row["name"]))
            conn.execute("UPDATE categories SET name = ? WHERE id = ?", (new_name, category_id))
        conn.commit()
        row = conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone()
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM products WHERE category = ?", (row["name"],)
        ).fetchone()["n"]
        return {"id": row["id"], "name": row["name"], "active": bool(row["active"]), "productCount": count}
    finally:
        conn.close()


@router.delete("/{category_id}")
def delete_category(category_id: str):
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM products WHERE category = ?", (row["name"],)
        ).fetchone()["n"]
        if count:
            raise HTTPException(
                status_code=400,
                detail=f"category '{row['name']}' still has {count} product(s) — reassign or delete them first",
            )
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
