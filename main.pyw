import os
import json
import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QGridLayout, QWidget, QLabel, QFrame, QScrollArea, \
    QComboBox, QFileDialog, QMessageBox, QPushButton, QHBoxLayout, QLineEdit, QCheckBox
from PySide6.QtGui import QPainter, QPalette, QColor, QMovie, QFont
from PySide6.QtCore import Qt, QSize, QTimer


class VideoPreviewWindow(QFrame):
    def __init__(self, title, preview_path, video_path):
        super().__init__()
        self.setFixedSize(180, 180)  # 调整窗口大小
        self.video_path = video_path
        self.preview_path = preview_path  # 保存预览路径以便于绘制

        layout = QVBoxLayout(self)

        label = QLabel(title)
        label.setAlignment(Qt.AlignCenter)

        # 设置字体颜色为白色
        palette = label.palette()
        palette.setColor(QPalette.WindowText, QColor('white'))  # 设置字体颜色
        label.setWordWrap(True)  # 让字体自动换行
        label.setPalette(palette)

        layout.addStretch()  # 使标签在垂直方向上居中
        layout.addWidget(label)
        self.setLayout(layout)

        # 创建一个 QFont 对象并设置字体大小
        font = QFont()
        font.setPointSize(8)  # 设置字体大小为 8（可以根据需要调整这个数值）
        label.setFont(font)  # 应用字体到标签

        # 初始化 QMovie
        self.movie = QMovie(self.preview_path)  # 使用 QMovie 而不是 QPixmap
        self.movie.setScaledSize(QSize(180, 180))  # 设置显示的大小
        self.movie.start()  # 开始播放 GIF

        # 设置定时器更新 GIF 动画
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)  # 每隔一段时间调用 update
        self.timer.start(1000 // 30)  # 设定更新频率（例如每秒 30 帧）

    def paintEvent(self, event):
        # 绘制 GIF 动画
        painter = QPainter(self)
        if self.movie.isValid():  # 确保 QMovie 是有效的
            painter.drawPixmap(self.rect(), self.movie.currentPixmap())  # 获取当前帧并绘制

        # 获取 QLabel 的高度和 y 坐标
        label = self.findChild(QLabel)
        label_height = label.height() + 20

        # 计算黑色矩形的 y 坐标，使其与 QLabel 在底部对齐
        rect_y = self.height() - label_height

        # 绘制带透明度的黑色矩形，调整位置和高度以匹配 QLabel
        painter.setBrush(QColor(0, 0, 0, 100))  # 设置黑色并设定透明度
        painter.setPen(Qt.NoPen)  # 禁用边框
        painter.drawRect(0, rect_y, self.width(), label_height)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:  # 左键双击
            os.startfile(self.video_path)  # 用默认方式打开视频
        elif event.button() == Qt.RightButton:  # 右键双击
            folder_path = os.path.dirname(self.video_path)  # 获取视频文件夹路径
            os.startfile(folder_path)  # 打开文件夹


class MainWindow(QMainWindow):
    def __init__(self, base_dir):
        super().__init__()
        self.setWindowTitle("Wallpaper视频预览")
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        # 创建 QScrollArea
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("border: none;")  # 设置为无边框

        self.layout = QVBoxLayout(central_widget)
        self.layout.addWidget(self.scroll_area)

        # 分页变量
        self.columns = 5
        self.page_size = 45  # 每页显示的视频预览个数
        self.current_page = 0
        self.video_info_list = []

        # 创建分页控件的布局
        self.pagination_layout = QHBoxLayout()  # 使用 QHBoxLayout 创建水平布局
        self.sort_combo = QComboBox(self)
        self.sort_combo.addItems(
            ["修改日期降序", "修改日期升序", "文件大小降序", "文件大小升序", "文件名降序", "文件名升序"])
        self.sort_combo.currentIndexChanged.connect(lambda: self.load_videos(base_dir))  # 确保scope中有base_dir

        self.pagination_layout.addWidget(self.sort_combo)  # 添加排序选择框

        self.prev_button = QPushButton("上一页")
        self.next_button = QPushButton("下一页")
        self.prev_button.clicked.connect(self.previous_page)
        self.next_button.clicked.connect(self.next_page)

        self.pagination_layout.addWidget(self.prev_button)
        self.pagination_layout.addWidget(self.next_button)

        # 当前页数显示
        self.page_info_label = QLabel(self)
        self.pagination_layout.addWidget(self.page_info_label)

        # 添加输入框用于跳转页码
        self.page_input = QLineEdit(self)  # 创建输入框
        self.page_input.setPlaceholderText("输入页码")  # 设置占位符文本
        self.page_input.setFixedWidth(100)  # 设置固定宽度
        self.pagination_layout.addWidget(self.page_input)  # 将输入框添加到分页布局中
        self.page_input.returnPressed.connect(self.jump_to_page)  # 连接输入框的信号

        self.layout.addLayout(self.pagination_layout)  # 将分页控件的布局添加到主布局中

        # 在 MainWindow 的初始化方法内添加复选框
        self.rating_check = QCheckBox("只显示成人内容", self)  # 创建复选框
        self.pagination_layout.addWidget(self.rating_check)  # 将复选框添加到分页控件的布局中
        self.rating_check.stateChanged.connect(lambda: self.load_videos(base_dir))  # 连接状态变化信号


        # 创建内容区域
        self.content_widget = QWidget()
        self.scroll_area.setWidget(self.content_widget)

        self.grid_layout = QGridLayout(self.content_widget)
        self.content_widget.setLayout(self.grid_layout)

        # 遍历目录
        self.load_videos(base_dir)

    def load_videos(self, base_dir):
        self.video_info_list.clear()  # 清空之前的视频信息
        for folder_name in os.listdir(base_dir):
            folder_path = os.path.join(base_dir, folder_name)
            if os.path.isdir(folder_path):
                project_file = os.path.join(folder_path, "project.json")
                if os.path.exists(project_file):
                    with open(project_file, 'r', encoding='utf-8') as f:
                        project_data = json.load(f)
                        title = project_data.get("title", "未命名")
                        preview_file = project_data.get("preview", "")
                        video_file = project_data.get("file", "")
                        video_type = project_data.get("type", "")  # 获取类型
                        content_rating = project_data.get("contentrating", "")  # 获取内容评级

                        # 只显示 type 为 "video" 的视频
                        if video_type.lower() != "video":
                            continue

                        # 如果复选框被选中，检查 contentrating
                        if self.rating_check.isChecked() and content_rating != "Mature":
                            continue

                        # 预览文件和视频文件的完整路径
                        preview_path = os.path.join(folder_path, preview_file)
                        video_path = os.path.join(folder_path, video_file)

                        # 确保文件存在
                        if os.path.exists(preview_path) and os.path.exists(video_path):
                            # 获取文件修改日期和大小
                            modify_time = os.path.getmtime(video_path)
                            file_size = os.path.getsize(video_path)

                            # 将这些信息存储到列表中
                            self.video_info_list.append((title, preview_path, video_path, modify_time, file_size))

        self.sort_videos()  # 调用排序方法
        self.update_display()

    def sort_videos(self):
        sort_option = self.sort_combo.currentIndex()
        if sort_option == 0:  # 修改日期降序
            self.video_info_list.sort(key=lambda x: x[3], reverse=True)
        elif sort_option == 1:  # 修改日期升序
            self.video_info_list.sort(key=lambda x: x[3])
        elif sort_option == 2:  # 文件大小降序
            self.video_info_list.sort(key=lambda x: x[4], reverse=True)
        elif sort_option == 3:  # 文件大小升序
            self.video_info_list.sort(key=lambda x: x[4])
        elif sort_option == 4:  # 文件名降序
            self.video_info_list.sort(key=lambda x: x[0], reverse=True)
        elif sort_option == 5:  # 文件名升序
            self.video_info_list.sort(key=lambda x: x[0])

    def update_display(self):
        # 清空布局并添加新的视频预览窗口
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget() is not None:
                child.widget().deleteLater()

        start_index = self.current_page * self.page_size
        end_index = start_index + self.page_size
        current_page_videos = self.video_info_list[start_index:end_index]

        row = 0
        for title, preview_path, video_path, modify_time, file_size in current_page_videos:
            video_preview = VideoPreviewWindow(title, preview_path, video_path)
            self.grid_layout.addWidget(video_preview, row, self.grid_layout.count() % self.columns)

            if (self.grid_layout.count() % self.columns) == 0:
                row += 1

        # 更新按钮的可用状态
        self.prev_button.setEnabled(self.current_page > 0)
        self.next_button.setEnabled(end_index < len(self.video_info_list))

        # 更新当前页数显示
        total_pages = (len(self.video_info_list) + self.page_size - 1) // self.page_size  # 计算总页数
        self.page_info_label.setText(f"当前页: {self.current_page + 1} / {total_pages}")  # 显示当前页和总页数

    def next_page(self):
        if (self.current_page + 1) * self.page_size < len(self.video_info_list):
            self.current_page += 1
            self.update_display()
            self.scroll_area.verticalScrollBar().setValue(0)  # 设置滚动条到顶部

    def previous_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_display()
            self.scroll_area.verticalScrollBar().setValue(0)  # 设置滚动条到顶部

    def jump_to_page(self):
        try:
            page_number = int(self.page_input.text())  # 获取输入的页码
            total_pages = (len(self.video_info_list) + self.page_size - 1) // self.page_size  # 计算总页数

            if 1 <= page_number <= total_pages:  # 检查页码是否合法
                self.current_page = page_number - 1  # 更新当前页
                self.update_display()  # 更新显示
            else:
                QMessageBox.warning(self, "警告", "请输入有效的页码。")  # 弹出警告框

        except ValueError:
            QMessageBox.warning(self, "警告", "请输入数字。")  # 弹出警告框


def read_config():
    """从 config.txt 中读取配置"""
    try:
        with open('config.txt', 'r', encoding='utf-8') as f:
            config = {}
            for line in f.readlines():
                key, value = line.strip().split(': ', 1)
                config[key] = value.strip().strip("'")  # 去掉首尾单引号
            return config.get('file_path', None)
    except FileNotFoundError:
        return None


def write_config(file_path):
    """将文件路径写入 config.txt"""
    with open('config.txt', 'w', encoding='utf-8') as f:
        f.write(f"file_path: '{file_path}'\n")


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 从 config.txt 中读取 base_directory
    base_directory = read_config()

    if not base_directory:  # 如果没有读取到路径，弹出选择窗口
        base_directory = QFileDialog.getExistingDirectory(None, "选择文件夹", "")
        if base_directory:  # 如果用户选择了路径
            write_config(base_directory)  # 将选择的路径写入 config.txt
        else:
            QMessageBox.critical(None, "错误", "未选择任何路径，将退出程序。")
            sys.exit(1)  # 如果没有选择路径，退出程序

    window = MainWindow(base_directory)
    window.resize(985, 612)
    window.show()
    sys.exit(app.exec())
