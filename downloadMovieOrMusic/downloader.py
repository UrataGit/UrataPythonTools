"""
downloader.py
動画・音楽ダウンローダー (yt-dlp + tkinter)
"""

import sys
import subprocess
import threading
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# yt-dlp の自動最新化
# ---------------------------------------------------------------------------

def ensure_dependencies():
    """yt-dlp を最新化する。ffmpeg は同階層の ffmpeg.exe を使用。"""
    print("yt-dlp を最新化しています...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

ensure_dependencies()

# ---------------------------------------------------------------------------
# パス解決
# EXE化時は sys.executable のフォルダ、通常実行時は __file__ のフォルダを参照
# ---------------------------------------------------------------------------

def _resolve_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

BASE_DIR = _resolve_base_dir()

# 同階層の ffmpeg.exe を優先。なければ PATH に任せる
_ffmpeg_local = BASE_DIR / "ffmpeg.exe"
FFMPEG_LOCATION = str(_ffmpeg_local) if _ffmpeg_local.exists() else None

# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

import tkinter as tk
from tkinter import ttk, messagebox
import yt_dlp  # noqa: E402

# ダウンロード形式の定義
FORMATS = {
    "MP3（音楽）": {
        "ydl_opts": {
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        },
    },
    "高音質音楽（FLAC/Opus）": {
        "ydl_opts": {
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "best",
                }
            ],
        },
    },
    "MP4（標準画質）": {
        "ydl_opts": {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
        },
    },
    "MP4（高画質）": {
        "ydl_opts": {
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
        },
    },
    "MP4（字幕付き・英語）": {
        "ydl_opts": {
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en"],
            "subtitlesformat": "srt",
            "postprocessors": [
                {"key": "FFmpegEmbedSubtitle"},
            ],
        },
    },
}


