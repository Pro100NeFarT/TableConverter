"""
Вікна допомоги операторові: «Помічник» (реквізити, контроль, налаштування 1С) і діалог колонок профілю.
"""
import tkinter as tk
from tkinter import ttk

import checks
import profiles

COLORS = {"ok": "#2e7d32", "warn": "#b26a00", "error": "#c62828"}
SYMBOLS = {"ok": "✓", "warn": "⚠", "error": "✗"}
NONE_LABEL = "— немає —"


class AssistantWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Помічник оператора")
        self.transient(app)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)
        self.info_tab = ttk.Frame(self.notebook)
        self.checks_tab = ttk.Frame(self.notebook)
        self.hints_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.info_tab, text="Реквізити")
        self.notebook.add(self.checks_tab, text="Контроль")
        self.notebook.add(self.hints_tab, text="Налаштування для 1С")
        self.refresh()
        x, y = app.winfo_rootx() + 40, app.winfo_rooty() + 60
        self.geometry(f"+{x}+{y}")

    def refresh(self):
        for tab in (self.info_tab, self.checks_tab, self.hints_tab):
            for child in tab.winfo_children():
                child.destroy()
        self._build_info()
        self._build_checks()
        self._build_hints()

    # ---------------------------------------------------------------- реквізити
    def _build_info(self):
        tab, app = self.info_tab, self.app
        tab.columnconfigure(1, weight=1)
        if not app.doc_info:
            ttk.Label(tab, text="Реквізити не знайдено (потрібен PDF з текстовим шаром).").grid(
                row=0, column=0, padx=10, pady=10
            )
            return
        for i, (label, value) in enumerate(app.doc_info):
            ttk.Label(tab, text=label).grid(row=i, column=0, sticky="w", padx=(10, 6), pady=3)
            entry = ttk.Entry(tab, width=75)
            entry.insert(0, value)
            entry.configure(state="readonly")
            entry.grid(row=i, column=1, sticky="we", pady=3)
            ttk.Button(tab, text="Копіювати", command=lambda lb=label, v=value: app._copy(lb, v)).grid(
                row=i, column=2, padx=(6, 10), pady=3
            )
        ttk.Button(tab, text="Копіювати все", command=app._copy_all).grid(
            row=len(app.doc_info), column=2, padx=(6, 10), pady=(6, 10), sticky="e"
        )

    # ---------------------------------------------------------------- контроль
    def _build_checks(self):
        text = tk.Text(self.checks_tab, width=95, height=16, wrap="word")
        text.pack(fill="both", expand=True, padx=8, pady=8)
        for level, color in COLORS.items():
            text.tag_configure(level, foreground=color)
        text.tag_configure("title", font=("Segoe UI", 9, "bold"))
        try:
            groups = self.app.assistant_checks()
        except Exception as exc:
            groups = []
            text.insert("end", f"Не вдалося виконати контроль: {exc}\n")
        if not groups:
            text.insert("end", "Оберіть таблицю, щоб побачити контроль.")
        worst = "ok"
        for name, results in groups:
            text.insert("end", f"{name}\n", "title")
            for level, message in results:
                text.insert("end", f"  {SYMBOLS[level]} {message}\n", level)
                if level == "error" or (level == "warn" and worst != "error"):
                    worst = level
            text.insert("end", "\n")
        text.configure(state="disabled")
        suffix = {"ok": "✓", "warn": "⚠", "error": "✗"}[worst] if groups else ""
        self.notebook.tab(self.checks_tab, text=f"Контроль {suffix}".strip())

    # ---------------------------------------------------------------- підказки
    def _build_hints(self):
        text = tk.Text(self.hints_tab, width=95, height=16, wrap="word")
        text.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        try:
            lines = self.app.assistant_hints()
        except Exception as exc:
            lines = [f"Не вдалося підготувати підказку: {exc}"]
        content = "\n".join(lines).strip()
        text.insert("1.0", content)
        text.configure(state="disabled")
        ttk.Button(
            self.hints_tab, text="Копіювати все", command=lambda: self.app._copy("підказку налаштувань", content)
        ).pack(anchor="e", padx=8, pady=(0, 8))


class ColumnsDialog(tk.Toplevel):
    """Підбір колонок таблиці для полів профілю; вибір можна зберегти для постачальника."""

    def __init__(self, app, table):
        super().__init__(app)
        self.app, self.table = app, table
        self.title(f"Колонки профілю - {table.name}")
        self.transient(app)
        self.profile_key = app.profile_key() or "none"
        prepared = app.prepare_table(table)
        self.headers = [h for h in dict.fromkeys(str(h).strip() for h in prepared[0] if str(h).strip())]
        self.mapping = app.mapping_for(table)
        self.vars = {}

        grid = ttk.Frame(self)
        grid.pack(fill="x", padx=10, pady=10)
        for i, field in enumerate(self.mapping):
            ttk.Label(grid, text=field).grid(row=i, column=0, sticky="w", padx=(0, 10), pady=3)
            var = tk.StringVar(value=self.mapping[field] or NONE_LABEL)
            combo = ttk.Combobox(grid, textvariable=var, values=[NONE_LABEL] + self.headers, state="readonly", width=42)
            combo.grid(row=i, column=1, pady=3)
            combo.bind("<<ComboboxSelected>>", lambda e: self._changed())
            self.vars[field] = var

        ttk.Label(self, text="Результат (перші рядки):").pack(anchor="w", padx=10)
        self.preview = tk.Text(self, height=6, width=90, wrap="none")
        self.preview.pack(fill="x", padx=10, pady=(0, 6))

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(buttons, text="Авто-підбір", command=self._auto).pack(side="left")
        ttk.Button(buttons, text="Зберегти для постачальника", command=self._save).pack(side="left", padx=8)
        ttk.Button(buttons, text="Готово", command=self.destroy).pack(side="right")
        self.bind("<Destroy>", self._on_destroy)
        self._changed()

    def _current(self):
        return {f: (None if v.get() == NONE_LABEL else v.get()) for f, v in self.vars.items()}

    def _changed(self):
        self.mapping.update(self._current())
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", self.app.preview_for(self.table))

    def _auto(self):
        prepared = self.app.prepare_table(self.table)
        fresh = profiles.detect_mapping(prepared[0], prepared[1:], list(self.mapping))
        for field, var in self.vars.items():
            var.set(fresh.get(field) or NONE_LABEL)
        self._changed()

    def _save(self):
        profiles.save_mapping(self.app.supplier_key(), self.profile_key, self._current())
        self.app.status_var.set("Підбір колонок збережено для постачальника.")

    def _on_destroy(self, event):
        if event.widget is self:
            self.app.on_mapping_changed()
