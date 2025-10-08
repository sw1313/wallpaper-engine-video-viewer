import os
import sys
import json
import math
import tempfile
import ctypes
import webbrowser
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QGridLayout, QWidget, QLabel, QFrame, QScrollArea,
    QComboBox, QFileDialog, QMessageBox, QPushButton, QHBoxLayout, QLineEdit, QCheckBox, QMenu,
    QRubberBand
)
from PySide6.QtGui import QPainter, QPalette, QColor, QFont, QPen, QMouseEvent, QPixmap, QMovie
from PySide6.QtCore import (
    Qt, QSize, QRect, QPoint, Signal, QObject, QEvent, QTimer, QFileSystemWatcher,
    QByteArray, QBuffer, QIODevice
)

# ====== 常量：统一最小间距、最小方框边长 ======
MIN_SPACING = 8          # 上下左右 & 网格间距都用它
MIN_TILE_EDGE = 180      # 方框最小边长（会随窗口变大）


# =========================
# 数据模型
# =========================

@dataclass
class VideoItem:
    id: str
    title: str
    preview_path: str
    video_path: str
    mtime: float
    size: int
    rating: str  # contentrating
    vtype: str   # type


@dataclass
class FolderNode:
    title: str
    items: List[str] = field(default_factory=list)       # item ids
    subfolders: List['FolderNode'] = field(default_factory=list)


# =========================
# 配置读写（本程序用）
# =========================

CONFIG_TXT = "config.txt"


def read_config_txt() -> Dict[str, str]:
    cfg = {}
    if os.path.exists(CONFIG_TXT):
        try:
            with open(CONFIG_TXT, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or ": " not in line:
                        continue
                    k, v = line.split(": ", 1)
                    cfg[k.strip()] = v.strip().strip("'").strip('"')
        except Exception:
            pass
    # 兼容旧键
    if "workshop_path" not in cfg and "file_path" in cfg:
        cfg["workshop_path"] = cfg["file_path"]
    return cfg


def write_config_txt(workshop_path: str, we_path: str):
    with open(CONFIG_TXT, "w", encoding="utf-8") as f:
        f.write(f"workshop_path: '{workshop_path}'\n")
        f.write(f"we_path: '{we_path}'\n")


# =========================
# 读取 Wallpaper Engine 配置（只读）
# =========================

def load_we_config(we_path: str) -> dict:
    cfg_path = os.path.join(we_path, "config.json")
    if not os.path.exists(cfg_path):
        raise FileNotFoundError(f"找不到 config.json：{cfg_path}")
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_folders_list(we_cfg: dict) -> List[dict]:
    """
    在顶层用户段落下优先查找 general.browser.folders；
    若缺失，再尝试 general.folders。
    不读取任何用户名键名，仅遍历顶层对象。
    """
    for _, v in we_cfg.items():
        if not isinstance(v, dict):
            continue
        general = v.get("general", {})
        if not isinstance(general, dict):
            continue
        browser = general.get("browser", {})
        folders = []
        if isinstance(browser, dict):
            folders = browser.get("folders", [])
        if not folders:
            folders = general.get("folders", [])
        if isinstance(folders, list) and folders:
            return folders
    return []


def build_folder_tree(folders_list: List[dict]) -> List[FolderNode]:
    def parse_folder(fobj: dict) -> FolderNode:
        title = fobj.get("title", "未命名文件夹")
        items_map = fobj.get("items", {}) or {}
        items = [str(x) for x in items_map.keys()]
        subnodes = [parse_folder(sf) for sf in (fobj.get("subfolders", []) or [])]
        return FolderNode(title=title, items=items, subfolders=subnodes)

    return [parse_folder(f) for f in folders_list]


# =========================
# 扫描创意工坊目录
# =========================

def safe_join(*parts) -> str:
    return os.path.normpath(os.path.join(*parts))


def scan_workshop_items(workshop_root_431960: str) -> Dict[str, VideoItem]:
    id_map: Dict[str, VideoItem] = {}
    if not os.path.isdir(workshop_root_431960):
        return id_map

    for entry in os.listdir(workshop_root_431960):
        if not entry.isdigit():
            continue
        id_dir = safe_join(workshop_root_431960, entry)
        if not os.path.isdir(id_dir):
            continue

        pj = safe_join(id_dir, "project.json")
        if not os.path.exists(pj):
            continue

        try:
            with open(pj, "r", encoding="utf-8") as f:
                pdata = json.load(f)
        except Exception:
            continue

        title = pdata.get("title", entry)
        preview_file = pdata.get("preview", "")
        video_file = pdata.get("file", "")
        vtype = (pdata.get("type", "") or "").lower()
        rating = pdata.get("contentrating", "")

        # 只收 video
        if vtype != "video":
            continue

        preview_path = safe_join(id_dir, preview_file) if preview_file else ""
        video_path = safe_join(id_dir, video_file) if video_file else ""
        if not (os.path.exists(preview_path) and os.path.exists(video_path)):
            continue

        try:
            mtime = os.path.getmtime(video_path)
            size = os.path.getsize(video_path)
        except Exception:
            mtime, size = 0.0, 0

        id_map[entry] = VideoItem(
            id=entry, title=title, preview_path=preview_path, video_path=video_path,
            mtime=mtime, size=size, rating=rating, vtype=vtype
        )
    return id_map


def collect_unassigned_items(id_map: Dict[str, VideoItem], roots: List[FolderNode]) -> List[str]:
    assigned: Set[str] = set()

    def walk(node: FolderNode):
        assigned.update(node.items)
        for sf in node.subfolders:
            walk(sf)

    for r in roots:
        walk(r)
    return sorted([i for i in id_map.keys() if i not in assigned])


# =========================
# 预览 Tile（基类 / 视频 / 文件夹）
# =========================

class BaseTile(QFrame):
    clicked = Signal(object)
    contextRequested = Signal(object, QPoint)
    doubleActivated = Signal(object)

    def __init__(self, title: str):
        super().__init__()
        self._edge = MIN_TILE_EDGE
        self.setFixedSize(self._edge, self._edge)
        self._selected = False

        self._title_label = QLabel(title, self)
        self._title_label.setAlignment(Qt.AlignCenter)
        pal = self._title_label.palette()
        pal.setColor(QPalette.WindowText, QColor('white'))
        self._title_label.setPalette(pal)
        self._title_label.setWordWrap(True)
        font = QFont()
        font.setPointSize(8)
        self._title_label.setFont(font)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        layout.addWidget(self._title_label)
        self.setLayout(layout)

        self.setMouseTracking(True)
        self.setFrameShape(QFrame.StyledPanel)

    def setTileEdge(self, edge: int):
        if edge <= 0 or edge == self._edge:
            return
        self._edge = edge
        self.setFixedSize(edge, edge)
        self.update()

    def tileEdge(self) -> int:
        return self._edge

    def setSelected(self, val: bool):
        self._selected = val
        self.update()

    def isSelected(self) -> bool:
        return self._selected

    def labelRect(self) -> QRect:
        return self._title_label.geometry().adjusted(0, -4, 0, 4)

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self)
        elif e.button() == Qt.RightButton:
            self.contextRequested.emit(self, e.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self.doubleActivated.emit(self)
        elif e.button() == Qt.RightButton:
            self.contextRequested.emit(self, e.globalPosition().toPoint())

    # 选中高亮边框（蓝色）
    def paint_selection_frame(self, painter: QPainter):
        pen = QPen(QColor(0, 170, 255) if self._selected else QColor(255, 255, 255, 40))
        pen.setWidth(2 if self._selected else 1)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.rect().adjusted(1, 1, -1, -1))


