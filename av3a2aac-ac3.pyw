# -*- coding: utf-8 -*-
"""
AV3A转码工具 (Windows GUI, 现代深色 UI)

导入 TS 录像，自动探测其中的 AV3A (AVS3-P3 / Audio Vivid) 音轨并转码：
  - AC3 / EAC3 / AAC / PCM(无损)
视频、字幕、其他非 AV3A 音轨直接流复制，不重新编码。

依赖: Python 3 (tkinter)，ttkbootstrap，修改版 ffmpeg / ffprobe(已内置打包)。
运行: 双击本文件 (pyw) 或 `python av3a2aac-ac3.pyw`
"""

import json
import os
import re
import subprocess
import sys
import threading
import queue
import tkinter as tk
from tkinter import filedialog, messagebox

import ttkbootstrap as ttkb
from ttkbootstrap.constants import *

# ttkbootstrap 2.x 在顶层导出全部 widget（Frame/Label/Treeview...）
ttk = ttkb

DEFAULT_FFMPEG_DIR = r"C:\Users\13568\Downloads\ffmpeg-av3a"

AV3A_RE = re.compile(r"av3a", re.IGNORECASE)


def bundled_ffmpeg_dir():
    """PyInstaller 打包时内置的 ffmpeg 目录；未打包则返回 None"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, "ffmpeg")
    return d if os.path.isfile(os.path.join(d, "ffmpeg.exe")) else None


def find_exe(directory, name):
    for d in (directory, os.path.join(directory, "bin")):
        path = os.path.join(d, name + ".exe")
        if os.path.isfile(path):
            return path
    return None


class ConverterApp:
    def __init__(self, root):
        self.root = root
        self.task_queue = queue.Queue()
        self.worker = None
        self.cancel_flag = threading.Event()
        self.results = {}          # input path -> status string
        self.tree_items = {}       # input path -> treeview item id
        self.file_info = {}        # input path -> probe result dict
        self._ffmpeg_path = None
        self.ffmpeg_dir = bundled_ffmpeg_dir() or DEFAULT_FFMPEG_DIR

        self._build_ui()
        self.root.after(100, self._poll_queue)

    # ---------------- UI ----------------
    def _build_ui(self):
        self.root.title("AV3A转码工具")
        self.root.geometry("960x850")
        self.root.minsize(880, 780)

        # 变量
        self.outdir_var = tk.StringVar(value="")  # 空 = 与源文件相同
        self.codec_var = tk.StringVar(value="ac3")
        self.ac3_br_var = tk.StringVar(value="640")
        self.eac3_br_var = tk.StringVar(value="768")
        self.aac_br_var = tk.StringVar(value="192")
        self.ac3_br_choices = ["128", "192", "224", "256", "320", "384", "448", "512", "576", "640"]
        self.eac3_br_choices = ["192", "256", "320", "384", "448", "512", "640", "768", "960", "1024"]
        self.aac_br_choices = ["64", "96", "128", "160", "192", "224", "256", "320", "384", "448", "512"]
        self.delete_src_var = tk.BooleanVar(value=False)

        main = ttk.Frame(self.root, padding=(16, 12))
        main.pack(fill="both", expand=True)

        # ---- 底部按钮（先占住底部，避免被内容挤出窗口）----
        btns = ttk.Frame(main)
        btns.pack(side="bottom", fill="x", pady=(10, 0))
        self.start_btn = ttk.Button(btns, text="▶ 开始转换", bootstyle="success",
                                    command=self._start)
        self.start_btn.pack(side="left", ipadx=14, padx=(0, 8))
        self.cancel_btn = ttk.Button(btns, text="■ 停止", bootstyle="danger-outline",
                                     command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", ipadx=10)

        # ---- 头部标题 ----
        head = ttk.Frame(main)
        head.pack(fill="x", pady=(0, 10))
        ttk.Label(head, text="AV3A转码工具",
                  font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
        ttk.Label(head, text="Audio Vivid → AC3 / EAC3 / AAC / PCM",
                  bootstyle="secondary", font=("Microsoft YaHei UI", 10)).pack(side="left", padx=10)

        # ---- 文件操作卡片 ----
        card1 = ttk.Labelframe(main, text=" ① 添加文件 ", bootstyle="primary", padding=10)
        card1.pack(fill="x", pady=(0, 8))
        btnrow = ttk.Frame(card1)
        btnrow.pack(fill="x")
        ttk.Button(btnrow, text="⊕ 添加 TS 文件", bootstyle="primary",
                   command=self._add_files).pack(side="left", padx=(0, 8))
        ttk.Button(btnrow, text="📂 添加文件夹", bootstyle="primary-outline",
                   command=self._add_folder).pack(side="left", padx=(0, 8))
        ttk.Button(btnrow, text="✖ 移除选中", bootstyle="secondary-outline",
                   command=self._remove_selected).pack(side="left", padx=(0, 8))
        ttk.Button(btnrow, text="清空列表", bootstyle="secondary-outline",
                   command=self._clear_list).pack(side="left")

        # 输出目录
        orow = ttk.Frame(card1)
        orow.pack(fill="x", pady=(10, 0))
        ttk.Label(orow, text="输出目录:", bootstyle="secondary").pack(side="left")
        self.outdir_entry = ttk.Entry(orow, textvariable=self.outdir_var)
        self.outdir_entry.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(orow, text="浏览", bootstyle="secondary-outline",
                   command=self._browse_outdir).pack(side="left")
        ttk.Label(card1, text="留空则输出到源文件目录",
                  bootstyle="secondary", font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(3, 0))

        # ---- 参数卡片 ----
        card2 = ttk.Labelframe(main, text=" ② 转码设置 ", bootstyle="info", padding=10)
        card2.pack(fill="x", pady=(0, 8))

        grow = ttk.Frame(card2)
        grow.pack(fill="x")
        ttk.Label(grow, text="转码格式:").pack(side="left")
        self.codec_box = ttk.Combobox(grow, textvariable=self.codec_var,
                                      values=["ac3", "eac3", "aac", "pcm"],
                                      width=8, state="readonly")
        self.codec_box.pack(side="left", padx=(6, 16))
        ttk.Label(grow, text="AC3码率:").pack(side="left")
        ttk.Combobox(grow, textvariable=self.ac3_br_var, values=self.ac3_br_choices,
                     width=5, state="readonly").pack(side="left", padx=(4, 12))
        ttk.Label(grow, text="EAC3码率:").pack(side="left")
        ttk.Combobox(grow, textvariable=self.eac3_br_var, values=self.eac3_br_choices,
                     width=5, state="readonly").pack(side="left", padx=(4, 12))
        ttk.Label(grow, text="AAC码率:").pack(side="left")
        ttk.Combobox(grow, textvariable=self.aac_br_var, values=self.aac_br_choices,
                     width=5, state="readonly").pack(side="left", padx=(4, 12))
        self.del_check = ttk.Checkbutton(grow, text="完成后删除源文件",
                                         variable=self.delete_src_var, bootstyle="danger-round-toggle")
        self.del_check.pack(side="right")

        # ---- 文件列表卡片 ----
        card3 = ttk.Labelframe(main, text=" ③ 文件列表 ", bootstyle="success", padding=(10, 6))
        card3.pack(fill="both", expand=True, pady=(0, 8))
        columns = ("file", "video", "audio", "status")
        self.tree = ttk.Treeview(card3, columns=columns, show="headings",
                                 height=6, bootstyle="primary")
        self.tree.heading("file", text="文件")
        self.tree.heading("video", text="视频")
        self.tree.heading("audio", text="音频 (AV3A)")
        self.tree.heading("status", text="状态")
        self.tree.column("file", width=380)
        self.tree.column("video", width=150, anchor="center")
        self.tree.column("audio", width=210, anchor="center")
        self.tree.column("status", width=110, anchor="center")
        vsb = ttk.Scrollbar(card3, orient="vertical", command=self.tree.yview, bootstyle="round-primary")
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        # ---- 进度 ----
        prow = ttk.Frame(main)
        prow.pack(fill="x", pady=(0, 8))
        self.progress = ttk.Progressbar(prow, mode="determinate", maximum=100,
                                        bootstyle="success-striped")
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress_label = ttk.Label(prow, text="就绪", width=32, anchor="e",
                                        bootstyle="secondary")
        self.progress_label.pack(side="left", padx=(10, 0))

        # ---- 日志卡片 ----
        card4 = ttk.Labelframe(main, text=" ④ 日志 ", bootstyle="secondary", padding=(10, 6))
        card4.pack(fill="x", pady=(0, 8))
        self.log_text = tk.Text(card4, height=7, state="disabled", wrap="none",
                                bg="#1e2229", fg="#d8dee9", insertbackground="#d8dee9",
                                relief="flat", font=("Consolas", 9))
        lsb = ttk.Scrollbar(card4, orient="vertical", command=self.log_text.yview,
                            bootstyle="round-secondary")
        self.log_text.configure(yscrollcommand=lsb.set)
        lsb.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

    # ---------------- UI 回调 ----------------
    def _ui(self, fn):
        """线程安全的 UI 调用：放入队列，由主循环执行"""
        self.task_queue.put(fn)

    def log(self, msg):
        self._ui(lambda: self._append_log(msg))

    def _append_log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def set_status(self, path, status):
        self._ui(lambda: self._set_status_main(path, status))

    def _set_status_main(self, path, status):
        item = self.tree_items.get(path)
        if item:
            self.tree.set(item, "status", status)

    def _browse_outdir(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.outdir_var.set(d)

    def _add_files(self):
        files = filedialog.askopenfilenames(
            title="选择 TS 录像",
            filetypes=[("MPEG-TS 文件", "*.ts *.m2ts *.mts *.trp"), ("所有文件", "*.*")])
        for f in files:
            self._add_file(f)

    def _add_folder(self):
        d = filedialog.askdirectory(title="选择包含 TS 的文件夹")
        if not d:
            return
        for name in sorted(os.listdir(d)):
            if name.lower().endswith((".ts", ".m2ts", ".mts", ".trp")):
                self._add_file(os.path.join(d, name))

    def _add_file(self, path):
        path = os.path.abspath(path)
        if path in self.tree_items:
            return
        item = self.tree.insert("", "end", values=(path, "…", "…", "探测中"))
        self.tree_items[path] = item
        self.results[path] = "等待中"
        threading.Thread(target=self._probe_and_fill,
                         args=(path,), daemon=True).start()

    def _probe_and_fill(self, path):
        try:
            ffmpeg = find_exe(self.ffmpeg_dir, "ffmpeg")
            if not ffmpeg:
                self.log(f"!! 探测失败: 找不到 ffmpeg.exe ({self.ffmpeg_dir})")
                self._set_row(path, ("?", "?", "探测失败"))
                return
            self._ffmpeg_path = ffmpeg
            ffprobe = find_exe(self.ffmpeg_dir, "ffprobe")
            info = self.probe(ffprobe, path)
            self.file_info[path] = info
            v = info.get("video") or {}
            video_txt = f"{v.get('codec','?')} {v.get('bit_rate') or '?'}"
            av3a = [s for s in info["audios"] if AV3A_RE.search(s.get("codec_name", ""))]
            if av3a:
                audio_txt = "; ".join(
                    f"AV3A {s.get('channels','?')}ch {s.get('bit_rate') or '?'}"
                    for s in av3a)
            elif info["audios"]:
                audio_txt = "无AV3A: " + "; ".join(
                    f"{s.get('codec_name')} {s.get('bit_rate') or '?'}"
                    for s in info["audios"])
            else:
                audio_txt = "无音轨"
            self._set_row(path, (video_txt, audio_txt, "等待中"))
            self.log(f"探测: {os.path.basename(path)}  视频 {video_txt} | 音频 {audio_txt}")
        except Exception as e:
            self._set_row(path, ("?", "?", "探测失败"))
            self.log(f"!! 探测失败: {os.path.basename(path)}: {e}")

    def _set_row(self, path, values):
        self._ui(lambda: self._set_row_main(path, values))

    def _set_row_main(self, path, values):
        item = self.tree_items.get(path)
        if item:
            self.tree.item(item, values=(path,) + tuple(values))

    def _remove_selected(self):
        for item in self.tree.selection():
            for p, i in list(self.tree_items.items()):
                if i == item:
                    del self.tree_items[p]
                    self.results.pop(p, None)
            self.tree.delete(item)

    def _clear_list(self):
        self.tree.delete(*self.tree.get_children())
        self.tree_items.clear()
        self.results.clear()
        self.file_info.clear()

    def _start(self):
        ffmpeg = find_exe(self.ffmpeg_dir, "ffmpeg")
        ffprobe = find_exe(self.ffmpeg_dir, "ffprobe")
        if not ffmpeg:
            messagebox.showerror("错误", f"找不到 ffmpeg.exe:\n{self.ffmpeg_dir}")
            return
        self._ffmpeg_path = ffmpeg
        files = [p for p, s in self.results.items() if s not in ("完成",)]
        if not files:
            messagebox.showinfo("提示", "请先添加待转换的 TS 文件。")
            return
        self.cancel_flag.clear()
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.worker = threading.Thread(
            target=self._worker,
            args=(files, ffmpeg, ffprobe),
            daemon=True)
        self.worker.start()

    def _cancel(self):
        self.cancel_flag.set()
        self.log(">>> 已请求停止，等待当前任务结束...")

    # ---------------- 核心逻辑 ----------------
    def probe(self, ffprobe, path):
        """返回 {'audios':[...], 'dur':秒或None, 'video':{'codec','bit_rate'}}
        有 ffprobe 用 JSON 输出；否则解析 ffmpeg -i 的 stderr。"""
        if ffprobe:
            cmd = [ffprobe, "-v", "error", "-print_format", "json",
                   "-show_streams", "-show_format", path]
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=120)
            if out.returncode != 0:
                raise RuntimeError("ffprobe 失败:\n" + out.stderr.strip())
            data = json.loads(out.stdout)
            streams = data.get("streams", [])
            audios = [s for s in streams if s.get("codec_type") == "audio"]
            for s in audios:
                br = s.get("bit_rate")
                if br:
                    try:
                        s["bit_rate"] = f"{int(br) // 1000} kb/s"
                    except ValueError:
                        s["bit_rate"] = br
            videos = [s for s in streams if s.get("codec_type") == "video"]
            video = {}
            if videos:
                v = videos[0]
                vbr = v.get("bit_rate")
                if vbr:
                    try:
                        vbr = f"{int(vbr) // 1000} kb/s"
                    except ValueError:
                        pass
                video = {"codec": v.get("codec_name", "?"), "bit_rate": vbr}
            dur = None
            try:
                dur = float(data.get("format", {}).get("duration"))
            except (TypeError, ValueError):
                pass
            return {"audios": audios, "dur": dur, "video": video}
        return self.probe_with_ffmpeg(path)

    def probe_with_ffmpeg(self, path):
        cmd = [self._ffmpeg_path, "-hide_banner", "-i", path]
        out = subprocess.run(cmd, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=120)
        text = out.stderr
        if "At least one output file must be specified" not in text and \
           "Stream #" not in text and out.returncode not in (0, 1):
            raise RuntimeError("ffmpeg 探测失败:\n" + text.strip())
        audios = []
        for m in re.finditer(r"^\s*Stream #0:(\d+)(?:\[[^\]]*\])?(?:\([^)]*\))?:\s*Audio: (\w+)"
                             r".*?,\s*(\d+) Hz,\s*([^,\n]+),[^\n]*", text, re.MULTILINE):
            idx = int(m.group(1))
            cname = m.group(2).strip()
            ch = self._parse_channels(m.group(4))
            line = m.group(0)
            bm = re.search(r"(\d+(?:\.\d+)?)\s*kb/s", line)
            bit_rate = f"{float(bm.group(1)):g} kb/s" if bm else None
            audios.append({"index": idx, "codec_name": cname,
                           "channels": ch, "sample_rate": m.group(3),
                           "bit_rate": bit_rate})
        dur = None
        dm = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", text)
        if dm:
            dur = int(dm.group(1)) * 3600 + int(dm.group(2)) * 60 + float(dm.group(3))
        video = {}
        vm = re.search(r"^\s*Stream #0:(\d+)(?:\[[^\]]*\])?(?:\([^)]*\))?:\s*Video: (\w+)[^\n]*",
                       text, re.MULTILINE)
        if vm:
            vbm = re.search(r"(\d+(?:\.\d+)?)\s*kb/s", vm.group(0))
            video = {"codec": vm.group(2),
                     "bit_rate": f"{float(vbm.group(1)):g} kb/s" if vbm else None}
        return {"audios": audios, "dur": dur, "video": video}

    @staticmethod
    def _parse_channels(layout):
        layout = (layout or "").strip().lower()
        named = {"mono": 1, "stereo": 2, "2.1": 3, "3.0": 3, "3.1": 4,
                 "quad": 4, "4.0": 4, "4.1": 5, "5.0": 5, "5.1": 6,
                 "5.1(side)": 6, "6.0": 6, "6.1": 7, "7.0": 8, "7.1": 8}
        if layout in named:
            return named[layout]
        # 5.1.4 / 7.1.4 / 9.1.6 等带天空声道的布局：各段数字相加
        m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?(?:\([^)]*\))?$", layout)
        if m:
            return sum(int(g) for g in m.groups() if g)
        # FL+FR+FC+LFE+BL+BR+...
        if "+" in layout:
            return len([p for p in layout.split("+") if p.strip()])
        m = re.search(r"(\d+)\s*channels?", layout)
        return int(m.group(1)) if m else 0

    def plan_targets(self, audios):
        """确定需要转码的音轨: {audio stream index: (codec, bitrate, downmix)}"""
        targets = {}
        audio_ordinal = 0  # -c:a:N 的 N 是按音频流顺序计数
        for s in audios:
            idx = audio_ordinal
            audio_ordinal += 1
            cname = s.get("codec_name", "")
            if AV3A_RE.search(cname):
                ch = int(s.get("channels") or 0)
                codec = self.codec_var.get()
                if codec == "pcm":
                    # 无损保留原始声道数(如5.1.4)，容器自动改用 MKV
                    targets[idx] = ("pcm", None, None)
                    continue
                if codec == "ac3":
                    br = self._int_or(self.ac3_br_var.get(), 640)
                elif codec == "eac3":
                    br = self._int_or(self.eac3_br_var.get(), 768)
                else:
                    br = self._int_or(self.aac_br_var.get(), 192)
                # AAC 不支持 >2 声道封装时自动下混到立体声;
                # AC3/EAC3 编码器上限 5.1(6ch)，>6ch 自动下混到 5.1
                # ch==0 表示声道数未知（如自定义布局解析失败），AAC 一律强制下混 2.0
                if codec == "aac" and (ch > 2 or ch == 0):
                    downmix = 2
                elif codec in ("ac3", "eac3") and (ch > 6 or ch == 0):
                    downmix = 6
                else:
                    downmix = None
                targets[idx] = (codec, f"{br}k", downmix)
        return targets

    @staticmethod
    def _int_or(val, default):
        try:
            v = int(str(val).strip())
            return v if v > 0 else default
        except ValueError:
            return default

    def build_cmd(self, ffmpeg, src, dst, targets, n_audio):
        # 视频流复制，不重新编码；非 AV3A 音轨也保持复制
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "warning", "-stats",
               "-i", src, "-map", "0", "-dn", "-sn", "-c:v", "copy"]
        for i in range(n_audio):
            if i in targets:
                codec, br, downmix = targets[i]
                if codec == "pcm":
                    cmd += [f"-c:a:{i}", "pcm_s16le"]
                else:
                    cmd += [f"-c:a:{i}", codec, f"-b:a:{i}", br]
                    if downmix:
                        # 显式两步：解码后的 PCM 先由 aresample 下混为目标声道布局
                        # (AAC → 2.0 PCM；AC3/EAC3 → 5.1 PCM)，再交给编码器
                        layout = "stereo" if downmix == 2 else "5.1"
                        cmd += [f"-filter:a:{i}", f"aresample=ochl={layout}",
                                f"-ac:a:{i}", str(downmix)]
            else:
                cmd += [f"-c:a:{i}", "copy"]
        cmd += ["-max_muxing_queue_size", "9999", dst]
        return cmd

    def run_convert(self, ffmpeg, ffprobe, path):
        self._ffmpeg_path = ffmpeg
        base = os.path.basename(path)
        self.log(f"== 探测: {base}")
        info = self.file_info.get(path)
        if not info:
            info = self.probe(ffprobe, path)
            self.file_info[path] = info
        audios, dur = info["audios"], info["dur"]
        targets = self.plan_targets(audios)
        if not targets:
            self.log(f"   未发现 AV3A 音轨 (音频流: " +
                     ", ".join(f"#{s.get('index')}={s.get('codec_name')}({s.get('channels','?')}ch)" for s in audios) +
                     ")，跳过。")
            return "无AV3A音轨"
        av3a_tracks = [s for s in audios if AV3A_RE.search(s.get("codec_name", ""))]
        self.log(f"   共发现 {len(av3a_tracks)} 条 AV3A 音轨 (音频流共 {len(audios)} 条)")
        v = info.get("video") or {}
        self.log(f"   视频: {v.get('codec','?')} 源码率 {v.get('bit_rate') or '未知'} (流复制，不重编)")
        for idx, tgt in sorted(targets.items()):
            codec, br, downmix = tgt
            s = audios[idx]
            src_br = s.get("bit_rate") or "未知"
            if codec == "pcm":
                dst_ch = f" → PCM 无损保留{s.get('channels','?')}ch"
            elif downmix == 6:
                dst_ch = " → 先下混为5.1 PCM(天空声道折入) 再编码"
            elif downmix == 2:
                dst_ch = " → 先下混为2.0 PCM 再编码"
            else:
                dst_ch = ""
            self.log(f"   音轨 #{s.get('index')}: {s.get('codec_name')} {s.get('channels','?')}ch "
                     f"{s.get('sample_rate','?')}Hz 源码率 {src_br} → "
                     + ("PCM 无损" if codec == "pcm" else f"{codec.upper()} @ {br}") + dst_ch)
        use_pcm = any(t[0] == "pcm" for t in targets.values())
        outdir = self.outdir_var.get().strip() or os.path.dirname(path)
        os.makedirs(outdir, exist_ok=True)
        root_, ext = os.path.splitext(base)
        if use_pcm:
            # PCM 多声道需 MKV 容器
            dst = os.path.join(outdir, root_ + ".mkv")
        elif ext.lower() in (".ts", ".m2ts", ".mts", ".trp"):
            dst = os.path.join(outdir, root_ + ext.lower())
        else:
            dst = os.path.join(outdir, root_ + ".ts")
        # 避免覆盖到源文件自身
        if os.path.abspath(dst) == os.path.abspath(path):
            dst = os.path.join(outdir, root_ + "_converted" + os.path.splitext(dst)[1])
        if os.path.exists(dst):
            i = 1
            while os.path.exists(os.path.join(outdir, f"{root_} ({i}){os.path.splitext(dst)[1]}")):
                i += 1
            dst = os.path.join(outdir, f"{root_} ({i}){os.path.splitext(dst)[1]}")

        cmd = self.build_cmd(ffmpeg, path, dst, targets, len(audios))
        self.log(f"== 转换: {base} → {os.path.basename(dst)}")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace",
                                creationflags=subprocess.CREATE_NO_WINDOW)

        time_re = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
        for line in proc.stdout:
            if self.cancel_flag.is_set():
                proc.kill()
                return "已取消"
            m = time_re.search(line)
            if m and dur:
                sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                pct = min(100.0, sec / dur * 100)
                self._set_progress(pct, f"{base}: {pct:.1f}%")
            elif line.strip():
                self.log("   " + line.rstrip())
        proc.wait()
        self._set_progress(0, "就绪")
        if proc.returncode != 0:
            self.log(f"!! ffmpeg 退出码 {proc.returncode}，转换失败: {base}")
            if os.path.exists(dst):
                try:
                    os.remove(dst)
                except OSError:
                    pass
            raise RuntimeError("ffmpeg 转码失败，详见上方日志")
        self.log(f"== 完成: {os.path.basename(dst)}")
        return "完成"

    def _set_progress(self, pct, text):
        self._ui(lambda: (self.progress.configure(value=pct),
                          self.progress_label.configure(text=text)))

    def _worker(self, files, ffmpeg, ffprobe):
        for path in files:
            if self.cancel_flag.is_set():
                break
            self.set_status(path, "处理中")
            try:
                status = self.run_convert(ffmpeg, ffprobe, path)
                self.results[path] = status
                self.set_status(path, status)
                if status == "完成" and self.delete_src_var.get():
                    try:
                        os.remove(path)
                        self.log(f"   已删除源文件: {os.path.basename(path)}")
                    except OSError as e:
                        self.log(f"   删除源文件失败: {e}")
            except Exception as e:
                self.results[path] = "失败"
                self.set_status(path, "失败")
                self.log(f"!! 失败: {os.path.basename(path)}\n   {e}")
        self.log(">>> 全部任务结束。")
        self._ui(lambda: (self.start_btn.configure(state="normal"),
                          self.cancel_btn.configure(state="disabled")))

    def _poll_queue(self):
        try:
            while True:
                fn = self.task_queue.get_nowait()
                try:
                    fn()
                except Exception:
                    pass
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)


def main():
    root = ttkb.Window(title="AV3A转码工具", themename="darkly",
                       size=(960, 850), minsize=(880, 780))
    ConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
