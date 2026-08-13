"""Tkinter user interface."""
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .common import get_resource_path
from .i18n import localize, tr

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None

# Theme
BG = "#1e1e1e"
PANEL = "#252526"
CARD = "#2d2d30"
CARD_HOVER = "#3a3a3d"
ACCENT = "#007acc"
TEXT = "#e8e8e8"
MUTED = "#9d9d9d"
DISABLED_CARD = "#232323"
DISABLED_TEXT = "#6b6b6b"

FONT = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_TITLE = ("Microsoft YaHei UI", 16, "bold")

_root = None
_last_dir = None


def _set_window_icon(window, default=False):
    try:
        icon = tk.PhotoImage(master=window, file=get_resource_path("icon.png"))
        window.iconphoto(default, icon)
        window._app_icon = icon
    except (OSError, tk.TclError):
        pass


class ChoiceDialog(tk.Toplevel):
    """List picker with optional thumbnails."""

    def __init__(self, parent, title, prompt, options, image_paths=None):
        super().__init__(parent)
        _set_window_icon(self)
        self.title(title)
        self.result = None
        self.transient(parent)
        self.configure(bg=BG)
        self.resizable(True, True)
        self.geometry("620x580" if image_paths else "620x390")
        self._images = []

        tk.Label(self, text=prompt, justify=tk.LEFT, wraplength=480,
                 bg=BG, fg=TEXT, font=FONT).pack(padx=14, pady=(12, 6), anchor="w")

        list_frame = tk.Frame(self, bg=BG)
        list_frame.pack(padx=14, pady=4, fill=tk.BOTH, expand=True)
        scrollbar = tk.Scrollbar(list_frame)
        style = ttk.Style(self)
        style.configure("Choice.Treeview", background=PANEL, foreground=TEXT,
                        fieldbackground=PANEL, borderwidth=0, font=FONT,
                        rowheight=82 if image_paths and Image is not None else 28)
        style.map("Choice.Treeview", background=[("selected", ACCENT)],
                  foreground=[("selected", "#ffffff")])
        self.listbox = ttk.Treeview(list_frame, show="tree", selectmode="browse",
                                    yscrollcommand=scrollbar.set, style="Choice.Treeview")
        scrollbar.config(command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        for index, option in enumerate(options):
            image = self._load_thumbnail(image_paths[index]) if image_paths and index < len(image_paths) else None
            self.listbox.insert("", tk.END, iid=str(index), text=f"  {option}", image=image or "")
        if options:
            self.listbox.selection_set("0")
            self.listbox.focus("0")
        self.listbox.bind("<Double-Button-1>", lambda e: self._ok())
        self.listbox.bind("<Return>", lambda e: self._ok())

        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.pack(pady=(6, 12))
        tk.Button(btn_frame, text=tr("确定", "OK"), width=10, command=self._ok,
                  bg=CARD, fg=TEXT, activebackground=CARD_HOVER,
                  activeforeground=TEXT, relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=8)
        tk.Button(btn_frame, text=tr("取消", "Cancel"), width=10, command=self._cancel,
                  bg=CARD, fg=TEXT, activebackground=CARD_HOVER,
                  activeforeground=TEXT, relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=8)

        self._center_on(parent)
        self.grab_set()
        self.wait_window()

    def _load_thumbnail(self, path):
        if Image is None or not path or not os.path.isfile(path):
            return None
        try:
            with Image.open(path) as source:
                source = source.convert("RGBA")
                source.thumbnail((72, 72), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(source.copy(), master=self)
            self._images.append(photo)
            return photo
        except (OSError, ValueError):
            return None

    def _center_on(self, parent):
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _ok(self):
        selection = self.listbox.selection()
        if selection:
            self.result = int(selection[0])
        self.destroy()

    def _cancel(self):
        self.destroy()


class InputDialog(tk.Toplevel):
    """Themed integer input dialog."""

    def __init__(self, parent, title, prompt, default=0, minvalue=0, maxvalue=255):
        super().__init__(parent)
        _set_window_icon(self)
        self.title(title)
        self.result = None
        self.transient(parent)
        self.configure(bg=BG)
        self._minvalue, self._maxvalue = minvalue, maxvalue

        tk.Label(self, text=prompt, justify=tk.LEFT, wraplength=460,
                 bg=BG, fg=TEXT, font=FONT).pack(padx=14, pady=(12, 8), anchor="w")
        self.entry = tk.Entry(self, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                              relief=tk.FLAT, font=FONT, highlightthickness=1,
                              highlightbackground="#3a3a3d")
        self.entry.insert(0, str(default))
        self.entry.pack(padx=14, fill=tk.X)
        self.entry.bind("<Return>", lambda e: self._ok())

        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.pack(pady=(10, 12))
        tk.Button(btn_frame, text=tr("确定", "OK"), width=10, command=self._ok,
                  bg=CARD, fg=TEXT, activebackground=CARD_HOVER,
                  activeforeground=TEXT, relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=8)
        tk.Button(btn_frame, text=tr("取消", "Cancel"), width=10, command=self._cancel,
                  bg=CARD, fg=TEXT, activebackground=CARD_HOVER,
                  activeforeground=TEXT, relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=8)

        self._center_on(parent)
        self.grab_set()
        self.entry.focus_set()
        self.wait_window()

    def _center_on(self, parent):
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _ok(self):
        try:
            value = int(self.entry.get().strip())
        except ValueError:
            return
        if value < self._minvalue or value > self._maxvalue:
            return
        self.result = value
        self.destroy()

    def _cancel(self):
        self.destroy()


class App(tk.Tk):
    def __init__(self, actions, account_loader=None, account_selector=None):
        """Build the window from localized action tuples."""
        super().__init__()
        _set_window_icon(self, default=True)
        self.title(tr("Inkscape2Forza", "Inkscape2Forza"))
        self.geometry("900x720")
        self.minsize(720, 520)
        self.configure(bg=BG)
        self._actions = actions
        self._account_loader = account_loader
        self._account_selector = account_selector
        self._cards = []
        self._busy = False
        self._ui_thread = threading.get_ident()
        self._ui_requests = queue.Queue()
        self._account_state_before_busy = "readonly"
        self._build_ui()
        self.after(20, self._process_ui_requests)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        # Header
        header = tk.Frame(self, bg=BG)
        header.pack(fill=tk.X, padx=24, pady=(20, 6))
        tk.Label(header, text=tr("Inkscape2Forza", "Inkscape2Forza"), font=FONT_TITLE,
                 bg=BG, fg=TEXT).pack(anchor="w")

        account_row = tk.Frame(header, bg=BG)
        account_row.pack(fill=tk.X, pady=(9, 0))
        tk.Label(account_row, text=tr("当前账户：", "Current account:"), font=FONT_SMALL,
                 bg=BG, fg=MUTED).pack(side=tk.LEFT)
        self.account_var = tk.StringVar()
        self.account_combo = ttk.Combobox(
            account_row, textvariable=self.account_var, state="readonly", width=42, font=FONT_SMALL
        )
        self.account_combo.pack(side=tk.LEFT, padx=(6, 0))
        self.account_combo.bind("<<ComboboxSelected>>", self._on_account_selected)
        self.refresh_accounts()

        # Action cards
        card_frame = tk.Frame(self, bg=BG)
        card_frame.pack(fill=tk.X, padx=24, pady=12)
        card_frame.grid_columnconfigure(0, weight=1)
        card_frame.grid_columnconfigure(1, weight=1)
        for i, (icon, cn, en, action) in enumerate(self._actions):
            row, col = i // 2, i % 2
            card = tk.Frame(card_frame, bg=CARD, highlightthickness=1,
                            highlightbackground="#3a3a3d", cursor="hand2")
            card.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)
            icon_label = tk.Label(card, text=icon, font=("Segoe UI Emoji", 20),
                                  bg=CARD, fg=TEXT)
            icon_label.pack(pady=(12, 2))
            name = tr(cn, en)
            name_label = tk.Label(card, text=name, font=("Microsoft YaHei UI", 11, "bold"),
                                bg=CARD, fg=TEXT)
            name_label.pack(pady=(0, 12))
            item = {"card": card,
                    "labels": [(icon_label, TEXT), (name_label, TEXT)]}
            card.bind("<Button-1>", lambda e, a=action, n=name: self.run_workflow(n, a))
            card.bind("<Enter>", lambda e, it=item: self._on_card_hover(it, True))
            card.bind("<Leave>", lambda e, it=item: self._on_card_hover(it, False))
            for child in (icon_label, name_label):
                child.bind("<Button-1>", lambda e, a=action, n=name: self.run_workflow(n, a))
            self._cards.append(item)

        # Log
        log_box = tk.LabelFrame(self, text=tr(" 运行日志 ", " Log "), bg=BG, fg=MUTED,
                                font=FONT_SMALL, bd=0, highlightthickness=1,
                                highlightbackground="#3a3a3d")
        log_box.pack(fill=tk.BOTH, expand=True, padx=24, pady=(0, 10))
        self.log_text = scrolledtext.ScrolledText(log_box, wrap=tk.WORD, state=tk.DISABLED,
                                                  bg=PANEL, fg=TEXT, insertbackground=TEXT,
                                                  font=FONT_SMALL, relief=tk.FLAT, padx=8, pady=6)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Status bar
        bottom = tk.Frame(self, bg=BG)
        bottom.pack(fill=tk.X, padx=24, pady=(0, 16))
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("dark.Horizontal.TProgressbar", troughcolor="#333333",
                        background=ACCENT, bordercolor="#333333",
                        lightcolor=ACCENT, darkcolor=ACCENT)
        self.progress = ttk.Progressbar(bottom, mode="indeterminate",
                                        style="dark.Horizontal.TProgressbar")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 12))
        self.status = tk.Label(bottom, text=tr("就绪", "Ready"), bg=BG, fg=MUTED, font=FONT_SMALL)
        self.status.pack(side=tk.RIGHT)
        tk.Button(bottom, text=tr("清空日志", "Clear log"), command=self.clear_log, bg=CARD, fg=TEXT,
                  activebackground=CARD_HOVER, activeforeground=TEXT,
                  relief=tk.FLAT, padx=12, cursor="hand2",
                  font=FONT_SMALL).pack(side=tk.RIGHT, padx=(0, 12))

    def log(self, message):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.update_idletasks()

    def refresh_accounts(self):
        accounts = list(self._account_loader(False)) if self._account_loader else []
        placeholder = tr("未找到存档账户", "No save account found")
        self.account_combo["values"] = accounts or (placeholder,)
        current = self.account_var.get()
        selected = current if current in accounts else (accounts[0] if accounts else placeholder)
        self.account_var.set(selected)
        self._account_state_before_busy = "readonly" if accounts else "disabled"
        state = "disabled" if self._busy else self._account_state_before_busy
        self.account_combo.configure(state=state)
        if accounts and self._account_selector:
            self._account_selector(selected)

    def _on_account_selected(self, _event=None):
        if self._account_selector:
            self._account_selector(self.account_var.get())

    def clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _on_card_hover(self, item, entering):
        if self._busy:
            return
        self._style_card(item, CARD_HOVER if entering else CARD, "hand2")

    def _style_card(self, item, bg, cursor, fg=None):
        item["card"].configure(bg=bg, cursor=cursor)
        for label, orig_fg in item["labels"]:
            label.configure(bg=bg, fg=orig_fg if fg is None else fg)

    def set_busy(self, busy):
        self._busy = busy
        if busy:
            self.account_combo.configure(state="disabled")
            self.progress.start(12)
            self.status.config(text=tr("处理中…", "Working…"), fg=TEXT)
            for item in self._cards:
                self._style_card(item, DISABLED_CARD, "arrow", DISABLED_TEXT)
        else:
            self.account_combo.configure(state=self._account_state_before_busy)
            self.progress.stop()
            self.status.config(text=tr("就绪", "Ready"), fg=MUTED)
            for item in self._cards:
                self._style_card(item, CARD, "hand2")
        self.config(cursor="watch" if busy else "")
        self.update_idletasks()

    def run_workflow(self, name, action):
        if self._busy:
            return
        self.log(f"========== {name} ==========")
        self.set_busy(True)
        threading.Thread(
            target=self._run_workflow, args=(action,),
            name="inkscape2forza-workflow", daemon=True,
        ).start()

    def _run_workflow(self, action):
        try:
            action()
        except Exception as e:
            self.call_on_ui(self.log, tr(f"错误：{e}", f"Error: {e}"))
            self.call_on_ui(
                messagebox.showerror, tr("错误", "Error"), str(e), parent=self
            )
        finally:
            self.call_on_ui(self._finish_workflow)

    def _finish_workflow(self):
        self.set_busy(False)
        self.log(tr("========== 完成 ==========", "========== Done =========="))

    def call_on_ui(self, callback, *args, **kwargs):
        if threading.get_ident() == self._ui_thread:
            return callback(*args, **kwargs)
        response = queue.Queue(maxsize=1)
        self._ui_requests.put((callback, args, kwargs, response))
        succeeded, value = response.get()
        if succeeded:
            return value
        raise value

    def _process_ui_requests(self):
        while True:
            try:
                callback, args, kwargs, response = self._ui_requests.get_nowait()
            except queue.Empty:
                break
            try:
                response.put((True, callback(*args, **kwargs)))
            except Exception as e:
                response.put((False, e))
        self.after(20, self._process_ui_requests)

    def on_close(self):
        if self._busy:
            if not messagebox.askyesno(tr("退出", "Quit"),
                                       tr("操作进行中，确定要退出吗？", "Operation in progress. Quit anyway?"),
                                       parent=self):
                return
        self.destroy()