class VideoTile(BaseTile):
    """
    预览懒加载 + 防锁定：
      - 把 GIF 读入内存（bytes -> QByteArray -> QBuffer）
      - 用 QBuffer 作为 QMovie 的 QIODevice，避免占用磁盘文件句柄
      - 隐藏/翻页/销毁时释放 QMovie 与 QBuffer
      - 随 tile 尺寸变化动态缩放 QMovie
    """
    def __init__(self, item: VideoItem):
        super().__init__(item.title)
        self.item = item
        self._movie: Optional[QMovie] = None
        self._buf: Optional[QBuffer] = None
        self._data: Optional[QByteArray] = None
        self._placeholder = QPixmap(self.tileEdge(), self.tileEdge())
        self._placeholder.fill(QColor(10, 10, 10))

    def setTileEdge(self, edge: int):
        old = self.tileEdge()
        super().setTileEdge(edge)
        if edge != old:
            self._placeholder = QPixmap(edge, edge)
            self._placeholder.fill(QColor(10, 10, 10))
            if self._movie is not None and self._movie.isValid():
                self._movie.setScaledSize(QSize(edge, edge))
            self.update()

    def ensure_movie(self):
        if self._movie is not None:
            return
        try:
            with open(self.item.preview_path, "rb") as f:
                raw = f.read()
            self._data = QByteArray(raw)
            self._buf = QBuffer(self._data)
            self._buf.open(QIODevice.ReadOnly)
            ext = os.path.splitext(self.item.preview_path)[1].lower()
            fmt = QByteArray(b"gif") if ext.endswith("gif") else QByteArray()
            self._movie = QMovie(self._buf, fmt)
            self._movie.setCacheMode(QMovie.CacheAll)
            self._movie.setScaledSize(QSize(self.tileEdge(), self.tileEdge()))
            self._movie.frameChanged.connect(self.update)
            self._movie.start()
        except Exception:
            self.release_movie()

    def release_movie(self):
        try:
            if self._movie is not None:
                self._movie.stop()
                self._movie.deleteLater()
        finally:
            self._movie = None
        try:
            if self._buf is not None:
                if self._buf.isOpen():
                    self._buf.close()
                self._buf.deleteLater()
        finally:
            self._buf = None
        self._data = None

    def showEvent(self, e):
        self.ensure_movie()
        super().showEvent(e)

    def hideEvent(self, e):
        self.release_movie()
        super().hideEvent(e)

    def event(self, ev: QEvent):
        if ev.type() in (QEvent.Hide, QEvent.HideToParent, QEvent.Close, QEvent.Destroy):
            self.release_movie()
        return super().event(ev)

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._movie is not None and self._movie.isValid():
            painter.drawPixmap(self.rect(), self._movie.currentPixmap())
        else:
            painter.drawPixmap(self.rect(), self._placeholder)

        rect_y = self.height() - (self.labelRect().height() + 10)
        painter.setBrush(QColor(0, 0, 0, 110))
        painter.setPen(Qt.NoPen)
        painter.drawRect(0, rect_y, self.width(), self.height() - rect_y)
        self.paint_selection_frame(painter)