class ProgressDialog(tk.Toplevel):
    """ダウンロード進捗ダイアログ（キャンセルボタン付き）"""

    def __init__(self, parent, total_urls: int):
        super().__init__(parent)
        self.title("ダウンロード中...")
        self.resizable(False, False)
        self.grab_set()

        self._total = total_urls
        self._current_index = 0
        self.cancelled = False          # キャンセルフラグ
        self._cancel_lock = threading.Lock()

        # ---- 全体進捗 ----
        tk.Label(self, text="全体の進捗:", anchor="w").pack(
            fill="x", padx=16, pady=(14, 0)
        )
        self.overall_bar = ttk.Progressbar(
            self, length=380, maximum=total_urls, mode="determinate"
        )
        self.overall_bar.pack(padx=16, pady=(2, 6))
        self.overall_label = tk.Label(
            self, text=f"0 / {total_urls} ファイル", anchor="w", fg="#555"
        )
        self.overall_label.pack(fill="x", padx=16)

        # ---- 現ファイル進捗 ----
        tk.Label(self, text="現在のファイル:", anchor="w").pack(
            fill="x", padx=16, pady=(10, 0)
        )
        self.file_bar = ttk.Progressbar(
            self, length=380, maximum=100, mode="determinate"
        )
        self.file_bar.pack(padx=16, pady=(2, 6))
        self.file_label = tk.Label(
            self, text="待機中...", anchor="w", fg="#555", wraplength=360
        )
        self.file_label.pack(fill="x", padx=16, pady=(0, 10))

        # ---- キャンセルボタン ----
        self.cancel_btn = ttk.Button(
            self, text="キャンセル", command=self._on_cancel
        )
        self.cancel_btn.pack(pady=(0, 14))

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)  # × でもキャンセル
        self._center(parent)

    # ------------------------------------------------------------------
    def _on_cancel(self):
        """キャンセルボタン押下 or ウィンドウ閉じる"""
        with self._cancel_lock:
            if self.cancelled:
                return
            self.cancelled = True
        self.cancel_btn.config(state="disabled", text="キャンセル中...")
        self.file_label.config(text="キャンセル中... 現在のファイルが終わり次第停止します")
        self.update_idletasks()

    # ------------------------------------------------------------------
    def _center(self, parent):
        self.update_idletasks()
        pw = parent.winfo_rootx() + parent.winfo_width() // 2
        ph = parent.winfo_rooty() + parent.winfo_height() // 2
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{pw - w//2}+{ph - h//2}")

    # ------------------------------------------------------------------
    def set_file_start(self, index: int, url: str):
        self._current_index = index
        short_url = url if len(url) <= 50 else url[:47] + "..."
        self.overall_bar["value"] = index
        self.overall_label.config(text=f"{index} / {self._total} ファイル")
        self.file_bar["value"] = 0
        self.file_label.config(text=f"[{index+1}/{self._total}] {short_url}")
        self.update_idletasks()

    def set_file_progress(self, percent: float, speed: str, eta: str):
        self.file_bar["value"] = percent
        self.file_label.config(
            text=f"[{self._current_index+1}/{self._total}] "
                 f"{percent:.1f}% | {speed} | ETA {eta}"
        )
        self.update_idletasks()

    def set_file_done(self):
        self.file_bar["value"] = 100
        completed = self._current_index + 1
        self.overall_bar["value"] = completed
        self.overall_label.config(text=f"{completed} / {self._total} ファイル")
        self.update_idletasks()


class DownloaderApp(tk.Tk):
    """メインウィンドウ"""

    def __init__(self):
        super().__init__()
        self.title("動画・音楽ダウンローダー")
        self.resizable(False, False)
        self._build_ui()
        self._center()

    # ------------------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 16, "pady": 6}

        tk.Label(self, text="URL（複数行可・1行1URL）:", anchor="w").pack(
            fill="x", **pad
        )
        frame_url = tk.Frame(self)
        frame_url.pack(fill="x", padx=16, pady=(0, 6))
        self.url_text = tk.Text(frame_url, height=6, width=52, wrap="none")
        sb = ttk.Scrollbar(frame_url, command=self.url_text.yview)
        self.url_text.configure(yscrollcommand=sb.set)
        self.url_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        tk.Label(self, text="ダウンロード形式:", anchor="w").pack(
            fill="x", **pad
        )
        self._format_var = tk.StringVar(value=list(FORMATS.keys())[0])
        for fmt_name in FORMATS:
            tk.Radiobutton(
                self,
                text=fmt_name,
                variable=self._format_var,
                value=fmt_name,
                anchor="w",
            ).pack(fill="x", padx=28, pady=1)

        ttk.Button(
            self, text="ダウンロード開始", command=self._start_download
        ).pack(pady=(10, 14))

    # ------------------------------------------------------------------
    def _center(self):
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

    # ------------------------------------------------------------------
    def _start_download(self):
        raw = self.url_text.get("1.0", "end").strip()
        urls = [u.strip() for u in raw.splitlines() if u.strip()]
        if not urls:
            messagebox.showwarning("URL未入力", "URLを1つ以上入力してください。")
            return

        fmt_cfg = FORMATS[self._format_var.get()]
        progress_dlg = ProgressDialog(self, total_urls=len(urls))

        def run():
            errors = []
            cancelled_count = 0

            for idx, url in enumerate(urls):

                # キャンセル済みなら次のURLへ進まず終了
                if progress_dlg.cancelled:
                    cancelled_count = len(urls) - idx
                    break

                self.after(0, progress_dlg.set_file_start, idx, url)

                def hook(d, _idx=idx):
                    if progress_dlg.cancelled:
                        # yt-dlp にキャンセルを伝える（例外を発生させる）
                        raise yt_dlp.utils.DownloadCancelled()
                    if d["status"] == "downloading":
                        pct_raw = d.get("_percent_str", "0%")
                        pct = float(re.sub(r"[^\d.]", "", pct_raw) or 0)
                        speed = d.get("_speed_str", "-- B/s").strip()
                        eta = d.get("_eta_str", "--").strip()
                        self.after(0, progress_dlg.set_file_progress, pct, speed, eta)
                    elif d["status"] == "finished":
                        self.after(0, progress_dlg.set_file_done)

                opts = {
                    **fmt_cfg["ydl_opts"],
                    "outtmpl": str(BASE_DIR / "%(title)s.%(ext)s"),
                    "progress_hooks": [hook],
                    "quiet": True,
                    "no_warnings": True,
                    "http_chunk_size": 10485760,        # 10MB単位で取得
                    "concurrent_fragment_downloads": 4, # 並列フラグメント数
                    "retries": 10,                      # エラー時リトライ回数
                    "noplaylist": True,                 # URLにリストが含まれても単一動画のみ取得
                    **({"ffmpeg_location": FFMPEG_LOCATION} if FFMPEG_LOCATION else {}),
                }

                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                except yt_dlp.utils.DownloadCancelled:
                    cancelled_count = len(urls) - idx
                    break
                except Exception as e:
                    errors.append(f"[{url}]\n{e}")

            # 完了後の通知
            self.after(0, progress_dlg.destroy)

            if cancelled_count > 0:
                done = len(urls) - cancelled_count - len(errors)
                self.after(
                    0,
                    lambda: messagebox.showwarning(
                        "キャンセル",
                        f"キャンセルしました。\n完了: {done} 件 / 未処理: {cancelled_count} 件",
                    ),
                )
            elif errors:
                msg = "以下のURLでエラーが発生しました:\n\n" + "\n\n".join(errors)
                self.after(0, lambda: messagebox.showerror("エラー", msg))
            else:
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "完了",
                        f"{len(urls)} 件のダウンロードが完了しました。\n保存先: {BASE_DIR}",
                    ),
                )

        threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = DownloaderApp()
    app.mainloop()