def run(app):
    global _root
    _root = app
    app.mainloop()


# Dialog helpers

def log(message):
    message = localize(message)
    if _root is not None:
        _root.call_on_ui(_root.log, message)
    else:
        print(message)


def _init_dir():
    global _last_dir
    if _last_dir and os.path.exists(_last_dir):
        return _last_dir
    home = os.path.expanduser('~/Documents')
    return home if os.path.exists(home) else os.path.expanduser('~')


def ask_folder(title):
    kwargs = {"title": localize(title), "parent": _root}
    if _root is not None:
        return _root.call_on_ui(filedialog.askdirectory, **kwargs)
    return filedialog.askdirectory(**kwargs)


def ask_open_file(title, filetypes):
    global _last_dir
    kwargs = {
        "title": localize(title),
        "filetypes": [(localize(name), pattern) for name, pattern in filetypes],
        "initialdir": _init_dir(),
        "parent": _root,
    }
    path = (_root.call_on_ui(filedialog.askopenfilename, **kwargs)
            if _root else filedialog.askopenfilename(**kwargs))
    if path:
        _last_dir = os.path.dirname(path)
    return path


def ask_save_file(title, filetypes, initialfile, defaultextension=".svg"):
    global _last_dir
    kwargs = {
        "title": localize(title),
        "filetypes": [(localize(name), pattern) for name, pattern in filetypes],
        "initialfile": initialfile,
        "initialdir": _init_dir(),
        "defaultextension": defaultextension,
        "parent": _root,
    }
    path = (_root.call_on_ui(filedialog.asksaveasfilename, **kwargs)
            if _root else filedialog.asksaveasfilename(**kwargs))
    if path:
        _last_dir = os.path.dirname(path)
    return path


def ask_confirm(title, message):
    args = (localize(title), localize(message))
    return (_root.call_on_ui(messagebox.askyesno, *args, parent=_root)
            if _root else messagebox.askyesno(*args))


def ask_int(title, prompt, default=0, minvalue=0, maxvalue=255):
    if _root is None:
        return None
    def show_dialog():
        dialog = InputDialog(_root, localize(title), localize(prompt), default, minvalue, maxvalue)
        return dialog.result

    return _root.call_on_ui(show_dialog)


def ask_choice(title, prompt, options, image_paths=None):
    if _root is None or not options:
        return None
    def show_dialog():
        dialog = ChoiceDialog(_root, localize(title), localize(prompt), options, image_paths)
        return dialog.result

    return _root.call_on_ui(show_dialog)


def refresh_accounts():
    if _root is not None:
        _root.call_on_ui(_root.refresh_accounts)
