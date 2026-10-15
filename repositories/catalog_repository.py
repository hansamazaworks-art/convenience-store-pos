"""SQL for categories, brands and units."""
from __future__ import annotations

from repositories.base import Repository

# Table names are fixed here (never from user input).
_TABLES = {"category": ("categories", "category_id"), "brand": ("brands", "brand_id")}


class CatalogRepository(Repository):
    # ------------------------------------------------- categories / brands
    def list_items(self, kind: str, include_inactive: bool = True, cur=None) -> list[dict]:
        table, fk = _TABLES[kind]
        sql = (f"SELECT t.id, t.name, t.is_active, "
               f"(SELECT COUNT(*) FROM products p WHERE p.{fk} = t.id) AS product_count "
               f"FROM {table} t")
        if not include_inactive:
            sql += " WHERE t.is_active = 1"
        return self._all(sql + " ORDER BY t.name", (), cur)

    def get_item(self, kind: str, item_id: int, cur=None, for_update=False) -> dict | None:
        table, _ = _TABLES[kind]
        return self._one(f"SELECT id, name, is_active FROM {table} WHERE id = %s"
                         + (" FOR UPDATE" if for_update else ""), (item_id,), cur)

    def find_item_by_name(self, kind: str, name: str, cur=None) -> dict | None:
        table, _ = _TABLES[kind]
        return self._one(f"SELECT id, name, is_active FROM {table} WHERE name = %s", (name,), cur)

    def insert_item(self, cur, kind: str, name: str) -> int:
        table, _ = _TABLES[kind]
        return self._exec(cur, f"INSERT INTO {table} (name) VALUES (%s)", (name,))

    def update_item(self, cur, kind: str, item_id: int, name: str, is_active: bool) -> None:
        table, _ = _TABLES[kind]
        self._exec(cur, f"UPDATE {table} SET name = %s, is_active = %s WHERE id = %s",
                   (name, int(is_active), item_id))

    # --------------------------------------------------------------- units
    def list_units(self, include_inactive: bool = True, cur=None) -> list[dict]:
        sql = ("SELECT u.id, u.code, u.name, u.allow_decimal, u.is_active, "
               "(SELECT COUNT(*) FROM products p WHERE p.unit_id = u.id) AS product_count "
               "FROM units u")
        if not include_inactive:
            sql += " WHERE u.is_active = 1"
        return self._all(sql + " ORDER BY u.name", (), cur)

    def get_unit(self, unit_id: int, cur=None, for_update=False) -> dict | None:
        return self._one("SELECT id, code, name, allow_decimal, is_active FROM units WHERE id = %s"
                         + (" FOR UPDATE" if for_update else ""), (unit_id,), cur)

    def find_unit(self, code: str, name: str, exclude_id: int | None = None, cur=None) -> dict | None:
        return self._one("SELECT id, code, name FROM units WHERE (code = %s OR name = %s) "
                         "AND id <> %s", (code, name, exclude_id or 0), cur)

    def insert_unit(self, cur, code: str, name: str, allow_decimal: bool) -> int:
        return self._exec(cur, "INSERT INTO units (code, name, allow_decimal) VALUES (%s, %s, %s)",
                          (code, name, int(allow_decimal)))

    def update_unit(self, cur, unit_id: int, code: str, name: str, allow_decimal: bool,
                    is_active: bool) -> None:
        self._exec(cur, "UPDATE units SET code = %s, name = %s, allow_decimal = %s, is_active = %s "
                        "WHERE id = %s", (code, name, int(allow_decimal), int(is_active), unit_id))
