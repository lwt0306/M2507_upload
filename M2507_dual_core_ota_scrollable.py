"""M2507 双核串口升级工具。

Windows 7 SP1 发布版兼容基线：Python 3.8.10 + pyserial 3.5 + PyInstaller 4.10。
Python 3.9 及以上的 DLL 不支持 Windows 7；修改源码后仍须重新打包。
运行时第三方依赖仅为 pyserial；Tkinter 随 Python 提供。
"""

import logging
from logging.handlers import RotatingFileHandler
import os
import queue
import struct
import sys
import tempfile
import threading
import time
import zlib
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import serial
import serial.tools.list_ports


# =========================
# 通信协议定义
# =========================

CMD_PROMPT_POWERON = b'\xEB\x90\x55\xaa\x55\xaa'  # 嵌入式->上位机：可以进入升级模式
CMD_ACK_INFO_OK    = b'\xEB\x90\x66\xbb\x66\xbb'  # 嵌入式->上位机：升级信息帧接收成功
CMD_ACK_INFO_ERR   = b'\xEB\x90\x77\xcc\x77\xcc'  # 嵌入式->上位机：升级信息帧接收异常
CMD_ACK_CRC_OK     = b'\xEB\x90\x88\xdd\x88\xdd'  # 嵌入式->上位机：程序 CRC 校验成功
CMD_ACK_CRC_ERR    = b'\xEB\x90\x99\xee\x99\xee'  # 嵌入式->上位机：程序 CRC 校验异常
CMD_ACK_FLASH_OK   = b'\xEB\x90\x22\x11\x22\x11'  # 嵌入式->上位机：Flash 写入并回读校验成功
CMD_ACK_FLASH_ERR  = b'\xEB\x90\x33\x11\x33\x11'  # 嵌入式->上位机：Flash 写入或回读校验异常
CMD_ACK_CORE_ERR   = b'\xEB\x90\x44\x11\x44\x11'  # 嵌入式->上位机：目标核选择异常；若下位机未实现，可忽略

FRAME_HEADER = b'\xEB\x90'

TARGET_CORE0 = 0x00
TARGET_CORE1 = 0x01

TARGET_NAMES = {
    TARGET_CORE0: "Core0 / SYS_USERAPP_PARTITION_START",
    TARGET_CORE1: "Core1 / CPU1_FLASH_START",
}

MAX_FIRMWARE_SIZE = 3 * 1024 * 1024
DEFAULT_CHUNK_SIZE = 512


class DualCoreOtaUpgraderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("M2507双核串口固件升级工具")

        # 根据当前屏幕尺寸自适应窗口高度，避免低分辨率屏幕底部按钮被裁掉。
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        win_w = min(920, max(780, screen_w - 120))
        win_h = min(720, max(520, screen_h - 120))
        self.root.geometry(f"{win_w}x{win_h}")
        self.root.minsize(760, 500)

        self.serial = None
        self.bin_data = b""
        self.file_path = ""
        self.file_size = 0
        self.file_crc = 0

        self.is_upgrading = False
        self.stop_event = threading.Event()
        self._closing = False
        self.worker = None
        self.ui_queue = queue.Queue()
        self.active_chunk_size = DEFAULT_CHUNK_SIZE
        self._rx_buffer = b""

        self.target_core_var = tk.IntVar(value=TARGET_CORE0)
        self.active_target_core = TARGET_CORE0
        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value="115200")
        self.chunk_size_var = tk.StringVar(value=str(DEFAULT_CHUNK_SIZE))
        self.status_var = tk.StringVar(value="未连接")
        self.file_info_var = tk.StringVar(value="尚未选择固件文件")
        self.path_var = tk.StringVar(value="未选择文件")

        self._setup_style()
        self._setup_ui()
        self.refresh_ports()

        self.root.after(50, self._process_ui_queue)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # =========================
    # UI
    # =========================

    def _setup_style(self):
        style = ttk.Style()
        try:
            # clam 主题对自定义按钮颜色、进度条颜色支持更稳定
            style.theme_use("clam")
        except tk.TclError:
            pass

        # 高级感配色：深海军蓝 + 亮蓝主色 + 白色卡片 + 青绿色成功色
        self.colors = {
            "bg": "#EEF4FF",
            "bg_deep": "#0B1220",
            "hero": "#101B33",
            "hero_2": "#172554",
            "card": "#FFFFFF",
            "card_soft": "#F8FAFF",
            "border": "#D7E3FF",
            "shadow": "#C7D2FE",
            "primary": "#2563EB",
            "primary_dark": "#1D4ED8",
            "primary_soft": "#DBEAFE",
            "accent": "#7C3AED",
            "accent_soft": "#EDE9FE",
            "success": "#10B981",
            "success_dark": "#059669",
            "warning": "#F59E0B",
            "danger": "#EF4444",
            "danger_dark": "#DC2626",
            "text": "#0F172A",
            "muted": "#64748B",
            "white": "#FFFFFF",
            "log_bg": "#070B18",
            "log_fg": "#D8EAFE",
        }

        self.root.configure(bg=self.colors["bg"])

        style.configure("App.TFrame", background=self.colors["bg"])
        style.configure("TFrame", background=self.colors["bg"])
        style.configure("Card.TFrame", background=self.colors["card"])
        style.configure("SoftCard.TFrame", background=self.colors["card_soft"])

        style.configure(
            "TLabel",
            background=self.colors["bg"],
            foreground=self.colors["text"],
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "Card.TLabel",
            background=self.colors["card"],
            foreground=self.colors["text"],
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "Muted.TLabel",
            background=self.colors["card"],
            foreground=self.colors["muted"],
            font=("Microsoft YaHei UI", 9),
        )
        style.configure(
            "Status.TLabel",
            background=self.colors["bg"],
            foreground=self.colors["hero"],
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.configure(
            "Section.TLabel",
            background=self.colors["card"],
            foreground=self.colors["text"],
            font=("Microsoft YaHei UI", 11, "bold"),
        )

        style.configure(
            "TButton",
            font=("Microsoft YaHei UI", 10),
            padding=(12, 7),
            background=self.colors["card_soft"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["card"],
            darkcolor=self.colors["border"],
            relief="flat",
        )
        style.map(
            "TButton",
            background=[("active", self.colors["primary_soft"]), ("pressed", self.colors["primary_soft"])],
            foreground=[("disabled", "#94A3B8")],
        )

        style.configure(
            "Primary.TButton",
            font=("Microsoft YaHei UI", 11, "bold"),
            padding=(18, 10),
            background=self.colors["primary"],
            foreground=self.colors["white"],
            bordercolor=self.colors["primary"],
            lightcolor=self.colors["primary"],
            darkcolor=self.colors["primary_dark"],
            relief="flat",
        )
        style.map(
            "Primary.TButton",
            background=[("active", self.colors["primary_dark"]), ("pressed", self.colors["primary_dark"]), ("disabled", "#CBD5E1")],
            foreground=[("active", self.colors["white"]), ("pressed", self.colors["white"]), ("disabled", "#F8FAFC")],
        )

        style.configure(
            "Danger.TButton",
            font=("Microsoft YaHei UI", 10, "bold"),
            padding=(12, 8),
            background=self.colors["danger"],
            foreground=self.colors["white"],
            bordercolor=self.colors["danger"],
            lightcolor=self.colors["danger"],
            darkcolor=self.colors["danger_dark"],
            relief="flat",
        )
        style.map(
            "Danger.TButton",
            background=[("active", self.colors["danger_dark"]), ("pressed", self.colors["danger_dark"]), ("disabled", "#CBD5E1")],
            foreground=[("active", self.colors["white"]), ("pressed", self.colors["white"]), ("disabled", "#F8FAFC")],
        )

        style.configure(
            "TCombobox",
            padding=5,
            fieldbackground=self.colors["white"],
            background=self.colors["white"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            arrowcolor=self.colors["primary"],
        )

        style.configure(
            "Horizontal.TProgressbar",
            thickness=15,
            background=self.colors["success"],
            troughcolor=self.colors["primary_soft"],
            bordercolor=self.colors["primary_soft"],
            lightcolor=self.colors["success"],
            darkcolor=self.colors["success_dark"],
        )

        style.configure(
            "TRadiobutton",
            background=self.colors["card"],
            foreground=self.colors["text"],
            font=("Microsoft YaHei UI", 10),
        )
        style.map(
            "TRadiobutton",
            background=[("active", self.colors["card"])],
            foreground=[("active", self.colors["primary"])],
        )

    def _bind_mousewheel(self, widget):
        """让鼠标滚轮可以滚动主界面，兼容 Windows / Linux。"""
        widget.bind_all("<MouseWheel>", self._on_mousewheel)
        widget.bind_all("<Button-4>", self._on_mousewheel)
        widget.bind_all("<Button-5>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        if not hasattr(self, "main_canvas"):
            return

        if getattr(event, "num", None) == 4:
            self.main_canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", None) == 5:
            self.main_canvas.yview_scroll(1, "units")
        else:
            delta = int(-1 * (event.delta / 120))
            self.main_canvas.yview_scroll(delta, "units")

    def _setup_ui(self):
        # 主界面使用 Canvas + 垂直滚动条，适配高度不足的屏幕。
        container = ttk.Frame(self.root, style="App.TFrame")
        container.pack(fill="both", expand=True)

        self.main_canvas = tk.Canvas(
            container,
            bg=self.colors["bg"],
            highlightthickness=0,
            bd=0,
        )
        self.main_scrollbar = ttk.Scrollbar(
            container,
            orient="vertical",
            command=self.main_canvas.yview,
        )
        self.main_canvas.configure(yscrollcommand=self.main_scrollbar.set)

        self.main_scrollbar.pack(side="right", fill="y")
        self.main_canvas.pack(side="left", fill="both", expand=True)

        main = ttk.Frame(self.main_canvas, padding=18, style="App.TFrame")
        self.main_window = self.main_canvas.create_window((0, 0), window=main, anchor="nw")

        def _update_scrollregion(event=None):
            self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))

        def _resize_inner_width(event):
            self.main_canvas.itemconfigure(self.main_window, width=event.width)

        main.bind("<Configure>", _update_scrollregion)
        self.main_canvas.bind("<Configure>", _resize_inner_width)
        self._bind_mousewheel(self.main_canvas)

        # 顶部深色标题区，强化产品感和层级感
        hero = tk.Frame(main, bg=self.colors["hero"], bd=0, highlightthickness=0)
        hero.pack(fill="x", pady=(0, 16))

        hero_inner = tk.Frame(hero, bg=self.colors["hero"])
        hero_inner.pack(fill="x", padx=20, pady=14)

        title_row = tk.Frame(hero_inner, bg=self.colors["hero"])
        title_row.pack(fill="x")

        tk.Label(
            title_row,
            text="M2507双核串口固件升级工具",
            bg=self.colors["hero"],
            fg=self.colors["white"],
            font=("Microsoft YaHei UI", 20, "bold"),
        ).pack(side="left", anchor="w")

        tk.Label(
            title_row,
            text="DUAL CORE OTA",
            bg=self.colors["primary"],
            fg=self.colors["white"],
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=4,
        ).pack(side="right", anchor="e")

        tk.Label(
            hero_inner,
            text="支持 Core0 / Core1 分区升级，协议：EB 90 + core_id + length[4] + crc32[4]",
            bg=self.colors["hero"],
            fg="#BFDBFE",
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(8, 0))

        body = ttk.Frame(main, style="App.TFrame")
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=False, padx=(0, 12))

        right = ttk.Frame(body)
        right.pack(side="right", fill="both", expand=True)

        self._build_serial_card(left)
        self._build_file_card(left)
        self._build_target_card(left)
        self._build_action_card(left)
        self._build_log_card(right)

        status_bar = ttk.Frame(main, style="App.TFrame")
        status_bar.pack(fill="x", pady=(12, 0))
        ttk.Label(status_bar, textvariable=self.status_var, style="Status.TLabel").pack(side="left")
        self.progress_label = ttk.Label(status_bar, text="0%", style="Status.TLabel")
        self.progress_label.pack(side="right")

    def _make_card(self, parent, title):
        # 用浅蓝边框 + 微阴影模拟卡片层级，避免整窗偏灰
        shadow = tk.Frame(parent, bg=self.colors["shadow"], bd=0)
        shadow.pack(fill="x", pady=(0, 10))

        outer = tk.Frame(
            shadow,
            bg=self.colors["card"],
            bd=0,
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            highlightcolor=self.colors["border"],
        )
        outer.pack(fill="both", expand=True, padx=(0, 2), pady=(0, 2))

        inner = ttk.Frame(outer, style="Card.TFrame", padding=12)
        inner.pack(fill="both", expand=True)

        title_row = tk.Frame(inner, bg=self.colors["card"])
        title_row.pack(fill="x", pady=(0, 11))

        tk.Frame(title_row, bg=self.colors["primary"], width=4, height=22).pack(side="left", padx=(0, 8))
        tk.Label(
            title_row,
            text=title,
            bg=self.colors["card"],
            fg=self.colors["text"],
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(side="left", anchor="w")

        return inner

    def _build_serial_card(self, parent):
        card = self._make_card(parent, "1. 串口设置")

        row1 = ttk.Frame(card, style="Card.TFrame")
        row1.pack(fill="x", pady=(0, 8))

        ttk.Label(row1, text="端口", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.cb_ports = ttk.Combobox(row1, textvariable=self.port_var, width=16, state="readonly")
        self.cb_ports.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(4, 0))

        ttk.Label(row1, text="波特率", style="Card.TLabel").grid(row=0, column=1, sticky="w")
        self.cb_baud = ttk.Combobox(
            row1,
            textvariable=self.baud_var,
            values=["9600", "57600", "115200", "256000", "460800", "921600"],
            width=12,
            state="readonly",
        )
        self.cb_baud.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(4, 0))

        ttk.Button(row1, text="刷新", command=self.refresh_ports).grid(row=1, column=2, padx=(0, 8), pady=(4, 0))
        self.btn_open = ttk.Button(row1, text="打开串口", command=self.toggle_serial)
        self.btn_open.grid(row=1, column=3, pady=(4, 0))

        row1.columnconfigure(0, weight=1)
        row1.columnconfigure(1, weight=1)

        row2 = ttk.Frame(card, style="Card.TFrame")
        row2.pack(fill="x")

        ttk.Label(row2, text="发送分包大小", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.cb_chunk = ttk.Combobox(
            row2,
            textvariable=self.chunk_size_var,
            values=["128", "256", "512", "1024"],
            width=8,
            state="readonly",
        )
        self.cb_chunk.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(row2, text="建议保持 512，与下位机 read 逻辑一致", style="Muted.TLabel").grid(row=0, column=2, sticky="w", padx=(10, 0))

    def _build_file_card(self, parent):
        card = self._make_card(parent, "2. 固件文件")

        self.lbl_path = ttk.Label(card, textvariable=self.path_var, style="Muted.TLabel", wraplength=320)
        self.lbl_path.pack(anchor="w", fill="x", pady=(0, 8))

        self.lbl_fileinfo = ttk.Label(card, textvariable=self.file_info_var, style="Card.TLabel", wraplength=320)
        self.lbl_fileinfo.pack(anchor="w", fill="x", pady=(0, 10))

        self.btn_select_file = ttk.Button(card, text="选择 Bin 文件", command=self.select_file)
        self.btn_select_file.pack(anchor="w")

    def _build_target_card(self, parent):
        card = self._make_card(parent, "3. 选择升级目标")

        self.rb_core0 = ttk.Radiobutton(
            card,
            text="Core0：写入 SYS_USERAPP_PARTITION_START",
            variable=self.target_core_var,
            value=TARGET_CORE0,
            command=self._on_target_changed,
        )
        self.rb_core0.pack(anchor="w", pady=(0, 8))

        self.rb_core1 = ttk.Radiobutton(
            card,
            text="Core1：写入 CPU1_FLASH_START",
            variable=self.target_core_var,
            value=TARGET_CORE1,
            command=self._on_target_changed,
        )
        self.rb_core1.pack(anchor="w")

    def _build_action_card(self, parent):
        card = self._make_card(parent, "4. 升级控制")

        self.progress = ttk.Progressbar(card, orient="horizontal", mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(0, 12))

        btn_row = ttk.Frame(card, style="Card.TFrame")
        btn_row.pack(fill="x")

        self.btn_start = ttk.Button(
            btn_row,
            text="等待设备上电并开始升级",
            command=self.start_upgrade,
            state="disabled",
            style="Primary.TButton",
        )
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_stop = ttk.Button(
            btn_row,
            text="停止",
            command=self.stop_upgrade,
            state="disabled",
            style="Danger.TButton",
        )
        self.btn_stop.pack(side="right")

    def _build_log_card(self, parent):
        outer = tk.Frame(parent, bg=self.colors["shadow"], bd=0)
        outer.pack(fill="both", expand=True)
        shell = tk.Frame(
            outer,
            bg=self.colors["card"],
            bd=0,
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            highlightcolor=self.colors["border"],
        )
        shell.pack(fill="both", expand=True, padx=(0, 2), pady=(0, 2))
        inner = ttk.Frame(shell, style="Card.TFrame", padding=15)
        inner.pack(fill="both", expand=True)

        top = ttk.Frame(inner, style="Card.TFrame")
        top.pack(fill="x", pady=(0, 10))

        ttk.Label(top, text="通信日志", style="Section.TLabel").pack(side="left")
        ttk.Button(top, text="清空日志", command=self.clear_log).pack(side="right")

        self.txt_log = scrolledtext.ScrolledText(
            inner,
            state="disabled",
            bg=self.colors["log_bg"],
            fg=self.colors["log_fg"],
            insertbackground=self.colors["log_fg"],
            font=("Consolas", 10),
            relief="flat",
            height=14,
        )
        self.txt_log.pack(fill="both", expand=True)

        self.txt_log.tag_config("info", foreground="#D8EAFE")
        self.txt_log.tag_config("ok", foreground="#6EE7B7")
        self.txt_log.tag_config("warn", foreground="#FBBF24")
        self.txt_log.tag_config("err", foreground="#FCA5A5")
        self.txt_log.tag_config("tx", foreground="#60A5FA")
        self.txt_log.tag_config("rx", foreground="#C084FC")

    # =========================
    # UI helpers
    # =========================

    def post_log(self, msg, level="info"):
        self.ui_queue.put(("log", msg, level))

    def post_progress(self, value):
        self.ui_queue.put(("progress", value))

    def post_status(self, msg):
        self.ui_queue.put(("status", msg))

    def _process_ui_queue(self):
        if self._closing:
            return
        try:
            while True:
                item = self.ui_queue.get_nowait()
                kind = item[0]

                if kind == "log":
                    _, msg, level = item
                    self._append_log(msg, level)
                elif kind == "progress":
                    _, value = item
                    self.progress["value"] = value
                    self.progress_label.config(text=f"{value:.1f}%")
                elif kind == "status":
                    _, msg = item
                    self.status_var.set(msg)
                elif kind == "finished":
                    self.is_upgrading = False
                    self.check_ready_state()
                elif kind == "dialog":
                    _, success, msg = item
                    if success:
                        messagebox.showinfo("升级成功", msg, parent=self.root)
                    else:
                        messagebox.showerror("升级失败", msg, parent=self.root)
        except queue.Empty:
            pass

        self.root.after(50, self._process_ui_queue)

    def _append_log(self, msg, level="info"):
        self.txt_log.config(state="normal")
        timestamp = time.strftime("[%H:%M:%S] ")
        self.txt_log.insert("end", timestamp + msg + "\n", level)
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")

    def clear_log(self):
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.config(state="disabled")

    def _on_target_changed(self):
        target = self.target_core_var.get()
        self.post_log(f"升级目标已选择：{TARGET_NAMES.get(target, '未知目标')}", "info")

    def refresh_ports(self):
        ports = list(serial.tools.list_ports.comports())
        values = [p.device for p in ports]
        self.cb_ports["values"] = values

        if values and not self.port_var.get():
            self.port_var.set(values[0])

        if values:
            self.post_status(f"发现 {len(values)} 个串口")
        else:
            self.post_status("未发现串口")

    def check_ready_state(self):
        ready = (
            self.serial is not None
            and self.serial.is_open
            and self.file_size > 0
            and not self.is_upgrading
        )

        self.btn_start.config(state="normal" if ready else "disabled")
        self.btn_stop.config(
            state="normal" if self.is_upgrading and not self.stop_event.is_set() else "disabled"
        )
        # 防止升级期间修改固件、目标核或串口，保证信息帧与数据来自同一任务。
        state = "disabled" if self.is_upgrading else "normal"
        for widget in (self.btn_open, self.btn_select_file, self.rb_core0, self.rb_core1):
            widget.config(state=state)

    # =========================
    # Serial / file
    # =========================

    def toggle_serial(self):
        if self.serial is not None and self.serial.is_open:
            if self.is_upgrading:
                messagebox.showwarning("正在升级", "升级过程中不能关闭串口。")
                return

            try:
                self.serial.close()
            except Exception:
                pass

            self.btn_open.config(text="打开串口")
            self.cb_ports.config(state="readonly")
            self.cb_baud.config(state="readonly")
            self.cb_chunk.config(state="readonly")
            self.post_log("串口已关闭", "warn")
            self.post_status("串口已关闭")
            self.check_ready_state()
            return

        port = self.port_var.get().strip()
        if not port:
            messagebox.showerror("串口错误", "请选择串口。")
            return

        try:
            baud = int(self.baud_var.get())
            self.serial = serial.Serial(
                port=port,
                baudrate=baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.05,
                write_timeout=2.0,
            )
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()

            self.btn_open.config(text="关闭串口")
            self.cb_ports.config(state="disabled")
            self.cb_baud.config(state="disabled")
            self.cb_chunk.config(state="disabled")

            self.post_log(f"串口已打开：{port} @ {baud} bps", "ok")
            self.post_status(f"已连接：{port} @ {baud}")
            self.check_ready_state()

        except Exception as exc:
            messagebox.showerror("串口错误", f"无法打开串口：\n{exc}")
            self.post_log(f"打开串口失败：{exc}", "err")
            self.post_status("串口打开失败")

    def select_file(self):
        if self.is_upgrading:
            messagebox.showwarning("正在升级", "请等待升级结束后再选择固件。")
            return
        path = filedialog.askopenfilename(
            title="选择升级固件",
            filetypes=[("Bin Files", "*.bin"), ("All Files", "*.*")],
        )

        if not path:
            return

        try:
            with open(path, "rb") as f:
                data = f.read()

            if len(data) == 0:
                messagebox.showerror("文件错误", "选择的文件为空。")
                return

            if len(data) > MAX_FIRMWARE_SIZE:
                messagebox.showerror(
                    "文件过大",
                    f"固件大小超过限制：{len(data)} Bytes > {MAX_FIRMWARE_SIZE} Bytes",
                )
                return

            self.file_path = path
            self.bin_data = data
            self.file_size = len(data)
            self.file_crc = zlib.crc32(data) & 0xFFFFFFFF

            self.path_var.set(path)
            self.file_info_var.set(
                f"文件：{os.path.basename(path)}\n"
                f"大小：{self.file_size} Bytes / 0x{self.file_size:08X}\n"
                f"CRC32：0x{self.file_crc:08X}"
            )

            self.post_log(f"加载固件成功：{os.path.basename(path)}", "ok")
            self.post_log(f"固件大小：{self.file_size} Bytes，CRC32：0x{self.file_crc:08X}", "info")
            self.check_ready_state()

        except Exception as exc:
            messagebox.showerror("文件错误", f"读取固件失败：\n{exc}")
            self.post_log(f"读取固件失败：{exc}", "err")

    # =========================
    # 升级流程
    # =========================

    def start_upgrade(self):
        if self.is_upgrading:
            return

        if self.serial is None or not self.serial.is_open:
            messagebox.showerror("条件不足", "请先打开串口。")
            return

        if self.file_size <= 0:
            messagebox.showerror("条件不足", "请先选择固件文件。")
            return

        target_core = self.target_core_var.get()
        if target_core not in (TARGET_CORE0, TARGET_CORE1):
            messagebox.showerror("条件不足", "请选择有效的升级目标核。")
            return

        # Tkinter 变量只在主线程读取，工作线程使用这次任务的固定参数。
        try:
            chunk_size = int(self.chunk_size_var.get())
            if chunk_size <= 0:
                raise ValueError("分包大小必须为正整数")
        except ValueError:
            messagebox.showerror("参数错误", "发送分包大小必须为正整数。")
            return

        self.active_target_core = target_core
        self.active_chunk_size = chunk_size
        self.stop_event.clear()
        self.is_upgrading = True
        self.check_ready_state()
        self.post_progress(0)
        self.post_status("等待设备上电提示帧")

        self.post_log("=" * 58, "warn")
        self.post_log("升级任务开始", "warn")
        self.post_log(f"升级目标：{TARGET_NAMES[target_core]}", "info")
        self.post_log(f"固件文件：{os.path.basename(self.file_path)}", "info")
        self.post_log(f"Length=0x{self.file_size:08X}, CRC32=0x{self.file_crc:08X}", "info")

        self.worker = threading.Thread(target=self.upgrade_task, daemon=True)
        self.worker.start()

    def stop_upgrade(self):
        if self.is_upgrading and not self.stop_event.is_set():
            # 停止请求与任务状态分开：线程退出前不能再次启动另一个升级线程。
            self.stop_event.set()
            self.btn_stop.config(state="disabled")
            self.post_log("用户请求停止升级，等待当前串口操作结束。", "warn")
            self.post_status("正在停止")

    def wait_for_response(self, expected_cmd: bytes, timeout_sec: float, desc: str):
        deadline = time.monotonic() + timeout_sec

        error_map = {
            CMD_ACK_INFO_ERR: "下位机返回：升级程序信息接收异常",
            CMD_ACK_CRC_ERR: "下位机返回：接收程序 CRC 校验异常",
            CMD_ACK_FLASH_ERR: "下位机返回：升级程序写 Flash 或回读校验异常",
            CMD_ACK_CORE_ERR: "下位机返回：目标核选择异常",
        }

        known_commands = (CMD_PROMPT_POWERON, CMD_ACK_INFO_OK, CMD_ACK_CRC_OK, CMD_ACK_FLASH_OK)

        while time.monotonic() < deadline:
            if self.stop_event.is_set():
                raise Exception("升级已被用户停止")

            # 按帧依次消费，保留尚未处理的帧。CRC/Flash ACK 同一次到达时不能丢掉后者。
            while len(self._rx_buffer) >= len(FRAME_HEADER):
                start = self._rx_buffer.find(FRAME_HEADER)
                if start < 0:
                    self._rx_buffer = self._rx_buffer[-1:] if self._rx_buffer.endswith(b"\xEB") else b""
                    break
                self._rx_buffer = self._rx_buffer[start:]
                if len(self._rx_buffer) < 6:
                    break
                cmd = self._rx_buffer[:6]
                if cmd not in known_commands and cmd not in error_map:
                    self._rx_buffer = self._rx_buffer[1:]
                    continue
                self._rx_buffer = self._rx_buffer[6:]
                if cmd in error_map:
                    raise Exception(error_map[cmd])
                if cmd == expected_cmd:
                    return True

            waiting = self.serial.in_waiting
            if waiting > 0:
                data = self.serial.read(min(waiting, 4096))
                self._rx_buffer += data
                self.post_log(f"RX: {data.hex(' ').upper()}", "rx")
            else:
                self.stop_event.wait(0.01)

        raise Exception(f"等待响应超时：{desc}，timeout={timeout_sec}s")

    def make_info_frame(self) -> bytes:
        target_core = self.active_target_core

        # 新流程信息帧：
        # EB 90 + core_id + length[4, little endian] + crc32[4, little endian]
        return (
            FRAME_HEADER
            + struct.pack("<B", target_core)
            + struct.pack("<I", self.file_size)
            + struct.pack("<I", self.file_crc)
        )

    def _write_serial(self, data):
        written = self.serial.write(data)
        if written != len(data):
            raise serial.SerialTimeoutException(
                f"串口发送不完整：{written}/{len(data)} Bytes，请检查连接后重新升级。"
            )
        self.serial.flush()

    def upgrade_task(self):
        try:
            self._rx_buffer = b""
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()

            self.post_log("等待嵌入式设备上电提示帧，请给设备重新上电或复位。", "info")
            self.wait_for_response(CMD_PROMPT_POWERON, timeout_sec=60, desc="设备上电提示帧")
            self.post_log("收到设备上电提示帧。", "ok")
            self.post_status("发送升级信息帧")

            info_frame = self.make_info_frame()
            self._write_serial(info_frame)

            self.post_log(f"TX 信息帧: {info_frame.hex(' ').upper()}", "tx")
            self.post_log(
                f"信息帧解析：core_id=0x{self.active_target_core:02X}, "
                f"length=0x{self.file_size:08X}, crc32=0x{self.file_crc:08X}",
                "info",
            )

            self.wait_for_response(CMD_ACK_INFO_OK, timeout_sec=5, desc="信息帧确认")
            self.post_log("设备确认升级信息帧成功。", "ok")

            chunk_size = self.active_chunk_size

            self.post_status("正在发送固件数据")
            self.post_log(f"开始发送 Bin 数据，分包大小：{chunk_size} Bytes", "info")

            total_sent = 0
            last_log_percent = -1

            for pos in range(0, self.file_size, chunk_size):
                if self.stop_event.is_set():
                    raise Exception("升级已被用户停止")

                chunk = self.bin_data[pos:pos + chunk_size]
                self._write_serial(chunk)

                total_sent += len(chunk)
                percent = (total_sent * 100.0) / self.file_size
                self.post_progress(percent)

                int_percent = int(percent)
                if int_percent // 10 != last_log_percent // 10:
                    last_log_percent = int_percent
                    self.post_log(f"发送进度：{int_percent}% ({total_sent}/{self.file_size})", "info")

                # 下位机 read 后有 Sys_DelayMs(30)，这里保留节流，防止串口 FIFO 或驱动缓存溢出。
                self.stop_event.wait(0.01)

            self.post_progress(100)
            self.post_log("Bin 数据发送完毕，等待设备 CRC 校验。", "ok")
            self.post_status("等待 CRC 校验")

            self.wait_for_response(CMD_ACK_CRC_OK, timeout_sec=20, desc="CRC 校验结果")
            self.post_log("设备 CRC 校验通过，等待写入 QSPI Flash 并回读校验。", "ok")
            self.post_status("等待 Flash 写入和回读校验")

            self.wait_for_response(CMD_ACK_FLASH_OK, timeout_sec=120, desc="Flash 写入和回读校验结果")
            self.post_log("升级成功：Flash 写入与回读校验通过。", "ok")
            self.post_log("=" * 58, "warn")
            self.post_status("升级成功")
            self.ui_queue.put(("dialog", True, "固件升级并校验成功。"))

        except Exception as exc:
            self.post_log(f"升级失败：{exc}", "err")
            self.post_status("升级失败")
            self.ui_queue.put(("dialog", False, str(exc)))

        finally:
            self.ui_queue.put(("finished",))

    def on_close(self):
        if self.is_upgrading:
            if not messagebox.askyesno("确认退出", "当前正在升级，强制退出可能导致升级中断。\n确定要退出吗？"):
                return
            self.stop_event.set()

        self._closing = True

        try:
            if self.serial is not None and self.serial.is_open:
                self.serial.close()
        except Exception:
            pass

        self.root.destroy()


def main():
    # --windowed 发布版没有控制台，将 Python 启动/回调异常记录到可写目录。
    # 此日志只能记录 Python 启动后的错误；DLL 加载失败必须修复打包环境。
    log_dir = os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(), "M2507OTA")
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "error.log")
        handler = RotatingFileHandler(log_path, maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
    except OSError:
        log_path = os.path.join(tempfile.gettempdir(), "M2507OTA-error.log")
        handler = logging.FileHandler(log_path, encoding="utf-8")
    logger = logging.getLogger("M2507OTA")
    logger.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.info("启动 Python %s (%s)", sys.version.split()[0], sys.platform)

    root = None
    try:
        root = tk.Tk()

        def report_callback_exception(exc_type, exc_value, exc_tb):
            logger.error("界面回调异常", exc_info=(exc_type, exc_value, exc_tb))
            messagebox.showerror("程序异常", f"{exc_value}\n\n详细日志：{log_path}", parent=root)

        root.report_callback_exception = report_callback_exception
        app = DualCoreOtaUpgraderApp(root)
        root.mainloop()
    except Exception as exc:
        logger.exception("程序启动或运行失败")
        try:
            messagebox.showerror("启动失败", f"{exc}\n\n详细日志：{log_path}", parent=root)
        except tk.TclError:
            pass
        if root is not None:
            try:
                root.destroy()
            except tk.TclError:
                pass
        return 1
    finally:
        handler.close()
        logger.removeHandler(handler)
    return 0


if __name__ == "__main__":
    sys.exit(main())
