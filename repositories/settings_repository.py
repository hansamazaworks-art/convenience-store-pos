"""SQL for store-wide settings (app_settings key/value table)."""
from __future__ import annotations

from repositories.base import Repository


class SettingsRepository(Repository):
    def get_all(self, cur=None) -> dict[str, str]:
        rows = self._all("SELECT setting_key, setting_value FROM app_settings", (), cur)
        return {r["setting_key"]: r["setting_value"] for r in rows}

    def upsert(self, cur, key: str, value: str) -> None:
        self._exec(
            cur,
            "INSERT INTO app_settings (setting_key, setting_value) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)",
            (key, value),
        )
