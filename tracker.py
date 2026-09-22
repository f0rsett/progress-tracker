import customtkinter as ctk
from tkinter import messagebox, filedialog
import sqlite3
import os
import sys
import re
import uuid
import json
import warnings
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.patches import FancyBboxPatch
import matplotlib.dates as mdates

warnings.filterwarnings("ignore", message=".*Glyph.*missing from font.*")
warnings.filterwarnings("ignore", message=".*missing from current font.*")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG_FIG, BG_AX, GRID = "#242424", "#2b2b2b", "#3a3a3a"
TXT, LINE, ACCENT, ACCENT2 = "#cccccc", "#555555", "#3B8ED0", "#f0a030"
HEAT_PALETTE = ["#252b35", "#0e3d63", "#1f70b5", "#42a5e6", "#8ed3ff"]
RU_MONTHS = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн",
             "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]

DEFAULT_WEAPONS = [
    "Classic", "Shorty", "Frenzy", "Ghost", "Sheriff",
    "Stinger", "Spectre", "Bucky", "Judge",
    "Bulldog", "Guardian", "Phantom", "Vandal",
    "Marshal", "Operator", "Ares", "Odin",
    "Melee",
]
NO_WEAPON = "— не выбрано —"


# ---------- пути к данным ----------
if getattr(sys, "frozen", False):
    SCRIPT_DIR = os.path.dirname(sys.executable)
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
DEFAULT_DATA_DIR = os.path.join(SCRIPT_DIR, "data")


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


_cfg = load_config()
_configured = _cfg.get("data_dir")

if _configured and os.path.isdir(_configured):
    DATA_DIR = _configured
else:
    if _configured:
        print(f"Внимание: папка {_configured} недоступна, использую {DEFAULT_DATA_DIR}")
    DATA_DIR = DEFAULT_DATA_DIR

PROFILES_DIR = os.path.join(DATA_DIR, "profiles")


def get_weapons() -> list:
    cfg = load_config()
    w = cfg.get("weapons")
    if isinstance(w, list) and w:
        return [str(x).strip() for x in w if str(x).strip()]
    return list(DEFAULT_WEAPONS)


def set_weapons(weapons: list):
    cfg = load_config()
    cfg["weapons"] = weapons
    save_config(cfg)


def set_data_dir(path: str):
    global DATA_DIR, PROFILES_DIR
    DATA_DIR = path
    PROFILES_DIR = os.path.join(DATA_DIR, "profiles")
    cfg = load_config()
    cfg["data_dir"] = path
    save_config(cfg)


print("=" * 60)
print("Режим запуска:     ", "EXE" if getattr(sys, "frozen", False) else "PY")
print("Папка с данными:   ", DATA_DIR)
print("Папка с профилями: ", PROFILES_DIR)
print("Существует:        ", os.path.isdir(PROFILES_DIR))
print("=" * 60)


# ---------- утилиты ----------
def sanitize_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[^\w.\- ]", "", name, flags=re.UNICODE)
    name = name.replace(" ", "_").strip("._-")
    return name[:40]


def game_dir(game: str) -> str:
    return os.path.join(PROFILES_DIR, game)


def profile_path(game: str, nick: str) -> str:
    return os.path.join(PROFILES_DIR, game, f"{nick}.db")


def list_profiles():
    result = []
    if not os.path.isdir(PROFILES_DIR):
        return result
    for game in sorted(os.listdir(PROFILES_DIR)):
        gp = os.path.join(PROFILES_DIR, game)
        if not os.path.isdir(gp):
            continue
        for f in sorted(os.listdir(gp)):
            if f.endswith(".db"):
                result.append((game, os.path.splitext(f)[0]))
    return result


def parse_time(s: str) -> int:
    s = s.strip()
    if not s:
        raise ValueError("Пусто")
    parts = s.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        raise ValueError("Неверный формат")
    if len(nums) == 1: return nums[0]
    if len(nums) == 2: return nums[0] * 60 + nums[1]
    if len(nums) == 3: return nums[0] * 3600 + nums[1] * 60 + nums[2]
    raise ValueError("Неверный формат")


def format_time(sec) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_datetime(iso: str) -> str:
    for fi, fo in (("%Y-%m-%d %H:%M", "%d.%m %H:%M"),
                   ("%Y-%m-%d %H:%M:%S", "%d.%m %H:%M"),
                   ("%d.%m %H:%M", "%d.%m %H:%M")):
        try:
            return datetime.strptime(iso, fi).strftime(fo)
        except Exception:
            continue
    return iso or ""


