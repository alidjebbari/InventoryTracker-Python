import csv
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).with_name("inventory.db")
EXPORT_PATH = Path(__file__).with_name("inventory_export.csv")


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_tables():
    with connect_db() as conn, closing(conn.cursor()) as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY,
                item TEXT UNIQUE NOT NULL,
                category TEXT NOT NULL DEFAULT 'General',
                qty INTEGER NOT NULL CHECK (qty >= 0),
                reorder_level INTEGER NOT NULL DEFAULT 5 CHECK (reorder_level >= 0)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY,
                item_id INTEGER NOT NULL,
                qty INTEGER NOT NULL CHECK (qty > 0),
                note TEXT,
                ordered_at TEXT NOT NULL,
                FOREIGN KEY(item_id) REFERENCES inventory(id)
            )
            """
        )
        conn.commit()


def prompt_int(message, *, minimum=0):
    while True:
        try:
            value = int(input(message))
        except ValueError:
            print("Please enter a valid number.")
            continue
        if value < minimum:
            print(f"Value must be at least {minimum}.")
            continue
        return value


def add_or_update_item():
    item = input("Item name: ").strip()
    if not item:
        print("Item name cannot be empty.")
        return
    category = input("Category (default General): ").strip() or "General"
    qty = prompt_int("Quantity: ", minimum=0)
    reorder_level = prompt_int("Reorder level: ", minimum=0)
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO inventory (item, category, qty, reorder_level)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(item) DO UPDATE SET
                category=excluded.category,
                qty=excluded.qty,
                reorder_level=excluded.reorder_level
            """,
            (item, category, qty, reorder_level),
        )
        conn.commit()
    print(f"Saved '{item}' ({qty} units).")


def view_inventory():
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT item, category, qty, reorder_level FROM inventory ORDER BY item"
        ).fetchall()
    if not rows:
        print("Inventory is empty.")
        return
    print(f"\n{'Item':20} {'Category':15} {'Qty':5} {'Reorder @':10}")
    print("-" * 55)
    for row in rows:
        print(
            f"{row['item'][:20]:20} {row['category'][:15]:15} {row['qty']:5} {row['reorder_level']:10}"
        )


def search_inventory():
    term = input("Search term: ").strip().lower()
    if not term:
        print("Nothing to search.")
        return
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT item, category, qty, reorder_level
            FROM inventory
            WHERE lower(item) LIKE ? OR lower(category) LIKE ?
            ORDER BY item
            """,
            (f"%{term}%", f"%{term}%"),
        ).fetchall()
    if not rows:
        print("No matching items found.")
        return
    for row in rows:
        print(
            f"{row['item']} ({row['category']}) - {row['qty']} units (reorder @ {row['reorder_level']})"
        )


def adjust_quantity():
    item = input("Item to adjust: ").strip()
    delta = prompt_int("Adjustment amount (use positive numbers): ", minimum=0)
    direction = input("Add or subtract (a/s): ").strip().lower() or "a"
    multiplier = 1 if direction.startswith("a") else -1
    with connect_db() as conn:
        row = conn.execute(
            "SELECT id, qty FROM inventory WHERE item = ?", (item,)
        ).fetchone()
        if not row:
            print("Item not found.")
            return
        new_qty = row["qty"] + multiplier * delta
        if new_qty < 0:
            print("Cannot reduce below zero.")
            return
        conn.execute("UPDATE inventory SET qty = ? WHERE id = ?", (new_qty, row["id"]))
        conn.commit()
    print(f"{item} now has {new_qty} units.")


def place_order():
    item = input("Item to order: ").strip()
    qty = prompt_int("Quantity: ", minimum=1)
    note = input("Note (optional): ").strip() or None
    with connect_db() as conn:
        row = conn.execute(
            "SELECT id, qty FROM inventory WHERE item = ?", (item,)
        ).fetchone()
        if not row:
            print("Item not found.")
            return
        if row["qty"] < qty:
            print("Not enough stock for this order.")
            return
        conn.execute(
            "UPDATE inventory SET qty = qty - ? WHERE id = ?", (qty, row["id"])
        )
        conn.execute(
            "INSERT INTO orders (item_id, qty, note, ordered_at) VALUES (?, ?, ?, ?)",
            (row["id"], qty, note, datetime.utcnow().isoformat()),
        )
        conn.commit()
    print(f"Order recorded for {qty} units of {item}.")


def view_orders():
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT o.id, i.item, o.qty, o.note, o.ordered_at
            FROM orders o
            JOIN inventory i ON o.item_id = i.id
            ORDER BY o.ordered_at DESC
            """
        ).fetchall()
    if not rows:
        print("No orders recorded.")
        return
    for row in rows:
        note = f" ({row['note']})" if row["note"] else ""
        print(f"{row['ordered_at']}: #{row['id']} {row['item']} x{row['qty']}{note}")


def view_low_stock():
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT item, qty, reorder_level
            FROM inventory
            WHERE qty <= reorder_level
            ORDER BY qty
            """
        ).fetchall()
    if not rows:
        print("No items at or below reorder level.")
        return
    print("Items needing restock:")
    for row in rows:
        print(f"- {row['item']}: {row['qty']} (reorder @ {row['reorder_level']})")


def export_inventory():
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT item, category, qty, reorder_level FROM inventory ORDER BY item"
        ).fetchall()
    if not rows:
        print("Inventory empty, nothing to export.")
        return
    with EXPORT_PATH.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "category", "qty", "reorder_level"])
        writer.writerows(
            (row["item"], row["category"], row["qty"], row["reorder_level"])
            for row in rows
        )
    print(f"Exported {len(rows)} rows to {EXPORT_PATH.name}.")


def inventory_summary():
    with connect_db() as conn:
        totals = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(qty), 0) FROM inventory"
        ).fetchone()
        per_category = conn.execute(
            """
            SELECT category, COUNT(*) items, COALESCE(SUM(qty), 0) qty
            FROM inventory
            GROUP BY category
            ORDER BY qty DESC
            """
        ).fetchall()
    print("=== Snapshot ===")
    print(f"Items tracked: {totals[0]}")
    print(f"Units on hand: {totals[1]}")
    if per_category:
        print("Per category:")
        for row in per_category:
            print(f"- {row['category']}: {row['qty']} units across {row['items']} items")
    else:
        print("No category data yet.")


def delete_item():
    item = input("Item to delete: ").strip()
    with connect_db() as conn:
        deleted = conn.execute("DELETE FROM inventory WHERE item = ?", (item,)).rowcount
        conn.commit()
    if deleted:
        print(f"Deleted {item}. Related order history remains for auditing.")
    else:
        print("Item not found.")


def main():
    create_tables()
    menu_options = {
        "1": ("Add or update item", add_or_update_item),
        "2": ("View inventory", view_inventory),
        "3": ("Search inventory", search_inventory),
        "4": ("Adjust quantity", adjust_quantity),
        "5": ("Record customer order", place_order),
        "6": ("View order history", view_orders),
        "7": ("View low-stock items", view_low_stock),
        "8": ("Delete item", delete_item),
        "9": ("Export inventory to CSV", export_inventory),
        "10": ("Snapshot summary", inventory_summary),
        "11": ("Exit", None),
    }
    while True:
        print("\nInventory Tracker")
        for key, (label, _) in menu_options.items():
            print(f"{key}. {label}")
        choice = input("Choose: ").strip()
        if choice == "11":
            break
        action = menu_options.get(choice)
        if action:
            _, func = action
            func()
        else:
            print("Unknown option.")


if __name__ == "__main__":
    main()