class FolderTile(BaseTile):
    def __init__(self, title: str, count: int):
        super().__init__(f"{title}\n({count})")
        self.title = title

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(30, 30, 30))
        lid = QRect(int(self.width() * 0.11), int(self.height() * 0.22), int(self.width() * 0.78), int(self.height() * 0.14))
        painter.fillRect(lid, QColor(200, 170, 60, 200))
        body = QRect(int(self.width() * 0.08), int(self.height() * 0.36), int(self.width() * 0.84), int(self.height() * 0.47))
        painter.fillRect(body, QColor(230, 190, 70, 220))
        rect_y = self.height() - (self.labelRect().height() + 10)
        painter.setBrush(QColor(0, 0, 0, 110))
        painter.setPen(Qt.NoPen)
        painter.drawRect(0, rect_y, self.width(), self.height() - rect_y)
        self.paint_selection_frame(painter)


# =========================
# 主窗口
# =========================

class MainWindow(QMainWindow):
    def __init__(self, workshop_path: str, we_path: str):
        super().__init__()
        self.setWindowTitle("Wallpaper 视频预览")
        self.workshop_root = os.path.abspath(workshop_path)
        self.we_path = we_path

        # 动态布局参数
        self.columns = 1
        self.tile_edge = MIN_TILE_EDGE
        self.page_size = 45
        self.current_page = 0

        # 运行态
        self.id_map: Dict[str, VideoItem] = {}
        self.folder_roots: List[FolderNode] = []
        self.root_unassigned_ids: List[str] = []
        self.nav_stack: List[Tuple[str, List[FolderNode], List[str]]] = []
        self.current_subfolders: List[FolderNode] = []
        self.current_item_ids: List[str] = []
        self._tiles: List[BaseTile] = []
        self._last_focus_index: Optional[int] = None
        self._rubber: Optional[QRubberBand] = None
        self._rubber_origin = QPoint()
        self._rubber_active = False

        # === UI ===
        central = QWidget(self)
        self.setCentralWidget(central)

        self.scroll_area = QScrollArea(self)
        # 关键：不要让内容被强行拉伸到视口大小
        self.scroll_area.setWidgetResizable(False)
        # 关键：内容小于视口时，靠左并贴顶
        self.scroll_area.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.scroll_area.setStyleSheet("border: none;")

        self.layout = QVBoxLayout(central)
        self.layout.setContentsMargins(MIN_SPACING, MIN_SPACING, MIN_SPACING, MIN_SPACING)
        self.layout.setSpacing(MIN_SPACING)
        self.layout.addWidget(self.scroll_area)

        # 顶部工具条
        self.pagination_layout = QHBoxLayout()
        self.pagination_layout.setContentsMargins(0, 0, 0, 0)
        self.pagination_layout.setSpacing(MIN_SPACING)

        self.back_btn = QPushButton("← 返回上一级")
        self.back_btn.clicked.connect(self.nav_back)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.reload_everything)

        self.breadcrumb = QLabel("当前位置：/")

        self.sort_combo = QComboBox(self)
        self.sort_combo.addItems(
            ["修改日期降序", "修改日期升序", "文件大小降序", "文件大小升序", "文件名降序", "文件名升序"]
        )
        self.sort_combo.currentIndexChanged.connect(self.refresh_grid)

        self.prev_button = QPushButton("上一页")
        self.next_button = QPushButton("下一页")
        self.prev_button.clicked.connect(self.previous_page)
        self.next_button.clicked.connect(self.next_page)

        self.page_info_label = QLabel(self)
        self.page_input = QLineEdit(self)
        self.page_input.setPlaceholderText("输入页码")
        self.page_input.setFixedWidth(100)
        self.page_input.returnPressed.connect(self.jump_to_page)

        self.rating_check = QCheckBox("只显示成人内容", self)
        self.rating_check.stateChanged.connect(self.refresh_grid)

        self.pagination_layout.addWidget(self.back_btn)
        self.pagination_layout.addWidget(self.refresh_btn)
        self.pagination_layout.addWidget(self.breadcrumb)
        self.pagination_layout.addStretch(1)
        self.pagination_layout.addWidget(self.sort_combo)
        self.pagination_layout.addWidget(self.prev_button)
        self.pagination_layout.addWidget(self.next_button)
        self.pagination_layout.addWidget(self.page_info_label)
        self.pagination_layout.addWidget(self.page_input)
        self.pagination_layout.addWidget(self.rating_check)
        self.layout.addLayout(self.pagination_layout)

        # 内容网格
        self.content_widget = QWidget()
        self.grid_layout = QGridLayout(self.content_widget)
        self.grid_layout.setSpacing(MIN_SPACING)
        self.grid_layout.setContentsMargins(MIN_SPACING, MIN_SPACING, MIN_SPACING, MIN_SPACING)
        self.content_widget.installEventFilter(self)
        self.scroll_area.setWidget(self.content_widget)

        # 初次加载
        self.reload_everything()

        # === 文件系统监听：config.json + workshop 根目录 ===
        self._fswatcher = QFileSystemWatcher(self)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(500)
        self._debounce.timeout.connect(self._do_reload_after_fs_event)

        cfg_path = os.path.join(self.we_path, "config.json")
        if os.path.exists(cfg_path):
            self._fswatcher.addPath(cfg_path)
        if os.path.isdir(self.workshop_root):
            self._fswatcher.addPath(self.workshop_root)
        self._fswatcher.fileChanged.connect(self._on_fs_event)
        self._fswatcher.directoryChanged.connect(self._on_fs_event)

    # ---------- 首次显示后再做一次布局（修复启动只有一列） ----------

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._after_first_show)

    def _after_first_show(self):
        cols, edge = self.compute_grid_metrics()
        if cols != self.columns or edge != self.tile_edge:
            self.columns, self.tile_edge = cols, edge
            self.refresh_grid()

    # ---------- 自适应：根据视口宽度计算列数与 tile 边长 ----------

    def compute_grid_metrics(self) -> Tuple[int, int]:
        """返回 (columns, tile_edge)，保持固定间距，尽量多列；tile 可变大。"""
        viewport = self.scroll_area.viewport()
        w = max(0, viewport.width() - 2 * MIN_SPACING)
        if w <= 0:
            return 1, MIN_TILE_EDGE
        # 尽量多放列；列数至少 1
        cols = max(1, int((w + MIN_SPACING) // (MIN_TILE_EDGE + MIN_SPACING)))
        # 根据列数反推本次方框边长，保证左右间距固定为 MIN_SPACING
        edge = int((w - (cols - 1) * MIN_SPACING) // cols)
        edge = max(edge, MIN_TILE_EDGE)
        return cols, edge

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cols, edge = self.compute_grid_metrics()
        if cols != self.columns or edge != self.tile_edge:
            self.columns = cols
            self.tile_edge = edge
            self.refresh_grid()

    # ---------- 监听与刷新 ----------

    def _on_fs_event(self, _path: str):
        self._debounce.start()

    def _do_reload_after_fs_event(self):
        crumb = [t for t, _, _ in self.nav_stack]
        self.reload_everything()
        if crumb:
            self._restore_folder_by_titles(crumb)

    def reload_everything(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            we_cfg = load_we_config(self.we_path)
            folders_list = extract_folders_list(we_cfg)
            self.folder_roots = build_folder_tree(folders_list)

            self.id_map = scan_workshop_items(self.workshop_root)

            self.root_unassigned_ids = collect_unassigned_items(self.id_map, self.folder_roots)

            self.nav_stack.clear()
            self.current_subfolders = self.folder_roots
            self.current_item_ids = self.root_unassigned_ids[:]
            self.breadcrumb.setText("当前位置：/")
            self.current_page = 0

            # 初始化一次度量
            self.columns, self.tile_edge = self.compute_grid_metrics()
            self.refresh_grid()
        finally:
            QApplication.restoreOverrideCursor()

    def _restore_folder_by_titles(self, titles: List[str]):
        def find_child(nodes: List[FolderNode], title: str) -> Optional[FolderNode]:
            for n in nodes:
                if n.title == title:
                    return n
            return None

        nodes = self.folder_roots
        stack: List[Tuple[str, List[FolderNode], List[str]]] = []
        for t in titles:
            n = find_child(nodes, t)
            if not n:
                break
            stack.append((n.title, n.subfolders, n.items))
            nodes = n.subfolders

        if stack:
            self.nav_stack = stack
            last = stack[-1]
            self.current_subfolders = last[1]
            self.current_item_ids = last[2]
            self.breadcrumb.setText("当前位置：/" + "/".join([s[0] for s in self.nav_stack]))
            self.current_page = 0
            self.refresh_grid()

    # ---------- 导航 ----------

    def nav_back(self):
        if not self.nav_stack:
            return
        self.nav_stack.pop()
        if not self.nav_stack:
            self.current_subfolders = self.folder_roots
            self.current_item_ids = self.root_unassigned_ids[:]
            self.breadcrumb.setText("当前位置：/")
        else:
            title, subfolders, item_ids = self.nav_stack[-1]
            self.current_subfolders = subfolders
            self.current_item_ids = item_ids
            self.breadcrumb.setText("当前位置：/" + "/".join([s[0] for s in self.nav_stack]))
        self.current_page = 0
        self.refresh_grid()

    def enter_folder(self, node: FolderNode):
        self.nav_stack.append((node.title, node.subfolders, node.items))
        self.current_subfolders = node.subfolders
        self.current_item_ids = node.items
        self.breadcrumb.setText("当前位置：/" + "/".join([s[0] for s in self.nav_stack]))
        self.current_page = 0
        self.refresh_grid()

    # ---------- 数据/分页（仅按需构建可见页） ----------

    def current_videos_filtered_sorted(self) -> List[str]:
        ids: List[str] = []
        for vid_id in self.current_item_ids:
            item = self.id_map.get(vid_id)
            if not item:
                continue
            if self.rating_check.isChecked() and item.rating != "Mature":
                continue
            ids.append(vid_id)

        idx = self.sort_combo.currentIndex()
        key_funcs = {
            0: lambda i: self.id_map[i].mtime,
            1: lambda i: self.id_map[i].mtime,
            2: lambda i: self.id_map[i].size,
            3: lambda i: self.id_map[i].size,
            4: lambda i: self.id_map[i].title,
            5: lambda i: self.id_map[i].title,
        }
        reverse = idx in (0, 2, 4)
        ids.sort(key=key_funcs.get(idx, lambda i: self.id_map[i].mtime), reverse=reverse)
        return ids

    def refresh_grid(self):
        # 再确认一次度量（极端场景）
        cols, edge = self.compute_grid_metrics()
        self.columns, self.tile_edge = cols, edge

        # 清空旧页
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()
        self._tiles.clear()

        folders = list(self.current_subfolders)
        video_ids_sorted = self.current_videos_filtered_sorted()

        total_tiles = len(folders) + len(video_ids_sorted)
        start = self.current_page * self.page_size
        end = min(start + self.page_size, total_tiles)
        page_tiles = end - start

        row = 0
        for pos in range(start, end):
            if pos < len(folders):
                node = folders[pos]
                count = self._count_items_recursive(node)
                tile = FolderTile(node.title, count)
                tile.setTileEdge(self.tile_edge)
                tile.doubleActivated.connect(lambda t, node=node: self.enter_folder(node))
                tile.clicked.connect(self.on_tile_clicked)
                tile.contextRequested.connect(self.on_tile_context)
            else:
                vid_index = pos - len(folders)
                vid_id = video_ids_sorted[vid_index]
                v = self.id_map[vid_id]
                tile = VideoTile(v)
                tile.setTileEdge(self.tile_edge)
                tile.doubleActivated.connect(lambda t, item=v: self.play_single(item))
                tile.clicked.connect(self.on_tile_clicked)
                tile.contextRequested.connect(self.on_tile_context)

            col = (pos - start) % self.columns
            self.grid_layout.addWidget(tile, row, col)
            self._tiles.append(tile)
            if col == self.columns - 1:
                row += 1

        # 分页控件
        self.prev_button.setEnabled(self.current_page > 0)
        self.next_button.setEnabled(end < total_tiles)
        total_pages = max(1, (total_tiles + self.page_size - 1) // self.page_size)
        self.page_info_label.setText(f"当前页: {self.current_page + 1} / {total_pages}")
        self._last_focus_index = None

        # 关键：根据“本页实际行列数”设置内容部件大小，防止被拉伸导致间距变化
        rows = max(1, math.ceil(page_tiles / max(1, self.columns))) if page_tiles > 0 else 1
        used_cols = min(self.columns, page_tiles) if page_tiles > 0 else 1

        m = self.grid_layout.contentsMargins()
        inner_w = used_cols * self.tile_edge + (used_cols - 1) * MIN_SPACING
        inner_h = rows * self.tile_edge + (rows - 1) * MIN_SPACING
        total_w = inner_w + m.left() + m.right()
        total_h = inner_h + m.top() + m.bottom()

        # 固定内容大小，让 QScrollArea 以左上对齐展示；上下/左右间距恒定
        self.content_widget.setMinimumSize(total_w, total_h)
        self.content_widget.resize(total_w, total_h)

    def _count_items_recursive(self, node: FolderNode) -> int:
        total = len(node.items)
        for sf in node.subfolders:
            total += self._count_items_recursive(sf)
        return total

    def next_page(self):
        folders_count = len(self.current_subfolders)
        videos_count = len(self.current_videos_filtered_sorted())
        total_tiles = folders_count + videos_count
        if (self.current_page + 1) * self.page_size < total_tiles:
            self.current_page += 1
            self.refresh_grid()
            self.scroll_area.verticalScrollBar().setValue(0)

    def previous_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.refresh_grid()
            self.scroll_area.verticalScrollBar().setValue(0)

    def jump_to_page(self):
        try:
            p = int(self.page_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "警告", "请输入数字。")
            return

        folders_count = len(self.current_subfolders)
        videos_count = len(self.current_videos_filtered_sorted())
        total_tiles = folders_count + videos_count
        total_pages = max(1, (total_tiles + self.page_size - 1) // self.page_size)

        if 1 <= p <= total_pages:
            self.current_page = p - 1
            self.refresh_grid()
        else:
            QMessageBox.warning(self, "警告", "请输入有效的页码。")

    # ---------- 选择 / 框选 / 快捷键 ----------

    def eventFilter(self, obj: QObject, ev: QEvent):
        if obj is self.content_widget:
            if ev.type() == QEvent.MouseButtonPress:
                mev: QMouseEvent = ev  # type: ignore
                if mev.button() == Qt.LeftButton:
                    self._rubber_active = True
                    self._rubber_origin = mev.position().toPoint()
                    if self._rubber is None:
                        self._rubber = QRubberBand(QRubberBand.Rectangle, self.content_widget)
                    self._rubber.setGeometry(QRect(self._rubber_origin, QSize()))
                    self._rubber.show()
                    if not (QApplication.keyboardModifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
                        self.clear_selection()
                    return True

            elif ev.type() == QEvent.MouseMove and getattr(self, "_rubber_active", False):
                pos = ev.position().toPoint()  # type: ignore
                rect = QRect(self._rubber_origin, pos).normalized()
                if self._rubber:
                    self._rubber.setGeometry(rect)
                for t in self._tiles:
                    g = t.geometry()
                    if g.intersects(rect):
                        t.setSelected(True)
                    else:
                        if not (QApplication.keyboardModifiers() & Qt.ControlModifier):
                            t.setSelected(False)
                return True

            elif ev.type() == QEvent.MouseButtonRelease and getattr(self, "_rubber_active", False):
                self._rubber_active = False
                if self._rubber:
                    self._rubber.hide()
                return True

        return super().eventFilter(obj, ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_A and (ev.modifiers() & Qt.ControlModifier):
            for t in self._tiles:
                t.setSelected(True)
            ev.accept()
            return
        super().keyPressEvent(ev)

    def on_tile_clicked(self, tile: QFrame):
        mods = QApplication.keyboardModifiers()
        idx = self._tiles.index(tile) if tile in self._tiles else None

        if mods & Qt.ShiftModifier and self._last_focus_index is not None and idx is not None:
            a, b = sorted([idx, self._last_focus_index])
            for i in range(a, b + 1):
                self._tiles[i].setSelected(True)
        elif mods & Qt.ControlModifier:
            tile.setSelected(not tile.isSelected())
        else:
            self.clear_selection()
            tile.setSelected(True)

        if idx is not None:
            self._last_focus_index = idx

    def clear_selection(self):
        for t in self._tiles:
            t.setSelected(False)

    def selected_tiles(self) -> List[QFrame]:
        return [t for t in self._tiles if t.isSelected()]

    # ---------- 右键菜单 & 播放 / 删除 / 跳转链接 / 多选操作 ----------

    def on_tile_context(self, tile: QFrame, gpos: QPoint):
        menu = QMenu(self)

        sel = self.selected_tiles()
        if not sel or tile not in sel:
            self.clear_selection()
            tile.setSelected(True)
            sel = [tile]

        video_items: List[VideoItem] = []
        folder_nodes: List[FolderNode] = []

        for t in sel:
            if isinstance(t, VideoTile):
                video_items.append(t.item)
            elif isinstance(t, FolderTile):
                node = self._find_node_by_title_in_current(t.title)
                if node:
                    folder_nodes.append(node)

        # —— 单视频操作 —— #
        if isinstance(tile, VideoTile) and len(video_items) == 1 and len(sel) == 1:
            menu.addAction("播放此视频", lambda it=tile.item: self.play_single(it))
            menu.addAction("打开所在文件夹", lambda it=tile.item: self.open_containing_folder(it))
            menu.addAction("打开创意工坊链接", lambda it=tile.item: self.open_workshop_page(it))
            menu.addSeparator()
            menu.addAction("删除（移到回收站）", lambda it=tile.item: self.delete_workshop_item(it))

        # —— 多选视频操作（≥2） —— #
        if len(video_items) >= 2:
            unique_dirs_count = len({
                os.path.dirname(v.video_path)
                for v in video_items
                if os.path.isdir(os.path.dirname(v.video_path))
            })
            id_dirs_set = {
                d for d in (
                    self._find_10digit_id_dir(v.video_path) for v in video_items
                ) if d
            }
            menu.addSeparator()
            menu.addAction(
                f"打开所选文件所在文件夹（{unique_dirs_count} 个）",
                lambda vis=video_items: self.open_containing_folders(vis)
            )
            menu.addAction(
                f"删除所选创意工坊项（{len(id_dirs_set)} 项，移到回收站）",
                lambda vis=video_items: self.delete_workshop_items(vis)
            )

        # —— 文件夹相关（原有） —— #
        if isinstance(tile, FolderTile) and len(sel) == 1:
            node = self._find_node_by_title_in_current(tile.title)
            if node:
                menu.addAction("打开此文件夹", lambda n=node: self.enter_folder(n))
                menu.addAction("播放此文件夹", lambda n=node: self.play_folders([n]))

        # 保留原有“批量播放”
        total_count = len(video_items) + sum(self._count_items_recursive(n) for n in folder_nodes)
        if total_count > 0:
            menu.addSeparator()
            menu.addAction(
                f"批量播放（{total_count} 项）",
                lambda vs=video_items, fs=folder_nodes: self.play_mixed(vs, fs)
            )

        menu.exec(gpos)

    def _find_node_by_title_in_current(self, title: str) -> Optional[FolderNode]:
        for n in self.current_subfolders:
            if n.title == title:
                return n
        return None

    def _gather_folder_items(self, node: FolderNode) -> List[VideoItem]:
        out: List[VideoItem] = []
        for iid in node.items:
            it = self.id_map.get(iid)
            if it and (not self.rating_check.isChecked() or it.rating == "Mature"):
                out.append(it)
        for sf in node.subfolders:
            out.extend(self._gather_folder_items(sf))
        return out

    # ---------- 单项操作（复用批量实现） ----------

    def play_single(self, item: VideoItem):
        try:
            os.startfile(item.video_path)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开：{e}")

    def open_containing_folder(self, item: VideoItem):
        self.open_containing_folders([item])

    def delete_workshop_item(self, item: VideoItem):
        self.delete_workshop_items([item])

    def open_workshop_page(self, item: VideoItem):
        try:
            wid = item.id if (item.id.isdigit() and len(item.id) == 10) else None
            if not wid:
                id_dir = self._find_10digit_id_dir(item.video_path)
                if id_dir:
                    name = os.path.basename(id_dir)
                    if name.isdigit() and len(name) == 10:
                        wid = name
            if not wid:
                QMessageBox.warning(self, "无法打开", "未找到 10 位创意工坊 ID。")
                return
            url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={wid}"
            webbrowser.open(url)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开创意工坊链接：{e}")

    # ---------- 批量：打开所在文件夹 / 删除到回收站 ----------

    def open_containing_folders(self, items: List[VideoItem]):
        dirs = []
        for it in items:
            d = os.path.dirname(it.video_path)
            if d and os.path.isdir(d):
                dirs.append(os.path.abspath(d))
        uniq_dirs = sorted(set(dirs))
        if not uniq_dirs:
            QMessageBox.information(self, "提示", "未找到可打开的文件夹。")
            return
        errors = []
        for d in uniq_dirs:
            try:
                os.startfile(d)
            except Exception as e:
                errors.append(f"{d} → {e}")
        if errors:
            QMessageBox.warning(self, "部分失败", "以下文件夹未能打开：\n" + "\n".join(errors))

    # === 删除：将 10 位 ID 的创意工坊文件夹移到回收站（Windows） ===

    def _find_10digit_id_dir(self, any_path: str) -> Optional[str]:
        p = os.path.abspath(any_path)
        wr = self.workshop_root
        while True:
            parent = os.path.dirname(p)
            if os.path.samefile(parent, p):
                return None
            if os.path.samefile(parent, wr):
                name = os.path.basename(p)
                if name.isdigit() and len(name) == 10:
                    return p
                return None
            p = parent

    def _send_to_recycle_bin(self, path: str):
        class SHFILEOPSTRUCT(ctypes.Structure):
            _fields_ = [
                ('hwnd', wintypes.HWND),
                ('wFunc', ctypes.c_uint),
                ('pFrom', wintypes.LPCWSTR),
                ('pTo', wintypes.LPCWSTR),
                ('fFlags', ctypes.c_uint),
                ('fAnyOperationsAborted', wintypes.BOOL),
                ('hNameMappings', ctypes.c_void_p),
                ('lpszProgressTitle', wintypes.LPCWSTR),
            ]
        FO_DELETE = 3
        FOF_ALLOWUNDO = 0x0040
        FOF_NOCONFIRMATION = 0x0010
        FOF_SILENT = 0x0004

        p_from = path + '\0\0'
        op = SHFILEOPSTRUCT()
        op.hwnd = 0
        op.wFunc = FO_DELETE
        op.pFrom = p_from
        op.pTo = None
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
        res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if res != 0:
            raise OSError(f"SHFileOperationW failed with code {res}")

    def delete_workshop_items(self, items: List[VideoItem]):
        id_dirs = []
        for it in items:
            d = self._find_10digit_id_dir(it.video_path)
            if d:
                id_dirs.append(os.path.abspath(d))
        uniq_dirs = sorted(set(id_dirs))
        if not uniq_dirs:
            QMessageBox.warning(self, "无法删除", "没有符合条件的 10 位 ID 创意工坊目录。")
            return

        ids_preview = ", ".join(os.path.basename(d) for d in uniq_dirs[:10])
        more = "" if len(uniq_dirs) <= 10 else f" 等共 {len(uniq_dirs)} 项"
        ret = QMessageBox.question(
            self, "确认删除",
            f"将删除以下创意工坊条目（移到回收站）：\n{ids_preview}{more}\n\n确定继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if ret != QMessageBox.Yes:
            return

        try:
            # 释放当前页所有预览占用
            for t in self._tiles:
                if isinstance(t, VideoTile):
                    t.release_movie()

            failed = []
            for d in uniq_dirs:
                try:
                    self._send_to_recycle_bin(d)
                except Exception as e:
                    failed.append(f"{d} → {e}")

            if failed:
                QMessageBox.warning(self, "部分失败", "以下目录未能移到回收站：\n" + "\n".join(failed))
            else:
                QMessageBox.information(self, "已删除", f"已移到回收站：{len(uniq_dirs)} 项")

            self.reload_everything()
        except Exception as e:
            QMessageBox.critical(self, "删除失败", f"删除时出错：{e}")

    # ---------- 播放逻辑（原样保留） ----------

    def play_folders(self, folders: List[FolderNode]):
        videos: List[VideoItem] = []
        for f in folders:
            videos.extend(self._gather_folder_items(f))
        self._play_as_playlist(videos)

    def play_mixed(self, videos: List[VideoItem], folders: List[FolderNode]):
        all_videos = list(videos)
        for f in folders:
            all_videos.extend(self._gather_folder_items(f))
        seen: Set[str] = set()
        uniq: List[VideoItem] = []
        for v in all_videos:
            if v.video_path not in seen:
                seen.add(v.video_path)
                uniq.append(v)
        self._play_as_playlist(uniq)

    def _play_as_playlist(self, videos: List[VideoItem]):
        if not videos:
            QMessageBox.information(self, "提示", "没有可播放的视频。")
            return
        m3u = os.path.join(tempfile.gettempdir(), "we_preview_playlist.m3u")
        try:
            with open(m3u, "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")
                for v in videos:
                    f.write(v.video_path + "\n")
            os.startfile(m3u)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"播放列表创建/打开失败：{e}")


# =========================
# 入口
# =========================

def main():
    app = QApplication(sys.argv)

    cfg = read_config_txt()
    workshop = cfg.get("workshop_path", "")
    wepath = cfg.get("we_path", "")

    if not workshop:
        workshop = QFileDialog.getExistingDirectory(
            None, "选择创意工坊目录（…\\SteamLibrary\\steamapps\\workshop\\content\\431960）", ""
        )
        if not workshop:
            QMessageBox.critical(None, "错误", "未选择创意工坊目录，将退出程序。")
            sys.exit(1)

    if not wepath:
        wepath = QFileDialog.getExistingDirectory(
            None, "选择 Wallpaper Engine 主目录（…\\SteamLibrary\\steamapps\\common\\wallpaper_engine）", ""
        )
        if not wepath:
            QMessageBox.critical(None, "错误", "未选择 Wallpaper Engine 目录，将退出程序。")
            sys.exit(1)

    if not os.path.isdir(workshop):
        QMessageBox.critical(None, "错误", f"创意工坊目录无效：{workshop}")
        sys.exit(1)
    if not os.path.isdir(wepath):
        QMessageBox.critical(None, "错误", f"Wallpaper Engine 目录无效：{wepath}")
        sys.exit(1)

    write_config_txt(workshop, wepath)

    win = MainWindow(workshop, wepath)
    win.resize(1100, 680)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()