# ---------- база ----------
class DB:
    def __init__(self, path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._create_schema()
        self._migrate()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def _create_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS goals (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, target INTEGER NOT NULL,
                type TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id TEXT NOT NULL,
                k INTEGER, d INTEGER, a INTEGER, time_sec INTEGER,
                bots INTEGER, created_at TEXT NOT NULL,
                FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_entries_goal ON entries(goal_id);
            CREATE INDEX IF NOT EXISTS idx_entries_date ON entries(created_at);
        """)
        self.conn.commit()

    def _migrate(self):
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(goals)")]
        if "is_daily" not in cols:
            self.conn.execute(
                "ALTER TABLE goals ADD COLUMN is_daily INTEGER NOT NULL DEFAULT 0")

        ecols = [r[1] for r in self.conn.execute("PRAGMA table_info(entries)")]
        if "weapon" not in ecols:
            self.conn.execute("ALTER TABLE entries ADD COLUMN weapon TEXT")
        if "bots" not in ecols:
            self.conn.execute("ALTER TABLE entries ADD COLUMN bots INTEGER")
        self.conn.commit()

        rows = self.conn.execute(
            "SELECT id, created_at FROM entries WHERE created_at NOT LIKE '____-__-__%'"
        ).fetchall()
        for r in rows:
            try:
                dt = datetime.strptime(r["created_at"], "%d.%m %H:%M")
                dt = dt.replace(year=datetime.now().year)
                self.conn.execute("UPDATE entries SET created_at=? WHERE id=?",
                                  (dt.strftime("%Y-%m-%d %H:%M"), r["id"]))
            except Exception:
                pass
        self.conn.commit()

    def list_goals(self):
        return self.conn.execute("SELECT * FROM goals ORDER BY created_at").fetchall()

    def get_goal(self, gid):
        return self.conn.execute("SELECT * FROM goals WHERE id=?", (gid,)).fetchone()

    def add_goal(self, name, target, gtype, is_daily=0):
        gid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO goals(id,name,target,type,created_at,is_daily) "
            "VALUES (?,?,?,?,?,?)",
            (gid, name, target, gtype,
             datetime.now().strftime("%Y-%m-%d %H:%M"), is_daily))
        self.conn.commit()
        return gid

    def delete_goal(self, gid):
        self.conn.execute("DELETE FROM goals WHERE id=?", (gid,))
        self.conn.commit()

    def _date_clause(self, dfrom, dto):
        sql, params = "", []
        if dfrom:
            sql += " AND date(created_at) >= date(?)"; params.append(dfrom)
        if dto:
            sql += " AND date(created_at) <= date(?)"; params.append(dto)
        return sql, params

    def list_entries(self, gid, dfrom=None, dto=None):
        sql = "SELECT * FROM entries WHERE goal_id=?"
        p = [gid]
        c, cp = self._date_clause(dfrom, dto); sql += c; p += cp
        sql += " ORDER BY id DESC"
        return self.conn.execute(sql, p).fetchall()

    def count_entries(self, gid, dfrom=None, dto=None):
        sql = "SELECT COUNT(*) FROM entries WHERE goal_id=?"
        p = [gid]
        c, cp = self._date_clause(dfrom, dto); sql += c; p += cp
        return self.conn.execute(sql, p).fetchone()[0]

    def add_kda_entry(self, gid, k, d, a, weapon=None):
        self.conn.execute(
            "INSERT INTO entries(goal_id,k,d,a,weapon,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (gid, k, d, a, weapon, datetime.now().strftime("%Y-%m-%d %H:%M")))
        self.conn.commit()

    def add_time_entry(self, gid, sec, weapon=None):
        self.conn.execute(
            "INSERT INTO entries(goal_id,time_sec,weapon,created_at) "
            "VALUES (?,?,?,?)",
            (gid, sec, weapon, datetime.now().strftime("%Y-%m-%d %H:%M")))
        self.conn.commit()

    def add_range_entry(self, gid, sec, bots, weapon=None):
        self.conn.execute(
            "INSERT INTO entries(goal_id,time_sec,bots,weapon,created_at) "
            "VALUES (?,?,?,?,?)",
            (gid, sec, bots, weapon, datetime.now().strftime("%Y-%m-%d %H:%M")))
        self.conn.commit()

    def delete_entry(self, eid):
        self.conn.execute("DELETE FROM entries WHERE id=?", (eid,))
        self.conn.commit()

    def kda_stats(self, gid, dfrom=None, dto=None):
        sql = """SELECT COUNT(*) AS n, AVG(k) AS avg_k, AVG(d) AS avg_d,
                        AVG(a) AS avg_a, SUM(k) AS sum_k, SUM(d) AS sum_d,
                        SUM(a) AS sum_a FROM entries WHERE goal_id=?"""
        p = [gid]
        c, cp = self._date_clause(dfrom, dto); sql += c; p += cp
        return self.conn.execute(sql, p).fetchone()

    def time_stats(self, gid, dfrom=None, dto=None):
        sql = """SELECT COUNT(*) AS n, MIN(time_sec) AS best, AVG(time_sec) AS avg
                 FROM entries WHERE goal_id=? AND time_sec IS NOT NULL"""
        p = [gid]
        c, cp = self._date_clause(dfrom, dto); sql += c; p += cp
        return self.conn.execute(sql, p).fetchone()

    def range_stats(self, gid, dfrom=None, dto=None):
        sql = """SELECT COUNT(*) AS n, MIN(time_sec) AS best, AVG(time_sec) AS avg,
                        MAX(bots) AS max_bots, AVG(bots) AS avg_bots,
                        SUM(bots) AS total_bots
                 FROM entries WHERE goal_id=? AND time_sec IS NOT NULL"""
        p = [gid]
        c, cp = self._date_clause(dfrom, dto); sql += c; p += cp
        return self.conn.execute(sql, p).fetchone()

    def daily_counts(self, gid):
        return self.conn.execute(
            """SELECT date(created_at) AS d, COUNT(*) AS cnt
               FROM entries WHERE goal_id=?
               GROUP BY date(created_at) ORDER BY d""", (gid,)).fetchall()

    def daily_kda(self, gid):
        return self.conn.execute(
            """SELECT date(created_at) AS d,
                      SUM(k) AS sum_k, SUM(d) AS sum_d, SUM(a) AS sum_a
               FROM entries WHERE goal_id=?
               GROUP BY date(created_at) ORDER BY d""", (gid,)).fetchall()

    def daily_time(self, gid):
        return self.conn.execute(
            """SELECT date(created_at) AS d, MIN(time_sec) AS best, AVG(time_sec) AS avg
               FROM entries WHERE goal_id=? AND time_sec IS NOT NULL
               GROUP BY date(created_at) ORDER BY d""", (gid,)).fetchall()

    def daily_range(self, gid):
        return self.conn.execute(
            """SELECT date(created_at) AS d, MIN(time_sec) AS best, AVG(time_sec) AS avg,
                      MAX(bots) AS max_bots, AVG(bots) AS avg_bots
               FROM entries WHERE goal_id=? AND time_sec IS NOT NULL
               GROUP BY date(created_at) ORDER BY d""", (gid,)).fetchall()


# ---------- окно входа ----------
class LoginWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("🎯 Прогресс-трекер")
        self.geometry("500x740")
        self.resizable(False, False)
        self.chosen = None

        ctk.CTkLabel(self, text="🎯 Прогресс-трекер",
                     font=ctk.CTkFont(size=28, weight="bold")).pack(pady=(30, 5))
        ctk.CTkLabel(self, text="Выбери игру и введи игровой ник",
                     text_color="gray", font=ctk.CTkFont(size=13)).pack(pady=(0, 20))

        ctk.CTkLabel(self, text="Игра", anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(
            fill="x", padx=80, pady=(0, 3))
        self.game_entry = ctk.CTkEntry(self, placeholder_text="Например: Valorant",
                                       width=340, height=40)
        self.game_entry.pack(pady=(0, 10))

        ctk.CTkLabel(self, text="Ник", anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(
            fill="x", padx=80, pady=(0, 3))
        self.nick_entry = ctk.CTkEntry(self, placeholder_text="Например: Shadow",
                                       width=340, height=40)
        self.nick_entry.pack(pady=(0, 5))

        self.game_entry.bind("<Return>", lambda _: self.nick_entry.focus_set())
        self.nick_entry.bind("<Return>", lambda _: self.login())

        ctk.CTkButton(self, text="Войти", width=340, height=42,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      command=self.login).pack(pady=(15, 20))

        ctk.CTkLabel(self, text="Сохранённые профили",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     anchor="w").pack(fill="x", padx=80, pady=(0, 5))

        self.profiles_frame = ctk.CTkScrollableFrame(self, width=340)
        self.profiles_frame.pack(padx=80, pady=(0, 10), fill="both", expand=True)
        self._load_profiles()

        ctk.CTkButton(self, text="📁  Изменить папку для сохранения",
                      width=340, height=32,
                      fg_color="#3a3a3a", hover_color="#3B8ED0",
                      command=self.choose_folder).pack(pady=(5, 5))

        self.path_label = ctk.CTkLabel(self, text=f"📁 {PROFILES_DIR}",
                                       text_color="gray",
                                       font=ctk.CTkFont(size=9),
                                       wraplength=440, justify="center")
        self.path_label.pack(pady=(0, 15))

    def _check_writable(self, game: str) -> bool:
        folder = os.path.join(PROFILES_DIR, game)
        try:
            os.makedirs(folder, exist_ok=True)
            test_file = os.path.join(folder, ".write_test")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(test_file)
            return True
        except OSError as e:
            messagebox.showerror(
                "Ошибка",
                f"Не удалось использовать папку:\n{folder}\n\n{e}\n\n"
                "Выбери другую папку кнопкой\n"
                "«📁  Изменить папку для сохранения».",
                parent=self)
            return False

    def choose_folder(self):
        folder = filedialog.askdirectory(
            title="Выбери папку для хранения баз данных",
            initialdir=PROFILES_DIR if os.path.isdir(PROFILES_DIR) else SCRIPT_DIR)
        if not folder:
            return
        folder = os.path.normpath(folder)
        set_data_dir(folder)
        self.path_label.configure(text=f"📁 {PROFILES_DIR}")
        self._load_profiles()
        messagebox.showinfo(
            "Готово",
            f"Новая папка для данных:\n{PROFILES_DIR}\n\n"
            "Папка создастся автоматически при первом входе под профилем.",
            parent=self)

    def _load_profiles(self):
        for w in self.profiles_frame.winfo_children():
            w.destroy()
        profiles = list_profiles()
        if not profiles:
            ctk.CTkLabel(self.profiles_frame, text="Профилей пока нет",
                         text_color="gray").pack(pady=20)
            return
        by_game = {}
        for game, nick in profiles:
            by_game.setdefault(game, []).append(nick)
        for game in sorted(by_game):
            ctk.CTkLabel(self.profiles_frame, text=f"🎮  {game}",
                         anchor="w", text_color="#9ecbff",
                         font=ctk.CTkFont(size=12, weight="bold")).pack(
                fill="x", padx=5, pady=(8, 2))
            for nick in sorted(by_game[game]):
                ctk.CTkButton(
                    self.profiles_frame, text=f"👤  {nick}", anchor="w",
                    fg_color="#2b2b2b", hover_color="#3B8ED0",
                    command=lambda g=game, n=nick: self._quick_login(g, n)
                ).pack(fill="x", pady=2, padx=3)

    def _quick_login(self, game, nick):
        if not self._check_writable(game):
            return
        self.chosen = (game, nick)
        self.destroy()

    def login(self):
        raw_game = self.game_entry.get().strip()
        raw_nick = self.nick_entry.get().strip()
        if not raw_game:
            messagebox.showerror("Ошибка", "Введи название игры", parent=self); return
        if not raw_nick:
            messagebox.showerror("Ошибка", "Введи ник", parent=self); return
        game = sanitize_name(raw_game)
        nick = sanitize_name(raw_nick)
        if not game:
            messagebox.showerror("Ошибка", "Название игры содержит "
                                 "только недопустимые символы", parent=self); return
        if not nick:
            messagebox.showerror("Ошибка", "Ник содержит "
                                 "только недопустимые символы", parent=self); return
        if not self._check_writable(game):
            return
        self.chosen = (game, nick)
        self.destroy()


# ---------- приложение ----------
class App(ctk.CTk):
    def __init__(self, game: str, nickname: str):
        super().__init__()
        self.game = game
        self.nickname = nickname
        self.switch_requested = False

        self.title(f"🎯 Прогресс-трекер — {game} / {nickname}")
        self.geometry("1200x820")
        self.minsize(1000, 650)

        self.db = DB(profile_path(game, nickname))

        goals = self.db.list_goals()
        self.selected_goal_id = goals[0]["id"] if goals else None

        self.date_filter = "all"
        self.single_date = None
        self.custom_from = None
        self.custom_to = None
        self.weapon_filter = None

        if goals:
            g0 = self.db.get_goal(goals[0]["id"])
            if g0 and g0["is_daily"]:
                self.date_filter = "today"

        self.last_weapon = NO_WEAPON
        self.chart_view = "chart"

        self._current_date = datetime.now().date()
        self.chart_goal_map = {}

        self.tabview = ctk.CTkTabview(self, anchor="w")
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)
        tab_goals = self.tabview.add("🎯 Цели")
        tab_charts = self.tabview.add("📈 Графики")

        tab_goals.grid_columnconfigure(0, weight=0, minsize=340)
        tab_goals.grid_columnconfigure(1, weight=1)
        tab_goals.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(tab_goals, corner_radius=0, width=340)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        ctk.CTkLabel(self.sidebar, text="Мои цели",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
            pady=(20, 10), padx=20, anchor="w")

        tools = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        tools.pack(pady=(0, 10), padx=20, fill="x")
        ctk.CTkButton(tools, text="+ Новая цель",
                      command=self.add_goal_dialog).pack(
            side="left", fill="x", expand=True)
        ctk.CTkButton(tools, text="⚙", width=42,
                      fg_color="#3a3a3a", hover_color="#3B8ED0",
                      command=self.edit_weapons_dialog).pack(
            side="right", padx=(6, 0))

        footer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=15, pady=10)

        row_game = ctk.CTkFrame(footer, fg_color="transparent")
        row_game.pack(fill="x")
        ctk.CTkLabel(row_game, text=f"🎮  {game}",
                     anchor="w", text_color="#9ecbff",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left", padx=5)

        row_nick = ctk.CTkFrame(footer, fg_color="transparent")
        row_nick.pack(fill="x", pady=(2, 0))
        ctk.CTkLabel(row_nick, text=f"👤  {nickname}",
                     anchor="w", text_color="#9ecbff",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left", padx=5)
        ctk.CTkButton(row_nick, text="Сменить", width=90, height=28,
                      fg_color="#3a3a3a", hover_color="#3B8ED0",
                      command=self.switch_profile).pack(side="right")

        row_btn = ctk.CTkFrame(footer, fg_color="transparent")
        row_btn.pack(fill="x", pady=(6, 0))
        ctk.CTkButton(row_btn, text="📂  Открыть папку с данными",
                      height=28,
                      fg_color="#3a3a3a", hover_color="#3B8ED0",
                      command=self.open_data_folder).pack(fill="x")

        ctk.CTkLabel(footer, text=game_dir(game),
                     text_color="gray", font=ctk.CTkFont(size=8),
                     wraplength=300, justify="left").pack(
            fill="x", padx=5, pady=(4, 0))

        self.goals_frame = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent")
        self.goals_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.main = ctk.CTkFrame(tab_goals, corner_radius=0, fg_color="transparent")
        self.main.grid(row=0, column=1, sticky="nsew")

        top = ctk.CTkFrame(tab_charts, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(10, 5))
        ctk.CTkLabel(top, text="Цель:", font=ctk.CTkFont(size=14)).pack(
            side="left", padx=(5, 8))
        self.chart_goal_var = ctk.StringVar(value="—")
        self.chart_goal_menu = ctk.CTkOptionMenu(
            top, variable=self.chart_goal_var, values=["—"],
            command=lambda _=None: self.draw_chart(), width=220)
        self.chart_goal_menu.pack(side="left")

        ctk.CTkLabel(top, text="Вид:", font=ctk.CTkFont(size=14)).pack(
            side="left", padx=(25, 8))
        self.view_var = ctk.StringVar(value="График")
        self.view_menu = ctk.CTkOptionMenu(
            top, variable=self.view_var, values=["График", "Тепловая карта"],
            command=self._on_view_change, width=170)
        self.view_menu.pack(side="left")

        self.chart_frame = ctk.CTkFrame(tab_charts, fg_color="transparent")
        self.chart_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.refresh()
        self.after(60_000, self._check_date_change)

    def _cancel_all_afters(self):
        try:
            pending = self.tk.call("after", "info")
            ids = pending.split() if isinstance(pending, str) else list(pending)
            for jid in ids:
                try:
                    self.after_cancel(jid)
                except Exception:
                    pass
        except Exception:
            pass

    def report_callback_exception(self, exc, val, tb):
        if "invalid command name" in str(val):
            return
        super().report_callback_exception(exc, val, tb)

    def destroy(self):
        self._cancel_all_afters()
        try:
            self.db.close()
        except Exception:
            pass
        super().destroy()

    def switch_profile(self):
        if messagebox.askyesno(
                "Сменить профиль",
                f"Выйти из профиля «{self.nickname}» ({self.game})?"):
            self.switch_requested = True
            self.destroy()

    def open_data_folder(self):
        path = game_dir(self.game)
        try:
            if os.name == "nt":
                os.startfile(path)
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", path])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror(
                "Ошибка",
                f"Не удалось открыть папку:\n{e}\n\nПуть:\n{path}")

    def _on_view_change(self, choice):
        self.chart_view = "heatmap" if choice == "Тепловая карта" else "chart"
        self.draw_chart()

    def _check_date_change(self):
        today = datetime.now().date()
        if today != self._current_date:
            self._current_date = today
            self.refresh()
        self.after(60_000, self._check_date_change)

    def get_date_range(self, goal=None):
        if self.date_filter == "all":
            return None, None
        if self.date_filter == "today":
            t = datetime.now().strftime("%Y-%m-%d"); return t, t
        if self.date_filter == "week":
            t = datetime.now().date()
            return (t - timedelta(days=6)).isoformat(), t.isoformat()
        if self.date_filter == "month":
            t = datetime.now().date()
            return (t - timedelta(days=29)).isoformat(), t.isoformat()
        if self.date_filter == "day":
            return self.single_date, self.single_date
        if self.date_filter == "custom":
            return self.custom_from, self.custom_to
        return None, None

    def filter_label(self, goal=None):
        return {
            "all": "за всё время", "today": "за сегодня",
            "week": "за 7 дней", "month": "за 30 дней",
            "day": f"за {self.single_date}" if self.single_date else "",
            "custom": f"{self.custom_from or '…'} — {self.custom_to or '…'}",
        }.get(self.date_filter, "")

    def compute_streaks(self, gid, target):
        rows = self.db.daily_counts(gid)
        days_done = {}
        for r in rows:
            try:
                days_done[datetime.strptime(r["d"], "%Y-%m-%d").date()] = r["cnt"]
            except Exception:
                pass

        def ok(d):
            return days_done.get(d, 0) >= target

        today = datetime.now().date()
        current = 0
        d = today if ok(today) else today - timedelta(days=1)
        while ok(d):
            current += 1
            d -= timedelta(days=1)

        best = 0
        if days_done:
            ok_days = sorted([d for d in days_done if ok(d)])
            cur = 0
            prev = None
            for day in ok_days:
                if prev is not None and (day - prev).days == 1:
                    cur += 1
                else:
                    cur = 1
                best = max(best, cur)
                prev = day
        return current, best

    def _header_texts(self, ax, parts, y=1.06):
        total = sum(0.6 * size * len(txt) for txt, _, size in parts)
        cur = -total / 2
        for txt, color, size in parts:
            w = 0.6 * size * len(txt)
            ax.annotate(
                txt, xy=(0.5, y), xycoords="axes fraction",
                xytext=(cur, 0), textcoords="offset points",
                ha="left", va="bottom",
                color=color, fontsize=size, fontweight="bold",
            )
            cur += w

    def refresh(self):
        self.create_goals_frame()
        self.refresh_main()
        self.refresh_chart_menu()

    def create_goals_frame(self):
        for w in self.goals_frame.winfo_children():
            w.destroy()

        goals = self.db.list_goals()
        if not goals:
            ctk.CTkLabel(self.goals_frame, text="Целей пока нет",
                         text_color="gray").pack(pady=20)
            return

        for g in goals:
            dfrom, dto = self.get_date_range(g)
            done = self.db.count_entries(g["id"], dfrom, dto)
            total = self.db.count_entries(g["id"])
            streak = None
            if g["is_daily"]:
                streak, _ = self.compute_streaks(g["id"], g["target"])
            self.create_goal_card(g, done, total, streak)

    def create_goal_card(self, goal, done, total, streak=None):
        target = max(goal["target"], 1)
        pct = min(done / target, 1.0)
        selected = goal["id"] == self.selected_goal_id

        card = ctk.CTkFrame(
            self.goals_frame, corner_radius=10,
            fg_color=("#3B8ED0", "#1F6AA5") if selected else ("#ebebeb", "#2b2b2b"))
        card.pack(fill="x", pady=5, padx=3)

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(10, 2))

        title = goal["name"] + ("  🔁" if goal["is_daily"] else "")
        ctk.CTkLabel(header, text=title, anchor="w",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(side="left")
        if streak and streak > 0:
            ctk.CTkLabel(header, text=f"🔥{streak}", anchor="e",
                         text_color="#ffb060",
                         font=ctk.CTkFont(size=13, weight="bold")).pack(side="right")

        sub = f"{done} / {goal['target']}"
        if goal["is_daily"]:
            sub += "  (сегодня)"
        sub += f"   •   всего: {total}"
        ctk.CTkLabel(card, text=sub, anchor="w",
                     font=ctk.CTkFont(size=12)).pack(fill="x", padx=15)

        bar = ctk.CTkProgressBar(card, height=8, corner_radius=4)
        bar.pack(fill="x", padx=15, pady=(4, 12))
        bar.set(pct)

        def select(_=None, gid=goal["id"]):
            self.selected_goal_id = gid
            g = self.db.get_goal(gid)
            self.date_filter = "today" if g and g["is_daily"] else "all"
            self.single_date = None
            self.custom_from = None
            self.custom_to = None
            self.weapon_filter = None
            self.last_weapon = NO_WEAPON
            self.refresh()

        def bind_all(w):
            w.bind("<Button-1>", select)
            for c in w.winfo_children():
                bind_all(c)
        bind_all(card)

    def refresh_main(self):
        for w in self.main.winfo_children():
            w.destroy()

        goal = self.db.get_goal(self.selected_goal_id) if self.selected_goal_id else None
        if not goal:
            ctk.CTkLabel(self.main, text="Выбери цель слева или создай новую",
                         font=ctk.CTkFont(size=16),
                         text_color="gray").pack(expand=True)
            return

        top = ctk.CTkFrame(self.main, fg_color="transparent")
        top.pack(fill="x", padx=30, pady=(25, 5))
        ctk.CTkLabel(top, text=goal["name"],
                     font=ctk.CTkFont(size=28, weight="bold")).pack(side="left")
        if goal["is_daily"]:
            ctk.CTkLabel(top, text="  • ежедневная", text_color="#9ecbff",
                         font=ctk.CTkFont(size=13)).pack(side="left", padx=5)
        ctk.CTkButton(top, text="Удалить цель", width=130,
                      fg_color="#a03030", hover_color="#802020",
                      command=lambda: self.delete_goal(goal)).pack(side="right")

        if goal["is_daily"]:
            current, best = self.compute_streaks(goal["id"], goal["target"])
            row = ctk.CTkFrame(self.main, fg_color="transparent")
            row.pack(fill="x", padx=30, pady=(10, 0))
            streak_color = "#ffb060" if current > 0 else "gray"
            ctk.CTkLabel(row, text=f"🔥 Streak: {current} дн.",
                         text_color=streak_color,
                         font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
            ctk.CTkLabel(row, text=f"     🏆 Рекорд: {best} дн.",
                         text_color="#9ecbff",
                         font=ctk.CTkFont(size=14)).pack(side="left")

        self.build_filter_bar(goal)

        dfrom, dto = self.get_date_range(goal)
        count = self.db.count_entries(goal["id"], dfrom, dto)
        total = self.db.count_entries(goal["id"])
        target = max(goal["target"], 1)
        pct = min(count / target, 1.0)

        ctk.CTkLabel(
            self.main,
            text=f"{count} / {goal['target']}   ({int(pct * 100)}%)   "
                 f"{self.filter_label(goal)}      •      всего записей: {total}",
            font=ctk.CTkFont(size=15)
        ).pack(anchor="w", padx=30, pady=(10, 0))

        bar = ctk.CTkProgressBar(self.main, height=22, corner_radius=11)
        bar.pack(fill="x", padx=30, pady=(5, 10))
        bar.set(pct)

        stats_text = self.build_stats_text(goal, dfrom, dto)
        if stats_text:
            ctk.CTkLabel(self.main, text=stats_text, text_color="#9ecbff",
                         justify="left",
                         font=ctk.CTkFont(size=13)).pack(
                anchor="w", padx=30, pady=(0, 10))

        self.build_add_form(goal)
        self.build_entries_section(goal)

    def build_filter_bar(self, goal):
        row = ctk.CTkFrame(self.main, fg_color="transparent")
        row.pack(fill="x", padx=30, pady=(5, 0))

        ctk.CTkLabel(row, text="Период:").pack(side="left", padx=(0, 8))
        options = ["Все время", "Сегодня", "7 дней", "30 дней",
                   "Конкретный день", "Свой период"]
        key_map = {"Все время": "all", "Сегодня": "today", "7 дней": "week",
                   "30 дней": "month", "Конкретный день": "day",
                   "Свой период": "custom"}
        rev = {v: k for k, v in key_map.items()}

        def on_change(choice):
            self.date_filter = key_map[choice]
            self.after(0, self.refresh)

        opt = ctk.CTkOptionMenu(row, values=options, command=on_change, width=170)
        opt.set(rev.get(self.date_filter, "Все время"))
        opt.pack(side="left")

        if self.date_filter == "day":
            e_day = ctk.CTkEntry(row, width=130, placeholder_text="2026-09-15")
            if self.single_date:
                e_day.insert(0, self.single_date)
            e_day.pack(side="left", padx=(10, 5))

            def apply_day():
                d = e_day.get().strip()
                if not d:
                    messagebox.showerror("Ошибка", "Введи дату (YYYY-MM-DD)"); return
                try:
                    datetime.strptime(d, "%Y-%m-%d")
                except ValueError:
                    messagebox.showerror("Ошибка",
                                         "Формат даты: YYYY-MM-DD"); return
                self.single_date = d
                self.refresh()

            ctk.CTkButton(row, text="Показать", width=100,
                          command=apply_day).pack(side="left")
            ctk.CTkButton(row, text="Сегодня", width=90,
                          fg_color="#3a3a3a", hover_color="#3B8ED0",
                          command=lambda: (setattr(
                              self, "single_date",
                              datetime.now().strftime("%Y-%m-%d")),
                              self.refresh())).pack(side="left", padx=(6, 0))

        if self.date_filter == "custom":
            e_from = ctk.CTkEntry(row, width=120, placeholder_text="2026-01-01")
            e_to = ctk.CTkEntry(row, width=120, placeholder_text="2026-12-31")
            if self.custom_from: e_from.insert(0, self.custom_from)
            if self.custom_to: e_to.insert(0, self.custom_to)
            e_from.pack(side="left", padx=(10, 3))
            ctk.CTkLabel(row, text="—").pack(side="left")
            e_to.pack(side="left", padx=(3, 10))

            def apply():
                f = e_from.get().strip() or None
                t = e_to.get().strip() or None
                for x in (f, t):
                    if x:
                        try:
                            datetime.strptime(x, "%Y-%m-%d")
                        except ValueError:
                            messagebox.showerror("Ошибка",
                                                 "Формат даты: YYYY-MM-DD"); return
                self.custom_from, self.custom_to = f, t
                self.refresh()

            ctk.CTkButton(row, text="Применить", width=100,
                          command=apply).pack(side="left")

    def build_stats_text(self, goal, dfrom, dto):
        if goal["type"] == "kda":
            s = self.db.kda_stats(goal["id"], dfrom, dto)
            if not s["n"]:
                return None
            ratio = (s["sum_k"] + s["sum_a"]) / max(s["sum_d"], 1)
            return (f"Среднее:  K {s['avg_k']:.1f}  D {s['avg_d']:.1f}  "
                    f"A {s['avg_a']:.1f}      Общий KDA: {ratio:.2f}")
        if goal["type"] == "time":
            s = self.db.time_stats(goal["id"], dfrom, dto)
            if not s["n"]:
                return None
            return (f"Лучшее время: {format_time(s['best'])}"
                    f"      Среднее: {format_time(s['avg'])}")
        s = self.db.range_stats(goal["id"], dfrom, dto)
        if not s["n"]:
            return None
        return (f"⏱ Лучшее: {format_time(s['best'])}   "
                f"среднее: {format_time(s['avg'])}      |      "
                f"🎯 боты: макс {int(s['max_bots'] or 0)}   "
                f"среднее {s['avg_bots']:.1f}   "
                f"всего {int(s['total_bots'] or 0)}")

    def build_add_form(self, goal):
        form = ctk.CTkFrame(self.main, corner_radius=12)
        form.pack(fill="x", padx=30, pady=(5, 15))

        weapons = get_weapons()
        weapon_var = ctk.StringVar(value=self.last_weapon)

        def current_weapon_value():
            w = weapon_var.get()
            self.last_weapon = w
            return None if w == NO_WEAPON else w

        if goal["type"] == "kda":
            for i, label in enumerate(["K", "D", "A"]):
                ctk.CTkLabel(form, text=label).grid(
                    row=0, column=i, padx=(15, 5), pady=(10, 0))
            e_k = ctk.CTkEntry(form, width=70); e_k.grid(
                row=1, column=0, padx=(15, 5), pady=(0, 12))
            e_d = ctk.CTkEntry(form, width=70); e_d.grid(
                row=1, column=1, padx=5, pady=(0, 12))
            e_a = ctk.CTkEntry(form, width=70); e_a.grid(
                row=1, column=2, padx=5, pady=(0, 12))

            def add():
                try:
                    k, d, a = int(e_k.get()), int(e_d.get()), int(e_a.get())
                except ValueError:
                    messagebox.showerror("Ошибка",
                                         "Введи целые числа для K / D / A"); return
                self.db.add_kda_entry(goal["id"], k, d, a, current_weapon_value())
                self.refresh()

            ctk.CTkButton(form, text="Добавить", command=add).grid(
                row=0, column=3, rowspan=2, padx=20, pady=10)

        elif goal["type"] == "time":
            ctk.CTkLabel(form, text="Время (MM:SS  или  секунды)").grid(
                row=0, column=0, padx=(15, 5), pady=(10, 0), sticky="w")
            e_t = ctk.CTkEntry(form, width=150); e_t.grid(
                row=1, column=0, padx=(15, 5), pady=(0, 12))

            def add():
                try:
                    secs = parse_time(e_t.get())
                except ValueError as ex:
                    messagebox.showerror("Ошибка", str(ex)); return
                self.db.add_time_entry(goal["id"], secs, current_weapon_value())
                self.refresh()

            ctk.CTkButton(form, text="Добавить", command=add).grid(
                row=0, column=1, rowspan=2, padx=20, pady=10)

        else:  # range
            ctk.CTkLabel(form, text="Время (MM:SS  или  секунды)").grid(
                row=0, column=0, padx=(15, 5), pady=(10, 0), sticky="w")
            ctk.CTkLabel(form, text="Убито ботов").grid(
                row=0, column=1, padx=5, pady=(10, 0), sticky="w")
            e_t = ctk.CTkEntry(form, width=140); e_t.grid(
                row=1, column=0, padx=(15, 5), pady=(0, 12))
            e_b = ctk.CTkEntry(form, width=100); e_b.grid(
                row=1, column=1, padx=5, pady=(0, 12))

            def add():
                try:
                    secs = parse_time(e_t.get())
                except ValueError as ex:
                    messagebox.showerror("Ошибка", str(ex)); return
                try:
                    bots = int(e_b.get())
                    if bots < 0:
                        raise ValueError
                except ValueError:
                    messagebox.showerror("Ошибка",
                                         "Количество ботов — целое число ≥ 0"); return
                self.db.add_range_entry(goal["id"], secs, bots,
                                        current_weapon_value())
                self.refresh()

            ctk.CTkButton(form, text="Добавить", command=add).grid(
                row=0, column=2, rowspan=2, padx=20, pady=10)

        wrow = ctk.CTkFrame(form, fg_color="transparent")
        wrow.grid(row=2, column=0, columnspan=4,
                  padx=15, pady=(0, 12), sticky="w")
        ctk.CTkLabel(wrow, text="Оружие:").pack(side="left", padx=(0, 8))
        ctk.CTkComboBox(
            wrow, values=[NO_WEAPON] + weapons,
            variable=weapon_var, width=240).pack(side="left")
        ctk.CTkButton(
            wrow, text="⚙", width=36, height=28,
            fg_color="#3a3a3a", hover_color="#3B8ED0",
            command=self.edit_weapons_dialog).pack(side="left", padx=(6, 0))

    def build_entries_section(self, goal):
        header = ctk.CTkFrame(self.main, fg_color="transparent")
        header.pack(fill="x", padx=30, pady=(5, 5))

        dfrom, dto = self.get_date_range(goal)
        entries = self.db.list_entries(goal["id"], dfrom, dto)
        if self.weapon_filter:
            entries = [e for e in entries if e["weapon"] == self.weapon_filter]

        ctk.CTkLabel(header, text=f"Записи ({len(entries)})",
                     font=ctk.CTkFont(size=17, weight="bold")).pack(side="left")

        weapons = get_weapons()
        if self.weapon_filter and self.weapon_filter not in weapons:
            self.weapon_filter = None

        if weapons:
            ALL = "Все оружия"

            def on_weapon(choice):
                self.weapon_filter = None if choice == ALL else choice
                self.after(0, self.refresh_main)

            wopt = ctk.CTkOptionMenu(
                header, values=[ALL] + weapons, width=180,
                command=on_weapon)
            wopt.set(self.weapon_filter or ALL)
            wopt.pack(side="right")

        if not entries:
            ctk.CTkLabel(self.main, text="Записей нет",
                         text_color="gray").pack(anchor="w", padx=30)
            return

        scroll = ctk.CTkScrollableFrame(self.main, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        for entry in entries:
            row = ctk.CTkFrame(scroll, corner_radius=8)
            row.pack(fill="x", pady=3, padx=5)

            if goal["type"] == "kda":
                ratio = (entry["k"] + entry["a"]) / max(entry["d"], 1)
                text = (f"K {entry['k']}   D {entry['d']}   A {entry['a']}"
                        f"      KDA {ratio:.2f}")
            elif goal["type"] == "time":
                text = f"⏱  {format_time(entry['time_sec'])}"
            else:  # range
                bots = entry["bots"] if "bots" in entry.keys() else None
                bots_txt = f"{int(bots)}" if bots is not None else "—"
                text = (f"⏱  {format_time(entry['time_sec'])}"
                        f"      🎯  боты: {bots_txt}")

            ctk.CTkLabel(row, text=text, anchor="w",
                         font=ctk.CTkFont(size=14)).pack(
                side="left", padx=15, pady=10)

            weapon = entry["weapon"] if "weapon" in entry.keys() else None
            if weapon:
                ctk.CTkLabel(row, text=f"[{weapon}]",
                             text_color="#8ed3ff",
                             font=ctk.CTkFont(size=13, weight="bold")).pack(
                    side="left", padx=(0, 8))

            ctk.CTkLabel(row, text=fmt_datetime(entry["created_at"]),
                         text_color="gray",
                         font=ctk.CTkFont(size=11)).pack(side="left", padx=5)

            ctk.CTkButton(row, text="✕", width=32,
                          fg_color="#a03030", hover_color="#802020",
                          command=lambda eid=entry["id"]: self.delete_entry(eid)
                          ).pack(side="right", padx=10, pady=8)

    def edit_weapons_dialog(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Список оружия")
        dlg.geometry("420x560")
        dlg.transient(self)
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="Список оружия (одно на строку)",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(
            pady=(20, 5), padx=20, anchor="w")
        ctk.CTkLabel(dlg, text="Этот список появится в выпадающем меню на форме добавления.",
                     text_color="gray", font=ctk.CTkFont(size=11)).pack(
            pady=(0, 10), padx=20, anchor="w")

        textbox = ctk.CTkTextbox(dlg, height=350)
        textbox.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        textbox.insert("1.0", "\n".join(get_weapons()))

        def reset_default():
            textbox.delete("1.0", "end")
            textbox.insert("1.0", "\n".join(DEFAULT_WEAPONS))

        def save():
            raw = textbox.get("1.0", "end").strip()
            weapons = [line.strip() for line in raw.splitlines() if line.strip()]
            if not weapons:
                messagebox.showerror("Ошибка", "Список не может быть пустым",
                                     parent=dlg); return
            set_weapons(weapons)
            self.weapon_filter = None
            self.last_weapon = NO_WEAPON
            self.refresh()
            dlg.destroy()

        btns = ctk.CTkFrame(dlg, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=(0, 20))
        ctk.CTkButton(btns, text="Valorant по умолчанию",
                      fg_color="#3a3a3a", hover_color="#3B8ED0",
                      command=reset_default).pack(side="left")
        ctk.CTkButton(btns, text="Сохранить", command=save).pack(side="right")

    def refresh_chart_menu(self):
        goals = self.db.list_goals()
        self.chart_goal_map = {g["name"]: g["id"] for g in goals}
        values = list(self.chart_goal_map.keys()) or ["—"]
        self.chart_goal_menu.configure(values=values)
        if self.chart_goal_var.get() not in self.chart_goal_map:
            self.chart_goal_var.set(values[0])
        self.draw_chart()

    def draw_chart(self):
        for w in self.chart_frame.winfo_children():
            w.destroy()
        gid = self.chart_goal_map.get(self.chart_goal_var.get())
        if not gid:
            ctk.CTkLabel(self.chart_frame, text="Нет целей для отображения",
                         text_color="gray").pack(expand=True)
            return
        goal = self.db.get_goal(gid)
        if not goal:
            return
        if self.chart_view == "heatmap":
            self._draw_heatmap(goal)
        else:
            self._draw_line_chart(goal)

    def _draw_line_chart(self, goal):
        fig = Figure(figsize=(9, 5.5), dpi=100)
        fig.patch.set_facecolor(BG_FIG)
        ax = fig.add_subplot(111)
        ax.set_facecolor(BG_AX)
        plotted = False

        if goal["is_daily"]:
            rows = self.db.daily_counts(goal["id"])
            if rows:
                dates = [datetime.strptime(r["d"], "%Y-%m-%d") for r in rows]
                counts = [r["cnt"] for r in rows]
                colors = [ACCENT if c >= goal["target"] else "#666666"
                          for c in counts]
                ax.bar(dates, counts, color=colors, width=0.7)
                ax.axhline(goal["target"], color=ACCENT2, linestyle="--",
                           linewidth=1.5, label=f"Цель = {goal['target']}")
                cur, best = self.compute_streaks(goal["id"], goal["target"])
                self._header_texts(ax, [
                    (f"{goal['name']} — выполнение по дням", "#ffffff", 13),
                    ("      ", "#ffffff", 13),
                    (f"★ серия: {cur} дн.", "#ffb060", 13),
                    ("      ", "#ffffff", 13),
                    (f"★ рекорд: {best} дн.", "#8ed3ff", 13),
                ])
                ax.set_ylabel("Записей за день", color=TXT)
                ax.legend(facecolor=BG_AX, edgecolor=LINE, labelcolor="white")
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
                fig.autofmt_xdate(rotation=30)
                plotted = True

        elif goal["type"] == "kda":
            rows = self.db.daily_kda(goal["id"])
            if rows:
                dates = [datetime.strptime(r["d"], "%Y-%m-%d") for r in rows]
                ratios = [(r["sum_k"] + r["sum_a"]) / max(r["sum_d"], 1)
                          for r in rows]
                ax.plot(dates, ratios, marker="o", color=ACCENT,
                        linewidth=2, markersize=6)
                ax.fill_between(dates, ratios, alpha=0.15, color=ACCENT)
                self._header_texts(ax, [
                    (f"{goal['name']} — KDA по дням", "#ffffff", 13),
                ])
                ax.set_ylabel("KDA", color=TXT)
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
                fig.autofmt_xdate(rotation=30)
                plotted = True

        elif goal["type"] == "time":
            rows = self.db.daily_time(goal["id"])
            if rows:
                dates = [datetime.strptime(r["d"], "%Y-%m-%d") for r in rows]
                bests = [r["best"] for r in rows]
                avgs = [r["avg"] for r in rows]
                ax.plot(dates, bests, marker="o", color=ACCENT,
                        linewidth=2, markersize=6, label="Лучшее")
                ax.plot(dates, avgs, marker="s", color=ACCENT2,
                        linewidth=1.5, markersize=5, label="Среднее", alpha=0.85)
                self._header_texts(ax, [
                    (f"{goal['name']} — время по дням", "#ffffff", 13),
                ])
                ax.set_ylabel("Секунды", color=TXT)
                ax.legend(facecolor=BG_AX, edgecolor=LINE, labelcolor="white")
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
                fig.autofmt_xdate(rotation=30)
                plotted = True

        else:  # range
            rows = self.db.daily_range(goal["id"])
            if rows:
                dates = [datetime.strptime(r["d"], "%Y-%m-%d") for r in rows]
                bests = [r["best"] for r in rows]
                avg_bots = [r["avg_bots"] for r in rows]

                l1, = ax.plot(dates, bests, marker="o", color=ACCENT,
                              linewidth=2, markersize=6,
                              label="Лучшее время (сек)")
                ax.set_ylabel("Время, сек", color=ACCENT)
                ax.tick_params(axis="y", colors=ACCENT)

                ax2 = ax.twinx()
                l2, = ax2.plot(dates, avg_bots, marker="s", color=ACCENT2,
                               linewidth=1.5, markersize=5,
                               label="Среднее ботов", alpha=0.9)
                ax2.set_ylabel("Ботов за сессию", color=ACCENT2)
                ax2.tick_params(axis="y", colors=ACCENT2)
                for sp in ax2.spines.values():
                    sp.set_color(LINE)

                self._header_texts(ax, [
                    (f"{goal['name']} — время и боты по дням", "#ffffff", 13),
                ])
                ax.legend(handles=[l1, l2],
                          facecolor=BG_AX, edgecolor=LINE, labelcolor="white",
                          loc="upper left")
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
                fig.autofmt_xdate(rotation=30)
                plotted = True

        if not plotted:
            ctk.CTkLabel(self.chart_frame, text="Нет данных для графика",
                         text_color="gray").pack(expand=True)
            return

        # X-ось — всегда серым
        ax.tick_params(axis="x", colors=TXT, labelsize=9)
        # Y-ось: для range цвета уже выставлены (синий/оранжевый).
        # Для остальных — светло-серый, чтобы было видно.
        if not (goal["type"] == "range" and not goal["is_daily"]):
            ax.tick_params(axis="y", colors=TXT, labelsize=9)

        for sp in ax.spines.values():
            sp.set_color(LINE)
        ax.grid(True, color=GRID, linestyle="--", linewidth=0.5, alpha=0.6)

        canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    def _draw_heatmap(self, goal):
        fig = Figure(figsize=(11, 4.4), dpi=100)
        fig.patch.set_facecolor(BG_FIG)
        ax = fig.add_subplot(111)
        ax.set_facecolor(BG_FIG)

        rows = self.db.daily_counts(goal["id"])
        counts = {}
        for r in rows:
            try:
                counts[datetime.strptime(r["d"], "%Y-%m-%d").date()] = r["cnt"]
            except Exception:
                pass

        today = datetime.now().date()
        end_sunday = today + timedelta(days=6 - today.weekday())
        start_monday = end_sunday - timedelta(days=52 * 7 - 1)

        target = max(goal["target"], 1)
        max_count = max(counts.values()) if counts else 1

        def color_for(cnt):
            if cnt <= 0:
                return HEAT_PALETTE[0]
            if goal["is_daily"]:
                # ежедневные: относительно цели дня
                ratio = min(cnt / target, 1.0)
                if ratio < 0.25: return HEAT_PALETTE[1]
                if ratio < 0.5:  return HEAT_PALETTE[2]
                if ratio < 0.85: return HEAT_PALETTE[3]
                return HEAT_PALETTE[4]
            # не-ежедневные: абсолютная шкала
            if cnt == 1: return HEAT_PALETTE[1]   # тёмно-синий
            if cnt == 2: return HEAT_PALETTE[2]   # средний
            if cnt == 3: return HEAT_PALETTE[3]   # светлее
            return HEAT_PALETTE[4]                # 4+ → самый светлый

        CELL, GAP = 0.9, 0.12
        SIZE = CELL - GAP
        ROUND = 0.18
        weeks = 52

        def rounded_cell(x, y, size, color, rounding=ROUND):
            ax.add_patch(FancyBboxPatch(
                (x + GAP / 2, y + GAP / 2), size, size,
                boxstyle=f"round,pad=0,rounding_size={rounding}",
                facecolor=color, edgecolor="none", linewidth=0,
            ))

        for w in range(weeks):
            for d in range(7):
                date = start_monday + timedelta(weeks=w, days=d)
                if date > today:
                    continue
                cnt = counts.get(date, 0)
                rounded_cell(w, d, SIZE, color_for(cnt))

        month_pos = []
        cur = start_monday.replace(day=1)
        if cur < start_monday:
            cur = (cur + timedelta(days=32)).replace(day=1)
        while cur <= today:
            idx = (cur - start_monday).days // 7
            month_pos.append((idx, RU_MONTHS[cur.month - 1]))
            if cur.month == 12:
                cur = cur.replace(year=cur.year + 1, month=1)
            else:
                cur = cur.replace(month=cur.month + 1)
        ax.set_xticks([w for w, _ in month_pos])
        ax.set_xticklabels([m for _, m in month_pos], fontsize=9)
        ax.set_yticks([0, 2, 4, 6])
        ax.set_yticklabels(["Пн", "Ср", "Пт", "Вс"], fontsize=9)
        ax.set_xlim(-0.5, weeks + 0.5)
        ax.set_ylim(8.6, -1.4)
        ax.set_aspect("equal")

        legend_y = 7.7
        ax.text(weeks - 7.6, legend_y + 0.42, "Меньше",
                ha="right", va="center", color=TXT, fontsize=9)
        for i, c in enumerate(HEAT_PALETTE):
            ax.add_patch(FancyBboxPatch(
                (weeks - 7.4 + i * 0.9 + 0.06, legend_y + 0.06),
                0.78, 0.78,
                boxstyle="round,pad=0,rounding_size=0.14",
                facecolor=c, edgecolor="none", linewidth=0,
            ))
        ax.text(weeks - 7.4 + 5 * 0.9 + 0.1, legend_y + 0.42, "Больше",
                ha="left", va="center", color=TXT, fontsize=9)

        if goal["is_daily"]:
            cur_streak, best = self.compute_streaks(goal["id"], goal["target"])
            self._header_texts(ax, [
                (f"{goal['name']} — активность за год", "#ffffff", 13),
                ("      ", "#ffffff", 13),
                (f"★ серия: {cur_streak} дн.", "#ffb060", 13),
                ("      ", "#ffffff", 13),
                (f"★ рекорд: {best} дн.", "#8ed3ff", 13),
            ], y=1.04)
        else:
            self._header_texts(ax, [
                (f"{goal['name']} — активность за год", "#ffffff", 13),
            ], y=1.04)

        ax.tick_params(colors=TXT)
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.grid(False)

        canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    def delete_entry(self, eid):
        self.db.delete_entry(eid)
        self.refresh()

    def delete_goal(self, goal):
        if not messagebox.askyesno(
                "Удалить", f"Удалить цель «{goal['name']}» со всеми записями?"):
            return
        self.db.delete_goal(goal["id"])
        goals = self.db.list_goals()
        self.selected_goal_id = goals[0]["id"] if goals else None
        self.weapon_filter = None
        if self.selected_goal_id:
            g = self.db.get_goal(self.selected_goal_id)
            self.date_filter = "today" if g and g["is_daily"] else "all"
        else:
            self.date_filter = "all"
        self.refresh()

    def add_goal_dialog(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Новая цель")
        dlg.geometry("500x420")
        dlg.transient(self)
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="Название").pack(pady=(20, 5), padx=20, anchor="w")
        name_entry = ctk.CTkEntry(dlg, placeholder_text="Например: Range (move)")
        name_entry.pack(fill="x", padx=20)

        ctk.CTkLabel(dlg, text="Сколько раз выполнить").pack(
            pady=(15, 5), padx=20, anchor="w")
        target_entry = ctk.CTkEntry(dlg)
        target_entry.insert(0, "5")
        target_entry.pack(fill="x", padx=20)

        ctk.CTkLabel(dlg, text="Что записывать").pack(
            pady=(15, 5), padx=20, anchor="w")
        type_var = ctk.StringVar(value="kda")
        tf = ctk.CTkFrame(dlg, fg_color="transparent")
        tf.pack(fill="x", padx=20)
        ctk.CTkRadioButton(tf, text="KDA (K/D/A)", variable=type_var,
                           value="kda").pack(anchor="w", pady=2)
        ctk.CTkRadioButton(tf, text="Время + количество ботов",
                           variable=type_var, value="range").pack(anchor="w", pady=2)

        daily_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            dlg,
            text="🔁 Ежедневная цель (прогресс сбрасывается каждый день)",
            variable=daily_var).pack(pady=(15, 5), padx=20, anchor="w")

        def create():
            name = name_entry.get().strip()
            if not name:
                messagebox.showerror("Ошибка", "Введи название", parent=dlg); return
            try:
                target = int(target_entry.get())
                if target <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Ошибка",
                                     "Цель должна быть положительным числом",
                                     parent=dlg); return

            self.selected_goal_id = self.db.add_goal(
                name, target, type_var.get(), 1 if daily_var.get() else 0)
            self.weapon_filter = None
            self.last_weapon = NO_WEAPON
            self.date_filter = "today" if daily_var.get() else "all"
            self.refresh()
            dlg.destroy()

        ctk.CTkButton(dlg, text="Создать", command=create).pack(pady=20)


# ---------- запуск ----------
def run():
    while True:
        login = LoginWindow()
        login.mainloop()
        if not login.chosen:
            return
        game, nick = login.chosen

        app = App(game, nick)
        app.mainloop()
        if not app.switch_requested:
            return


if __name__ == "__main__":
    run()