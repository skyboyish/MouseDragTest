# -*- coding: utf-8 -*-
import sys
import math
import time
import os
import csv
import numpy as np
from PyQt5 import QtWidgets, QtGui, QtCore


def get_all_dist_record_path():
    """获取汇总CSV文件路径"""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
    else:
        exe_dir = os.path.dirname(os.path.abspath(__file__))
    csv_dir = os.path.join(exe_dir, "mouse_drag_record")
    os.makedirs(csv_dir, exist_ok=True)
    return os.path.join(csv_dir, "all_dist_record.csv")


def ensure_all_dist_record_header():
    """确保汇总CSV文件存在且格式正确（有表头）"""
    csv_path = get_all_dist_record_path()
    if not os.path.exists(csv_path):
        # 文件不存在，创建并写入表头
        try:
            with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['序号', '时间', '鼠标延迟(毫秒)', '距离均值', '平滑度', '备注', '详细数据'])
                writer.writeheader()
        except Exception:
            pass


def read_all_dist_record():
    """读取汇总CSV，返回列表[{'序号', '时间', '鼠标延迟(毫秒)', '距离均值', '平滑度', '备注', '详细数据'}, ...]"""
    csv_path = get_all_dist_record_path()
    if not os.path.exists(csv_path):
        return []
    try:
        import csv
        records = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(row)
        return records
    except Exception:
        return []


def write_all_dist_record(time_str, mean_val, std_val, detail_csv_path, remark=""):
    """追加一条记录到汇总CSV"""
    import csv as csv_module
    csv_path = get_all_dist_record_path()

    # 确保文件存在且有正确的表头
    ensure_all_dist_record_header()

    # 读取现有记录数来计算序号
    records = read_all_dist_record()
    seq_num = len(records) + 1

    try:
        with open(csv_path, 'a', encoding='utf-8', newline='') as f:
            writer = csv_module.DictWriter(f, fieldnames=['序号', '时间', '鼠标延迟(毫秒)', '距离均值', '平滑度', '备注', '详细数据'])
            writer.writerow({
                '序号': seq_num,
                '时间': time_str,
                '鼠标延迟(毫秒)': f"{mean_val * 2.34:.2f}",
                '距离均值': f"{mean_val:.2f}",
                '平滑度': f"{std_val:.2f}",
                '备注': remark,
                '详细数据': detail_csv_path
            })
        return seq_num
    except Exception:
        return None


def update_record_remark(seq_num, remark):
    """更新指定序号（1-based）的备注"""
    csv_path = get_all_dist_record_path()
    if not os.path.exists(csv_path):
        return False
    try:
        import csv
        records = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(row)

        # 找到对应记录并更新
        for i, row in enumerate(records):
            if int(row['序号']) == seq_num:
                records[i]['备注'] = remark
                break

        # 重新写入
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['序号', '时间', '鼠标延迟(毫秒)', '距离均值', '平滑度', '备注', '详细数据'])
            writer.writeheader()
            writer.writerows(records)
        return True
    except Exception:
        return False


def capture_screen_region(x, y, w, h):
    """
    截取指定屏幕区域（支持多屏）。
    使用 mss 库，支持多显示器、负坐标。
    返回 HxWx3 numpy array (RGB)，或 None。
    """
    try:
        import mss
        with mss.mss() as sct:
            monitor = {
                "left": int(x),
                "top": int(y),
                "width": int(w),
                "height": int(h)
            }
            sct_img = sct.grab(monitor)
            arr = np.array(sct_img)
            if arr.size == 0:
                return None
            # BGRA -> RGB，不翻转（mss 的 y 轴和屏幕坐标一致）
            rgb = arr[:, :, :3]
            return rgb
    except Exception as e:
        return None


def detect_one_dot(region, threshold=60, min_area=5):
    """检测黑点质心，返回 (sx+x, sy+y) 或 None。"""
    if region is None:
        return None
    gray = np.mean(region, axis=2)
    binary = (gray < threshold).astype(np.uint8) * 255
    try:
        import cv2
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    except Exception:
        return None
    if not contours:
        return None
    areas = [cv2.contourArea(c) for c in contours]
    if not areas:
        return None
    idx = np.argmax(areas)
    m = cv2.moments(contours[idx])
    if m['m00'] <= 0:
        return None
    cx = float(m['m10'] / m['m00'])
    cy = float(m['m01'] / m['m00'])
    return (cx, cy)  # 相对于检测区域左上角


class StatsThread(QtCore.QThread):
    """独立的统计线程，不影响画圈速度"""
    # 信号：距离记录 (distance, dot_x, dot_y, mouse_x, mouse_y)
    distance_recorded = QtCore.pyqtSignal(float, float, float, float, float)

    def __init__(self):
        super().__init__()
        self.running = False
        self.lock = QtCore.QMutex()
        self.stats_interval_ms = 100  # 统计间隔

        # 检测区域参数
        self.sx = 0
        self.sy = 0
        self.w = 500
        self.h = 500
        self.threshold = 60
        self.min_area = 5

        # CSV相关
        self.csv_path = None
        self.csv_index = 0

    def configure(self, sx, sy, w, h, threshold, min_area, stats_interval_ms):
        """从主线程更新配置"""
        self.sx = sx
        self.sy = sy
        self.w = w
        self.h = h
        self.threshold = threshold
        self.min_area = min_area
        self.stats_interval_ms = stats_interval_ms

    def set_csv(self, path):
        """设置CSV文件路径"""
        self.csv_path = path
        self.csv_index = 0

    def start_stats(self):
        """启动统计"""
        self.lock.lock()
        self.running = True
        self.lock.unlock()
        if not self.isRunning():
            self.start()

    def stop_stats(self):
        """停止统计"""
        self.lock.lock()
        self.running = False
        self.lock.unlock()
        self.wait()

    def run(self):
        """统计线程主循环，独立于画圈定时器"""
        import mss
        import cv2

        with mss.mss() as sct:
            while True:
                # 检查是否停止
                self.lock.lock()
                if not self.running:
                    self.lock.unlock()
                    break
                self.lock.unlock()

                # 执行截图和检测
                monitor = {"left": int(self.sx), "top": int(self.sy), "width": int(self.w), "height": int(self.h)}
                try:
                    sct_img = sct.grab(monitor)
                    arr = np.array(sct_img)
                    if arr.size == 0:
                        time.sleep(self.stats_interval_ms / 1000.0)
                        continue
                    rgb = arr[:, :, :3]
                except Exception:
                    time.sleep(self.stats_interval_ms / 1000.0)
                    continue

                # 检测黑点
                gray = np.mean(rgb, axis=2)
                binary = (gray < self.threshold).astype(np.uint8) * 255
                try:
                    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                except Exception:
                    time.sleep(self.stats_interval_ms / 1000.0)
                    continue

                if not contours:
                    time.sleep(self.stats_interval_ms / 1000.0)
                    continue

                areas = [cv2.contourArea(c) for c in contours]
                if not areas:
                    time.sleep(self.stats_interval_ms / 1000.0)
                    continue

                idx = np.argmax(areas)
                m = cv2.moments(contours[idx])
                if m['m00'] <= 0:
                    time.sleep(self.stats_interval_ms / 1000.0)
                    continue

                cx = float(m['m10'] / m['m00'])
                cy = float(m['m01'] / m['m00'])
                dot_x = self.sx + cx
                dot_y = self.sy + cy

                # 检测完成后立即获取鼠标坐标（时间差最小）
                mouse_pos = QtGui.QCursor.pos()
                mouse_x, mouse_y = mouse_pos.x(), mouse_pos.y()

                # 计算距离（用鼠标当前位置和检测到的黑点位置）
                dist = math.sqrt((mouse_x - dot_x) ** 2 + (mouse_y - dot_y) ** 2)

                # 发送信号到主线程
                self.distance_recorded.emit(dist, dot_x, dot_y, mouse_x, mouse_y)

                # 写入CSV（如果开启了）
                if self.csv_path is not None:
                    try:
                        with open(self.csv_path, 'a', encoding='utf-8') as f:
                            f.write(f"{self.csv_index},{self.csv_index},{mouse_x},{mouse_y},{dot_x},{dot_y},{dist:.2f}\n")
                        self.csv_index += 1
                    except Exception:
                        pass

                # 按自己的间隔休眠（不受主线程影响）
                time.sleep(self.stats_interval_ms / 1000.0)


