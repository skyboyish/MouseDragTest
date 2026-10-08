# -*- coding: utf-8 -*-
"""
鼠标跟手度测试 v2 — 新增动态渐变色背景功能
"""
import sys
import time
import ctypes
from PyQt5 import QtWidgets, QtGui, QtCore


def get_system_uptime_dh():
    """返回系统启动时长文本，格式：X天X小时（不精确到秒）"""
    try:
        GetTickCount64 = ctypes.windll.kernel32.GetTickCount64
        GetTickCount64.restype = ctypes.c_ulonglong  # 声明返回64位无符号，否则超24.8天会变负数
        ms = GetTickCount64()
    except Exception:
        ms = int(time.clock() * 1000) if hasattr(time, 'clock') else 0
    total_hours = ms // 3600000
    days = total_hours // 24
    hours = total_hours % 24
    return f"{days}天 {hours}小时"


def make_dot_cursor(radius, color):
    size = radius * 2 + 2
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    qp = QtGui.QPainter(pixmap)
    qp.setRenderHint(QtGui.QPainter.Antialiasing)
    qp.setBrush(QtGui.QBrush(color))
    qp.setPen(QtCore.Qt.NoPen)
    qp.drawEllipse(QtCore.QPoint(radius + 1, radius + 1), radius, radius)
    qp.end()
    return QtGui.QCursor(pixmap, radius + 1, radius + 1)


