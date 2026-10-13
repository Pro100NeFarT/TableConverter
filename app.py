"""
Конвертер таблиць: Excel / PDF (з текстовим шаром) -> CSV.
Обираємо файл -> знаходимо таблиці -> аналізуємо вільний роздільник -> зберігаємо CSV.
"""
import csv
import io
import json
import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

import app_version
import assistant
import checks
import converter
import docinfo
import hints
import jsonexport
import ocr_rapid
import ocr_windows
import profiles
import scans
import sources
import updater

NO_PROFILE_TITLE = "Без профілю (колонки як у файлі)"


def resource_path(relative):
    """Шлях до ресурсу: поруч із кодом або всередині зібраного exe (PyInstaller)."""
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), relative)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Конвертер таблиць (Excel / PDF -> CSV)")
        self.minsize(720, 720)
        self._logo_images = []
        self._set_icon()

        self.tables = []
        self.file_path = None
        self.candidates_report = []
        self._cells_with_newline = 0
        self._cells_with_quote = 0
        self._trailing_empty = {}
        self._loading = False
        self.doc_info = []
        self._info_win = None
        self.user_mapping = {}
        self._layout_cache = {}
        self._pending_update = None
        self._update_busy = False
        self._ocr_source = False
        self._ocr_busy = False

        self._build_ui()
        self._fit_to_screen(860, 960)
        self.after(1500, self._check_updates)
        self.after(600, self._refresh_ocr_status)

    def _set_icon(self):
        try:
            from PIL import Image, ImageTk

            logo = Image.open(resource_path(os.path.join("assets", "logo.png"))).convert("RGBA")
            self._logo_images = [ImageTk.PhotoImage(logo.resize((s, s), Image.LANCZOS)) for s in (64, 32)]
            self.iconphoto(True, *self._logo_images)
            self._header_logo = ImageTk.PhotoImage(logo.resize((46, 46), Image.LANCZOS))
        except Exception:
            self._header_logo = None

    def _fit_to_screen(self, want_w, want_h):
        """Відкриває вікно бажаного розміру, але не більшого за екран, по центру."""
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        w = min(want_w, screen_w - 60)
        h = min(want_h, screen_h - 80)
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        # --- Заголовок: логотип і для чого застосунок ---
        header = ttk.Frame(self)
        header.pack(fill="x", padx=12, pady=(8, 0))
        if self._header_logo is not None:
            tk.Label(header, image=self._header_logo).pack(side="left")
        titles = ttk.Frame(header)
        titles.pack(side="left", padx=10)
        tk.Label(titles, text="Конвертер таблиць", font=("Segoe UI", 13, "bold"), anchor="w").pack(anchor="w")
        tk.Label(
            titles,
            text="Рахунки, накладні й акти (Excel, PDF, скани, фото)  →  CSV або Excel для імпорту в 1С",
            fg="gray35",
            anchor="w",
        ).pack(anchor="w")

        # --- Крок 1: файл ---
        frame1 = ttk.LabelFrame(self, text="1. Файл (Excel, PDF, скан або фото)")
        frame1.pack(fill="x", **pad)

        ocr_row = ttk.Frame(frame1)
        ocr_row.pack(side="bottom", fill="x", padx=8, pady=(0, 6))
        ttk.Label(ocr_row, text="Розпізнавання сканів і фото (OCR):").pack(side="left")
        self.ocr_label = tk.Label(ocr_row, text="перевірка...", fg="gray40", font=("Segoe UI", 9, "bold"))
        self.ocr_label.pack(side="left", padx=8)
        self.ocr_btn = ttk.Button(ocr_row, text=f"Встановити (≈{ocr_rapid.PACK_SIZE_MB} МБ)", command=self._install_ocr)

        self.file_label = ttk.Label(frame1, text="Файл не обрано", anchor="w")
        self.file_label.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        ttk.Button(frame1, text="Обрати файл...", command=self.choose_file).pack(
            side="right", padx=8, pady=8
        )

        # --- Крок 2: таблиці ---
        frame2 = ttk.LabelFrame(self, text="2. Таблиці / аркуші для конвертації")
        frame2.pack(fill="x", **pad)

        list_frame = ttk.Frame(frame2)
        list_frame.pack(fill="x", padx=8, pady=(8, 4))
        self.tables_list = tk.Listbox(
            list_frame, selectmode="extended", height=5, exportselection=False
        )
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tables_list.yview)
        self.tables_list.configure(yscrollcommand=sb.set)
        self.tables_list.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")
        self.tables_list.bind("<<ListboxSelect>>", lambda e: self.update_preview())

        pdf_frame = ttk.Frame(frame2)
        pdf_frame.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(pdf_frame, text="PDF, пошук таблиць:").pack(side="left")
        self.mode_var = tk.StringVar(value=sources.PDF_MODES["auto"])
        self.mode_combo = ttk.Combobox(
            pdf_frame,
            textvariable=self.mode_var,
            values=list(sources.PDF_MODES.values()),
            state="readonly",
            width=42,
        )
        self.mode_combo.pack(side="left", padx=6)
        self.merge_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            pdf_frame, text="Склеювати таблицю, що триває на наступній сторінці", variable=self.merge_var
        ).pack(side="left", padx=6)
        self.reload_btn = ttk.Button(pdf_frame, text="Знайти заново", command=self.reload_pdf)
        self.reload_btn.pack(side="right")
        self.info_btn = ttk.Button(pdf_frame, text="Помічник...", command=self._show_info, state="disabled")
        self.info_btn.pack(side="right", padx=6)

        ttk.Button(frame2, text="Аналізувати", command=self.analyze).pack(
            anchor="e", padx=8, pady=(0, 8)
        )

        # --- Крок 3: роздільник ---
        frame3 = ttk.LabelFrame(self, text="3. Роздільник CSV")
        frame3.pack(fill="both", expand=True, **pad)

        cols = ("char", "name", "status")
        self.tree = ttk.Treeview(frame3, columns=cols, show="headings", height=5, selectmode="browse")
        self.tree.heading("char", text="Символ")
        self.tree.heading("name", text="Назва")
        self.tree.heading("status", text="Стан у даних")
        self.tree.column("char", width=70, anchor="center")
        self.tree.column("name", width=260, anchor="w")
        self.tree.column("status", width=220, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        self.tree.bind("<<TreeviewSelect>>", self.on_select_delimiter)

        custom_frame = ttk.Frame(frame3)
        custom_frame.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(custom_frame, text="Або свій символ роздільника:").pack(side="left")
        self.custom_delim_var = tk.StringVar()
        custom_entry = ttk.Entry(custom_frame, textvariable=self.custom_delim_var, width=6)
        custom_entry.pack(side="left", padx=6)
        custom_entry.bind("<KeyRelease>", lambda e: self.update_preview())

        ttk.Label(frame3, text="Прев'ю (перші рядки першої обраної таблиці):").pack(anchor="w", padx=8)
        self.preview_text = tk.Text(frame3, height=5, wrap="none")
        self.preview_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # --- Крок 4: конвертація ---
        frame4 = ttk.LabelFrame(self, text="4. Конвертація")
        frame4.pack(fill="x", **pad)

        fmt_frame = ttk.Frame(frame4)
        fmt_frame.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(fmt_frame, text="Зберегти як:").pack(side="left")
        self.format_var = tk.StringVar(value="csv")
        ttk.Radiobutton(
            fmt_frame, text="CSV", value="csv", variable=self.format_var, command=self._on_format_change
        ).pack(side="left", padx=8)
        ttk.Radiobutton(
            fmt_frame, text="Excel (.xlsx)", value="xlsx", variable=self.format_var, command=self._on_format_change
        ).pack(side="left", padx=8)
        ttk.Radiobutton(
            fmt_frame, text="JSON (для 1С)", value="json", variable=self.format_var, command=self._on_format_change
        ).pack(side="left", padx=8)
        self.only_table_var = tk.BooleanVar(value=False)
        self.only_table_cb = ttk.Checkbutton(
            fmt_frame,
            text="Excel із PDF: лише таблиця (інакше 1 в 1, як у PDF)",
            variable=self.only_table_var,
            state="disabled",
        )
        self.only_table_cb.pack(side="left", padx=16)

        profile_frame = ttk.Frame(frame4)
        profile_frame.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Label(profile_frame, text="Профіль для 1С (CSV):").pack(side="left")
        self.profile_var = tk.StringVar(value=NO_PROFILE_TITLE)
        self.profile_combo = ttk.Combobox(
            profile_frame,
            textvariable=self.profile_var,
            values=[NO_PROFILE_TITLE] + [p["title"] for p in profiles.PROFILES.values()],
            state="readonly",
            width=40,
        )
        self.profile_combo.pack(side="left", padx=8)
        self.profile_combo.bind("<<ComboboxSelected>>", lambda e: self._on_profile_change())
        self.columns_btn = ttk.Button(profile_frame, text="Колонки...", command=self._open_columns)
        self.columns_btn.pack(side="left")

        checks_frame = ttk.Frame(frame4)
        checks_frame.pack(side="left", padx=8, pady=8)

        def check(text, var, row, col, preview=True):
            cb = ttk.Checkbutton(
                checks_frame, text=text, variable=var, command=self.update_preview if preview else None
            )
            cb.grid(row=row, column=col, sticky="w", padx=(0, 16))
            return cb

        self.bom_var = tk.BooleanVar(value=True)
        self.bom_cb = check("UTF-8 з BOM (для Excel)", self.bom_var, 0, 0, preview=False)
        self.flatten_var = tk.BooleanVar(value=True)
        self.flatten_cb = check("Переноси рядків у клітинках -> пробіл", self.flatten_var, 1, 0)
        self.quotes_var = tk.BooleanVar(value=True)
        self.quotes_cb = check('Лапки " у тексті -> апостроф', self.quotes_var, 2, 0)
        self.trim_var = tk.BooleanVar(value=True)
        self.trim_cb = check("Відкидати порожні рядки в кінці", self.trim_var, 0, 1)
        self.fill_merges_var = tk.BooleanVar(value=True)
        self.fill_merges_cb = check("Об'єднані комірки: унікальні назви колонок", self.fill_merges_var, 1, 1)
        self.numbers_var = tk.BooleanVar(value=True)
        self.numbers_cb = check("Нормалізувати числа (3 600,00 -> 3600.00)", self.numbers_var, 2, 1)

        ttk.Button(frame4, text="Зберегти...", command=self.convert).pack(
            side="right", padx=8, pady=8
        )

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=10, pady=(0, 6))
        self.status_var = tk.StringVar(value="Готово")
        ttk.Label(bottom, textvariable=self.status_var, anchor="w", wraplength=640).pack(
            side="left", fill="x", expand=True
        )
        self.version_label = tk.Label(
            bottom, text=f"v{app_version.APP_VERSION}", cursor="hand2", fg="gray40", font=("Segoe UI", 9)
        )
        self.version_label.pack(side="right")
        self.version_label.bind("<Button-1>", lambda e: self._on_version_click())
        repo_label = tk.Label(bottom, text="GitHub", cursor="hand2", fg="#0b5cad", font=("Segoe UI", 9, "underline"))
        repo_label.pack(side="right", padx=(0, 12))
        repo_label.bind("<Button-1>", lambda e: webbrowser.open(updater.REPO_URL))

    # ------------------------------------------------------------------ рушій розпізнавання (OCR)

    def _refresh_ocr_status(self):
        if self._ocr_busy:
            return
        if ocr_rapid.is_installed():
            self.set_ocr_status(True, None)
            return
        q = queue.Queue()

        def work():
            try:
                q.put(("ok", ocr_windows.available_languages()))
            except Exception as exc:
                q.put(("err", str(exc)))

        threading.Thread(target=work, daemon=True).start()
        self.after(200, self._poll_ocr_status, q)

    def _poll_ocr_status(self, q):
        try:
            windows = q.get_nowait()
        except queue.Empty:
            self.after(200, self._poll_ocr_status, q)
            return
        self.set_ocr_status(False, windows)

    def set_ocr_status(self, rapid_installed, windows):
        """Індикатор: зелений - рушій для української встановлено; помаранчевий - немає, працює Windows OCR
        (є кнопка 'Встановити'); червоний - немає жодного рушія. windows: ('ok', мови) | ('err', текст) | None."""
        green, orange, red = "#2e7d32", "#b26a00", "#c62828"
        if rapid_installed:
            version = ocr_rapid.installed_version()
            text, color, show_button = f"рушій для української встановлено ✓ {('v' + version) if version else ''}".strip(), green, False
        elif windows and windows[0] == "ok" and windows[1]:
            text = "рушій для української не встановлено: працює Windows OCR, українські «і/ї/є» читає погано"
            color, show_button = orange, True
        else:
            text, color, show_button = "розпізнавання недоступне: встановіть рушій для української", red, True
        self.ocr_label.configure(text=text, fg=color)
        if show_button:
            self.ocr_btn.pack(side="left")
        else:
            self.ocr_btn.pack_forget()

    def _install_ocr(self):
        if self._ocr_busy:
            return
        if not messagebox.askyesno(
            "Рушій розпізнавання",
            f"Буде завантажено рушій розпізнавання для української (≈{ocr_rapid.PACK_SIZE_MB} МБ, з GitHub). "
            "Права адміністратора не потрібні. Продовжити?",
        ):
            return
        self._ocr_busy = True
        self.ocr_btn.configure(state="disabled")
        self.ocr_label.configure(text="завантаження... 0%", fg="#b26a00")
        q = queue.Queue()

        def work():
            try:
                ocr_rapid.install(progress=lambda done, total: q.put(("p", done, total)))
                q.put(("done", None))
            except Exception as exc:
                q.put(("err", str(exc)))

        threading.Thread(target=work, daemon=True).start()
        self.after(300, self._poll_ocr_install, q)

    def _poll_ocr_install(self, q):
        finished = None
        try:
            while True:
                msg = q.get_nowait()
                if msg[0] == "p":
                    percent = f"{100 * msg[1] // msg[2]}%" if msg[2] else f"{msg[1] // (1024 * 1024)} МБ"
                    self.ocr_label.configure(text=f"завантаження... {percent}", fg="#b26a00")
                else:
                    finished = msg
        except queue.Empty:
            pass
        if finished is None:
            self.after(300, self._poll_ocr_install, q)
            return
        self.finish_ocr_install(finished[0] == "done", finished[1])

    def finish_ocr_install(self, ok, error):
        self._ocr_busy = False
        self.ocr_btn.configure(state="normal")
        if ok:
            messagebox.showinfo("Рушій розпізнавання", "Рушій для української встановлено й використовується автоматично.")
        else:
            messagebox.showwarning("Рушій розпізнавання", f"Не вдалося встановити рушій: {error}")
        self._refresh_ocr_status()

    # ------------------------------------------------------------------ оновлення з GitHub

    def _check_updates(self, manual=False):
        if self._update_busy:
            return
        self._update_busy = True
        q = queue.Queue()
        threading.Thread(target=lambda: q.put(updater.check(app_version.APP_VERSION)), daemon=True).start()
        self.after(200, self._poll_update_check, q, manual)

    def _poll_update_check(self, q, manual):
        try:
            result = q.get_nowait()
        except queue.Empty:
            self.after(200, self._poll_update_check, q, manual)
            return
        self._update_busy = False
        self.on_update_result(result, manual)

    def on_update_result(self, result, manual):
        kind, value = result
        if kind == "newer":
            self._pending_update = value
            self.version_label.configure(text=f"v{app_version.APP_VERSION} ↑", fg="orange red")
            if manual:
                self._prompt_update()
        elif manual and kind == "current":
            messagebox.showinfo("Перевірка оновлень", f"У вас найновіша версія ({app_version.APP_VERSION}).")
        elif manual:
            messagebox.showwarning(
                "Перевірка оновлень", "Не вдалося перевірити оновлення. Перевірте підключення до інтернету."
            )

    def _on_version_click(self):
        if self._pending_update:
            self._prompt_update()
        else:
            self._check_updates(manual=True)

    def _prompt_update(self):
        if messagebox.askyesno(
            "Оновлення",
            f"Доступна нова версія {self._pending_update} (поточна {app_version.APP_VERSION}). Оновити зараз?",
        ):
            self._perform_update()

    def _perform_update(self):
        if not updater.can_self_update():
            messagebox.showinfo(
                "Оновлення",
                "Застосунок запущено з вихідного коду - оновіть його через git pull.\n"
                "Зібраний exe оновлюється автоматично.",
            )
            return
        if self._update_busy:
            return
        self._update_busy = True
        exe_path = os.path.abspath(sys.executable)
        new_path = exe_path + ".new"
        self.status_var.set("Завантаження оновлення...")
        q = queue.Queue()

        def work():
            try:
                updater.download(updater.EXE_URL, new_path)
                q.put(("ok", None))
            except Exception as exc:
                q.put(("err", exc))

        threading.Thread(target=work, daemon=True).start()
        self.after(300, self._poll_update_download, q, exe_path, new_path)

    def _poll_update_download(self, q, exe_path, new_path):
        try:
            kind, value = q.get_nowait()
        except queue.Empty:
            self.after(300, self._poll_update_download, q, exe_path, new_path)
            return
        self._update_busy = False
        if kind == "err":
            self.status_var.set("Не вдалося завантажити оновлення.")
            messagebox.showerror("Оновлення", f"Не вдалося оновити застосунок: {value}")
            return
        try:
            updater.launch_update(exe_path, new_path)
        except Exception as exc:
            messagebox.showerror("Оновлення", f"Не вдалося оновити застосунок: {exc}")
            return
        self.destroy()

    # ------------------------------------------------------------------ завантаження

    def choose_file(self):
        path = filedialog.askopenfilename(
            title="Обрати файл",
            filetypes=[
                ("Excel, PDF та фото", "*.xlsx *.xlsm *.xls *.pdf *.jpg *.jpeg *.png *.bmp *.tif *.tiff"),
                ("Excel файли", "*.xlsx *.xlsm *.xls"),
                ("PDF файли", "*.pdf"),
                ("Фото та скани", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff"),
                ("Усі файли", "*.*"),
            ],
        )
        if not path:
            return
        self.file_path = path
        self.file_label.config(text=path)
        self._clear_results()
        self.reload()

    def _clear_results(self):
        self.tables = []
        self.tables_list.delete(0, "end")
        self.tree.delete(*self.tree.get_children())
        self.preview_text.delete("1.0", "end")
        self.candidates_report = []
        self._set_info([], show=False)

    def _pdf_controls_state(self, enabled):
        state = "readonly" if enabled else "disabled"
        self.mode_combo.configure(state=state)
        self.reload_btn.configure(state="normal" if enabled else "disabled")

    def _on_format_change(self):
        is_csv = self.format_var.get() == "csv"
        for cb in (
            self.bom_cb, self.flatten_cb, self.quotes_cb, self.trim_cb, self.fill_merges_cb, self.numbers_cb
        ):
            cb.configure(state="normal" if is_csv else "disabled")
        is_pdf = bool(self.file_path) and sources.is_pdf(self.file_path) and not self._ocr_source
        is_xlsx = self.format_var.get() == "xlsx"
        self.only_table_cb.configure(state="normal" if (is_xlsx and is_pdf) else "disabled")
        self.update_preview()

    def reload(self):
        if not self.file_path:
            return
        is_pdf = sources.is_pdf(self.file_path)
        is_scan = is_pdf or scans.is_image(self.file_path)
        self._ocr_source = scans.is_image(self.file_path)
        # PDF/скани (друковані форми): унікальні назви колонок і числа - так за замовчуванням; Excel - без змін даних
        self.fill_merges_var.set(is_scan)
        self.numbers_var.set(is_scan)
        self._on_format_change()
        if is_scan:
            self._pdf_controls_state(is_pdf)
            self._load_pdf_async()
        else:
            self._pdf_controls_state(False)
            try:
                tables = sources.load_excel_tables(self.file_path)
            except Exception as exc:
                messagebox.showerror("Помилка", f"Не вдалося відкрити файл:\n{exc}")
                return
            self._set_tables(tables)
            form = next((t for t in tables if t.lines), None)
            if form:  # друкована форма (рахунок, накладна): реквізити з комірок, очищення як для PDF
                self.fill_merges_var.set(True)
                self.numbers_var.set(True)
                info = docinfo.parse_header_text("\n".join(form.lines), os.path.basename(self.file_path))
                self._set_info(info, show=True)
                self.status_var.set(
                    "Знайдено друковану форму: таблицю взято з аркуша, реквізити - з комірок поза таблицею."
                )
            else:
                self._set_info([], show=False)
                self.status_var.set("Файл завантажено. Оберіть аркуші та натисніть 'Аналізувати'.")

    def reload_pdf(self):
        if self.file_path and sources.is_pdf(self.file_path):
            self._clear_results()
            self._load_pdf_async()

    def _current_mode(self):
        for key, label in sources.PDF_MODES.items():
            if label == self.mode_var.get():
                return key
        return "auto"

    def _load_pdf_async(self):
        if self._loading:
            return
        self._loading = True
        self.reload_btn.configure(state="disabled")
        self.status_var.set("Пошук таблиць у PDF...")
        q = queue.Queue()
        path, mode, merge = self.file_path, self._current_mode(), self.merge_var.get()

        def parse_lines(lines):
            return docinfo.parse_header_text("\n".join(lines), os.path.basename(path))

        def work():
            try:
                if scans.is_image(path):
                    q.put(("o", 0, 1))
                    tables, lines, notes = scans.ocr_image(path)
                    q.put(("done", tables, parse_lines(lines), True, notes))
                elif scans.has_text_layer(path):
                    tables = sources.load_pdf_tables(
                        path, mode=mode, merge_continued=merge, progress=lambda i, n: q.put(("p", i, n))
                    )
                    try:
                        info = docinfo.extract_pdf_info(path)
                    except Exception:
                        info = []
                    q.put(("done", tables, info, False, []))
                else:
                    tables, lines, notes = scans.ocr_pdf(path, progress=lambda i, n: q.put(("o", i, n)))
                    q.put(("done", tables, parse_lines(lines), True, notes))
            except Exception as exc:
                q.put(("err", exc))

        threading.Thread(target=work, daemon=True).start()
        self.after(100, self._poll_pdf, q)

    def _poll_pdf(self, q):
        finished = False
        try:
            while True:
                msg = q.get_nowait()
                if msg[0] == "p":
                    self.status_var.set(f"Пошук таблиць у PDF: сторінка {msg[1]} з {msg[2]}...")
                elif msg[0] == "o":
                    self.status_var.set(f"Розпізнавання тексту (OCR), може тривати кілька секунд: {max(msg[1], 1)} з {msg[2]}...")
                elif msg[0] == "done":
                    finished = True
                    self._ocr_source = msg[3]
                    self._on_format_change()
                    self._set_tables(msg[1])
                    self._set_info(msg[2], show=True)
                    if msg[1]:
                        self.status_var.set(
                            f"Знайдено таблиць: {len(msg[1])}. Оберіть потрібні та натисніть 'Аналізувати'. "
                            + " ".join(msg[4])
                        )
                    else:
                        self.status_var.set("Таблиць не знайдено.")
                        hint = (
                            "На фото чи скані таблицю не знайдено: знімайте рівно, при хорошому світлі, "
                            "щоб увесь документ був у кадрі, і спробуйте ще раз."
                            if msg[3]
                            else "У PDF не знайдено таблиць. Спробуйте інший режим пошуку "
                            "(наприклад, 'За вирівнюванням тексту') і натисніть 'Знайти заново'."
                        )
                        messagebox.showinfo("Таблиць не знайдено", hint)
                elif msg[0] == "err":
                    finished = True
                    self.status_var.set("Помилка читання PDF.")
                    messagebox.showerror("Помилка", f"Не вдалося прочитати PDF:\n{msg[1]}")
        except queue.Empty:
            pass
        if finished:
            self._loading = False
            self.reload_btn.configure(state="normal")
        else:
            self.after(100, self._poll_pdf, q)

    # ------------------------------------------------------------------ реквізити документа

    def _set_info(self, fields, show):
        self.doc_info = fields
        self.user_mapping = {}
        self._sync_assistant_button()
        if self._info_win is not None and self._info_win.winfo_exists():
            self._info_win.destroy()
        self._info_win = None
        if fields and show:
            self._show_info()

    def _sync_assistant_button(self):
        self.info_btn.configure(state="normal" if (self.doc_info or self.tables) else "disabled")

    def _show_info(self, tab=None):
        if not (self.doc_info or self.tables):
            return
        if self._info_win is not None and self._info_win.winfo_exists():
            self._info_win.refresh()
            self._info_win.lift()
        else:
            self._info_win = assistant.AssistantWindow(self)
        if tab == "hints":
            self._info_win.notebook.select(self._info_win.hints_tab)

    def _copy(self, label, value):
        self.clipboard_clear()
        self.clipboard_append(value)
        self.update()
        self.status_var.set(f"Скопійовано: {label}")

    def _copy_all(self):
        self._copy("усі реквізити", "\n".join(f"{label}\t{value}" for label, value in self.doc_info))

    # ------------------------------------------------------------------ профіль, підбір колонок, помічник

    def profile_key(self):
        title = self.profile_var.get()
        for key, profile in profiles.PROFILES.items():
            if profile["title"] == title:
                return key
        return None

    def _active_profile(self):
        """Профіль діє лише для CSV."""
        return self.profile_key() if self.format_var.get() == "csv" else None

    def supplier_key(self):
        info = dict(self.doc_info)
        return info.get("Постачальник: код") or info.get("Постачальник") or ""

    def prepare_table(self, table, output=False, delimiter=None):
        if output:
            opts = self._csv_options()
            if self._active_profile():
                opts["fill_merges"] = True
                if delimiter:
                    opts["replace_char"] = delimiter
        else:
            opts = dict(
                flatten_newlines=True, trim_trailing_empty=True, sanitize_quotes=False,
                fill_merges=True, normalize_numbers=False,
            )
        return converter.prepare_rows(table.rows, table.merges, **opts)

    def map_profile(self):
        """Профіль, за яким підбираються колонки: обраний; для JSON - завжди УпрИмпортИзExcel."""
        return "upr" if self.format_var.get() == "json" else self.profile_key()

    def mapping_for(self, table):
        key = (table.name, self.map_profile() or "none")
        if key not in self.user_mapping:
            prepared = self.prepare_table(table)
            self.user_mapping[key] = (
                profiles.resolve_mapping(prepared[0], prepared[1:], key[1], self.supplier_key()) if prepared else {}
            )
        return self.user_mapping[key]

    def output_rows(self, table, delim):
        key = self._active_profile()
        if key:
            prepared = self.prepare_table(table, output=True, delimiter=delim)
            return profiles.apply_profile(prepared, key, self.mapping_for(table)) if prepared else []
        return converter.prepare_rows(table.rows, table.merges, **self._csv_options())

    def json_preview(self, table, max_items=2):
        prepared = self.prepare_table(table)
        items = jsonexport.build_items(prepared, self.mapping_for(table)) if prepared else []
        return json.dumps(items[:max_items], ensure_ascii=False, indent=1)

    def preview_for(self, table, delim=None, max_rows=5):
        if self.format_var.get() == "json":
            return self.json_preview(table)
        key = self._active_profile()
        delim = delim or self.get_selected_delimiter() or (profiles.PROFILES[key]["delimiter"] if key else ";")
        buf = io.StringIO()
        csv.writer(buf, delimiter=delim).writerows(self.output_rows(table, delim)[:max_rows])
        return buf.getvalue()

    def on_mapping_changed(self):
        self.update_preview()
        if self._info_win is not None and self._info_win.winfo_exists():
            self._info_win.refresh()

    def _select_profile_delimiter(self):
        key = self._active_profile()
        if not key or not self.candidates_report:
            return
        delim = profiles.PROFILES[key]["delimiter"]
        for i, r in enumerate(self.candidates_report):
            if r["char"] == delim:
                item = self.tree.get_children()[i]
                self.tree.selection_set(item)
                self.tree.see(item)
                return

    def _on_profile_change(self):
        if self.profile_key():
            self.fill_merges_var.set(True)
            self.numbers_var.set(True)
        self._select_profile_delimiter()
        self.on_mapping_changed()

    def _open_columns(self):
        tables = self.selected_tables()
        if not self.map_profile():
            messagebox.showinfo("Колонки", "Спершу оберіть профіль для 1С.")
            return
        if not tables:
            messagebox.showwarning("Увага", "Оберіть таблицю.")
            return
        assistant.ColumnsDialog(self, tables[0])

    def assistant_checks(self):
        info = dict(self.doc_info)
        return [
            (f"Таблиця «{t.name}»", checks.run_checks(self.prepare_table(t), self.mapping_for(t), info))
            for t in self.selected_tables()
        ]

    def _layout_sheets(self):
        if self.file_path not in self._layout_cache:
            self._layout_cache[self.file_path] = sources.load_pdf_layout(self.file_path)
        return self._layout_cache[self.file_path]

    def assistant_hints(self):
        tables = self.selected_tables()
        if self.format_var.get() == "json":
            return hints.json_lines(self.json_document(tables)) if tables else ["Оберіть таблицю."]
        if self.format_var.get() == "csv":
            key = self.profile_key()
            if not key:
                return ["Оберіть профіль для 1С (УпрИмпортИзExcel або ИмпортИзExcel) - тут з'явиться "
                        "готова інструкція: роздільник і порядок колонок."]
            delim = self.get_selected_delimiter() or profiles.PROFILES[key]["delimiter"]
            return hints.csv_lines(key, delim)
        if not tables:
            return ["Оберіть таблицю."]
        headers = {t.name: (self.prepare_table(t) or [[]])[0] for t in tables}
        if sources.is_pdf(self.file_path) and not self._ocr_source and not self.only_table_var.get():
            entries = [(t, headers[t.name], self.mapping_for(t)) for t in tables]
            return hints.excel_lines_layout(self._layout_sheets(), entries)
        entries = [(t.name, t.rows, headers[t.name], self.mapping_for(t)) for t in tables]
        return hints.excel_lines_table_only(entries)

    def _set_tables(self, tables):
        self.tables = tables
        self.tables_list.delete(0, "end")
        for t in tables:
            self.tables_list.insert("end", f"{t.name}   ({t.n_rows} рядків x {t.n_cols} колонок)")
        for i, t in enumerate(tables):
            if t.selected:
                self.tables_list.selection_set(i)
        self.user_mapping = {}
        self._sync_assistant_button()

    def selected_tables(self):
        return [self.tables[i] for i in self.tables_list.curselection()]

    # ------------------------------------------------------------------ аналіз

    def analyze(self):
        if not self.tables:
            messagebox.showwarning("Увага", "Спершу оберіть файл із таблицями.")
            return
        tables = self.selected_tables()
        if not tables:
            messagebox.showwarning("Увага", "Оберіть хоча б одну таблицю.")
            return

        counter, total_cells, with_nl, with_quote = converter.analyze_characters(tables)
        self.candidates_report = converter.get_candidates_report(counter)
        self._cells_with_newline = with_nl
        self._cells_with_quote = with_quote
        self._trailing_empty = {t.name: converter.count_trailing_empty_rows(t.rows) for t in tables}

        self.tree.delete(*self.tree.get_children())
        first_safe_item = None
        for r in self.candidates_report:
            status = "безпечний" if r["safe"] else f"є в тексті ({r['count']} разів)"
            item_id = self.tree.insert(
                "", "end", values=(r["char"] if r["char"] != "\t" else "[Tab]", r["name"], status)
            )
            if r["safe"] and first_safe_item is None:
                first_safe_item = item_id

        status = f"Проаналізовано клітинок: {total_cells}, унікальних символів: {len(counter)}"
        if with_nl:
            status += f". Клітинок із переносом рядка всередині: {with_nl}"
        if with_quote:
            status += f". Клітинок із лапками всередині: {with_quote}"
        total_trailing = sum(self._trailing_empty.values())
        if total_trailing:
            status += f". Порожніх рядків у кінці: {total_trailing} (будуть відкинуті)"
        self.status_var.set(status)

        if first_safe_item:
            self.tree.selection_set(first_safe_item)
            self.tree.see(first_safe_item)
            self._select_profile_delimiter()
        else:
            messagebox.showwarning(
                "Увага",
                "Усі стандартні кандидати вже використовуються в даних. "
                "Введіть свій символ роздільника вручну.",
            )

    def get_selected_delimiter(self):
        custom = self.custom_delim_var.get()
        if custom:
            return custom[0]
        sel = self.tree.selection()
        if not sel:
            return None
        return self.candidates_report[self.tree.index(sel[0])]["char"]

    def on_select_delimiter(self, event=None):
        self.custom_delim_var.set("")
        self.update_preview()

    def update_preview(self):
        tables = self.selected_tables()
        key = self._active_profile()
        delim = self.get_selected_delimiter() or (
            profiles.PROFILES[key]["delimiter"] if key else ("\t" if self.format_var.get() in ("xlsx", "json") else None)
        )
        if not tables or not delim:
            return
        try:
            preview = self.preview_for(tables[0], delim)
        except Exception as exc:
            preview = f"(помилка прев'ю: {exc})"
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", preview)

    # ------------------------------------------------------------------ збереження

    def _csv_options(self):
        if self.format_var.get() == "xlsx":  # Excel - без очищення; прев'ю показує дані як є
            return dict(
                flatten_newlines=False,
                trim_trailing_empty=False,
                sanitize_quotes=False,
                fill_merges=False,
                normalize_numbers=False,
            )
        return dict(
            flatten_newlines=self.flatten_var.get(),
            trim_trailing_empty=self.trim_var.get(),
            sanitize_quotes=self.quotes_var.get(),
            fill_merges=self.fill_merges_var.get(),
            normalize_numbers=self.numbers_var.get(),
        )

    def json_source(self):
        info = {"Файл": os.path.basename(self.file_path or ""), "Программа": f"TableConverter {app_version.APP_VERSION}"}
        if self._ocr_source:
            info["Тип"] = "scan"
            info["OCR"] = True
        else:
            info["Тип"] = "pdf" if sources.is_pdf(self.file_path or "") else "excel"
        return info

    def json_document(self, tables):
        data = [(self.prepare_table(t), self.mapping_for(t), t.name) for t in tables]
        return jsonexport.build_document(self.doc_info, data, self.json_source())

    def _save_json(self, base_dir, base_name):
        tables = self.selected_tables()
        if not tables:
            messagebox.showwarning("Увага", "Оберіть хоча б одну таблицю.")
            return
        document = self.json_document(tables)
        errors = [m["Сообщение"] for m in document["Контроль"] if m["Уровень"] == "error"]
        if errors and not messagebox.askyesno(
            "Контроль виявив помилки", "\n\n".join(errors) + "\n\nВсе одно зберегти?"
        ):
            self._show_info()
            return
        out_path = filedialog.asksaveasfilename(
            title="Зберегти JSON як",
            initialdir=base_dir,
            initialfile=f"{base_name}.json",
            defaultextension=".json",
            filetypes=[("JSON файли", "*.json")],
        )
        if not out_path:
            return
        try:
            jsonexport.write_json(document, out_path)
        except Exception as exc:
            messagebox.showerror("Помилка", f"Не вдалося зберегти JSON:\n{exc}")
            return
        self.status_var.set(f"Готово: збережено {out_path}")
        messagebox.showinfo("Готово", f"JSON збережено:\n{out_path}")
        self._show_info("hints")

    def _save_xlsx(self, base_dir, base_name):
        full_page = sources.is_pdf(self.file_path) and not self._ocr_source and not self.only_table_var.get()
        tables = self.selected_tables()
        if not full_page and not tables:
            messagebox.showwarning("Увага", "Оберіть хоча б одну таблицю.")
            return
        out_path = filedialog.asksaveasfilename(
            title="Зберегти Excel як",
            initialdir=base_dir,
            initialfile=f"{base_name}.xlsx",
            defaultextension=".xlsx",
            filetypes=[("Excel файли", "*.xlsx")],
        )
        if not out_path:
            return
        try:
            if full_page:
                self.status_var.set("Готую Excel 1 в 1...")
                self.update_idletasks()
                tables = sources.load_pdf_layout(self.file_path)
                if not tables:
                    messagebox.showwarning("Увага", "У PDF не знайдено тексту (можливо, це скан).")
                    return
            converter.convert_tables_to_xlsx(tables, out_path)
        except Exception as exc:
            messagebox.showerror("Помилка", f"Не вдалося зберегти Excel:\n{exc}")
            return
        self.status_var.set(f"Готово: збережено {out_path}")
        messagebox.showinfo("Готово", f"Конвертацію завершено:\n{out_path}")
        self._show_info("hints")

    def convert(self):
        if not self.file_path:
            messagebox.showwarning("Увага", "Спершу оберіть файл.")
            return
        base_dir = os.path.dirname(self.file_path)
        base_name = os.path.splitext(os.path.basename(self.file_path))[0]

        if self.format_var.get() == "xlsx":
            self._save_xlsx(base_dir, base_name)
            return
        if self.format_var.get() == "json":
            self._save_json(base_dir, base_name)
            return

        tables = self.selected_tables()
        if not tables:
            messagebox.showwarning("Увага", "Оберіть хоча б одну таблицю.")
            return
        delim = self.get_selected_delimiter()
        if not delim:
            messagebox.showwarning("Увага", "Спершу натисніть 'Аналізувати' і оберіть роздільник.")
            return

        if self._active_profile():
            problems = []
            for t in tables:
                results = checks.run_checks(self.prepare_table(t), self.mapping_for(t), dict(self.doc_info))
                errors = [text for level, text in results if level == "error"]
                if errors:
                    problems.append(f"{t.name}: " + " ".join(errors))
            if problems and not messagebox.askyesno(
                "Контроль виявив помилки", "\n\n".join(problems) + "\n\nВсе одно зберегти?"
            ):
                self._show_info()
                return

        if len(tables) == 1:
            out_path = filedialog.asksaveasfilename(
                title="Зберегти CSV як",
                initialdir=base_dir,
                initialfile=f"{base_name}.csv",
                defaultextension=".csv",
                filetypes=[("CSV файли", "*.csv")],
            )
            if not out_path:
                return
            targets = [(tables[0], out_path)]
        else:
            out_dir = filedialog.askdirectory(title="Обрати теку для збереження CSV", initialdir=base_dir)
            if not out_dir:
                return
            targets = [
                (t, os.path.join(out_dir, f"{base_name}_{self._safe_filename(t.name)}.csv")) for t in tables
            ]

        try:
            for table, out_path in targets:
                converter.write_rows_csv(
                    self.output_rows(table, delim), delim, out_path, use_bom=self.bom_var.get()
                )
        except Exception as exc:
            messagebox.showerror("Помилка", f"Не вдалося зберегти CSV:\n{exc}")
            return

        self.status_var.set(f"Готово: збережено {len(targets)} файл(и/ів).")
        messagebox.showinfo("Готово", "Конвертацію завершено:\n" + "\n".join(p for _, p in targets))
        if self._active_profile():
            self._show_info("hints")

    @staticmethod
    def _safe_filename(name):
        return "".join(c if c not in '\\/:*?"<>|' else "_" for c in name).strip()


if __name__ == "__main__":
    app = App()
    app.mainloop()