class RubberBand(QtWidgets.QWidget):
    """覆盖全屏（支持多屏）的橡皮筋选择框，固定500x500正方形。"""
    selected = QtCore.pyqtSignal(QtCore.QRect)
    SQUARE_SIZE = 500  # 固定正方形边长

    def __init__(self):
        super().__init__(None)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint
        )
        self.setMouseTracking(True)
        self.setCursor(QtCore.Qt.CrossCursor)

        # 覆盖整个虚拟桌面
        desktop = QtWidgets.QApplication.desktop()
        self.setGeometry(desktop.geometry())

        # 窗口整体 15% 透明度，便于透视
        self.setWindowOpacity(0.15)

        self.start_pos = None
        self.rb_rect = QtCore.QRect()

        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def paintEvent(self, e):
        qp = QtGui.QPainter(self)
        qp.setRenderHint(QtGui.QPainter.Antialiasing)

        if self.rb_rect.isValid():
            # 选区区域：完全透明（清除父窗口的半透明）
            qp.setCompositionMode(QtGui.QPainter.CompositionMode_Clear)
            qp.fillRect(self.rb_rect, QtCore.Qt.transparent)
            qp.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)

            # 红框
            qp.setPen(QtGui.QPen(QtCore.Qt.red, 3))
            qp.setBrush(QtCore.Qt.NoBrush)
            qp.drawRect(self.rb_rect)

            # 尺寸标签（不透明背景）
            half = self.SQUARE_SIZE // 2
            label_rect = QtCore.QRect(self.rb_rect.x(), self.rb_rect.y() - 26,
                                     max(150, self.SQUARE_SIZE + 10), 22)
            qp.fillRect(label_rect, QtGui.QColor(0, 0, 0, 240))
            qp.setPen(QtGui.QPen(QtCore.Qt.white, 1))
            qp.drawText(label_rect.adjusted(8, 2, 0, 0),
                        QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                        f"{self.SQUARE_SIZE} x {self.SQUARE_SIZE}")

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.start_pos = e.globalPos()
            # 以点击位置为中心，创建500x500正方形
            self._update_rect(self.start_pos)
            self.update()

    def mouseMoveEvent(self, e):
        if self.start_pos is not None:
            # 移动时，以当前鼠标位置为中心更新区域
            self._update_rect(e.globalPos())
            self.update()

    def _update_rect(self, center_pos):
        """以给定位置为中心更新正方形区域。"""
        half = self.SQUARE_SIZE // 2
        self.rb_rect = QtCore.QRect(
            center_pos.x() - half,
            center_pos.y() - half,
            self.SQUARE_SIZE,
            self.SQUARE_SIZE
        )

    def mouseReleaseEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton and self.rb_rect.isValid():
            # 释放时，以最终位置为中心确认区域
            self._update_rect(e.globalPos())
            self.selected.emit(self.rb_rect.normalized())
        self.close()

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Escape:
            self.close()


class DistToolWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("鼠标跟手度测试")
        self.setGeometry(150, 150, 700, 360)

        # 有边框普通窗口，支持拖动
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Window)
        self.setStyleSheet(self._styleSheet())

        self.measure_timer = QtCore.QTimer()
        self.measure_timer.timeout.connect(self._do_measure)
        self.interval_ms = 200
        self.running = False
        self.last_dist = None
        self.select_mode = False

        # 独立统计线程（不影响画圈速度）
        self.stats_thread = StatsThread()
        self.stats_thread.distance_recorded.connect(self._on_stats_recorded)

        # 间隔置顶窗口定时器
        self.topmost_timer = QtCore.QTimer()
        self.topmost_timer.timeout.connect(self._raise_window)

        self._build_ui()

        # 置顶复选框的信号连接（需在_build_ui之后，widget已创建）
        self.topmost_check.stateChanged.connect(self._on_topmost_changed)

    def _styleSheet(self):
        return """
            QMainWindow { background-color: #f0f0f0; }
            QLabel { color: #222; }
            QGroupBox { font-weight: bold; color: #333; }
            QSpinBox, QLineEdit {
                background: white;
                border: 1px solid #bbb;
                border-radius: 3px;
                padding: 2px 4px;
            }
            QSlider::groove:horizontal {
                border: 1px solid #bbb;
                height: 6px;
                border-radius: 3px;
                background: #ddd;
            }
            QSlider::handle:horizontal {
                background: #2196F3;
                width: 14px;
                margin: -4px 0;
                border-radius: 3px;
            }
            QPushButton {
                background: #e0e0e0;
                border: 1px solid #bbb;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover { background: #d0d0d0; }
            QPushButton:pressed { background: #c0c0c0; }
            QPushButton[role="primary"] {
                background: #1976D2;
                color: white;
                border: none;
            }
            QPushButton[role="primary"]:hover { background: #1565C0; }
            QPushButton[role="danger"] {
                background: #d32f2f;
                color: white;
                border: none;
            }
            QPushButton[role="danger"]:hover { background: #c62828; }
            QPushButton[role="select"] {
                background: #ef6c00;
                color: white;
                border: none;
                font-weight: bold;
            }
            QPushButton[role="select"]:hover { background: #e65100; }
            QPushButton[role="select_active"] {
                background: #2e7d32;
                color: white;
                border: none;
                font-weight: bold;
            }
            QPushButton[role="select_active"]:hover { background: #1b5e20; }
            #resultBox { background: white; border: 1px solid #ccc; border-radius: 6px; }
            #distLabel { font-size: 42px; font-weight: bold; color: #1565C0; }
        """

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setSpacing(8)

        # =========================================================
        # 公共配置（最顶部）
        # =========================================================
        common_section = QtWidgets.QGroupBox("检测区域配置")
        common_section.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                color: #555;
                border: 1px solid #bbb;
                border-radius: 4px;
                margin-top: 4px;
                padding-top: 4px;
                background-color: #fafafa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 2px;
            }
        """)
        common_layout = QtWidgets.QVBoxLayout(common_section)
        common_layout.setSpacing(6)

        # 检测区域行1：框选区域 + 预览按钮（单独一行）
        region_row1 = QtWidgets.QHBoxLayout()
        self.select_btn = QtWidgets.QPushButton("选择测试区域")
        self.select_btn.setProperty("role", "select")
        self.select_btn.setToolTip("在屏幕上拖动画出检测区域")
        self.select_btn.clicked.connect(self._enter_select_mode)
        region_row1.addWidget(self.select_btn)

        self.preview_btn = QtWidgets.QPushButton("预览")
        self.preview_btn.setToolTip("预览当前选择的检测区域（显示2秒后自动消失）")
        self.preview_btn.clicked.connect(self._preview_region)
        region_row1.addWidget(self.preview_btn)
        # 隐藏：预览按钮功能有问题，后续再放开
        self.preview_btn.setVisible(False)
        region_row1.addStretch()

        # 高级配置开关
        self.show_advanced_check = QtWidgets.QCheckBox("显示检测区域配置")
        self.show_advanced_check.setChecked(False)
        self.show_advanced_check.stateChanged.connect(self._toggle_advanced_config)
        region_row1.addWidget(self.show_advanced_check)
        common_layout.addLayout(region_row1)

        # 高级配置容器（默认隐藏）
        self.advanced_container = QtWidgets.QWidget()
        advanced_vbox = QtWidgets.QVBoxLayout(self.advanced_container)
        advanced_vbox.setContentsMargins(0, 4, 0, 4)
        advanced_vbox.setSpacing(4)

        # 检测区域行2：坐标
        region_row2 = QtWidgets.QHBoxLayout()
        for lbl, key, default in [("X", "sx", 0), ("Y", "sy", 0), ("W", "sw", 500), ("H", "sh", 500)]:
            region_row2.addWidget(QtWidgets.QLabel(f"{lbl}:"))
            spin = QtWidgets.QSpinBox()
            spin.setRange(0, 9999)
            spin.setValue(default)
            spin.setMaximumWidth(72)
            spin.valueChanged.connect(self._on_region_change)
            setattr(self, f"{key}_spin", spin)
            region_row2.addWidget(spin)
        region_row2.addStretch()
        advanced_vbox.addLayout(region_row2)

        # 公共参数行
        param_row = QtWidgets.QHBoxLayout()
        param_row.addWidget(QtWidgets.QLabel("黑点阈值:"))
        self.threshold_spin = QtWidgets.QSpinBox()
        self.threshold_spin.setRange(1, 200)
        self.threshold_spin.setValue(60)
        self.threshold_spin.setMaximumWidth(65)
        self.threshold_spin.setToolTip("RGB均值小于此值视为黑点")
        param_row.addWidget(self.threshold_spin)

        param_row.addSpacing(6)
        param_row.addWidget(QtWidgets.QLabel("最小面积:"))
        self.min_area_spin = QtWidgets.QSpinBox()
        self.min_area_spin.setRange(1, 1000)
        self.min_area_spin.setValue(5)
        self.min_area_spin.setMaximumWidth(65)
        param_row.addWidget(self.min_area_spin)

        param_row.addStretch()
        advanced_vbox.addLayout(param_row)

        self.advanced_container.setVisible(False)
        common_layout.addWidget(self.advanced_container)

        layout.addWidget(common_section)

        # =========================================================
        # 区域1：跟手度测试
        # =========================================================
        circle_section = QtWidgets.QGroupBox("自动测试")
        circle_section.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                color: #1565C0;
                border: 2px solid #1976D2;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
                background-color: #f5f9ff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }
        """)
        circle_layout = QtWidgets.QVBoxLayout(circle_section)
        circle_layout.setSpacing(6)

        # 画圈参数行1：鼠标运行模型（速度+点数）
        circle_param_row1 = QtWidgets.QHBoxLayout()
        circle_param_row1.addWidget(QtWidgets.QLabel("鼠标运行模型:"))
        circle_param_row1.addSpacing(6)
        circle_param_row1.addWidget(QtWidgets.QLabel("速度:"))
        self.circle_speed_spin = QtWidgets.QSpinBox()
        self.circle_speed_spin.setRange(1, 100)
        self.circle_speed_spin.setValue(30)
        self.circle_speed_spin.setMaximumWidth(60)
        self.circle_speed_spin.setToolTip("数值越小越慢")
        circle_param_row1.addWidget(self.circle_speed_spin)

        circle_param_row1.addSpacing(6)
        circle_param_row1.addWidget(QtWidgets.QLabel("点数:"))
        self.circle_points_spin = QtWidgets.QSpinBox()
        self.circle_points_spin.setRange(8, 3000)
        self.circle_points_spin.setValue(1200)
        self.circle_points_spin.setMaximumWidth(60)
        self.circle_points_spin.setToolTip("点数越多圆越平滑")
        circle_param_row1.addWidget(self.circle_points_spin)
        circle_param_row1.addStretch()

        # 画圈参数行2：按次数/按时间
        circle_param_row2 = QtWidgets.QHBoxLayout()
        # 模式选择：按次数 vs 按时间
        self.circle_mode_group = QtWidgets.QButtonGroup(circle_section)
        self.circle_mode_count = QtWidgets.QRadioButton("按次数")
        self.circle_mode_count.setChecked(True)
        self.circle_mode_time = QtWidgets.QRadioButton("按时间")
        self.circle_mode_group.addButton(self.circle_mode_count)
        self.circle_mode_group.addButton(self.circle_mode_time)
        self.circle_mode_count.toggled.connect(self._on_circle_mode_changed)
        circle_param_row2.addWidget(self.circle_mode_count)
        circle_param_row2.addWidget(self.circle_mode_time)

        circle_param_row2.addSpacing(10)
        circle_param_row2.addWidget(QtWidgets.QLabel("次数:"))
        self.circle_count_spin = QtWidgets.QSpinBox()
        self.circle_count_spin.setRange(1, 9999)
        self.circle_count_spin.setValue(10)
        self.circle_count_spin.setMaximumWidth(60)
        self.circle_count_spin.setToolTip("画圈次数")
        circle_param_row2.addWidget(self.circle_count_spin)

        circle_param_row2.addSpacing(6)
        circle_param_row2.addWidget(QtWidgets.QLabel("时间(秒):"))
        self.circle_duration_spin = QtWidgets.QSpinBox()
        self.circle_duration_spin.setRange(1, 3600)
        self.circle_duration_spin.setValue(10)
        self.circle_duration_spin.setMaximumWidth(70)
        self.circle_duration_spin.setSuffix(" s")
        self.circle_duration_spin.setToolTip("画圈时长(秒)")
        self.circle_duration_spin.setEnabled(False)
        circle_param_row2.addWidget(self.circle_duration_spin)
        circle_param_row2.addStretch()

        # 画圈参数行3：统计选项
        circle_param_row3 = QtWidgets.QHBoxLayout()
        # 统计选项
        self.enable_mean_check = QtWidgets.QCheckBox("统计均值")
        self.enable_mean_check.setChecked(True)
        self.enable_mean_check.setToolTip("启用后记录画圈过程中的距离均值")
        circle_param_row3.addWidget(self.enable_mean_check)

        self.csv_record_check = QtWidgets.QCheckBox("CSV记录")
        self.csv_record_check.setChecked(True)
        self.csv_record_check.setToolTip("记录坐标到CSV，画圈结束后计算均值")
        circle_param_row3.addWidget(self.csv_record_check)

        self.multi_thread_check = QtWidgets.QCheckBox("多线程统计")
        self.multi_thread_check.setChecked(True)
        self.multi_thread_check.setToolTip("开启后统计在独立线程执行，画圈速度不受影响")
        circle_param_row3.addWidget(self.multi_thread_check)
        self.multi_thread_check.setVisible(False)

        circle_param_row3.addSpacing(6)
        circle_param_row3.addWidget(QtWidgets.QLabel("统计间隔:"))
        self.stats_interval_spin = QtWidgets.QSpinBox()
        self.stats_interval_spin.setRange(50, 1000)
        self.stats_interval_spin.setValue(50)
        self.stats_interval_spin.setMaximumWidth(60)
        self.stats_interval_spin.setSuffix(" ms")
        self.stats_interval_spin.setToolTip("多线程模式下的统计间隔")
        circle_param_row3.addWidget(self.stats_interval_spin)
        circle_param_row3.addStretch()

        # 画圈操作按钮
        circle_btn_row = QtWidgets.QHBoxLayout()
        self.draw_circle_btn = QtWidgets.QPushButton("开始测试")
        self.draw_circle_btn.setProperty("role", "primary")
        self.draw_circle_btn.setMinimumHeight(32)
        self.draw_circle_btn.setToolTip("在框选区域内模拟鼠标画圆")
        self.draw_circle_btn.clicked.connect(self._draw_circle)
        circle_btn_row.addWidget(self.draw_circle_btn)

        self.stop_circle_btn = QtWidgets.QPushButton("按Esc键停止测试")
        self.stop_circle_btn.setProperty("role", "danger")
        self.stop_circle_btn.setMinimumHeight(32)
        self.stop_circle_btn.setToolTip("停止画圈")
        self.stop_circle_btn.clicked.connect(lambda: self._stop_circle("画圈已停止"))
        circle_btn_row.addWidget(self.stop_circle_btn)

        self.topmost_check = QtWidgets.QCheckBox("间隔置顶窗口")
        self.topmost_check.setToolTip("勾选后每隔5秒自动将当前窗口置顶，防止被其他窗口遮挡")
        self.topmost_check.setChecked(False)
        circle_btn_row.addWidget(self.topmost_check)

        self.auto_calibrate_check = QtWidgets.QCheckBox("自动校准模型")
        self.auto_calibrate_check.setToolTip("勾选后开始测试前先自动校准画圈快慢（以单圈耗时接近3600ms为标准调整点数），校准完成后再正式开始距离统计")
        self.auto_calibrate_check.setChecked(True)
        circle_btn_row.addWidget(self.auto_calibrate_check)

        circle_btn_row.addStretch()

        # 鼠标延迟显示（暂时位于最下方）
        circle_delay_row = QtWidgets.QHBoxLayout()
        self.circle_delay_title = QtWidgets.QLabel("鼠标延迟(毫秒):")
        circle_delay_row.addWidget(self.circle_delay_title)
        self.circle_delay_label = QtWidgets.QLabel("--")
        self.circle_delay_label.setStyleSheet("font-size: 48px; font-weight: bold; color: #1565C0;")
        self.circle_delay_label.setMinimumWidth(150)
        self.circle_delay_label.setAlignment(QtCore.Qt.AlignLeft)
        circle_delay_row.addWidget(self.circle_delay_label)
        circle_delay_row.addStretch()

        # 画圈结果显示 - 第1行：距离均值 + 平滑度 + 完成倒计时 + 状态
        circle_result_row1 = QtWidgets.QHBoxLayout()
        circle_result_row1.addWidget(QtWidgets.QLabel("距离均值:"))
        self.circle_mean_label = QtWidgets.QLabel("--")
        self.circle_mean_label.setStyleSheet("font-size: 48px; font-weight: bold; color: #0D47A1;")
        self.circle_mean_label.setMinimumWidth(150)
        self.circle_mean_label.setAlignment(QtCore.Qt.AlignLeft)
        circle_result_row1.addWidget(self.circle_mean_label)

        circle_result_row1.addSpacing(20)
        circle_result_row1.addWidget(QtWidgets.QLabel("平滑度:"))
        self.circle_std_label = QtWidgets.QLabel("--")
        self.circle_std_label.setStyleSheet("font-size: 48px; font-weight: bold; color: #0D47A1;")
        self.circle_std_label.setMinimumWidth(150)
        self.circle_std_label.setAlignment(QtCore.Qt.AlignLeft)
        circle_result_row1.addWidget(self.circle_std_label)

        circle_result_row1.addSpacing(20)
        circle_result_row1.addWidget(QtWidgets.QLabel("完成倒计时:"))
        self.circle_countdown_label = QtWidgets.QLabel("--")
        self.circle_countdown_label.setStyleSheet("font-size: 48px; font-weight: bold; color: #d32f2f;")
        self.circle_countdown_label.setMinimumWidth(100)
        self.circle_countdown_label.setAlignment(QtCore.Qt.AlignLeft)
        circle_result_row1.addWidget(self.circle_countdown_label)

        circle_result_row1.addStretch()
        # 状态标签
        self.circle_status_label = QtWidgets.QLabel("状态: 就绪")
        self.circle_status_label.setStyleSheet("color: #888; font-size: 12px;")
        circle_result_row1.addWidget(self.circle_status_label)

        # 画圈结果显示 - 第2行：距离长度示意图
        self.circle_mean_line_hbox = QtWidgets.QHBoxLayout()
        self.circle_mean_line_hbox.addSpacing(0)
        self.circle_mean_line_hbox.addWidget(QtWidgets.QLabel("距离长度示意:"))
        self.circle_mean_line = QtWidgets.QLabel()
        self.circle_mean_line.setFixedHeight(4)
        self.circle_mean_line.setFixedWidth(0)
        self.circle_mean_line.setStyleSheet("background-color: #0D47A1; border-radius: 2px;")
        self.circle_mean_line.setVisible(False)
        self.circle_mean_line_hbox.addWidget(self.circle_mean_line)
        self.circle_mean_line_hbox.addStretch()

        # 画圈结果显示 - 第3行：已画圈数 | 单圈耗时 | 均值 | 采样次数 | 瞬时距离
        circle_result_row3 = QtWidgets.QHBoxLayout()
        self.circle_count_label = QtWidgets.QLabel("已画圈数: 0")
        self.circle_count_label.setStyleSheet("font-size: 14px; color: #555;")
        circle_result_row3.addWidget(self.circle_count_label)

        circle_result_row3.addSpacing(10)
        self.circle_time_label = QtWidgets.QLabel("单圈耗时: --")
        self.circle_time_label.setStyleSheet("font-size: 14px; color: #555;")
        circle_result_row3.addWidget(self.circle_time_label)

        circle_result_row3.addSpacing(10)
        self.circle_mean_info_label = QtWidgets.QLabel("均值: --")
        self.circle_mean_info_label.setStyleSheet("font-size: 14px; color: #555;")
        circle_result_row3.addWidget(self.circle_mean_info_label)

        circle_result_row3.addSpacing(10)
        self.circle_record_count_label = QtWidgets.QLabel("采样次数: 0")
        self.circle_record_count_label.setStyleSheet("font-size: 14px; color: #555;")
        circle_result_row3.addWidget(self.circle_record_count_label)

        circle_result_row3.addSpacing(10)
        self.circle_instant_label = QtWidgets.QLabel("瞬时距离: --")
        self.circle_instant_label.setStyleSheet("font-size: 14px; color: #555;")
        circle_result_row3.addWidget(self.circle_instant_label)

        circle_result_row3.addStretch()

        # 画圈结果显示 - 第4行：结果信息（画圈次数到、CSV均值等）
        circle_result_row4 = QtWidgets.QHBoxLayout()
        self.circle_result_label = QtWidgets.QLabel("")
        self.circle_result_label.setStyleSheet("color: #888; font-size: 12px;")
        circle_result_row4.addWidget(self.circle_result_label)
        circle_result_row4.addStretch()

        # 组装画圈区域（先放按钮行，始终显示）
        circle_layout.addLayout(circle_btn_row)

        # 高级配置开关
        self.show_circle_advanced_check = QtWidgets.QCheckBox("显示自动测试配置")
        self.show_circle_advanced_check.setChecked(False)
        self.show_circle_advanced_check.stateChanged.connect(self._toggle_circle_advanced_config)
        circle_layout.addWidget(self.show_circle_advanced_check)

        # 高级配置容器（默认隐藏）
        self.circle_advanced_container = QtWidgets.QWidget()
        circle_advanced_vbox = QtWidgets.QVBoxLayout(self.circle_advanced_container)
        circle_advanced_vbox.setContentsMargins(0, 4, 0, 4)
        circle_advanced_vbox.setSpacing(4)
        circle_advanced_vbox.addLayout(circle_param_row1)
        circle_advanced_vbox.addLayout(circle_param_row2)
        circle_advanced_vbox.addLayout(circle_param_row3)
        self.circle_advanced_container.setVisible(False)
        circle_layout.addWidget(self.circle_advanced_container)

        circle_layout.addLayout(circle_delay_row)
        # 隐藏：鼠标延迟显示，等后续优化后再放开
        self.circle_delay_title.setVisible(False)
        self.circle_delay_label.setVisible(False)

        # 结果展示 4行布局
        circle_layout.addLayout(circle_result_row1)
        circle_layout.addLayout(self.circle_mean_line_hbox)
        circle_layout.addLayout(circle_result_row3)
        circle_layout.addLayout(circle_result_row4)

        layout.addWidget(circle_section)

        # =========================================================
        # 区域2：跟手度趋势图
        # =========================================================
        chart_section = QtWidgets.QGroupBox("跟手度趋势图")
        chart_section.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                color: #2E7D32;
                border: 2px solid #4CAF50;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
                background-color: #f5fff5;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }
        """)
        chart_layout = QtWidgets.QVBoxLayout(chart_section)
        chart_layout.setSpacing(6)

        # 图表显示标签
        self.chart_label = QtWidgets.QLabel()
        self.chart_label.setMinimumHeight(220)
        self.chart_label.setAlignment(QtCore.Qt.AlignCenter)
        self.chart_label.setStyleSheet("background-color: white; border: 1px solid #ccc;")
        self.chart_label.setText("开始测试后，测试完成将显示跟手度趋势图")
        chart_layout.addWidget(self.chart_label)

        # Y轴最大值配置
        chart_y_row = QtWidgets.QHBoxLayout()
        chart_y_row.addWidget(QtWidgets.QLabel("Y轴最大值:"))
        self.chart_y_max_spin = QtWidgets.QSpinBox()
        self.chart_y_max_spin.setRange(100, 10000)
        self.chart_y_max_spin.setSingleStep(100)
        self.chart_y_max_spin.setValue(100)
        self.chart_y_max_spin.setSuffix(" px")
        self.chart_y_max_spin.valueChanged.connect(self._on_chart_y_max_changed)
        chart_y_row.addWidget(self.chart_y_max_spin)

        auto_btn = QtWidgets.QPushButton("自适应")
        auto_btn.clicked.connect(self._on_chart_y_auto)
        chart_y_row.addWidget(auto_btn)
        chart_y_row.addStretch()
        chart_layout.addLayout(chart_y_row)

        layout.addWidget(chart_section)

        # =========================================================
        # 区域3：历史记录列表
        # =========================================================
        history_section = QtWidgets.QGroupBox("历史记录")
        history_section.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                color: #6A1B9A;
                border: 2px solid #9C27B0;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
                background-color: #fdf5ff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }
        """)
        history_layout = QtWidgets.QVBoxLayout(history_section)
        history_layout.setSpacing(6)

        # 历史记录表格
        self.history_table = QtWidgets.QTableWidget()
        self.history_table.setColumnCount(7)
        self.history_table.setHorizontalHeaderLabels(['序号', '时间', '鼠标延迟(毫秒)', '距离均值', '平滑度', '备注', '详细数据'])
        self.history_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.history_table.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked | QtWidgets.QAbstractItemView.EditKeyPressed)
        self.history_table.setColumnWidth(0, 50)   # 序号
        self.history_table.setColumnWidth(1, 140)  # 时间
        self.history_table.setColumnWidth(2, 100)  # 鼠标延迟(毫秒)
        self.history_table.setColumnWidth(3, 80)   # 距离均值
        self.history_table.setColumnWidth(4, 70)   # 平滑度
        self.history_table.setColumnWidth(5, 150)  # 备注
        self.history_table.setColumnWidth(6, 200)  # 详细数据
        # 允许用户手动调整列宽
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(6, QtWidgets.QHeaderView.Interactive)
        header.setStretchLastSection(True)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setFixedHeight(150)
        # 禁用文本省略号模式
        self.history_table.setTextElideMode(QtCore.Qt.ElideNone)
        self.history_table.itemChanged.connect(self._on_history_remark_changed)
        self.history_table.itemSelectionChanged.connect(self._on_history_selection_changed)
        history_layout.addWidget(self.history_table)

        # 加载历史记录
        self._load_history_records()

        layout.addWidget(history_section)

        # =========================================================
        # 区域4：实时统计（底部，带橙色主题）
        # =========================================================
        real_section = QtWidgets.QGroupBox("实时统计")
        real_section.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                color: #E65100;
                border: 2px solid #FF9800;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
                background-color: #fffbf5;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }
        """)
        real_layout = QtWidgets.QVBoxLayout(real_section)
        real_layout.setSpacing(6)

        # 采样间隔设置（只保留这个公共参数）
        interval_row = QtWidgets.QHBoxLayout()
        interval_row.addWidget(QtWidgets.QLabel("实时统计采样间隔:"))
        self.interval_spin = QtWidgets.QSpinBox()
        self.interval_spin.setRange(50, 5000)
        self.interval_spin.setValue(200)
        self.interval_spin.setMaximumWidth(80)
        self.interval_spin.setSuffix(" ms")
        self.interval_spin.setToolTip("开始统计时的采样间隔")
        self.interval_spin.valueChanged.connect(
            lambda v: setattr(self, 'interval_ms', v))
        interval_row.addWidget(self.interval_spin)
        interval_row.addStretch()
        real_layout.addLayout(interval_row)

        # 实时统计操作按钮
        real_btn_row = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton("▶ 开始统计")
        self.start_btn.setProperty("role", "primary")
        self.start_btn.setMinimumHeight(32)
        self.start_btn.clicked.connect(self._start)
        real_btn_row.addWidget(self.start_btn)

        self.stop_btn = QtWidgets.QPushButton("■ 停止")
        self.stop_btn.setProperty("role", "danger")
        self.stop_btn.setMinimumHeight(32)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        real_btn_row.addWidget(self.stop_btn)

        reset_btn = QtWidgets.QPushButton("清零")
        reset_btn.setMinimumHeight(32)
        reset_btn.clicked.connect(self._reset)
        real_btn_row.addWidget(reset_btn)

        real_btn_row.addStretch()

        # 实时统计结果显示
        real_result_row = QtWidgets.QHBoxLayout()

        self.dist_label = QtWidgets.QLabel("--")
        self.dist_label.setStyleSheet("font-size: 48px; font-weight: bold; color: #1565C0;")
        self.dist_label.setMinimumWidth(150)
        self.dist_label.setAlignment(QtCore.Qt.AlignLeft)
        real_result_row.addWidget(self.dist_label)

        real_result_row.addSpacing(20)
        coord_layout = QtWidgets.QVBoxLayout()
        self.p1_label = QtWidgets.QLabel("黑点: --")
        self.p1_label.setStyleSheet("color: #555; font-size: 13px;")
        self.p2_label = QtWidgets.QLabel("鼠标: --")
        self.p2_label.setStyleSheet("color: #555; font-size: 13px;")
        coord_layout.addWidget(self.p1_label)
        coord_layout.addWidget(self.p2_label)
        real_result_row.addLayout(coord_layout)

        real_result_row.addStretch()

        self.real_status_label = QtWidgets.QLabel("状态: 已停止")
        self.real_status_label.setStyleSheet("color: #888; font-size: 12px;")
        real_result_row.addWidget(self.real_status_label)

        # 组装实时统计区域
        real_layout.addLayout(real_btn_row)
        real_layout.addLayout(real_result_row)

        layout.addWidget(real_section)

        # 底部说明按钮
        about_row = QtWidgets.QHBoxLayout()
        about_row.addStretch()
        about_btn = QtWidgets.QPushButton("说明")
        about_btn.clicked.connect(self._show_help)
        about_row.addWidget(about_btn)
        layout.addLayout(about_row)

    def _on_region_change(self):
        pass

    def _toggle_advanced_config(self, state):
        self.advanced_container.setVisible(state > 0)

    def _toggle_circle_advanced_config(self, state):
        self.circle_advanced_container.setVisible(state > 0)

    def _enter_select_mode(self):
        self.select_btn.setText("框选中...")
        self.select_btn.setProperty("role", "select_active")
        self.select_btn.style().unpolish(self.select_btn)
        self.select_btn.style().polish(self.select_btn)
        self.select_btn.setEnabled(False)
        self.rb = RubberBand()
        self.rb.selected.connect(self._on_rb_selected)

    def _on_rb_selected(self, r):
        self.rb = None
        self.sx_spin.setValue(r.left())
        self.sy_spin.setValue(r.top())
        self.sw_spin.setValue(r.width())
        self.sh_spin.setValue(r.height())
        self.select_btn.setText("选择测试区域")
        self.select_btn.setProperty("role", "select")
        self.select_btn.style().unpolish(self.select_btn)
        self.select_btn.style().polish(self.select_btn)
        self.select_btn.setEnabled(True)

    def _preview_region(self):
        """预览当前选择的测试区域，显示2秒后自动消失。"""
        x = self.sx_spin.value()
        y = self.sy_spin.value()
        w = self.sw_spin.value()
        h = self.sh_spin.value()
        if w < 1 or h < 1:
            return

        # 创建半透明预览窗口
        preview = QtWidgets.QWidget(None)
        preview.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        preview.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        preview.setGeometry(x, y, w, h)
        preview.setWindowOpacity(0.7)  # 70% 透明度

        # 蓝色背景 + 红色边框（用样式表）
        preview.setStyleSheet("""
            background-color: rgba(33, 150, 243, 255);
            border: 3px solid #f44336;
        """)

        preview.show()
        preview.raise_

        # 2秒后自动关闭
        QtCore.QTimer.singleShot(2000, preview.close)

    def _on_topmost_changed(self, state):
        """间隔置顶窗口复选框状态变化"""
        if state > 0:
            # 立即置顶一次
            self._raise_window()
            self.topmost_timer.start(5000)
        else:
            self.topmost_timer.stop()

    def _raise_window(self):
        """将当前窗口置顶"""
        self.raise_()
        self.activateWindow()
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        self.show()

    def _compute_circle_points(self, num_points, cx, cy, radius):
        """按指定点数计算圆周上的点坐标。"""
        points = []
        for i in range(num_points):
            angle = 2 * math.pi * i / num_points
            px = cx + radius * math.cos(angle)
            py = cy + radius * math.sin(angle)
            points.append((int(px), int(py)))
        return points

    def _recalibrate_points(self, new_points):
        """自动校准：按新点数重新生成画圆路径，并同步更新UI点数。"""
        self.circle_point_count = new_points
        self.circle_points_spin.setValue(new_points)
        self.circle_points = self._compute_circle_points(
            new_points, self.circle_cx, self.circle_cy, self.circle_radius)

    def _finish_calibration(self):
        """校准完成，重置圈数并进入正式的画圈与距离统计。"""
        self.calibrating = False
        self.circle_drawn = 0
        self.circle_times = []
        self.circle_lap_start_time = None
        self.circle_index = 0
        self.circle_recording = False
        self.circle_time_label.setText("单圈耗时: --")
        self.circle_count_label.setText("已画圈数: 0")
        # 校准完成后从正式倒计时开始显示
        if not self.circle_use_time_mode and self.circle_count_limit:
            self.circle_countdown_label.setText(str(self.circle_count_limit))
        else:
            self.circle_countdown_label.setText("--")

    def _draw_circle(self):
        """在框选区域内模拟鼠标画圆。"""
        # 获取框选区域
        rx = self.sx_spin.value()
        ry = self.sy_spin.value()
        rw = self.sw_spin.value()
        rh = self.sh_spin.value()

        if rw < 10 or rh < 10:
            self.circle_status_label.setText("区域太小，无法画圆")
            return

        # 取矩形内最大的正方形
        if rw >= rh:
            square_size = rh
            offset_x = (rw - rh) // 2
            offset_y = 0
        else:
            square_size = rw
            offset_x = 0
            offset_y = (rh - rw) // 2

        # 正方形区域
        sq_x = rx + offset_x
        sq_y = ry + offset_y
        sq_w = square_size
        sq_h = square_size

        # 圆的中心点和半径
        cx = sq_x + sq_w / 2
        cy = sq_y + sq_h / 2
        radius = (square_size / 2) - 2  # 留一点边距

        # 获取参数
        speed = self.circle_speed_spin.value()  # 数值越小越慢
        num_points = self.circle_points_spin.value()

        # 判断模式
        use_time_mode = self.circle_mode_time.isChecked()
        if use_time_mode:
            circle_duration = self.circle_duration_spin.value()
            circle_count = 0  # 不限制次数
            self.circle_duration_limit = circle_duration
            self.circle_count_limit = None
        else:
            circle_count = self.circle_count_spin.value()
            circle_duration = 0
            self.circle_count_limit = circle_count
            self.circle_duration_limit = None

        # 记录圆心半径，供自动校准重新计算点数使用
        self.circle_cx = cx
        self.circle_cy = cy
        self.circle_radius = radius
        self.circle_point_count = num_points

        # 计算圆周上的点
        points = self._compute_circle_points(num_points, cx, cy, radius)

        # 初始化状态
        self.circle_index = 0
        self.circle_points = points
        self.circle_speed = speed
        self.circle_drawn = 0  # 已画圈数
        self.circle_start_time = None
        self.circle_running = True
        self.circle_recording = False  # 是否正在记录距离
        # 单圈耗时统计
        self.circle_times = []  # 每圈耗时(毫秒)
        self.circle_lap_start_time = None  # 当前圈的起始时间
        # 隐藏上次均值横线
        if hasattr(self, 'circle_mean_line'):
            self.circle_mean_line.setVisible(False)
        self.circle_record_distances = []  # 记录的距离值
        self.circle_wait_done = False  # 初始等待是否完成
        self.circle_stop_prepare = False  # 是否准备停止
        self.circle_record_counter = 0  # 记录计数器

        # 自动校准模型：校准画圈快慢（以单圈耗时接近3600ms为标准，通过调整点数实现）
        # 仅在次数模式下生效；时间模式与原逻辑保持一致
        self.circle_use_time_mode = use_time_mode
        self.auto_calibrate_on = self.auto_calibrate_check.isChecked() and not use_time_mode
        self.calibrating = self.auto_calibrate_on  # 是否处于校准阶段
        self.calib_laps_done = 0  # 校准阶段已画圈数
        self.calib_eval_at = 2  # 初始在第二圈后评估单圈耗时
        self.calib_attempts = 0  # 校准尝试次数（防止死循环）

        # CSV记录相关
        self.circle_csv_path = None
        use_multi_thread = self.multi_thread_check.isChecked()

        if self.csv_record_check.isChecked():
            import time as time_str
            import os
            import sys
            timestamp = time_str.strftime("%Y%m%d_%H%M%S")
            # 获取exe所在目录（PyInstaller打包后指向exe，未打包时指向脚本）
            if getattr(sys, 'frozen', False):
                exe_dir = os.path.dirname(sys.executable)
            else:
                exe_dir = os.path.dirname(os.path.abspath(__file__))
            csv_dir = os.path.join(exe_dir, "mouse_drag_record")
            os.makedirs(csv_dir, exist_ok=True)
            self.circle_csv_path = os.path.join(csv_dir, f"circle_{timestamp}.csv")
            # 写入CSV表头
            with open(self.circle_csv_path, 'w', encoding='utf-8') as f:
                f.write("index,point_index,mouse_x,mouse_y,dot_x,dot_y,distance\n")

        # 多线程模式：启动独立统计线程
        if use_multi_thread:
            self.stats_thread.configure(
                rx, ry, rw, rh,
                self.threshold_spin.value(),
                self.min_area_spin.value(),
                self.stats_interval_spin.value()
            )
            if self.circle_csv_path:
                self.stats_thread.set_csv(self.circle_csv_path)
            else:
                self.stats_thread.set_csv(None)
            self.stats_thread.start_stats()

        # 禁用画圈按钮
        self.draw_circle_btn.setEnabled(False)
        self.circle_status_label.setText("正在校准..." if self.calibrating else "正在画圈...")
        self.circle_delay_label.setText("--")
        self.circle_mean_label.setText("--")
        self.circle_std_label.setText("--")
        self.circle_count_label.setText("已画圈数: 0")
        self.circle_mean_info_label.setText("均值: --")
        self.circle_record_count_label.setText("采样次数: 0")
        self.circle_instant_label.setText("瞬时距离: --")
        self.circle_time_label.setText("单圈耗时: --")
        self.circle_result_label.setText(f"自动校准模型已开启：单圈耗时目标3600ms，点数默认{self.circle_points_spin.value()}" if self.calibrating else "")
        # 初始化完成倒计时（校准阶段显示"校准中..."）
        if self.calibrating:
            self.circle_countdown_label.setText("校准中...")
        elif not use_time_mode and self.circle_count_limit:
            self.circle_countdown_label.setText(str(self.circle_count_limit))
        else:
            self.circle_countdown_label.setText("--")

        import time as time_module

        def move_next_point():
            if not self.circle_running:
                return

            if self.circle_start_time is None:
                self.circle_start_time = time_module.time()

            elapsed = time_module.time() - self.circle_start_time

            # 时间模式：检查是否到达结束前500ms
            if use_time_mode and self.circle_duration_limit:
                if elapsed >= self.circle_duration_limit - 0.5:
                    # 停止记录，准备结束
                    self.circle_recording = False
                    self.circle_stop_prepare = True

            # 检查是否画完
            if self.circle_index >= len(self.circle_points):
                # 记录单圈耗时（跳过第一圈，第一圈起始时间未设置）
                lap_ms = None
                if self.circle_lap_start_time is not None:
                    lap_ms = int((time_module.time() - self.circle_lap_start_time) * 1000)
                    # 校准阶段仅用于判断，不纳入正式统计
                    if not (self.auto_calibrate_on and self.calibrating):
                        self.circle_times.append(lap_ms)
                        avg_lap = sum(self.circle_times) // len(self.circle_times)
                        self.circle_time_label.setText(f"单圈耗时: {lap_ms} ms | 均值: {avg_lap} ms")
                # 开始计时下一圈
                self.circle_lap_start_time = time_module.time()

                self.circle_drawn += 1
                self.circle_index = 0

                # ===== 自动校准逻辑（次数模式专属） =====
                if self.auto_calibrate_on and self.calibrating:
                    self.calib_laps_done += 1
                    self.circle_status_label.setText(f"正在校准... 第{self.circle_drawn}圈")
                    self.circle_count_label.setText(f"已画圈数: {self.circle_drawn}")
                    # 仅在设定的评估圈数（初始第二圈，之后每次调整后隔2圈）评估
                    if self.calib_laps_done >= self.calib_eval_at and lap_ms is not None:
                        self.calib_attempts += 1
                        if 3500 <= lap_ms <= 3700:
                            self._finish_calibration()
                        elif self.calib_attempts >= 15:
                            self.circle_status_label.setText("校准次数过多，直接开始正式测试")
                            self._finish_calibration()
                        else:
                            if lap_ms < 3500:
                                n = (3600 - lap_ms) / (lap_ms / 1200.0)
                                new_points = int(round(1200 + n))
                                adj_dir = "增加"
                            else:  # lap_ms > 3700，单圈耗时偏慢，减少点数
                                n = (lap_ms - 3600) / (lap_ms / 1200.0)
                                new_points = int(round(1200 - n))
                                adj_dir = "减少"
                            new_points = max(new_points, self.circle_points_spin.minimum())
                            new_points = min(new_points, self.circle_points_spin.maximum())
                            if new_points == self.circle_point_count:
                                # 点位未变化，无法继续校准，直接进入正式测试
                                self.circle_status_label.setText("单圈耗时偏差无法通过调整点数消除，开始正式测试")
                                self._finish_calibration()
                            else:
                                self._recalibrate_points(new_points)
                                self.circle_status_label.setText(
                                    f"校准中... 单圈{lap_ms}ms，{adj_dir}点数至{new_points}，再画2圈")
                                self.calib_eval_at = self.calib_laps_done + 2
                    return  # 校准阶段不更新正式倒计时/记录标志

                self.circle_status_label.setText(f"正在画圈... 第{self.circle_drawn}圈")
                self.circle_count_label.setText(f"已画圈数: {self.circle_drawn}")
                # 更新完成倒计时（次数模式）
                if not use_time_mode and self.circle_count_limit:
                    remaining = self.circle_count_limit - self.circle_drawn
                    self.circle_countdown_label.setText(str(max(remaining, 0)))

                # 次数模式：从第二圈开始记录，倒数第二圈结束
                # circle_drawn >= 1: 第二圈画完(=1)后开始记录，此时正在画第三圈
                # circle_drawn >= 2 会导致从第三圈才开始记录(晚一圈)，这是bug
                if not use_time_mode and self.circle_count_limit:
                    if self.circle_drawn >= 1 and self.circle_drawn < self.circle_count_limit - 1:
                        self.circle_recording = True
                    else:
                        self.circle_recording = False
                return

            px, py = self.circle_points[self.circle_index]

            # 时间模式：等待500ms后开始记录
            if use_time_mode and not self.circle_wait_done:
                if elapsed >= 0.5:
                    self.circle_wait_done = True
                    self.circle_recording = True

            # 单线程模式：同步检测（在多线程模式下跳过，由独立线程处理）
            # circle_drawn >= 1 跳过第一圈数据
            if not use_multi_thread and self.circle_drawn >= 1:
                if self.circle_recording and (self.enable_mean_check.isChecked() or self.circle_csv_path):
                    record_interval = self.record_interval_spin.value()
                    self.circle_record_counter += 1
                    if self.circle_record_counter >= record_interval:
                        self.circle_record_counter = 0
                        # 同步检测黑点
                        dot_local = detect_one_dot(
                            capture_screen_region(rx, ry, rw, rh),
                            self.threshold_spin.value(),
                            self.min_area_spin.value()
                        )
                        if dot_local is not None:
                            dot_x = rx + dot_local[0]
                            dot_y = ry + dot_local[1]
                            dist = math.sqrt((px - dot_x) ** 2 + (py - dot_y) ** 2)

                            # 统计均值
                            if self.enable_mean_check.isChecked():
                                self.circle_record_distances.append(dist)

                            # CSV记录
                            if self.circle_csv_path:
                                total_idx = (self.circle_drawn * len(self.circle_points) + self.circle_index)
                                with open(self.circle_csv_path, 'a', encoding='utf-8') as f:
                                    f.write(f"{total_idx},{self.circle_index},{px},{py},{dot_x},{dot_y},{dist:.2f}\n")

            # 检查时间限制
            if use_time_mode and self.circle_duration_limit and elapsed >= self.circle_duration_limit:
                mean_str = f"，均值: {self._calc_mean_distance():.1f}" if self.enable_mean_check.isChecked() else ""
                self._stop_circle(f"画圈时间到{mean_str}")
                return

            # 检查次数限制
            if not use_time_mode and self.circle_count_limit and self.circle_drawn >= self.circle_count_limit:
                mean_str = f"，均值: {self._calc_mean_distance():.1f}" if self.enable_mean_check.isChecked() else ""
                self._stop_circle(f"画圈次数到{mean_str}")
                return

            # 移动鼠标到目标点（画圆）
            QtGui.QCursor.setPos(px, py)
            self.circle_index += 1

        self.circle_timer = QtCore.QTimer()
        self.circle_timer.timeout.connect(move_next_point)
        # speed 越小，间隔越大（越慢），范围 1-100 -> 间隔 100ms-10000ms
        interval = int(10000 / (speed * 100))
        self.circle_timer.start(interval)

    def _calc_mean_distance(self):
        """计算记录的距离的均值。"""
        if not self.circle_record_distances:
            return 0.0
        return sum(self.circle_record_distances) / len(self.circle_record_distances)

    def _calc_std_distance(self):
        """计算记录的距离的标准差（平滑度）。"""
        if len(self.circle_record_distances) < 2:
            return 0.0
        mean = self._calc_mean_distance()
        variance = sum((x - mean) ** 2 for x in self.circle_record_distances) / len(self.circle_record_distances)
        return math.sqrt(variance)

    def _calc_csv_mean(self):
        """从CSV读取数据，计算中间部分的均值（排除开头和结尾各10%）。"""
        if not self.circle_csv_path:
            return None
        try:
            import csv
            distances = []
            with open(self.circle_csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    distances.append(float(row['distance']))
            if not distances:
                return None
            # CSV写入时已排除第一圈，这里直接计算全部数据的均值
            return sum(distances) / len(distances)
        except Exception as e:
            print(f"CSV读取失败: {e}")
            return None

    def _on_stats_recorded(self, dist, dot_x, dot_y, mouse_x, mouse_y):
        """统计线程的结果回调"""
        if not self.circle_running:
            return

        # 统计均值：只有开启时才记录，且跳过第一圈
        # circle_drawn >= 1 跳过第一圈数据
        if self.circle_drawn >= 1 and self.circle_recording and self.enable_mean_check.isChecked():
            self.circle_record_distances.append(dist)
            # 更新显示
            mean_val = self._calc_mean_distance()
            std_val = self._calc_std_distance()
            self.circle_delay_label.setText(f"{mean_val * 2.34:.1f}")
            self.circle_mean_label.setText(f"{mean_val:.1f}")
            self.circle_mean_info_label.setText(f"均值: {mean_val:.1f}")
            self.circle_record_count_label.setText(f"采样次数: {len(self.circle_record_distances)}")
            self.circle_instant_label.setText(f"瞬时距离: {dist:.1f}")
            self.circle_std_label.setText(f"{std_val:.2f}")
            if hasattr(self, 'circle_drawn'):
                self.circle_count_label.setText(f"已画圈数: {self.circle_drawn}")

    def _on_circle_mode_changed(self):
        """次数和时间互斥切换。"""
        if self.circle_mode_count.isChecked():
            self.circle_count_spin.setEnabled(True)
            self.circle_duration_spin.setEnabled(False)
        else:
            self.circle_count_spin.setEnabled(False)
            self.circle_duration_spin.setEnabled(True)

    def _stop_circle(self, reason):
        """停止画圈。"""
        if hasattr(self, 'circle_timer'):
            self.circle_timer.stop()
        self.circle_running = False
        self.draw_circle_btn.setEnabled(True)

        # 停止统计线程
        if self.stats_thread.isRunning():
            self.stats_thread.stop_stats()

        # 更新最终均值显示
        final_mean = 0.0
        final_std = 0.0
        if self.enable_mean_check.isChecked() and self.circle_record_distances:
            final_mean = self._calc_mean_distance()
            final_std = self._calc_std_distance()
            self.circle_delay_label.setText(f"{final_mean * 2.34:.1f}")
            self.circle_mean_label.setText(f"{final_mean:.1f}")
            self.circle_mean_info_label.setText(f"均值: {final_mean:.1f}")
            # 显示横线：长度为均值对应的像素数
            self.circle_mean_line.setFixedWidth(int(final_mean))
            self.circle_mean_line.setVisible(True)

        # CSV记录模式：从CSV读取并计算均值
        csv_mean = None
        detail_csv_path = self.circle_csv_path if hasattr(self, 'circle_csv_path') else None
        if self.csv_record_check.isChecked() and self.circle_csv_path:
            csv_mean = self._calc_csv_mean()
            if csv_mean is not None:
                reason += f"，CSV均值: {csv_mean:.1f}"

        # 写入汇总CSV并更新历史记录列表
        if self.csv_record_check.isChecked() and self.circle_csv_path:
            import time as time_str
            time_str_fmt = time_str.strftime("%Y-%m-%d %H:%M:%S")
            seq_num = write_all_dist_record(
                time_str_fmt,
                final_mean,
                final_std,
                self.circle_csv_path,
                ""
            )
            if seq_num:
                self._add_history_record(seq_num, time_str_fmt, final_mean, final_std, self.circle_csv_path, "")

        # 状态标签显示简短信息，结果标签显示详细信息
        self.circle_status_label.setText("测试完成")
        self.circle_result_label.setText(reason)

        # 更新趋势图
        self._update_chart()

    def _on_chart_y_max_changed(self):
        """Y轴最大值改变时立即刷新图表"""
        if self.circle_record_distances:
            self._update_chart()

    def _on_chart_y_auto(self):
        """点击自适应按钮，根据当前数据重新计算Y轴最大值"""
        if not self.circle_record_distances:
            return
        distances = self.circle_record_distances
        actual_max = max(distances) if distances else 100
        adaptive_max = ((int(actual_max * 1.1) + 99) // 100) * 100
        adaptive_max = max(adaptive_max, 100)
        self.chart_y_max_spin.blockSignals(True)
        self.chart_y_max_spin.setValue(adaptive_max)
        self.chart_y_max_spin.blockSignals(False)
        self._update_chart()

    def _update_chart(self):
        """生成并显示跟手度趋势图"""
        if not self.circle_record_distances:
            return
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import matplotlib.backends.backend_agg as agg
            from io import BytesIO

            # 设置中文字体
            plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
            plt.rcParams['axes.unicode_minus'] = False

            distances = self.circle_record_distances
            x = list(range(len(distances)))
            y = distances

            # 计算Y轴范围（以100为最小单位向上取整）
            configured_max = self.chart_y_max_spin.value()
            if configured_max > 0:
                max_y = configured_max
            else:
                # 自适应：取实际最大值向上取整到100的倍数，最小100
                actual_max = max(distances) if distances else 100
                max_y = ((int(actual_max * 1.1) + 99) // 100) * 100
                max_y = max(max_y, 100)
                # 更新spinbox显示（阻塞信号防止重复触发）
                self.chart_y_max_spin.blockSignals(True)
                self.chart_y_max_spin.setValue(max_y)
                self.chart_y_max_spin.blockSignals(False)

            # 创建图表（增加高度确保X轴标签显示）
            fig, ax = plt.subplots(figsize=(6, 2), dpi=80)
            fig.subplots_adjust(bottom=0.2)  # 增加底部边距给X轴标签
            ax.plot(x, y, 'b-', linewidth=0.8, alpha=0.8)
            ax.fill_between(x, y, alpha=0.3)
            ax.set_xlim(0, len(distances) - 1 if len(distances) > 1 else 1)
            ax.set_ylim(0, max_y)
            ax.set_xlabel("Sampling Count", fontsize=9)
            ax.set_ylabel("Distance (pixels)", fontsize=9)
            ax.set_title("Tracking Smoothness Trend", fontsize=10)
            ax.grid(True, alpha=0.3)

            # 渲染到QPixmap
            buf = BytesIO()
            agg.FigureCanvasAgg(fig).print_figure(buf, format='png')
            buf.seek(0)
            pixmap = QtGui.QPixmap()
            pixmap.loadFromData(buf.read())
            buf.close()
            plt.close(fig)

            self.chart_label.setPixmap(pixmap)
            self.chart_label.setText("")
        except Exception as e:
            self.chart_label.setText(f"Chart failed: {e}")

    def _load_history_records(self):
        """加载历史记录到表格"""
        # 确保CSV文件存在且格式正确
        ensure_all_dist_record_header()
        records = read_all_dist_record()
        self.history_table.blockSignals(True)
        self.history_table.setRowCount(len(records))
        for i, row in enumerate(records):
            self.history_table.setItem(i, 0, QtWidgets.QTableWidgetItem(row.get('序号', '')))
            self.history_table.setItem(i, 1, QtWidgets.QTableWidgetItem(row.get('时间', '')))
            self.history_table.setItem(i, 2, QtWidgets.QTableWidgetItem(row.get('鼠标延迟(毫秒)', '')))
            self.history_table.setItem(i, 3, QtWidgets.QTableWidgetItem(row.get('距离均值', '')))
            self.history_table.setItem(i, 4, QtWidgets.QTableWidgetItem(row.get('平滑度', '')))
            self.history_table.setItem(i, 5, QtWidgets.QTableWidgetItem(row.get('备注', '')))
            self.history_table.setItem(i, 6, QtWidgets.QTableWidgetItem(row.get('详细数据', '')))
            # 设置为只读（序号、时间、鼠标延迟(毫秒)、平滑度、详细数据不可编辑，备注可编辑）
            for col in [0, 1, 2, 4, 6]:
                item = self.history_table.item(i, col)
                if item:
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
        self.history_table.blockSignals(False)

    def _add_history_record(self, seq_num, time_str, mean_val, std_val, detail_csv_path, remark=""):
        """添加一条历史记录到表格"""
        row_idx = self.history_table.rowCount()
        self.history_table.blockSignals(True)
        self.history_table.insertRow(row_idx)
        self.history_table.setItem(row_idx, 0, QtWidgets.QTableWidgetItem(str(seq_num)))
        self.history_table.setItem(row_idx, 1, QtWidgets.QTableWidgetItem(time_str))
        self.history_table.setItem(row_idx, 2, QtWidgets.QTableWidgetItem(f"{mean_val * 2.34:.2f}"))
        self.history_table.setItem(row_idx, 3, QtWidgets.QTableWidgetItem(f"{mean_val:.2f}"))
        self.history_table.setItem(row_idx, 4, QtWidgets.QTableWidgetItem(f"{std_val:.2f}"))
        self.history_table.setItem(row_idx, 5, QtWidgets.QTableWidgetItem(remark))
        self.history_table.setItem(row_idx, 6, QtWidgets.QTableWidgetItem(detail_csv_path))
        # 设置为只读（序号、时间、鼠标延迟(毫秒)、平滑度、详细数据不可编辑，备注可编辑）
        for col in [0, 1, 2, 4, 6]:
            item = self.history_table.item(row_idx, col)
            if item:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
        self.history_table.blockSignals(False)
        # 滚动到最新行
        self.history_table.scrollToBottom()

    def _on_history_remark_changed(self, item):
        """备注列修改时更新CSV"""
        if item.column() == 5:  # 备注列（索引5）
            row = item.row()
            seq_item = self.history_table.item(row, 0)
            if seq_item:
                seq_num = int(seq_item.text())
                update_record_remark(seq_num, item.text())

    def _on_history_selection_changed(self):
        """选中历史记录时更新趋势图"""
        selected = self.history_table.selectedIndexes()
        if not selected:
            return
        row = selected[0].row()
        detail_path_item = self.history_table.item(row, 6)
        if detail_path_item:
            detail_path = detail_path_item.text()
            if detail_path and os.path.exists(detail_path):
                self._update_chart_from_csv(detail_path)

    def _update_chart_from_csv(self, csv_path):
        """从CSV文件更新趋势图"""
        try:
            import csv
            distances = []
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    distances.append(float(row['distance']))
            if not distances:
                return

            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import matplotlib.backends.backend_agg as agg
            from io import BytesIO

            plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
            plt.rcParams['axes.unicode_minus'] = False

            x = list(range(len(distances)))
            y = distances

            configured_max = self.chart_y_max_spin.value()
            if configured_max > 0:
                max_y = configured_max
            else:
                actual_max = max(distances) if distances else 100
                max_y = ((int(actual_max * 1.1) + 99) // 100) * 100
                max_y = max(max_y, 100)

            fig, ax = plt.subplots(figsize=(6, 2), dpi=80)
            fig.subplots_adjust(bottom=0.2)
            ax.plot(x, y, 'b-', linewidth=0.8, alpha=0.8)
            ax.fill_between(x, y, alpha=0.3)
            ax.set_xlim(0, len(distances) - 1 if len(distances) > 1 else 1)
            ax.set_ylim(0, max_y)
            ax.set_xlabel("Sampling Count", fontsize=9)
            ax.set_ylabel("Distance (pixels)", fontsize=9)
            ax.set_title("历史测试趋势图", fontsize=10)
            ax.grid(True, alpha=0.3)

            buf = BytesIO()
            agg.FigureCanvasAgg(fig).print_figure(buf, format='png')
            buf.seek(0)
            pixmap = QtGui.QPixmap()
            pixmap.loadFromData(buf.read())
            buf.close()
            plt.close(fig)

            self.chart_label.setPixmap(pixmap)
            self.chart_label.setText("")
        except Exception as e:
            self.chart_label.setText(f"历史趋势图加载失败: {e}")

    def _start(self):
        if self.running:
            return
        self.running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.real_status_label.setText("状态: 测量中")
        self.measure_timer.start(self.interval_ms)

    def _stop(self):
        self.running = False
        self.measure_timer.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.real_status_label.setText("状态: 已停止")

    def _reset(self):
        self.dist_label.setText("--")
        self.p1_label.setText("黑点: --")
        self.p2_label.setText("鼠标: --")
        self.last_dist = None

    def _do_measure(self):
        sx = self.sx_spin.value()
        sy = self.sy_spin.value()
        w = self.sw_spin.value()
        h = self.sh_spin.value()
        if w < 2 or h < 2:
            return
        threshold = self.threshold_spin.value()

        region = capture_screen_region(sx, sy, w, h)
        if region is None:
            self.real_status_label.setText("截图失败")
            return

        dot_local = detect_one_dot(region, threshold, self.min_area_spin.value())
        mouse_pos = QtGui.QCursor.pos()

        if dot_local is not None:
            dot_screen_x = sx + dot_local[0]
            dot_screen_y = sy + dot_local[1]
            dist = math.sqrt((mouse_pos.x() - dot_screen_x) ** 2 +
                             (mouse_pos.y() - dot_screen_y) ** 2)
            self.last_dist = dist
            self.dist_label.setStyleSheet(
                "font-size: 48px; font-weight: bold; color: #1565C0;")
            self.dist_label.setText(f"{dist:.1f}")
            self.p1_label.setText(f"黑点: ({dot_screen_x:.0f}, {dot_screen_y:.0f})")
            self.p2_label.setText(f"鼠标: ({mouse_pos.x()}, {mouse_pos.y()})")
            self.real_status_label.setText(f"测量中  |  区域 {w}x{h}")
        else:
            self.dist_label.setStyleSheet(
                "font-size: 48px; font-weight: bold; color: #e65100;")
            self.dist_label.setText("--")
            self.p1_label.setText("黑点: 未检测到")
            self.p2_label.setText(f"鼠标: ({mouse_pos.x()}, {mouse_pos.y()})")
            self.real_status_label.setText("未检测到黑点")

    def _show_help(self):
        QtWidgets.QMessageBox.information(self, "说明",
            "点距测量工具\n\n"
            "测量「检测区域内黑点质心」与「当前鼠标光标」之间的像素距离。\n\n"
            "1. 点击「框选检测区域」后在屏幕上拖动画出区域\n"
            "2. 或直接设置 X/Y/W/H 坐标定位黑点所在区域\n"
            "3. 点击「开始统计」，实时显示黑点到鼠标的直线距离\n"
            "4. 黑色点坐标 = 检测区域左上角 + 区域内质心（屏幕绝对坐标）\n"
            "5. 调整黑点阈值（RGB均值<阈值视为黑点）和最小面积\n"
            "6. 采样间隔越低刷新越快（毫秒）"
        )

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Escape:
            if self.circle_running:
                self._stop_circle("画圈已停止")
            elif self.running:
                self._stop()
            else:
                pass  # 不退出程序

    def closeEvent(self, e):
        """窗口关闭"""
        e.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = DistToolWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()