"""Message templates — reusable canned replies with {name}/{phone} variables."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db

router = APIRouter(prefix="/api/templates", tags=["templates"])


class TemplateIn(BaseModel):
    name: str
    category: str = "General"
    body: str


class TemplateUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    body: str | None = None


def _to_dict(row) -> dict:
    return {
        "id": row["id"], "name": row["name"], "category": row["category"],
        "body": row["body"], "used": row["used"], "createdAt": row["created_at"],
    }


@router.get("")
def list_templates():
    conn = db.get_conn()
    try:
        rows = conn.execute("SELECT * FROM templates ORDER BY used DESC, name").fetchall()
        return [_to_dict(r) for r in rows]
    finally:
        conn.close()


@router.post("", status_code=201)
def create_template(body: TemplateIn):
    if not body.name.strip() or not body.body.strip():
        raise HTTPException(status_code=400, detail="name and body are required")
    conn = db.get_conn()
    try:
        tid = db.new_id("tpl")
        conn.execute(
            "INSERT INTO templates (id, name, category, body, used, created_at) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (tid, body.name.strip(), body.category.strip() or "General", body.body, db._now()),
        )
        conn.commit()
        return _to_dict(conn.execute("SELECT * FROM templates WHERE id = ?", (tid,)).fetchone())
    finally:
        conn.close()


@router.patch("/{template_id}")
def update_template(template_id: str, body: TemplateUpdate):
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
        if updates:
            cols = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE templates SET {cols} WHERE id = ?", (*updates.values(), template_id))
            conn.commit()
        return _to_dict(conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone())
    finally:
        conn.close()


@router.delete("/{template_id}")
def delete_template(template_id: str):
    conn = db.get_conn()
    try:
        cur = conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True}
    finally:
        conn.close()


@router.post("/{template_id}/render")
def render_template(template_id: str, phone: str | None = None):
    """Fill variables from a customer (by phone) and bump the usage counter."""
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        name = None
        if phone:
            cust = conn.execute("SELECT name FROM customers WHERE phone = ?", (phone,)).fetchone()
            name = cust["name"] if cust else None
        conn.execute("UPDATE templates SET used = used + 1 WHERE id = ?", (template_id,))
        conn.commit()
        return {"text": db.render_template(row["body"], name, phone)}
    finally:
        conn.close()