class TrailWidget(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.trail_radius = 5
        self.trail_color = QtGui.QColor(QtCore.Qt.black)
        self.cursor_radius = 5
        self.cursor_color = QtGui.QColor(QtCore.Qt.red)
        self.mouse_pos = None
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self._apply_cursor()

        # ---- 渐变相关 ----
        self.gradient_enabled = False          # 渐变色开关
        self.gradient_colors = []              # 渐变色列表 [(QColor, pos), ...]
        self.gradient_angle = 0                # 当前渐变角度（度）
        self._gradient_timer = None            # 定时器，驱动动态渐变
        self.gradient_interval = 50            # 定时器间隔（毫秒），默认 50ms
        self.gradient_step = 2                 # 每帧旋转度数，默认 2°

        # ---- 时间显示 ----
        self.time_enabled = False              # 显示时间开关
        self.time_color = QtGui.QColor(QtCore.Qt.white)  # 时间文字颜色（默认白色）
        self.time_font_scale = 1.0             # 字号大小系数（默认1.0，越大字越大）
        self.time_font_family = "Microsoft YaHei"  # 字体，默认微软雅黑
        self._time_timer = None                # 驱动实时刷新的定时器
        self._font_cache = {}                  # 字号缓存 { (text, scale, width): QFont }
        self._cache_width = None               # 缓存对应的窗口宽度，缩放/变宽时失效

    def set_time_enabled(self, enabled):
        """开启/关闭显示时间"""
        self.time_enabled = enabled
        if enabled:
            self._start_time_timer()
        else:
            self._stop_time_timer()
        self.update()

    def set_time_color(self, c):
        """设置时间文字颜色"""
        self.time_color = c
        self.update()

    def set_time_font_scale(self, scale):
        """设置时间字号大小系数"""
        self.time_font_scale = scale
        self.update()

    def _start_time_timer(self):
        self._stop_time_timer()
        self._time_timer = QtCore.QTimer(self)
        self._time_timer.timeout.connect(self.update)
        self._time_timer.start(500)  # 每 500ms 刷新一次，保证秒在走动

    def _stop_time_timer(self):
        if self._time_timer:
            self._time_timer.stop()
            self._time_timer = None

    def _apply_cursor(self):
        self.setCursor(make_dot_cursor(self.cursor_radius, self.cursor_color))

    def set_trail_radius(self, r):
        self.trail_radius = r
        self.update()

    def set_trail_color(self, c):
        self.trail_color = c
        self.update()

    def set_cursor_radius(self, r):
        self.cursor_radius = r
        self._apply_cursor()

    def set_cursor_color(self, c):
        self.cursor_color = c
        self._apply_cursor()

    def set_bg_color(self, c):
        pal = self.palette()
        pal.setColor(self.backgroundRole(), c)
        self.setPalette(pal)
        self.setAutoFillBackground(True)

    def set_gradient_enabled(self, enabled):
        """开启/关闭渐变色背景"""
        self.gradient_enabled = enabled
        if enabled:
            # 如果没选颜色，给一组默认彩虹色
            if not self.gradient_colors:
                self.gradient_colors = [
                    (QtGui.QColor("#FF6B6B"), 0.0),
                    (QtGui.QColor("#4ECDC4"), 0.5),
                    (QtGui.QColor("#45B7D1"), 1.0),
                ]
            self.setAutoFillBackground(False)  # 关闭纯色填充，改用 paintEvent 画渐变
            self._start_gradient_animation()
        else:
            self._stop_gradient_animation()
            self.setAutoFillBackground(True)
            self.update()

    def set_gradient_colors(self, colors):
        """设置渐变色列表，元素为 (QColor, position_0_to_1)"""
        self.gradient_colors = colors[:]

    def set_gradient_interval(self, ms):
        """设置定时器间隔（毫秒），重启定时器生效"""
        self.gradient_interval = ms
        if self._gradient_timer and self._gradient_timer.isActive():
            self._gradient_timer.setInterval(ms)

    def set_gradient_step(self, degrees):
        """设置每帧旋转角度"""
        self.gradient_step = degrees

    def _start_gradient_animation(self):
        """启动渐变角度旋转动画"""
        self._stop_gradient_animation()
        self._gradient_timer = QtCore.QTimer(self)
        self._gradient_timer.timeout.connect(self._rotate_gradient)
        self._gradient_timer.start(self.gradient_interval)

    def _stop_gradient_animation(self):
        if self._gradient_timer:
            self._gradient_timer.stop()
            self._gradient_timer = None

    def _rotate_gradient(self):
        """每次定时器触发，角度 + step，然后重绘"""
        self.gradient_angle = (self.gradient_angle + self.gradient_step) % 360
        self.update()

    def mouseMoveEvent(self, e):
        self.mouse_pos = e.pos()
        self.update()

    def mousePressEvent(self, e):
        self.pressed = True
        self.mouse_pos = e.pos()
        self.update()

    def mouseReleaseEvent(self, e):
        self.pressed = False
        self.mouse_pos = e.pos()
        self.update()

    def paintEvent(self, e):
        qp = QtGui.QPainter(self)
        qp.setRenderHint(QtGui.QPainter.Antialiasing)

        if self.gradient_enabled and self.gradient_colors:
            # 画渐变色背景
            gradient = QtGui.QConicalGradient(self.rect().center(), self.gradient_angle)
            for color, pos in self.gradient_colors:
                gradient.setColorAt(pos, color)
            qp.fillRect(self.rect(), gradient)
        else:
            # 非渐变模式画纯色背景（从 palette 取色）
            bg = self.palette().color(self.backgroundRole())
            qp.fillRect(self.rect(), bg)

        # ---- 画提示文字 ----
        text = "把测试的区域放置于如下的方框内"
        qp.setPen(QtCore.Qt.black)
        font = qp.font()
        font.setPointSize(14)
        qp.setFont(font)
        text_rect = QtCore.QRect(0, 10, self.width(), 30)
        qp.drawText(text_rect, QtCore.Qt.AlignCenter, text)

        # ---- 显示时间（两行，贴近屏幕左右两边） ----
        if self.time_enabled:
            scale = self.time_font_scale
            qp.setPen(self.time_color)

            def fit_font(text, scale):
                # 缓存字号，避免每次 500ms 重绘都重复做耗时的字形测量循环
                w = self.width()
                if w != self._cache_width:
                    self._font_cache.clear()
                    self._cache_width = w
                key = (text, scale, w)
                cached = self._font_cache.get(key)
                if cached is not None:
                    return cached
                # 动态计算字号，使文字宽度贴近窗口满宽（左右各留 ~1.5% 边距）
                target = w * 0.97
                f = QtGui.QFont(self.time_font_family)
                f.setBold(True)
                size = 16
                while True:
                    f.setPointSize(int(size * scale))
                    if QtGui.QFontMetrics(f).horizontalAdvance(text) >= target or size > 300:
                        break
                    size += 1
                self._font_cache[key] = f
                return f

            # 两行水平都居中且撑满宽度，贴近左右两边
            center_y = self.height() // 2
            line1_text = "系统已启动: " + get_system_uptime_dh()
            font1 = fit_font(line1_text, scale)
            qp.setFont(font1)
            size1 = font1.pointSize()
            qp.drawText(QtCore.QRect(0, center_y - size1 * 3,
                                     self.width(), size1 * 2),
                        QtCore.Qt.AlignCenter, line1_text)

            now_str = time.strftime("%Y年%m月%d日 %H:%M:%S", time.localtime())
            font2 = fit_font(now_str, scale)
            qp.setFont(font2)
            size2 = font2.pointSize()
            qp.drawText(QtCore.QRect(0, center_y - size2 // 2,
                                     self.width(), size2 * 2),
                        QtCore.Qt.AlignCenter, now_str)

        # ---- 画中央淡蓝色方框 ----
        square_size = 600
        x = (self.width() - square_size) // 2
        # 方框顶部从文字底部下方开始，垂直居中
        y = (self.height() - square_size) // 2
        pen = QtGui.QPen(QtGui.QColor("#87CEEB"))
        pen.setWidth(2)
        qp.setPen(pen)
        qp.setBrush(QtCore.Qt.NoBrush)
        qp.drawRect(x, y, square_size, square_size)

        # ---- 画轨迹圆 ----
        if self.mouse_pos is not None:
            qp.setBrush(QtGui.QBrush(self.trail_color))
            qp.setPen(QtCore.Qt.NoPen)
            qp.drawEllipse(self.mouse_pos, self.trail_radius, self.trail_radius)

        qp.end()

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Escape:
            self.window().close()


class GradientEditDialog(QtWidgets.QDialog):
    """渐变色编辑对话框：可添加/删除/修改颜色停靠点"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("渐变色设置")
        self.setMinimumWidth(420)

        # 从父窗口获取当前渐变数据
        self.colors = []
        if parent and hasattr(parent, 'trail'):
            self.colors = [(QtGui.QColor(c), p) for c, p in parent.trail.gradient_colors]

        layout = QtWidgets.QVBoxLayout(self)

        # 预览条
        self.preview = QtWidgets.QLabel()
        self.preview.setFixedHeight(40)
        layout.addWidget(self.preview)

        # 颜色列表
        self.list_widget = QtWidgets.QListWidget()
        layout.addWidget(self.list_widget)

        # 按钮行
        btn_layout = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton("添加颜色")
        add_btn.clicked.connect(self._add_color)
        remove_btn = QtWidgets.QPushButton("删除选中")
        remove_btn.clicked.connect(self._remove_color)
        edit_btn = QtWidgets.QPushButton("修改颜色")
        edit_btn.clicked.connect(self._edit_color)

        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(remove_btn)
        btn_layout.addWidget(edit_btn)
        layout.addLayout(btn_layout)

        # 确定/取消
        ok_cancel = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        ok_cancel.accepted.connect(self.accept)
        ok_cancel.rejected.connect(self.reject)
        layout.addWidget(ok_cancel)

        self._refresh_list()

    def _refresh_list(self):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for idx, (color, pos) in enumerate(self.colors):
            item = QtWidgets.QListWidgetItem(
                f"#{idx}: {color.name()}  @ {pos*100:.0f}%"
            )
            item.setBackground(color)
            item.setForeground(
                QtGui.QColor(QtCore.Qt.white)
                if color.lightness() < 128
                else QtGui.QColor(QtCore.Qt.black)
            )
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)
        self._update_preview()

    def _update_preview(self):
        pix = QtGui.QPixmap(max(self.preview.width(), 100), self.preview.height())
        pix.fill(QtCore.Qt.transparent)
        qp = QtGui.QPainter(pix)
        gradient = QtGui.QLinearGradient(0, 0, pix.width(), 0)
        for color, pos in self.colors:
            gradient.setColorAt(pos, color)
        qp.fillRect(pix.rect(), gradient)
        qp.end()
        self.preview.setPixmap(pix)

    def _add_color(self):
        color = QtWidgets.QColorDialog.getColor(QtCore.Qt.white, self)
        if not color.isValid():
            return
        ok, pos_text = QtWidgets.QInputDialog.getDouble(
            self, "停靠位置", "位置 (0.0 ~ 1.0):", 0.5, 0.0, 1.0, 2
        )
        if not ok:
            return
        self.colors.append((color, pos_text))
        self._refresh_list()

    def _remove_color(self):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        self.colors.pop(row)
        self._refresh_list()

    def _edit_color(self):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        color, pos = self.colors[row]
        new_color = QtWidgets.QColorDialog.getColor(color, self)
        if not new_color.isValid():
            return
        self.colors[row] = (new_color, pos)
        self._refresh_list()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_preview()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("鼠标跟手度测试 v2")
        self.setGeometry(100, 100, 900, 750)

        self.trail = TrailWidget()
        self.setCentralWidget(self.trail)

        # 默认白色背景
        self.trail.set_bg_color(QtCore.Qt.white)

        self._build_toolbar()
        self.statusBar().showMessage("鼠标坐标圆 + 系统光标圆 独立可调 | ESC退出")
        self.show()

    def _build_toolbar(self):
        tb = self.addToolBar("工具栏")

        # --- 鼠标坐标圆 ---
        tb.addWidget(QtWidgets.QLabel("  坐标圆半径:"))
        self.trail_r_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.trail_r_slider.setRange(3, 30)
        self.trail_r_slider.setValue(self.trail.trail_radius)
        self.trail_r_slider.setMaximumWidth(120)
        self.trail_r_slider.valueChanged.connect(
            lambda v: (self.trail.set_trail_radius(v),
                       self.statusBar().showMessage(f"坐标圆 半径={v}px  颜色={self.trail.trail_color.name()}")))
        tb.addWidget(self.trail_r_slider)

        tb.addWidget(QtWidgets.QLabel("  颜色:"))
        self.trail_color_btn = self._make_color_btn(self.trail.trail_color)
        self.trail_color_btn.clicked.connect(self._pick_trail_color)
        tb.addWidget(self.trail_color_btn)

        tb.addSeparator()

        # --- 系统光标圆 ---
        tb.addWidget(QtWidgets.QLabel("  光标圆半径:"))
        self.cursor_r_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.cursor_r_slider.setRange(3, 30)
        self.cursor_r_slider.setValue(self.trail.cursor_radius)
        self.cursor_r_slider.setMaximumWidth(120)
        self.cursor_r_slider.valueChanged.connect(
            lambda v: (self.trail.set_cursor_radius(v),
                       self.statusBar().showMessage(f"光标圆 半径={v}px  颜色={self.trail.cursor_color.name()}")))
        tb.addWidget(self.cursor_r_slider)

        tb.addWidget(QtWidgets.QLabel("  颜色:"))
        self.cursor_color_btn = self._make_color_btn(self.trail.cursor_color)
        self.cursor_color_btn.clicked.connect(self._pick_cursor_color)
        tb.addWidget(self.cursor_color_btn)

        tb.addSeparator()

        # --- 背景 ---
        bg_btn = QtWidgets.QPushButton("背景颜色")
        bg_btn.clicked.connect(self._pick_bg_color)
        tb.addWidget(bg_btn)

        tb.addSeparator()

        # ---- 渐变色功能 ----
        self.gradient_toggle = QtWidgets.QCheckBox("渐变色")
        self.gradient_toggle.stateChanged.connect(self._on_gradient_toggle)
        tb.addWidget(self.gradient_toggle)

        gradient_setup_btn = QtWidgets.QPushButton("设置渐变")
        gradient_setup_btn.clicked.connect(self._open_gradient_dialog)
        tb.addWidget(gradient_setup_btn)

        tb.addWidget(QtWidgets.QLabel("  速度:"))
        self.interval_spin = QtWidgets.QSpinBox()
        self.interval_spin.setRange(10, 500)
        self.interval_spin.setValue(self.trail.gradient_interval)
        self.interval_spin.setSuffix(" ms")
        self.interval_spin.setToolTip("定时器间隔（毫秒），越小越快")
        self.interval_spin.valueChanged.connect(self._on_interval_changed)
        tb.addWidget(self.interval_spin)

        tb.addWidget(QtWidgets.QLabel("  步长:"))
        self.step_spin = QtWidgets.QSpinBox()
        self.step_spin.setRange(1, 60)
        self.step_spin.setValue(self.trail.gradient_step)
        self.step_spin.setSuffix(" °")
        self.step_spin.setToolTip("每帧旋转角度，越大越快")
        self.step_spin.valueChanged.connect(self._on_step_changed)
        tb.addWidget(self.step_spin)

        tb.addSeparator()

        # ---- 时间显示功能 ----
        self.time_toggle = QtWidgets.QCheckBox("显示时间")
        self.time_toggle.stateChanged.connect(self._on_time_toggle)
        tb.addWidget(self.time_toggle)

        self.time_color_btn = self._make_color_btn(self.trail.time_color)
        self.time_color_btn.setToolTip("设置时间字体颜色")
        self.time_color_btn.clicked.connect(self._pick_time_color)
        tb.addWidget(self.time_color_btn)

        # 字号大小（系数，0.5~2.5）
        tb.addWidget(QtWidgets.QLabel("  字号:"))
        self.time_size_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.time_size_slider.setRange(5, 25)
        self.time_size_slider.setValue(12)   # 对应 1.2 倍（默认放大一点）
        self.time_size_slider.setMaximumWidth(100)
        self.time_size_slider.setToolTip("时间字号大小（随窗口缩放基础上微调）")
        self.time_size_slider.valueChanged.connect(self._on_time_size_changed)
        tb.addWidget(self.time_size_slider)

        tb.addSeparator()

        full_btn = QtWidgets.QPushButton("全屏")
        full_btn.clicked.connect(self._toggle_fullscreen)
        tb.addWidget(full_btn)

    def _make_color_btn(self, color):
        btn = QtWidgets.QPushButton()
        btn.setFixedSize(28, 22)
        btn.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #555;")
        return btn

    def _refresh_trail_color_btn(self):
        self.trail_color_btn.setStyleSheet(
            f"background-color: {self.trail.trail_color.name()}; border: 1px solid #555;")

    def _refresh_cursor_color_btn(self):
        self.cursor_color_btn.setStyleSheet(
            f"background-color: {self.trail.cursor_color.name()}; border: 1px solid #555;")

    def _pick_trail_color(self):
        c = QtWidgets.QColorDialog.getColor(self.trail.trail_color, self)
        if c.isValid():
            self.trail.set_trail_color(c)
            self._refresh_trail_color_btn()
            self.statusBar().showMessage(
                f"坐标圆 半径={self.trail.trail_radius}px  颜色={self.trail.trail_color.name()}")

    def _pick_cursor_color(self):
        c = QtWidgets.QColorDialog.getColor(self.trail.cursor_color, self)
        if c.isValid():
            self.trail.set_cursor_color(c)
            self._refresh_cursor_color_btn()
            self.statusBar().showMessage(
                f"光标圆 半径={self.trail.cursor_radius}px  颜色={self.trail.cursor_color.name()}")

    def _pick_bg_color(self):
        pal = self.palette()
        c = QtWidgets.QColorDialog.getColor(
            pal.color(self.backgroundRole()), self)
        if c.isValid():
            self.trail.set_bg_color(c)

    def _on_time_toggle(self, state):
        """显示时间开关状态变化"""
        enabled = state == QtCore.Qt.Checked
        self.trail.set_time_enabled(enabled)
        if enabled:
            self.statusBar().showMessage("已显示时间，颜色=" + self.trail.time_color.name())
        else:
            self.statusBar().showMessage("已隐藏时间")

    def _pick_time_color(self):
        """选择时间字体颜色，选后立即生效"""
        c = QtWidgets.QColorDialog.getColor(self.trail.time_color, self)
        if c.isValid():
            self.trail.set_time_color(c)
            self.time_color_btn.setStyleSheet(
                f"background-color: {c.name()}; border: 1px solid #555;")
            if self.trail.time_enabled:
                self.statusBar().showMessage("时间字体颜色已改为 " + c.name())
            else:
                self.statusBar().showMessage("已设置时间颜色(勾选'显示时间'后即生效) " + c.name())

    def _on_time_size_changed(self, val):
        """字号大小滑块变化：10 -> 1.0 倍"""
        scale = val / 10.0
        self.trail.set_time_font_scale(scale)
        self.statusBar().showMessage(f"时间字号 {scale:.1f} 倍")

    def _on_gradient_toggle(self, state):
        """渐变色开关状态变化"""
        enabled = state == QtCore.Qt.Checked
        self.trail.set_gradient_enabled(enabled)
        if enabled:
            self.statusBar().showMessage("渐变色背景已开启")
        else:
            self.statusBar().showMessage("渐变色背景已关闭")

    def _on_interval_changed(self, val):
        """定时器间隔变化（SpinBox）"""
        self.trail.set_gradient_interval(val)
        self.statusBar().showMessage(f"渐变间隔={val}ms")

    def _on_step_changed(self, val):
        """每帧步长变化（SpinBox）"""
        self.trail.set_gradient_step(val)
        self.statusBar().showMessage(f"渐变步长={val}°")

    def _open_gradient_dialog(self):
        """打开渐变色设置对话框"""
        dlg = GradientEditDialog(self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.trail.set_gradient_colors(dlg.colors)
            # 如果渐变已启用，重新触发更新
            if self.trail.gradient_enabled:
                self.trail.update()

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()