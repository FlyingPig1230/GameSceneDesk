import csv
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QProcess, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRegion
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QProxyStyle,
    QPushButton,
    QScrollArea,
    QStyle,
    QListView,
    QVBoxLayout,
    QWidget
)

from app_paths import (
    APP_DATA_ROOT,
    APP_NAME,
    ASSETS_DIR,
    DATA_DIR,
    RESOURCE_ROOT,
    SOURCE_DATA_DIR
)
from feedback import (
    FEEDBACK_LOG,
    save_feedback,
    save_irrelevant_feedback
)
from map_config import (
    AUTO_MAP,
    canonical_map_name,
    evaluation_dir
)
from model_service import ModelService


APP_DIR = RESOURCE_ROOT
APP_ICON_PATH = ASSETS_DIR / "app_icon_transparent.png"
VALORANT_MARK_PATH = (
    ASSETS_DIR / "valorant_mark_transparent.png"
)
RIOT_MARK_PATH = (
    ASSETS_DIR / "riot_mark_transparent.png"
)
LEGACY_EVALUATION_SUMMARY_PATH = (
    APP_DIR / "evaluation" / "summary.json"
)
LEGACY_EVALUATION_REPORT_PATH = (
    APP_DIR / "evaluation" / "report.csv"
)
ENABLE_MODEL_TOOLS = False
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp"
}


def ui_font(point_size):
    family = (
        "Microsoft YaHei UI"
        if sys.platform == "win32"
        else "PingFang SC"
    )
    return QFont(family, point_size)


class BorderlessComboStyle(QProxyStyle):
    def styleHint(
        self,
        hint,
        option=None,
        widget=None,
        return_data=None
    ):
        if hint == QStyle.SH_ComboBox_Popup:
            return 0

        return super().styleHint(
            hint,
            option,
            widget,
            return_data
        )


class BorderlessComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup_style = BorderlessComboStyle()
        self._popup_style.setParent(self)
        self.setStyle(self._popup_style)

        popup_view = QListView(self)
        popup_view.setObjectName("BorderlessComboPopup")
        popup_view.setFrameShape(QFrame.NoFrame)
        popup_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        self.setView(popup_view)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.Antialiasing,
            True
        )

        control_width = 34
        separator_x = self.width() - control_width
        line_color = (
            QColor("#334257")
            if self.isEnabled()
            else QColor("#273341")
        )
        painter.setPen(QPen(line_color, 1))
        painter.drawLine(
            separator_x,
            1,
            separator_x,
            self.height() - 2
        )

        arrow_color = (
            QColor("#f1f6fc")
            if self.isEnabled()
            else QColor("#657386")
        )
        arrow_pen = QPen(arrow_color, 2.2)
        arrow_pen.setCapStyle(Qt.RoundCap)
        arrow_pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(arrow_pen)

        center_x = separator_x + control_width / 2
        center_y = self.height() / 2
        arrow_path = QPainterPath()
        arrow_path.moveTo(
            center_x - 5,
            center_y - 2
        )
        arrow_path.lineTo(
            center_x,
            center_y + 3
        )
        arrow_path.lineTo(
            center_x + 5,
            center_y - 2
        )
        painter.drawPath(arrow_path)

    def showPopup(self):
        popup = self.view().window()
        popup.setWindowFlag(
            Qt.FramelessWindowHint,
            True
        )
        popup.setWindowFlag(
            Qt.NoDropShadowWindowHint,
            True
        )
        popup.setAttribute(
            Qt.WA_StyledBackground,
            True
        )
        popup.setAttribute(
            Qt.WA_TranslucentBackground,
            True
        )
        popup.setContentsMargins(0, 0, 0, 0)

        if popup.layout():
            popup.layout().setContentsMargins(
                0,
                0,
                0,
                0
            )

        popup.setStyleSheet(
            "background-color: transparent; border: 0;"
        )
        self.view().setStyleSheet(
            """
            QListView#BorderlessComboPopup {
                background-color: #101720;
                border: 1px solid #334257;
                border-radius: 8px;
                color: #f1f6fc;
                outline: 0;
                padding: 3px 0;
            }

            QListView#BorderlessComboPopup::item {
                min-height: 31px;
                padding: 2px 10px;
            }

            QListView#BorderlessComboPopup::item:selected {
                background-color: #29445a;
                color: #ffffff;
            }

            QListView#BorderlessComboPopup::item:hover {
                background-color: #20384c;
                color: #ffffff;
            }
            """
        )
        super().showPopup()
        self._finalize_popup()
        QTimer.singleShot(
            0,
            self._finalize_popup
        )

    def _finalize_popup(self):
        self._position_popup()
        self._apply_popup_mask()

    def _position_popup(self):
        popup = self.view().window()
        popup.resize(
            self.width(),
            popup.height()
        )

        gap = 4
        below = self.mapToGlobal(
            QPoint(0, self.height() + gap)
        )
        popup_x = below.x()
        popup_y = below.y()
        screen = self.screen()

        if screen is not None:
            available = screen.availableGeometry()

            if popup_y + popup.height() > available.bottom():
                above = self.mapToGlobal(
                    QPoint(
                        0,
                        -popup.height() - gap
                    )
                )
                popup_y = above.y()

            popup_x = max(
                available.left(),
                min(
                    popup_x,
                    available.right() - popup.width() + 1
                )
            )

        popup.move(popup_x, popup_y)

    def _apply_popup_mask(self):
        popup = self.view().window()
        popup_rect = QRectF(popup.rect()).adjusted(
            0,
            0,
            -1,
            -1
        )
        path = QPainterPath()
        path.addRoundedRect(
            popup_rect,
            8,
            8
        )
        popup.setMask(
            QRegion(
                path.toFillPolygon().toPolygon()
            )
        )


class ImagePreviewLabel(QLabel):
    def __init__(self, on_image_dropped):
        super().__init__()
        self.on_image_dropped = on_image_dropped
        self.empty_title = "拖入地图截图"
        self.empty_hint = "或点击上方选择图片"
        self.overlay_name = ""
        self.overlay_detail = ""
        self.overlay_badge = ""
        self.setAcceptDrops(True)

    def set_empty_state(self, title, hint):
        self.empty_title = title
        self.empty_hint = hint
        self.overlay_name = ""
        self.overlay_detail = ""
        self.overlay_badge = ""
        self.clear()
        self.update()

    def set_preview_image(
        self,
        pixmap,
        file_name,
        detail,
        badge
    ):
        self.overlay_name = file_name
        self.overlay_detail = detail
        self.overlay_badge = badge
        self.setPixmap(pixmap)
        self.update()

    def paintEvent(self, event):
        current_pixmap = self.pixmap()

        if current_pixmap and not current_pixmap.isNull():
            super().paintEvent(event)
            self._paint_preview_overlay()
            return

        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        icon_size = 58
        icon_left = int((self.width() - icon_size) / 2)
        icon_top = int(self.height() / 2 - 82)
        icon_rect = QRectF(
            icon_left,
            icon_top,
            icon_size,
            icon_size
        )

        painter.setPen(QPen(QColor("#35516a"), 1))
        painter.setBrush(QColor("#111e2a"))
        painter.drawRoundedRect(icon_rect, 10, 10)

        image_left = icon_left + 15
        image_top = icon_top + 17
        image_width = 28
        image_height = 23
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#86a1b9"), 1.8))
        painter.drawRoundedRect(
            QRectF(
                image_left,
                image_top,
                image_width,
                image_height
            ),
            3,
            3
        )
        painter.drawEllipse(
            QRectF(image_left + 18, image_top + 5, 4, 4)
        )
        painter.drawLine(
            image_left + 4,
            image_top + 18,
            image_left + 11,
            image_top + 11
        )
        painter.drawLine(
            image_left + 11,
            image_top + 11,
            image_left + 17,
            image_top + 17
        )
        painter.drawLine(
            image_left + 17,
            image_top + 17,
            image_left + 22,
            image_top + 13
        )

        badge_left = icon_left + 37
        badge_top = icon_top + 35
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ff4655"))
        painter.drawEllipse(
            QRectF(badge_left, badge_top, 15, 15)
        )
        painter.setPen(QPen(QColor("#ffffff"), 1.6))
        painter.drawLine(
            badge_left + 4,
            badge_top + 7,
            badge_left + 11,
            badge_top + 7
        )
        painter.drawLine(
            badge_left + 7.5,
            badge_top + 4,
            badge_left + 7.5,
            badge_top + 11
        )

        title_font = ui_font(16)
        title_font.setWeight(QFont.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor("#dfeaf3"))
        painter.drawText(
            QRectF(0, icon_top + 73, self.width(), 28),
            Qt.AlignHCenter | Qt.AlignVCenter,
            self.empty_title
        )

        hint_font = ui_font(12)
        hint_font.setWeight(QFont.Medium)
        painter.setFont(hint_font)
        painter.setPen(QColor("#708399"))
        painter.drawText(
            QRectF(0, icon_top + 101, self.width(), 24),
            Qt.AlignHCenter | Qt.AlignVCenter,
            self.empty_hint
        )

    def _paint_preview_overlay(self):
        if not self.overlay_name:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        box_width = min(320, self.width() - 32)
        box_rect = QRectF(16, 16, box_width, 56)
        painter.setPen(QPen(QColor("#3b5266"), 1))
        painter.setBrush(QColor(7, 13, 20, 224))
        painter.drawRoundedRect(box_rect, 7, 7)

        accent_color = (
            QColor("#ff4655")
            if self.overlay_badge.startswith("批量")
            else QColor("#4d7898")
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(accent_color)
        painter.drawRoundedRect(
            QRectF(27, 27, 3, 34),
            1,
            1
        )

        badge_font = ui_font(9)
        badge_font.setWeight(QFont.DemiBold)
        badge_metrics = QFontMetrics(badge_font)
        badge_width = max(
            52,
            badge_metrics.horizontalAdvance(
                self.overlay_badge
            ) + 18
        )
        badge_rect = QRectF(
            16 + box_width - badge_width - 10,
            33,
            badge_width,
            24
        )
        painter.setBrush(
            QColor("#6f2630")
            if self.overlay_badge.startswith("批量")
            else QColor("#203447")
        )
        painter.drawRoundedRect(badge_rect, 5, 5)
        painter.setFont(badge_font)
        painter.setPen(QColor("#f3f7fb"))
        painter.drawText(
            badge_rect,
            Qt.AlignCenter,
            self.overlay_badge
        )

        text_width = max(
            40,
            int(box_width - badge_width - 54)
        )
        name_font = ui_font(11)
        name_font.setWeight(QFont.DemiBold)
        name_metrics = QFontMetrics(name_font)
        display_name = name_metrics.elidedText(
            self.overlay_name,
            Qt.ElideMiddle,
            text_width
        )
        painter.setFont(name_font)
        painter.setPen(QColor("#f5f9fc"))
        painter.drawText(
            QRectF(39, 24, text_width, 23),
            Qt.AlignLeft | Qt.AlignVCenter,
            display_name
        )

        detail_font = ui_font(9)
        detail_font.setWeight(QFont.Medium)
        painter.setFont(detail_font)
        painter.setPen(QColor("#90a3b5"))
        painter.drawText(
            QRectF(39, 44, text_width, 20),
            Qt.AlignLeft | Qt.AlignVCenter,
            self.overlay_detail
        )

    def dragEnterEvent(self, event):
        if self._first_supported_image(event.mimeData()):
            event.acceptProposedAction()
            return

        event.ignore()

    def dropEvent(self, event):
        image_path = self._first_supported_image(
            event.mimeData()
        )

        if image_path:
            self.on_image_dropped(image_path)
            event.acceptProposedAction()
            return

        event.ignore()

    def _first_supported_image(self, mime_data):
        if not mime_data.hasUrls():
            return None

        for url in mime_data.urls():
            local_path = Path(url.toLocalFile())

            if local_path.suffix.lower() in IMAGE_EXTENSIONS:
                return str(local_path)

        return None


class LogoMark(QWidget):
    def __init__(self, image_path):
        super().__init__()
        self.image_path = Path(image_path)
        self.pixmap = QPixmap(str(self.image_path))
        self.setFixedSize(42, 42)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self.pixmap.isNull():
            return

        available_width = self.width() - 6
        available_height = self.height() - 6
        scale = min(
            available_width / self.pixmap.width(),
            available_height / self.pixmap.height()
        )
        target_width = self.pixmap.width() * scale
        target_height = self.pixmap.height() * scale
        target_rect = QRectF(
            (self.width() - target_width) / 2,
            (self.height() - target_height) / 2,
            target_width,
            target_height
        )
        source_rect = QRectF(
            0,
            0,
            self.pixmap.width(),
            self.pixmap.height()
        )
        painter.drawPixmap(
            target_rect,
            self.pixmap,
            source_rect
        )


class TacticalMark(LogoMark):
    def __init__(self):
        super().__init__(
            VALORANT_MARK_PATH
        )


class StudioMark(LogoMark):
    def __init__(self):
        super().__init__(RIOT_MARK_PATH)


class ResultDialog(QDialog):
    def __init__(
        self,
        parent,
        title,
        message,
        detail=None
    ):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlags(
            Qt.Dialog | Qt.FramelessWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(24, 24, 24, 24)

        card = QFrame()
        card.setObjectName("DialogCard")

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 14)
        shadow.setColor(QColor(0, 0, 0, 170))
        card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 22, 24, 22)
        card_layout.setSpacing(16)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(16)

        badge = QLabel("✓")
        badge.setObjectName("DialogBadge")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(54, 54)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("DialogTitle")
        title_label.setWordWrap(True)

        message_label = QLabel(message)
        message_label.setObjectName("DialogMessage")
        message_label.setWordWrap(True)

        text_layout.addWidget(title_label)
        text_layout.addWidget(message_label)

        header_layout.addWidget(badge)
        header_layout.addLayout(text_layout)

        card_layout.addLayout(header_layout)

        if detail:
            detail_label = QLabel(detail)
            detail_label.setObjectName("DialogDetail")
            detail_label.setWordWrap(True)
            card_layout.addWidget(detail_label)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        ok_button = QPushButton("完成")
        ok_button.setObjectName("DialogButton")
        ok_button.clicked.connect(self.accept)

        button_layout.addWidget(ok_button)
        card_layout.addLayout(button_layout)

        outer_layout.addWidget(card)

        self.setStyleSheet(
            """
            QFrame#DialogCard {
                background-color: #101923;
                border: 1px solid #31475c;
                border-radius: 10px;
            }

            QLabel#DialogBadge {
                background-color: #123629;
                border: 1px solid #21a67c;
                border-radius: 27px;
                color: #8ef0c1;
                font-family: "Helvetica Neue", Arial;
                font-size: 28px;
                font-weight: 800;
            }

            QLabel#DialogTitle {
                color: #f7fbff;
                font-family: "PingFang SC", "Helvetica Neue", Arial;
                font-size: 20px;
                font-weight: 700;
            }

            QLabel#DialogMessage {
                color: #b7c5d4;
                font-family: "PingFang SC", "Helvetica Neue", Arial;
                font-size: 14px;
                font-weight: 500;
            }

            QLabel#DialogDetail {
                background-color: #172331;
                border: 1px solid #2b3d50;
                border-radius: 8px;
                color: #d8e3ee;
                font-family: "PingFang SC", "Helvetica Neue", Arial;
                font-size: 13px;
                padding: 12px 14px;
            }

            QPushButton#DialogButton {
                background-color: #ff4655;
                border: 1px solid #ff7580;
                border-radius: 7px;
                color: #ffffff;
                font-family: "PingFang SC", "Helvetica Neue", Arial;
                font-size: 14px;
                font-weight: 700;
                min-width: 108px;
                min-height: 38px;
                padding: 4px 18px;
            }

            QPushButton#DialogButton:hover {
                background-color: #ff5967;
            }

            QPushButton#DialogButton:pressed {
                background-color: #d93b49;
            }
            """
        )


class EvaluationDialog(QDialog):
    def __init__(self, parent, summary, wrong_case_count):
        super().__init__(parent)
        self.start_review_requested = False
        self.setModal(True)
        self.setWindowTitle("模型评估报告")
        self.resize(760, 660)
        self.setMinimumSize(700, 600)

        accuracy = float(summary.get("accuracy", 0))
        test_images = int(summary.get("test_images", 0))
        correct = int(summary.get("correct", 0))
        wrong = int(summary.get("wrong", 0))
        map_name = summary.get("map_name", "Ascent")

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(20, 20, 20, 20)

        shell = QFrame()
        shell.setObjectName("EvaluationShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(22, 20, 22, 20)
        shell_layout.setSpacing(14)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(3)

        title_label = QLabel(f"{map_name} 模型评估报告")
        title_label.setObjectName("EvaluationTitle")

        subtitle_label = QLabel(
            "测试集表现与优先补强区域"
        )
        subtitle_label.setObjectName("EvaluationSubtitle")

        title_layout.addWidget(title_label)
        title_layout.addWidget(subtitle_label)

        report_badge = QLabel("EVAL")
        report_badge.setObjectName("EvaluationBadge")
        report_badge.setAlignment(Qt.AlignCenter)
        report_badge.setFixedSize(52, 36)

        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        header_layout.addWidget(report_badge)

        hero = QFrame()
        hero.setObjectName("EvaluationHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(18, 14, 18, 14)
        hero_layout.setSpacing(18)

        accuracy_layout = QVBoxLayout()
        accuracy_layout.setSpacing(3)

        accuracy_caption = QLabel("整体准确率")
        accuracy_caption.setObjectName(
            "EvaluationAccuracyCaption"
        )

        accuracy_value = QLabel(f"{accuracy:.2f}%")
        accuracy_value.setObjectName(
            "EvaluationAccuracyValue"
        )

        accuracy_bar = QProgressBar()
        accuracy_bar.setObjectName("EvaluationAccuracyBar")
        accuracy_bar.setRange(0, 10000)
        accuracy_bar.setValue(round(accuracy * 100))
        accuracy_bar.setTextVisible(False)
        accuracy_bar.setFixedHeight(7)

        accuracy_layout.addWidget(accuracy_caption)
        accuracy_layout.addWidget(accuracy_value)
        accuracy_layout.addWidget(accuracy_bar)

        hero_layout.addLayout(accuracy_layout, 2)
        hero_layout.addWidget(
            self._create_metric(
                "测试图片",
                test_images,
                "neutral"
            ),
            1
        )
        hero_layout.addWidget(
            self._create_metric(
                "预测正确",
                correct,
                "good"
            ),
            1
        )
        hero_layout.addWidget(
            self._create_metric(
                "需要纠错",
                wrong,
                "bad"
            ),
            1
        )

        weak_title = QLabel("优先补强区域")
        weak_title.setObjectName("EvaluationSectionTitle")

        weak_list = QWidget()
        weak_list.setObjectName("EvaluationList")
        weak_layout = QVBoxLayout(weak_list)
        weak_layout.setContentsMargins(0, 0, 0, 0)
        weak_layout.setSpacing(7)

        ranked_classes = self._ranked_classes(summary)

        if ranked_classes:
            for index, result in enumerate(
                ranked_classes[:5],
                start=1
            ):
                weak_layout.addWidget(
                    self._create_class_row(
                        index,
                        *result
                    )
                )
        else:
            empty_label = QLabel("暂无区域评估数据")
            empty_label.setObjectName("EvaluationSubtitle")
            empty_label.setAlignment(Qt.AlignCenter)
            weak_layout.addWidget(empty_label)

        action_layout = QHBoxLayout()
        action_layout.setSpacing(10)

        report_hint = QLabel(
            f"最近报告 · {wrong_case_count} 张可复核错题"
        )
        report_hint.setObjectName("EvaluationFooterHint")

        close_button = QPushButton("关闭")
        close_button.setObjectName("EvaluationCloseButton")
        close_button.clicked.connect(self.accept)

        review_button = QPushButton(
            f"开始错题纠错 · {wrong_case_count}"
        )
        review_button.setObjectName("EvaluationReviewButton")
        review_button.setEnabled(wrong_case_count > 0)
        review_button.clicked.connect(
            self._request_review
        )

        action_layout.addWidget(report_hint)
        action_layout.addStretch()
        action_layout.addWidget(close_button)
        action_layout.addWidget(review_button)

        shell_layout.addLayout(header_layout)
        shell_layout.addWidget(hero)
        shell_layout.addWidget(weak_title)
        shell_layout.addWidget(weak_list)
        shell_layout.addStretch()
        shell_layout.addLayout(action_layout)

        outer_layout.addWidget(shell)

        self.setStyleSheet(
            """
            QDialog {
                background-color: #091017;
            }

            QFrame#EvaluationShell {
                background-color: #101923;
                border: 1px solid #31475c;
                border-radius: 9px;
            }

            QLabel {
                font-family: "PingFang SC", "Helvetica Neue", Arial;
            }

            QLabel#EvaluationTitle {
                color: #f7fbff;
                font-size: 22px;
                font-weight: 700;
            }

            QLabel#EvaluationSubtitle,
            QLabel#EvaluationFooterHint {
                color: #8fa0b2;
                font-size: 12px;
                font-weight: 500;
            }

            QLabel#EvaluationBadge {
                background-color: #351a22;
                border: 1px solid #9a3f4c;
                border-radius: 7px;
                color: #ff8d97;
                font-size: 11px;
                font-weight: 800;
            }

            QFrame#EvaluationHero {
                background-color: #172331;
                border: 1px solid #30465a;
                border-radius: 8px;
            }

            QLabel#EvaluationAccuracyCaption {
                color: #9fb0c2;
                font-size: 12px;
                font-weight: 600;
            }

            QLabel#EvaluationAccuracyValue {
                color: #f2c255;
                font-size: 34px;
                font-weight: 800;
            }

            QProgressBar#EvaluationAccuracyBar,
            QProgressBar#EvaluationClassBar {
                background-color: #071018;
                border: 0;
                border-radius: 3px;
            }

            QProgressBar#EvaluationAccuracyBar::chunk {
                background-color: #f2b63e;
                border-radius: 3px;
            }

            QFrame#EvaluationMetric {
                background-color: #0f1923;
                border: 1px solid #263847;
                border-radius: 7px;
            }

            QLabel#EvaluationMetricTitle {
                color: #8fa0b2;
                font-size: 10px;
                font-weight: 600;
            }

            QLabel#EvaluationMetricValue {
                color: #dce8f2;
                font-size: 22px;
                font-weight: 800;
            }

            QLabel#EvaluationMetricValue[tone="good"] {
                color: #59d7a8;
            }

            QLabel#EvaluationMetricValue[tone="bad"] {
                color: #ff7b86;
            }

            QLabel#EvaluationSectionTitle {
                color: #f2f6fb;
                font-size: 14px;
                font-weight: 700;
            }

            QFrame#EvaluationClassRow {
                background-color: #0f1923;
                border: 1px solid #263847;
                border-radius: 7px;
            }

            QLabel#EvaluationClassRank {
                color: #ff7b86;
                font-size: 12px;
                font-weight: 800;
            }

            QLabel#EvaluationClassName {
                color: #f3f7fb;
                font-size: 12px;
                font-weight: 650;
            }

            QLabel#EvaluationClassDetail,
            QLabel#EvaluationClassAccuracy {
                color: #97a9ba;
                font-size: 11px;
                font-weight: 600;
            }

            QProgressBar#EvaluationClassBar::chunk {
                background-color: #527895;
                border-radius: 3px;
            }

            QProgressBar#EvaluationClassBar[critical="true"]::chunk {
                background-color: #ff4655;
            }

            QPushButton#EvaluationCloseButton,
            QPushButton#EvaluationReviewButton {
                border-radius: 7px;
                font-family: "PingFang SC", "Helvetica Neue", Arial;
                font-size: 12px;
                font-weight: 700;
                min-height: 36px;
                padding: 3px 16px;
            }

            QPushButton#EvaluationCloseButton {
                background-color: #263646;
                border: 1px solid #3d5062;
                color: #f5f9fc;
            }

            QPushButton#EvaluationCloseButton:hover {
                background-color: #304254;
            }

            QPushButton#EvaluationReviewButton {
                background-color: #ff4655;
                border: 1px solid #ff7580;
                color: #ffffff;
            }

            QPushButton#EvaluationReviewButton:hover {
                background-color: #ff5967;
            }

            QPushButton#EvaluationReviewButton:disabled {
                background-color: #1a222d;
                border-color: #273341;
                color: #657386;
            }
            """
        )

    def _create_metric(self, title, value, tone):
        metric = QFrame()
        metric.setObjectName("EvaluationMetric")
        metric.setMinimumWidth(92)

        layout = QVBoxLayout(metric)
        layout.setContentsMargins(11, 9, 11, 9)
        layout.setSpacing(1)

        title_label = QLabel(title)
        title_label.setObjectName("EvaluationMetricTitle")

        value_label = QLabel(str(value))
        value_label.setObjectName("EvaluationMetricValue")
        value_label.setProperty("tone", tone)

        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return metric

    def _ranked_classes(self, summary):
        ranked = []

        for class_name, result in summary.get(
            "class_results",
            {}
        ).items():
            total = int(result.get("total", 0))
            accuracy = result.get("accuracy")

            if total <= 0 or accuracy is None:
                continue

            ranked.append((
                class_name,
                int(result.get("correct", 0)),
                total,
                float(accuracy)
            ))

        ranked.sort(key=lambda item: (item[3], -item[2]))
        return ranked

    def _create_class_row(
        self,
        rank,
        class_name,
        correct,
        total,
        accuracy
    ):
        row = QFrame()
        row.setObjectName("EvaluationClassRow")
        row.setFixedHeight(48)

        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        rank_label = QLabel(f"#{rank}")
        rank_label.setObjectName("EvaluationClassRank")
        rank_label.setFixedWidth(30)

        name_label = QLabel(class_name)
        name_label.setObjectName("EvaluationClassName")
        name_label.setFixedWidth(116)

        detail_label = QLabel(f"{correct}/{total}")
        detail_label.setObjectName("EvaluationClassDetail")
        detail_label.setFixedWidth(48)

        bar = QProgressBar()
        bar.setObjectName("EvaluationClassBar")
        bar.setProperty("critical", accuracy < 25)
        bar.setRange(0, 10000)
        bar.setValue(round(accuracy * 100))
        bar.setTextVisible(False)
        bar.setFixedHeight(6)

        accuracy_label = QLabel(f"{accuracy:.2f}%")
        accuracy_label.setObjectName(
            "EvaluationClassAccuracy"
        )
        accuracy_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        accuracy_label.setFixedWidth(62)

        layout.addWidget(rank_label)
        layout.addWidget(name_label)
        layout.addWidget(detail_label)
        layout.addWidget(bar, 1)
        layout.addWidget(accuracy_label)
        return row

    def _request_review(self):
        self.start_review_requested = True
        self.accept()


class ConfirmDialog(QDialog):
    def __init__(
        self,
        parent,
        title,
        message,
        confirm_text="确认",
        cancel_text="取消"
    ):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlags(
            Qt.Dialog | Qt.FramelessWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(24, 24, 24, 24)

        card = QFrame()
        card.setObjectName("ConfirmCard")

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 14)
        shadow.setColor(QColor(0, 0, 0, 170))
        card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 22, 24, 22)
        card_layout.setSpacing(16)

        title_label = QLabel(title)
        title_label.setObjectName("ConfirmTitle")
        title_label.setWordWrap(True)

        message_label = QLabel(message)
        message_label.setObjectName("ConfirmMessage")
        message_label.setWordWrap(True)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_button = QPushButton(cancel_text)
        cancel_button.setObjectName("ConfirmCancelButton")
        cancel_button.clicked.connect(self.reject)

        confirm_button = QPushButton(confirm_text)
        confirm_button.setObjectName("ConfirmDangerButton")
        confirm_button.clicked.connect(self.accept)

        button_layout.addWidget(cancel_button)
        button_layout.addWidget(confirm_button)

        card_layout.addWidget(title_label)
        card_layout.addWidget(message_label)
        card_layout.addLayout(button_layout)

        outer_layout.addWidget(card)

        self.setStyleSheet(
            """
            QFrame#ConfirmCard {
                background-color: #101923;
                border: 1px solid #9a3f4c;
                border-radius: 10px;
            }

            QLabel#ConfirmTitle {
                color: #f7fbff;
                font-family: "PingFang SC", "Helvetica Neue", Arial;
                font-size: 20px;
                font-weight: 700;
            }

            QLabel#ConfirmMessage {
                color: #b7c5d4;
                font-family: "PingFang SC", "Helvetica Neue", Arial;
                font-size: 14px;
                font-weight: 500;
            }

            QPushButton#ConfirmCancelButton,
            QPushButton#ConfirmDangerButton {
                border-radius: 7px;
                font-family: "PingFang SC", "Helvetica Neue", Arial;
                font-size: 13px;
                font-weight: 700;
                min-width: 96px;
                min-height: 36px;
                padding: 4px 16px;
            }

            QPushButton#ConfirmCancelButton {
                background-color: #263646;
                border: 1px solid #3d5062;
                color: #f7fbff;
            }

            QPushButton#ConfirmCancelButton:hover {
                background-color: #304254;
            }

            QPushButton#ConfirmDangerButton {
                background-color: #9a3f4c;
                border: 1px solid #c05a69;
                color: #ffffff;
            }

            QPushButton#ConfirmDangerButton:hover {
                background-color: #ad4b59;
            }
            """
        )


class TrainingMapDialog(QDialog):
    def __init__(
        self,
        parent,
        map_names,
        selected_map
    ):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlags(
            Qt.Dialog | Qt.FramelessWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumWidth(500)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(24, 24, 24, 24)

        card = QFrame()
        card.setObjectName("TrainingMapCard")

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 14)
        shadow.setColor(QColor(0, 0, 0, 170))
        card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(26, 24, 26, 22)
        card_layout.setSpacing(14)

        eyebrow_label = QLabel("QUICK TRAIN")
        eyebrow_label.setObjectName("TrainingMapEyebrow")

        title_label = QLabel("选择训练地图")
        title_label.setObjectName("TrainingMapTitle")

        message_label = QLabel(
            "每张地图使用独立训练集、纠错记录与过滤器。"
        )
        message_label.setObjectName("TrainingMapMessage")
        message_label.setWordWrap(True)

        field_label = QLabel("训练地图")
        field_label.setObjectName("TrainingMapFieldLabel")

        self.map_combo = BorderlessComboBox()
        self.map_combo.setObjectName("TrainingMapSelector")

        for map_name in map_names:
            self.map_combo.addItem(map_name, map_name)

        selected_index = self.map_combo.findData(
            selected_map
        )
        self.map_combo.setCurrentIndex(
            selected_index if selected_index >= 0 else 0
        )
        self.map_combo.currentIndexChanged.connect(
            self._refresh_stats
        )

        self.stats_label = QLabel()
        self.stats_label.setObjectName("TrainingMapStats")
        self.stats_label.setWordWrap(True)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        button_layout.addStretch()

        cancel_button = QPushButton("取消")
        cancel_button.setObjectName("TrainingMapCancel")
        cancel_button.clicked.connect(self.reject)

        train_button = QPushButton("开始训练")
        train_button.setObjectName("TrainingMapConfirm")
        train_button.clicked.connect(self.accept)

        button_layout.addWidget(cancel_button)
        button_layout.addWidget(train_button)

        card_layout.addWidget(eyebrow_label)
        card_layout.addWidget(title_label)
        card_layout.addWidget(message_label)
        card_layout.addSpacing(2)
        card_layout.addWidget(field_label)
        card_layout.addWidget(self.map_combo)
        card_layout.addWidget(self.stats_label)
        card_layout.addSpacing(2)
        card_layout.addLayout(button_layout)
        outer_layout.addWidget(card)

        self.setStyleSheet(
            """
            QFrame#TrainingMapCard {
                background-color: #101923;
                border: 1px solid #415848;
                border-radius: 10px;
            }

            QLabel#TrainingMapEyebrow {
                color: #8ea477;
                font-family: "Helvetica Neue", Arial;
                font-size: 10px;
                font-weight: 800;
            }

            QLabel#TrainingMapTitle {
                color: #f7fbff;
                font-family: "PingFang SC", "Helvetica Neue", Arial;
                font-size: 21px;
                font-weight: 750;
            }

            QLabel#TrainingMapMessage,
            QLabel#TrainingMapStats {
                color: #9fb0c1;
                font-family: "PingFang SC", "Helvetica Neue", Arial;
                font-size: 13px;
                font-weight: 500;
            }

            QLabel#TrainingMapFieldLabel {
                color: #dce6ef;
                font-family: "PingFang SC", "Helvetica Neue", Arial;
                font-size: 12px;
                font-weight: 700;
            }

            QComboBox#TrainingMapSelector {
                min-height: 40px;
                padding: 2px 12px;
                background-color: #162432;
                border: 1px solid #365168;
                border-radius: 7px;
                color: #f7fbff;
                font-family: "PingFang SC", "Helvetica Neue", Arial;
                font-size: 14px;
                font-weight: 700;
            }

            QComboBox#TrainingMapSelector::drop-down {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 34px;
                background-color: transparent;
                border: 0;
            }

            QComboBox#TrainingMapSelector::down-arrow {
                image: none;
                width: 0;
                height: 0;
            }

            QComboBox#TrainingMapSelector:hover,
            QComboBox#TrainingMapSelector:focus {
                border-color: #71915d;
            }

            QComboBox#TrainingMapSelector QAbstractItemView {
                background-color: #162432;
                border: 1px solid #365168;
                color: #f7fbff;
                selection-background-color: #334936;
                selection-color: #ffffff;
                padding: 4px;
            }

            QPushButton#TrainingMapCancel,
            QPushButton#TrainingMapConfirm {
                border-radius: 7px;
                font-family: "PingFang SC", "Helvetica Neue", Arial;
                font-size: 13px;
                font-weight: 700;
                min-width: 96px;
                min-height: 36px;
                padding: 4px 16px;
            }

            QPushButton#TrainingMapCancel {
                background-color: #263646;
                border: 1px solid #3d5062;
                color: #f7fbff;
            }

            QPushButton#TrainingMapCancel:hover {
                background-color: #304254;
            }

            QPushButton#TrainingMapConfirm {
                background-color: #526a43;
                border: 1px solid #71915d;
                color: #ffffff;
            }

            QPushButton#TrainingMapConfirm:hover {
                background-color: #607c4e;
            }
            """
        )
        self._refresh_stats()

    @property
    def selected_map(self):
        return self.map_combo.currentData()

    def _refresh_stats(self):
        map_name = self.selected_map
        train_root = SOURCE_DATA_DIR / "train" / map_name
        feedback_root = (
            DATA_DIR / "feedback" / map_name
        )
        image_count = self._count_images(train_root)
        feedback_count = self._count_images(feedback_root)
        class_count = 0

        if train_root.exists():
            class_count = sum(
                1
                for path in train_root.iterdir()
                if path.is_dir()
                and self._count_images(path) > 0
            )

        self.stats_label.setText(
            f"{image_count} 张基础图片  ·  "
            f"{class_count} 个区域  ·  "
            f"{feedback_count} 张纠错图片"
        )

    @staticmethod
    def _count_images(root):
        if not root.exists():
            return 0

        return sum(
            1
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in IMAGE_EXTENSIONS
        )


class HistoryDialog(QDialog):
    def __init__(
        self,
        parent,
        records,
        skipped_count=0,
        on_clear_history=None
    ):
        super().__init__(parent)
        self.on_clear_history = on_clear_history
        self.history_cleared = False
        self.setModal(True)
        self.setWindowTitle("历史记录")
        self.resize(820, 620)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(20, 20, 20, 20)

        shell = QFrame()
        shell.setObjectName("HistoryShell")

        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(22, 20, 22, 20)
        shell_layout.setSpacing(16)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(14)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(4)

        title_label = QLabel("历史记录")
        title_label.setObjectName("HistoryTitle")

        correct_count = sum(
            1 for record in records
            if record.get("was_correct") is True
        )
        correction_count = sum(
            1 for record in records
            if record.get("was_correct") is False
        )

        summary_text = f"共 {len(records)} 条反馈记录"

        if skipped_count:
            summary_text += f" / 已跳过 {skipped_count} 条异常记录"

        summary_label = QLabel(summary_text)
        summary_label.setObjectName("HistorySubtitle")

        title_layout.addWidget(title_label)
        title_layout.addWidget(summary_label)

        clear_button = QPushButton("清空正确记录")
        clear_button.setObjectName("HistoryClearButton")
        clear_button.setEnabled(correct_count > 0)
        clear_button.clicked.connect(
            self._confirm_clear_history
        )

        close_button = QPushButton("关闭")
        close_button.setObjectName("HistoryCloseButton")
        close_button.clicked.connect(self.accept)

        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        header_layout.addWidget(clear_button)
        header_layout.addWidget(close_button)

        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(10)

        metrics_layout.addWidget(
            self._create_metric("总记录", len(records))
        )
        metrics_layout.addWidget(
            self._create_metric("预测正确", correct_count)
        )
        metrics_layout.addWidget(
            self._create_metric("纠错记录", correction_count)
        )

        scroll_area = QScrollArea()
        scroll_area.setObjectName("HistoryScroll")
        scroll_area.setWidgetResizable(True)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(10)

        if records:
            for record in records[:120]:
                scroll_layout.addWidget(
                    self._create_record_card(record)
                )

            if len(records) > 120:
                more_label = QLabel(
                    f"仅显示最新 120 条，还有 {len(records) - 120} 条未显示。"
                )
                more_label.setObjectName("HistorySubtitle")
                more_label.setAlignment(Qt.AlignCenter)
                scroll_layout.addWidget(more_label)
        else:
            empty_label = QLabel("还没有历史记录。")
            empty_label.setObjectName("HistoryEmpty")
            empty_label.setAlignment(Qt.AlignCenter)
            scroll_layout.addWidget(empty_label)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_content)

        shell_layout.addLayout(header_layout)
        shell_layout.addLayout(metrics_layout)
        shell_layout.addWidget(scroll_area)

        outer_layout.addWidget(shell)

        self.setStyleSheet(
            """
            QDialog {
                background-color: #091017;
            }

            QFrame#HistoryShell {
                background-color: #101923;
                border: 1px solid #31475c;
                border-radius: 10px;
            }

            QLabel {
                font-family: "PingFang SC", "Helvetica Neue", Arial;
            }

            QLabel#HistoryTitle {
                color: #f7fbff;
                font-size: 22px;
                font-weight: 700;
            }

            QLabel#HistorySubtitle {
                color: #9aa8b8;
                font-size: 13px;
            }

            QFrame#HistoryMetric {
                background-color: #172331;
                border: 1px solid #2b3d50;
                border-radius: 8px;
            }

            QLabel#HistoryMetricValue {
                color: #d8ad4f;
                font-size: 24px;
                font-weight: 800;
            }

            QLabel#HistoryMetricTitle {
                color: #9aa8b8;
                font-size: 12px;
                font-weight: 600;
            }

            QScrollArea#HistoryScroll {
                background-color: transparent;
                border: 0;
            }

            QScrollArea#HistoryScroll QWidget {
                background-color: transparent;
            }

            QFrame#HistoryRecord {
                background-color: #0f1923;
                border: 1px solid #263847;
                border-radius: 8px;
            }

            QFrame#HistoryRecordGood {
                background-color: #11241e;
                border: 1px solid #1d5c49;
                border-radius: 8px;
            }

            QLabel#HistoryBadgeGood {
                background-color: #123629;
                border: 1px solid #21a67c;
                border-radius: 7px;
                color: #8ef0c1;
                font-size: 12px;
                font-weight: 700;
                padding: 6px 10px;
            }

            QLabel#HistoryBadgeBad {
                background-color: #351a22;
                border: 1px solid #9a3f4c;
                border-radius: 7px;
                color: #ff9aa4;
                font-size: 12px;
                font-weight: 700;
                padding: 6px 10px;
            }

            QLabel#HistoryRecordTitle {
                color: #f7fbff;
                font-size: 15px;
                font-weight: 700;
            }

            QLabel#HistoryRecordMeta {
                color: #9aa8b8;
                font-size: 12px;
            }

            QLabel#HistoryConfidence {
                color: #d8ad4f;
                font-size: 16px;
                font-weight: 800;
            }

            QLabel#HistoryEmpty {
                color: #9aa8b8;
                font-size: 15px;
                min-height: 160px;
            }

            QPushButton#HistoryCloseButton,
            QPushButton#HistoryClearButton {
                background-color: #263646;
                border: 1px solid #3d5062;
                border-radius: 7px;
                color: #f7fbff;
                font-family: "PingFang SC", "Helvetica Neue", Arial;
                font-size: 13px;
                font-weight: 600;
                min-width: 82px;
                min-height: 34px;
            }

            QPushButton#HistoryCloseButton:hover {
                background-color: #304254;
                border-color: #5c7388;
            }

            QPushButton#HistoryClearButton {
                background-color: #351a22;
                border-color: #9a3f4c;
                color: #ffb3bb;
            }

            QPushButton#HistoryClearButton:hover {
                background-color: #4a2029;
                border-color: #c05a69;
            }

            QPushButton#HistoryClearButton:disabled {
                background-color: #1a222d;
                border-color: #273341;
                color: #657386;
            }
            """
        )

    def _confirm_clear_history(self):
        if not self.on_clear_history:
            return

        dialog = ConfirmDialog(
            self,
            "清空预测正确历史？",
            (
                "只会清空“预测正确”的历史记录，纠错记录会保留。"
                "地图图片文件也不会被删除。"
            ),
            confirm_text="清空正确记录",
            cancel_text="取消"
        )

        if dialog.exec() != QDialog.Accepted:
            return

        if self.on_clear_history():
            self.history_cleared = True
            self.accept()

    def _create_metric(self, title, value):
        metric = QFrame()
        metric.setObjectName("HistoryMetric")

        layout = QVBoxLayout(metric)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)

        value_label = QLabel(str(value))
        value_label.setObjectName("HistoryMetricValue")

        title_label = QLabel(title)
        title_label.setObjectName("HistoryMetricTitle")

        layout.addWidget(value_label)
        layout.addWidget(title_label)

        return metric

    def _create_record_card(self, record):
        was_correct = record.get("was_correct") is True

        card = QFrame()

        if was_correct:
            card.setObjectName("HistoryRecordGood")
        else:
            card.setObjectName("HistoryRecord")

        layout = QHBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        badge = QLabel(
            "正确" if was_correct else "纠错"
        )
        badge.setObjectName(
            "HistoryBadgeGood" if was_correct
            else "HistoryBadgeBad"
        )
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedWidth(62)

        predicted = record.get("predicted_class", "未知")
        correct = record.get("correct_class", "未知")
        map_name = record.get("map_name", "Ascent")

        if was_correct:
            title = f"{map_name} · 预测：{predicted}"
        else:
            title = f"{map_name} · {predicted} → {correct}"

        title_label = QLabel(title)
        title_label.setObjectName("HistoryRecordTitle")

        image_path = self._record_image_path(record)
        image_name = (
            Path(image_path).name
            if image_path
            else "未知图片"
        )
        timestamp = str(
            record.get("timestamp", "未知时间")
        ).replace("T", " ")

        meta_label = QLabel(
            f"{timestamp} · {image_name}"
        )
        meta_label.setObjectName("HistoryRecordMeta")
        meta_label.setWordWrap(True)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        text_layout.addWidget(title_label)
        text_layout.addWidget(meta_label)

        confidence = record.get("confidence")

        if isinstance(confidence, (int, float)):
            confidence_text = f"{confidence * 100:.2f}%"
        else:
            confidence_text = "--"

        confidence_label = QLabel(confidence_text)
        confidence_label.setObjectName("HistoryConfidence")
        confidence_label.setAlignment(
            Qt.AlignRight | Qt.AlignVCenter
        )
        confidence_label.setFixedWidth(92)

        layout.addWidget(badge)
        layout.addLayout(text_layout, 1)
        layout.addWidget(confidence_label)

        return card

    def _record_image_path(self, record):
        return (
            record.get("image")
            or record.get("source_image")
            or record.get("training_image")
            or record.get("saved_image")
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Valorant 多地图区域识别器")
        if APP_ICON_PATH.exists():
            self.setWindowIcon(
                QIcon(str(APP_ICON_PATH))
            )
        self.resize(1240, 820)
        self.setMinimumSize(1080, 700)

        self.current_image_path = None
        self.current_prediction = None
        self.current_map_name = None
        self.training_process = None
        self.training_map_name = None
        self.training_log_tail = []
        self.evaluation_process = None
        self.evaluation_map_name = None
        self.evaluation_log_tail = []
        self.batch_image_paths = []
        self.batch_index = -1
        self.batch_active = False
        self.batch_correct_count = 0
        self.batch_correction_count = 0
        self.batch_skipped_count = 0
        self.batch_irrelevant_count = 0
        self.batch_expected_classes = {}
        self.batch_kind = "manual"

        try:
            self.model_service = ModelService()
        except Exception as error:
            QMessageBox.critical(
                self,
                "模型加载失败",
                str(error)
            )
            raise

        self._build_ui()

    def _build_ui(self):
        central_widget = QWidget()
        central_widget.setObjectName("Root")
        self.setCentralWidget(central_widget)

        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(16)

        top_bar = QFrame()
        top_bar.setObjectName("TopBar")

        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(16, 10, 16, 10)
        top_layout.setSpacing(12)

        brand_icon = QLabel()
        brand_icon.setObjectName("BrandIcon")
        brand_icon.setFixedSize(44, 44)
        brand_icon.setAlignment(Qt.AlignCenter)

        if APP_ICON_PATH.exists():
            icon_pixmap = QPixmap(str(APP_ICON_PATH))
            brand_icon.setPixmap(
                icon_pixmap.scaled(
                    40,
                    40,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
            )
        else:
            brand_icon.setText("A")

        brand_text_layout = QVBoxLayout()
        brand_text_layout.setSpacing(2)

        app_title = QLabel("Valorant Map Recognizer")
        app_title.setObjectName("BrandTitle")

        app_subtitle = QLabel("多地图识别 / 区域预测 / 反馈校正")
        app_subtitle.setObjectName("BrandSubtitle")

        brand_text_layout.addWidget(app_title)
        brand_text_layout.addWidget(app_subtitle)

        system_status = QFrame()
        system_status.setObjectName("SystemStatus")
        system_status.setFixedHeight(42)
        system_status.setToolTip(
            "模型与反馈数据连接状态"
        )

        system_status_layout = QHBoxLayout(system_status)
        system_status_layout.setContentsMargins(11, 5, 12, 5)
        system_status_layout.setSpacing(9)

        system_status_dot = QLabel()
        system_status_dot.setObjectName("SystemStatusDot")
        system_status_dot.setFixedSize(8, 8)

        system_status_text_layout = QVBoxLayout()
        system_status_text_layout.setContentsMargins(0, 0, 0, 0)
        system_status_text_layout.setSpacing(0)

        self.model_status_label = QLabel(
            f"{len(self.model_service.map_names)} 个模型已加载"
        )
        self.model_status_label.setObjectName(
            "SystemStatusPrimary"
        )
        self.feedback_status_label = QLabel(
            f"{len(self.model_service.map_names)} 地图已开启"
            if self.model_service.relevance_available
            else "过滤器未就绪"
        )
        self.feedback_status_label.setObjectName(
            "SystemStatusSecondary"
        )
        self.feedback_status_label.setToolTip(
            self.model_service.relevance_status
        )

        system_status_text_layout.addWidget(
            self.model_status_label
        )
        system_status_text_layout.addWidget(
            self.feedback_status_label
        )
        system_status_layout.addWidget(system_status_dot)
        system_status_layout.addLayout(
            system_status_text_layout
        )

        self.history_button = QPushButton("历史")
        self.history_button.setObjectName("HeaderToolButton")
        self.history_button.setProperty("variant", "history")
        self.history_button.setToolTip("查看预测与纠错历史")
        self.history_button.clicked.connect(
            self.show_history
        )

        self.quick_train_button = QPushButton("训练")
        self.quick_train_button.setObjectName(
            "HeaderToolButton"
        )
        self.quick_train_button.setProperty("variant", "training")
        self.quick_train_button.setToolTip(
            "选择地图并使用对应反馈快速训练"
        )
        self.quick_train_button.clicked.connect(
            self.start_quick_training
        )

        self.evaluate_button = QPushButton("评估")
        self.evaluate_button.setObjectName("HeaderToolButton")
        self.evaluate_button.setProperty("variant", "evaluate")
        self.evaluate_button.setToolTip(
            "使用测试集评估当前模型"
        )
        self.evaluate_button.clicked.connect(
            self.start_evaluation
        )

        self.wrong_cases_button = QPushButton("错题")
        self.wrong_cases_button.setObjectName(
            "HeaderToolButton"
        )
        self.wrong_cases_button.setProperty(
            "variant",
            "review"
        )
        self.wrong_cases_button.setToolTip(
            "复核最近一次评估中的错误图片"
        )
        self.wrong_cases_button.setEnabled(
            ENABLE_MODEL_TOOLS
            and (
                any(
                    (
                        evaluation_dir(map_name)
                        / "report.csv"
                    ).exists()
                    for map_name in self.model_service.map_names
                )
                or LEGACY_EVALUATION_REPORT_PATH.exists()
            )
        )
        self.wrong_cases_button.clicked.connect(
            lambda: self.start_wrong_case_review()
        )

        header_tools = QFrame()
        header_tools.setObjectName("HeaderToolGroup")
        header_tools.setFixedHeight(42)

        header_tools_layout = QHBoxLayout(header_tools)
        header_tools_layout.setContentsMargins(3, 3, 3, 3)
        header_tools_layout.setSpacing(2)
        self.quick_train_button.setVisible(ENABLE_MODEL_TOOLS)
        self.evaluate_button.setVisible(ENABLE_MODEL_TOOLS)
        self.wrong_cases_button.setVisible(ENABLE_MODEL_TOOLS)

        if ENABLE_MODEL_TOOLS:
            header_tools_layout.addWidget(
                self.quick_train_button
            )
            header_tools_layout.addWidget(
                self.evaluate_button
            )
            header_tools_layout.addWidget(
                self.wrong_cases_button
            )

        header_tools_layout.addWidget(
            self.history_button
        )

        tactical_mark = TacticalMark()
        tactical_mark.setToolTip("战术识别标识")

        studio_mark = StudioMark()
        studio_mark.setToolTip("反馈数据标识")

        mark_layout = QHBoxLayout()
        mark_layout.setSpacing(8)
        mark_layout.addWidget(tactical_mark)
        mark_layout.addWidget(studio_mark)

        top_layout.addWidget(brand_icon)
        top_layout.addLayout(brand_text_layout)
        top_layout.addStretch()
        top_layout.addWidget(header_tools)
        top_layout.addWidget(system_status)
        top_layout.addLayout(mark_layout)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(18)

        # 左侧：上传与图片区域
        left_panel = QFrame()
        left_panel.setObjectName("WorkspacePanel")

        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(14)

        self.upload_bar = QFrame()
        self.upload_bar.setObjectName("UploadBar")
        self.upload_bar.setProperty("mode", "single")
        self.upload_bar.setFixedHeight(66)

        upload_layout = QHBoxLayout(self.upload_bar)
        upload_layout.setContentsMargins(16, 9, 16, 9)
        upload_layout.setSpacing(14)

        self.upload_accent = QFrame()
        self.upload_accent.setObjectName("UploadAccent")
        self.upload_accent.setProperty("mode", "single")
        self.upload_accent.setFixedSize(3, 34)

        upload_text_layout = QVBoxLayout()
        upload_text_layout.setSpacing(4)

        self.upload_title_label = QLabel("地图截图")
        self.upload_title_label.setObjectName("UploadTitle")

        self.upload_file_label = QLabel(
            "JPG · PNG · WEBP · BMP"
        )
        self.upload_file_label.setObjectName("UploadHint")
        self.upload_file_label.setWordWrap(True)

        upload_text_layout.addWidget(self.upload_title_label)
        upload_text_layout.addWidget(self.upload_file_label)

        self.select_button = QPushButton("选择图片")
        self.select_button.setProperty("variant", "secondary")
        self.select_button.clicked.connect(
            self.select_image
        )

        mode_switch = QFrame()
        mode_switch.setObjectName("ModeSwitch")
        mode_switch.setFixedHeight(42)

        mode_switch_layout = QHBoxLayout(mode_switch)
        mode_switch_layout.setContentsMargins(3, 3, 3, 3)
        mode_switch_layout.setSpacing(2)

        self.single_mode_button = QPushButton("单张识别")
        self.single_mode_button.setObjectName("ModeButton")
        self.single_mode_button.setProperty("mode", "single")
        self.single_mode_button.setProperty("active", True)
        self.single_mode_button.setToolTip("切换到单张图片识别")
        self.single_mode_button.clicked.connect(
            self.activate_single_mode
        )

        self.batch_button = QPushButton("批量纠错")
        self.batch_button.setObjectName("ModeButton")
        self.batch_button.setProperty("mode", "batch")
        self.batch_button.setProperty("active", False)
        self.batch_button.setToolTip("选择多张图片连续预测并纠错")
        self.batch_button.clicked.connect(
            self.toggle_batch_correction
        )

        mode_switch_layout.addWidget(
            self.single_mode_button
        )
        mode_switch_layout.addWidget(self.batch_button)

        self.predict_button = QPushButton("开始预测")
        self.predict_button.setProperty("variant", "primary")
        self.predict_button.setEnabled(False)
        self.predict_button.clicked.connect(
            self.run_prediction
        )

        upload_layout.addWidget(self.upload_accent)
        upload_layout.addLayout(upload_text_layout, 1)
        upload_layout.addWidget(mode_switch)
        upload_layout.addWidget(self.select_button)
        upload_layout.addWidget(self.predict_button)

        self.image_label = ImagePreviewLabel(
            self.load_image
        )
        self.image_label.setObjectName("MapPreview")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(620, 460)
        self.image_label.set_empty_state(
            "拖入地图截图",
            "或点击上方选择图片"
        )

        left_layout.addWidget(self.upload_bar)
        left_layout.addWidget(self.image_label, 1)

        # 右侧：预测与反馈区域
        right_panel = QFrame()
        right_panel.setObjectName("IntelPanel")

        right_panel_layout = QVBoxLayout(right_panel)
        right_panel_layout.setContentsMargins(0, 0, 0, 0)
        right_panel_layout.setSpacing(0)

        right_scroll_area = QScrollArea()
        right_scroll_area.setObjectName("IntelScroll")
        right_scroll_area.setWidgetResizable(True)
        right_scroll_area.setFrameShape(QFrame.NoFrame)
        right_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )

        right_content = QWidget()
        right_content.setObjectName("IntelContent")

        right_layout = QVBoxLayout(right_content)
        right_layout.setContentsMargins(18, 16, 18, 16)
        right_layout.setSpacing(10)

        title_label = QLabel("区域识别")
        title_label.setObjectName("PanelTitle")

        panel_header_layout = QHBoxLayout()
        panel_header_layout.setContentsMargins(0, 0, 0, 0)
        panel_header_layout.setSpacing(10)

        self.map_combo = BorderlessComboBox()
        self.map_combo.setObjectName("MapSelector")
        self.map_combo.setToolTip(
            "自动识别地图，或锁定一张地图"
        )
        self.map_combo.setFixedWidth(116)
        self.map_combo.addItem("自动地图", AUTO_MAP)

        for map_name in self.model_service.map_names:
            self.map_combo.addItem(map_name, map_name)

        self.map_combo.currentIndexChanged.connect(
            self._handle_map_mode_changed
        )

        panel_header_layout.addWidget(title_label)
        panel_header_layout.addStretch()
        panel_header_layout.addWidget(self.map_combo)

        title_hint = QLabel("最高匹配结果与 Top 3 置信度")
        title_hint.setObjectName("PanelHint")

        self.result_card = QFrame()
        self.result_card.setObjectName("PrimaryResult")

        result_layout = QHBoxLayout(self.result_card)
        result_layout.setContentsMargins(14, 14, 14, 14)
        result_layout.setSpacing(12)

        result_text_layout = QVBoxLayout()
        result_text_layout.setSpacing(4)

        self.result_caption_label = QLabel("最高匹配区域")
        self.result_caption_label.setObjectName("CardCaption")

        self.best_result_label = QLabel("等待地图")
        self.best_result_label.setObjectName("BestResult")
        self.best_result_label.setWordWrap(True)

        self.confidence_caption_label = QLabel("可信度")
        self.confidence_caption_label.setObjectName(
            "CardCaption"
        )

        self.confidence_label = QLabel("--")
        self.confidence_label.setObjectName("Confidence")

        result_text_layout.addWidget(
            self.result_caption_label
        )
        result_text_layout.addWidget(self.best_result_label)
        result_text_layout.addSpacing(6)
        result_text_layout.addWidget(
            self.confidence_caption_label
        )
        result_text_layout.addWidget(self.confidence_label)

        self.result_rank_label = QLabel("#1")
        self.result_rank_label.setObjectName("ResultRank")
        self.result_rank_label.setAlignment(Qt.AlignCenter)
        self.result_rank_label.setFixedSize(60, 60)

        result_layout.addLayout(result_text_layout)
        result_layout.addStretch()
        result_layout.addWidget(self.result_rank_label)

        self.top_three_title = QLabel("Top 3")
        self.top_three_title.setObjectName("SectionTitle")

        self.top_prediction_labels = []
        self.top_cards_container = QWidget()
        self.top_cards_container.setObjectName("PredictionList")
        self.top_cards_container.setMinimumHeight(208)

        top_cards_layout = QVBoxLayout()
        top_cards_layout.setContentsMargins(0, 0, 0, 0)
        top_cards_layout.setSpacing(8)
        self.top_cards_container.setLayout(top_cards_layout)

        for rank in range(1, 4):
            card, name_label, confidence_label, bar = (
                self._create_prediction_card(rank)
            )
            self.top_prediction_labels.append(
                (name_label, confidence_label, bar)
            )
            top_cards_layout.addWidget(card)

        self.feedback_title = QLabel("AI 判断是否正确？")
        self.feedback_title.setObjectName("SectionTitle")

        self.rejection_action_frame = QFrame()
        self.rejection_action_frame.setObjectName(
            "RejectionActions"
        )
        rejection_layout = QVBoxLayout(
            self.rejection_action_frame
        )
        rejection_layout.setContentsMargins(12, 11, 12, 11)
        rejection_layout.setSpacing(8)

        rejection_title = QLabel("未显示区域结果")
        rejection_title.setObjectName("RejectionTitle")

        rejection_hint = QLabel(
            "确认这是支持的地图截图时可以继续识别，"
            "否则将它加入无关图片样本。"
        )
        rejection_hint.setObjectName("RejectionHint")
        rejection_hint.setWordWrap(True)

        rejection_button_layout = QHBoxLayout()
        rejection_button_layout.setSpacing(8)

        self.force_predict_button = QPushButton("仍然识别")
        self.force_predict_button.setProperty(
            "variant",
            "force"
        )
        self.force_predict_button.clicked.connect(
            self.force_current_prediction
        )

        self.irrelevant_button = QPushButton(
            "确认为无关图片"
        )
        self.irrelevant_button.setProperty(
            "variant",
            "irrelevant"
        )
        self.irrelevant_button.clicked.connect(
            self.mark_irrelevant
        )

        rejection_button_layout.addWidget(
            self.force_predict_button
        )
        rejection_button_layout.addWidget(
            self.irrelevant_button
        )
        rejection_layout.addWidget(rejection_title)
        rejection_layout.addWidget(rejection_hint)
        rejection_layout.addLayout(rejection_button_layout)
        self.rejection_action_frame.setVisible(False)

        self.correct_button = QPushButton("预测正确")
        self.correct_button.setProperty("variant", "success")
        self.correct_button.setEnabled(False)
        self.correct_button.clicked.connect(
            self.mark_correct
        )

        self.class_combo = BorderlessComboBox()
        self.class_combo.addItems(
            self.model_service.class_names
        )
        self.class_combo.setEnabled(False)

        self.wrong_button = QPushButton(
            "保存纠正结果"
        )
        self.wrong_button.setProperty("variant", "corrective")
        self.wrong_button.setEnabled(False)
        self.wrong_button.clicked.connect(
            self.mark_wrong
        )

        self.status_label = QLabel("模型已加载")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)

        self.training_progress_frame = QFrame()
        self.training_progress_frame.setObjectName(
            "TrainingProgressPanel"
        )

        training_progress_layout = QVBoxLayout(
            self.training_progress_frame
        )
        training_progress_layout.setContentsMargins(
            12,
            10,
            12,
            10
        )
        training_progress_layout.setSpacing(8)

        training_progress_header = QHBoxLayout()
        training_progress_header.setSpacing(8)

        training_progress_title = QLabel("任务进度")
        training_progress_title.setObjectName(
            "TrainingProgressTitle"
        )

        self.training_progress_percent_label = QLabel("0%")
        self.training_progress_percent_label.setObjectName(
            "TrainingProgressPercent"
        )
        self.training_progress_percent_label.setAlignment(
            Qt.AlignRight | Qt.AlignVCenter
        )

        self.training_progress_label = QLabel("待机")
        self.training_progress_label.setObjectName(
            "TrainingProgressText"
        )
        self.training_progress_label.setWordWrap(True)

        self.training_progress_bar = QProgressBar()
        self.training_progress_bar.setObjectName(
            "TrainingProgressBar"
        )
        self.training_progress_bar.setRange(0, 100)
        self.training_progress_bar.setValue(0)
        self.training_progress_bar.setTextVisible(False)

        training_progress_header.addWidget(
            training_progress_title
        )
        training_progress_header.addStretch()
        training_progress_header.addWidget(
            self.training_progress_percent_label
        )

        training_progress_layout.addLayout(
            training_progress_header
        )
        training_progress_layout.addWidget(
            self.training_progress_bar
        )
        training_progress_layout.addWidget(
            self.training_progress_label
        )

        self.class_hint_label = QLabel(
            "若错误，请选择正确区域："
        )
        self.class_hint_label.setObjectName("HintLabel")

        right_layout.addLayout(panel_header_layout)
        right_layout.addWidget(title_hint)
        right_layout.addWidget(self.result_card)
        right_layout.addSpacing(8)
        right_layout.addWidget(self.top_three_title)
        right_layout.addWidget(self.top_cards_container)
        right_layout.addSpacing(10)
        right_layout.addWidget(self.feedback_title)
        right_layout.addWidget(self.rejection_action_frame)
        right_layout.addWidget(self.correct_button)
        right_layout.addWidget(self.class_hint_label)
        right_layout.addWidget(self.class_combo)
        right_layout.addWidget(self.wrong_button)
        right_layout.addSpacing(10)
        right_layout.addWidget(self.training_progress_frame)
        right_layout.addWidget(self.status_label)
        right_layout.addStretch()

        right_scroll_area.setWidget(right_content)
        right_panel_layout.addWidget(right_scroll_area)

        content_layout.addWidget(left_panel, 2)
        content_layout.addWidget(right_panel, 1)

        root_layout.addWidget(top_bar)
        root_layout.addLayout(content_layout)

        self.setStyleSheet(
            """
            QWidget#Root {
                background-color: #091017;
            }

            QFrame#TopBar,
            QFrame#WorkspacePanel,
            QFrame#IntelPanel {
                background-color: #111b25;
                border: 1px solid #21303f;
                border-radius: 8px;
            }

            QScrollArea#IntelScroll {
                background-color: transparent;
                border: 0;
            }

            QWidget#IntelContent,
            QWidget#PredictionList {
                background-color: transparent;
            }

            QScrollArea#IntelScroll QScrollBar:vertical {
                background-color: #0b141d;
                border: 0;
                border-radius: 3px;
                width: 6px;
                margin: 4px 1px 4px 1px;
            }

            QScrollArea#IntelScroll QScrollBar::handle:vertical {
                background-color: #334a60;
                border-radius: 3px;
                min-height: 28px;
            }

            QScrollArea#IntelScroll QScrollBar::add-line:vertical,
            QScrollArea#IntelScroll QScrollBar::sub-line:vertical {
                height: 0;
            }

            QLabel {
                color: #d8e3ee;
                font-family: "PingFang SC", "Helvetica Neue", Arial;
                font-size: 14px;
            }

            QLabel#BrandIcon {
                background-color: transparent;
                border: 0;
                color: #ffffff;
                font-size: 18px;
                font-weight: 800;
            }

            QLabel#BrandTitle {
                color: #f7fbff;
                font-size: 18px;
                font-weight: 700;
            }

            QLabel#BrandSubtitle,
            QLabel#PanelHint,
            QLabel#UploadHint,
            QLabel#HintLabel,
            QLabel#StatusLabel {
                color: #9aa8b8;
                font-size: 13px;
            }

            QFrame#HeaderToolGroup {
                background-color: #0a121a;
                border: 1px solid #263747;
                border-radius: 8px;
            }

            QPushButton#HeaderToolButton {
                background-color: transparent;
                border: 0;
                border-radius: 5px;
                color: #b8c7d8;
                font-size: 12px;
                font-weight: 650;
                min-height: 30px;
                min-width: 48px;
                padding: 2px 10px;
            }

            QPushButton#HeaderToolButton:hover {
                background-color: #1c2a38;
                color: #f8fbff;
            }

            QPushButton#HeaderToolButton[variant="training"] {
                background-color: #253126;
                color: #f2c255;
            }

            QPushButton#HeaderToolButton[variant="training"]:hover {
                background-color: #33402e;
                color: #ffd66f;
            }

            QPushButton#HeaderToolButton[variant="review"] {
                color: #ff8d97;
            }

            QPushButton#HeaderToolButton[variant="review"]:hover {
                background-color: #351a22;
                color: #ffb1b8;
            }

            QPushButton#HeaderToolButton:disabled {
                background-color: transparent;
                color: #536273;
            }

            QFrame#SystemStatus {
                background-color: #0c171f;
                border: 1px solid #263747;
                border-radius: 8px;
            }

            QLabel#SystemStatusDot {
                background-color: #28c991;
                border: 0;
                border-radius: 4px;
            }

            QLabel#SystemStatusPrimary {
                color: #dce8f2;
                font-size: 11px;
                font-weight: 650;
            }

            QLabel#SystemStatusSecondary {
                color: #708399;
                font-size: 10px;
                font-weight: 550;
            }

            QFrame#UploadBar {
                background-color: #172331;
                border: 1px solid #2b3d50;
                border-radius: 8px;
            }

            QFrame#UploadBar[mode="batch"] {
                background-color: #21191f;
                border-color: #ff4655;
            }

            QFrame#UploadAccent {
                background-color: #49677f;
                border: 0;
                border-radius: 1px;
            }

            QFrame#UploadAccent[mode="batch"] {
                background-color: #ff4655;
            }

            QFrame#ModeSwitch {
                background-color: #0a121a;
                border: 1px solid #304254;
                border-radius: 8px;
            }

            QPushButton#ModeButton {
                background-color: transparent;
                border: 0;
                border-radius: 5px;
                color: #91a2b4;
                font-size: 12px;
                font-weight: 650;
                min-height: 30px;
                min-width: 58px;
                padding: 2px 10px;
            }

            QPushButton#ModeButton:hover {
                background-color: #1c2a38;
                color: #f8fbff;
            }

            QPushButton#ModeButton[active="true"] {
                background-color: #26394b;
                color: #ffffff;
            }

            QPushButton#ModeButton[mode="batch"] {
                color: #ff7b86;
            }

            QPushButton#ModeButton[mode="batch"][active="true"] {
                background-color: #ff4655;
                color: #ffffff;
            }

            QPushButton#ModeButton:disabled {
                background-color: transparent;
                color: #536273;
            }

            QLabel#UploadTitle {
                color: #ffffff;
                font-size: 15px;
                font-weight: 700;
            }

            QLabel#MapPreview {
                background-color: #070d14;
                color: #77869a;
                border: 2px dashed #334a60;
                border-radius: 8px;
                font-size: 16px;
                font-weight: 500;
            }

            QLabel#PanelTitle {
                color: #f8fbff;
                font-size: 20px;
                font-weight: 700;
            }

            QFrame#PrimaryResult {
                background-color: #182636;
                border: 1px solid #344a60;
                border-radius: 8px;
            }

            QFrame#PrimaryResult[state="rejected"] {
                background-color: #211820;
                border-color: #7c4650;
            }

            QLabel#CardCaption {
                color: #9aa8b8;
                font-size: 12px;
                font-weight: 600;
            }

            QLabel#BestResult {
                color: #ffffff;
                font-size: 22px;
                font-weight: 700;
            }

            QLabel#BestResult[state="rejected"] {
                color: #ff9aa3;
            }

            QLabel#Confidence {
                color: #d8ad4f;
                font-size: 28px;
                font-weight: 800;
            }

            QLabel#ResultRank {
                background-color: #26333b;
                border: 1px solid #435158;
                border-radius: 8px;
                color: #d8ad4f;
                font-size: 21px;
                font-weight: 800;
            }

            QLabel#ResultRank[state="rejected"] {
                background-color: #351f28;
                border-color: #82505a;
                color: #ff8d97;
            }

            QFrame#RejectionActions {
                background-color: #15151d;
                border: 1px solid #5d3842;
                border-radius: 8px;
            }

            QLabel#RejectionTitle {
                color: #ff9aa3;
                font-size: 13px;
                font-weight: 700;
            }

            QLabel#RejectionHint {
                color: #a9b5c2;
                font-size: 12px;
                font-weight: 500;
            }

            QFrame#PredictionCard,
            QFrame#PredictionCardPrimary {
                background-color: #0f1923;
                border: 1px solid #263847;
                border-radius: 8px;
            }

            QFrame#PredictionCardPrimary {
                background-color: #23384a;
                border-color: #47637c;
            }

            QLabel#PredictionRank {
                color: #d8ad4f;
                font-size: 15px;
                font-weight: 800;
            }

            QLabel#PredictionName {
                color: #f6fbff;
                font-size: 13px;
                font-weight: 600;
                min-height: 24px;
            }

            QLabel#PredictionConfidence {
                color: #9fb0c2;
                font-size: 12px;
                font-weight: 600;
                min-height: 24px;
            }

            QProgressBar#PredictionBar {
                background-color: #071018;
                border: 0;
                border-radius: 2px;
                height: 4px;
            }

            QProgressBar#PredictionBar::chunk {
                background-color: #527895;
                border-radius: 2px;
            }

            QProgressBar#PredictionBar[rank="1"]::chunk {
                background-color: #ff4655;
            }

            QLabel#SectionTitle {
                color: #f2f6fb;
                font-size: 15px;
                font-weight: 700;
            }

            QFrame#TrainingProgressPanel {
                background-color: #0f1923;
                border: 1px solid #263847;
                border-radius: 8px;
            }

            QLabel#TrainingProgressTitle {
                color: #f2f6fb;
                font-size: 13px;
                font-weight: 700;
            }

            QLabel#TrainingProgressPercent {
                color: #d8ad4f;
                font-size: 13px;
                font-weight: 800;
            }

            QLabel#TrainingProgressText {
                color: #9aa8b8;
                font-size: 12px;
                font-weight: 600;
            }

            QProgressBar#TrainingProgressBar {
                background-color: #071018;
                border: 1px solid #2b3d50;
                border-radius: 4px;
                height: 8px;
            }

            QProgressBar#TrainingProgressBar::chunk {
                background-color: #ff4655;
                border-radius: 3px;
            }

            QPushButton {
                background-color: #263646;
                border: 1px solid #3d5062;
                border-radius: 7px;
                color: #f8fbff;
                font-family: "PingFang SC", "Helvetica Neue", Arial;
                font-size: 13px;
                font-weight: 600;
                min-height: 38px;
                padding: 3px 14px;
            }

            QPushButton:hover {
                background-color: #304254;
                border-color: #5c7388;
            }

            QPushButton:pressed {
                background-color: #1d2836;
            }

            QPushButton:disabled {
                background-color: #1a222d;
                border-color: #273341;
                color: #657386;
            }

            QPushButton[variant="secondary"] {
                background-color: #223448;
                border-color: #3c536a;
                color: #edf4fa;
            }

            QPushButton[variant="secondary"]:hover {
                background-color: #2b4258;
                border-color: #5b7891;
            }

            QPushButton[variant="primary"] {
                background-color: #ff4655;
                border-color: #ff7580;
            }

            QPushButton[variant="primary"]:hover {
                background-color: #ff5967;
            }

            QPushButton[variant="success"] {
                background-color: #12805c;
                border-color: #21a67c;
            }

            QPushButton[variant="success"]:hover {
                background-color: #16966d;
            }

            QPushButton[variant="danger"] {
                background-color: #9a3f4c;
                border-color: #c05a69;
            }

            QPushButton[variant="danger"]:hover {
                background-color: #ad4b59;
            }

            QPushButton[variant="corrective"] {
                background-color: #76551b;
                border-color: #c18b2b;
                color: #fff3cf;
            }

            QPushButton[variant="corrective"]:hover {
                background-color: #8b651f;
                border-color: #e0a63a;
                color: #ffffff;
            }

            QPushButton[variant="force"] {
                background-color: #263646;
                border-color: #4a6177;
                color: #e9f1f8;
            }

            QPushButton[variant="force"]:hover {
                background-color: #30465a;
            }

            QPushButton[variant="irrelevant"] {
                background-color: #8f3543;
                border-color: #c05262;
                color: #ffffff;
            }

            QPushButton[variant="irrelevant"]:hover {
                background-color: #a64150;
            }

            QPushButton[variant="history"] {
                background-color: #172533;
                border-color: #314458;
                color: #d8e3ee;
            }

            QPushButton[variant="history"]:hover {
                background-color: #223448;
                border-color: #4d6b86;
            }

            QPushButton[variant="training"] {
                background-color: #24364a;
                border-color: #d8ad4f;
                color: #ffd36a;
            }

            QPushButton[variant="training"]:hover {
                background-color: #2e445c;
                border-color: #f0c65d;
            }

            QPushButton[variant="evaluate"] {
                background-color: #172533;
                border-color: #3f6484;
                color: #d8e3ee;
            }

            QPushButton[variant="evaluate"]:hover {
                background-color: #223448;
                border-color: #5f86a8;
            }

            QPushButton[variant="primary"]:disabled,
            QPushButton[variant="secondary"]:disabled,
            QPushButton[variant="success"]:disabled,
            QPushButton[variant="danger"]:disabled,
            QPushButton[variant="corrective"]:disabled,
            QPushButton[variant="training"]:disabled,
            QPushButton[variant="evaluate"]:disabled {
                background-color: #1a222d;
                border-color: #273341;
                color: #657386;
            }

            QComboBox {
                background-color: #101720;
                border: 1px solid #334257;
                border-radius: 7px;
                color: #f1f6fc;
                font-family: "PingFang SC", "Helvetica Neue", Arial;
                min-height: 34px;
                font-size: 13px;
                padding: 3px 10px;
            }

            QComboBox::drop-down {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 34px;
                background-color: transparent;
                border: 0;
            }

            QComboBox::down-arrow {
                image: none;
                width: 0;
                height: 0;
            }

            QComboBox:disabled {
                background-color: #1a222d;
                border-color: #273341;
                color: #657386;
            }

            QComboBox QAbstractItemView {
                background-color: #101720;
                border: 1px solid #334257;
                color: #f1f6fc;
                selection-background-color: #2f80ed;
            }

            QMessageBox {
                background-color: #151c25;
            }

            QMessageBox QLabel {
                color: #dce6f2;
            }
            """
        )

    def _create_prediction_card(self, rank):
        card = QFrame()
        card.setFixedHeight(64)

        if rank == 1:
            card.setObjectName("PredictionCardPrimary")
        else:
            card.setObjectName("PredictionCard")

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 7, 14, 8)
        card_layout.setSpacing(4)

        card_header_layout = QHBoxLayout()
        card_header_layout.setContentsMargins(0, 0, 0, 0)
        card_header_layout.setSpacing(10)

        rank_label = QLabel(f"#{rank}")
        rank_label.setObjectName("PredictionRank")
        rank_label.setAlignment(Qt.AlignCenter)
        rank_label.setFixedWidth(38)

        name_label = QLabel("等待预测")
        name_label.setObjectName("PredictionName")
        name_label.setAlignment(
            Qt.AlignLeft | Qt.AlignVCenter
        )
        name_label.setWordWrap(False)

        confidence_label = QLabel("--")
        confidence_label.setObjectName("PredictionConfidence")
        confidence_label.setAlignment(
            Qt.AlignRight | Qt.AlignVCenter
        )
        confidence_label.setFixedWidth(76)

        confidence_bar = QProgressBar()
        confidence_bar.setObjectName("PredictionBar")
        confidence_bar.setProperty("rank", str(rank))
        confidence_bar.setRange(0, 1000)
        confidence_bar.setValue(0)
        confidence_bar.setTextVisible(False)
        confidence_bar.setFixedHeight(4)

        card_header_layout.addWidget(rank_label)
        card_header_layout.addWidget(name_label, 1)
        card_header_layout.addWidget(confidence_label)
        card_layout.addLayout(card_header_layout)
        card_layout.addWidget(confidence_bar)

        return (
            card,
            name_label,
            confidence_label,
            confidence_bar
        )

    def _set_top_prediction_cards(self, predictions):
        for index, labels in enumerate(
            self.top_prediction_labels
        ):
            name_label, confidence_label, confidence_bar = labels

            if index >= len(predictions):
                name_label.setText("等待预测")
                confidence_label.setText("--")
                confidence_bar.setValue(0)
                continue

            prediction = predictions[index]
            name_label.setText(
                prediction["class_name"]
            )
            confidence_label.setText(
                f"{prediction['confidence'] * 100:.2f}%"
            )
            confidence_bar.setValue(
                round(prediction["confidence"] * 1000)
            )

    def start_quick_training(self):
        if not ENABLE_MODEL_TOOLS:
            return

        if self.batch_active:
            batch_title = self._batch_mode_title()
            ResultDialog(
                self,
                f"{batch_title}正在进行",
                f"请结束当前{batch_title}后再开始训练。"
            ).exec()
            return

        if (
            self.training_process
            and self.training_process.state()
            != QProcess.NotRunning
        ):
            return

        if (
            self.evaluation_process
            and self.evaluation_process.state()
            != QProcess.NotRunning
        ):
            ResultDialog(
                self,
                "评估正在运行",
                "请等模型评估完成后再开始训练。"
            ).exec()
            return

        suggested_map = self._active_map_for_task()
        dialog = TrainingMapDialog(
            self,
            self.model_service.map_names,
            suggested_map
        )

        if dialog.exec() != QDialog.Accepted:
            return

        training_map = dialog.selected_map

        self.training_map_name = training_map
        self.training_log_tail = []
        self.quick_train_button.setEnabled(False)
        self.evaluate_button.setEnabled(False)
        self.wrong_cases_button.setEnabled(False)
        self.batch_button.setEnabled(False)
        self.map_combo.setEnabled(False)
        self.quick_train_button.setText("训练中")
        self.model_status_label.setText(
            f"{training_map} 训练中"
        )
        self._set_training_progress(
            0,
            "准备启动快速训练"
        )
        self.status_label.setText("快速训练已开始……")

        process = QProcess(self)
        process.setWorkingDirectory(str(APP_DIR))

        arch_path = Path("/usr/bin/arch")
        train_script = APP_DIR / "train.py"

        if arch_path.exists():
            process.setProgram(str(arch_path))
            process.setArguments([
                "-arm64",
                sys.executable,
                "-u",
                str(train_script),
                "--quick",
                "--map",
                training_map
            ])
        else:
            process.setProgram(sys.executable)
            process.setArguments([
                "-u",
                str(train_script),
                "--quick",
                "--map",
                training_map
            ])

        process.setProcessChannelMode(
            QProcess.MergedChannels
        )
        process.readyReadStandardOutput.connect(
            self._handle_training_output
        )
        process.finished.connect(
            self._handle_training_finished
        )
        process.errorOccurred.connect(
            self._handle_training_error
        )

        self.training_process = process
        process.start()

    def _set_training_progress(self, percent, message):
        percent = max(
            0,
            min(100, int(percent))
        )
        self.training_progress_bar.setValue(percent)
        self.training_progress_percent_label.setText(
            f"{percent}%"
        )
        self.training_progress_label.setText(message)

    def _handle_training_progress_line(self, line):
        prefix = "__TRAIN_PROGRESS__"

        if not line.startswith(prefix):
            return False

        try:
            payload = json.loads(
                line[len(prefix):]
            )
        except json.JSONDecodeError:
            return True

        percent = payload.get("percent", 0)
        message = payload.get(
            "message",
            "训练进度更新"
        )
        current = payload.get("current")
        total = payload.get("total")
        validation_accuracy = payload.get(
            "validation_accuracy"
        )

        if (
            current is not None
            and total
            and validation_accuracy is not None
        ):
            message = (
                f"{message} · "
                f"{current}/{total}"
            )

        self._set_training_progress(
            percent,
            message
        )
        self.status_label.setText(message)
        self.training_log_tail.append(message)
        self.training_log_tail = self.training_log_tail[-10:]
        return True

    def _handle_training_output(self):
        if not self.training_process:
            return

        output = bytes(
            self.training_process.readAllStandardOutput()
        ).decode(
            "utf-8",
            errors="replace"
        )
        lines = [
            line.strip()
            for line in output.splitlines()
            if line.strip()
        ]

        if not lines:
            return

        for line in lines:
            if self._handle_training_progress_line(line):
                continue

            self.training_log_tail.append(line)
            self.training_log_tail = self.training_log_tail[-10:]
            self.status_label.setText(line)

    def _handle_training_finished(
        self,
        exit_code,
        exit_status
    ):
        if self.training_process is None:
            return

        log_tail = "\n".join(
            self.training_log_tail[-6:]
        )
        training_map = (
            self.training_map_name
            or self.model_service.default_map
        )
        self.training_process = None
        self.quick_train_button.setEnabled(True)
        self.evaluate_button.setEnabled(True)
        self._refresh_wrong_cases_availability()
        self.batch_button.setEnabled(True)
        self.map_combo.setEnabled(True)
        self.quick_train_button.setText("训练")

        if (
            exit_status != QProcess.NormalExit
            or exit_code != 0
        ):
            self.training_map_name = None
            self.model_status_label.setText("模型未更新")
            self._set_training_progress(
                self.training_progress_bar.value(),
                "训练失败，模型没有更新"
            )
            self.status_label.setText("快速训练失败")
            ResultDialog(
                self,
                "训练失败",
                f"退出代码：{exit_code}",
                log_tail or "没有收到训练日志。"
            ).exec()
            return

        try:
            self._set_training_progress(
                100,
                "训练完成，正在重新加载模型"
            )
            self.model_service = ModelService()
            self._refresh_map_selector()
            self.feedback_status_label.setText(
                f"{len(self.model_service.map_names)} 地图已开启"
                if self.model_service.relevance_available
                else "过滤器未就绪"
            )
            self.feedback_status_label.setToolTip(
                self.model_service.relevance_status
            )
        except Exception as error:
            self.training_map_name = None
            self.model_status_label.setText("加载失败")
            self._set_training_progress(
                100,
                "训练完成，但新模型加载失败"
            )
            self.status_label.setText("新模型加载失败")
            QMessageBox.critical(
                self,
                "模型加载失败",
                str(error)
            )
            return

        self.training_map_name = None
        self.model_status_label.setText(
            f"{len(self.model_service.map_names)} 个模型已加载"
        )
        self._set_training_progress(
            100,
            "快速训练完成，模型已重新加载"
        )
        self.status_label.setText(
            "快速训练完成，模型已重新加载"
        )
        ResultDialog(
            self,
            f"{training_map} 训练完成",
            f"{training_map} 新模型已经加载，可以继续预测。",
            log_tail
        ).exec()

    def _handle_training_error(self, error):
        self.training_process = None
        self.training_map_name = None
        self.quick_train_button.setEnabled(True)
        self.evaluate_button.setEnabled(True)
        self._refresh_wrong_cases_availability()
        self.batch_button.setEnabled(True)
        self.map_combo.setEnabled(True)
        self.quick_train_button.setText("训练")
        self.model_status_label.setText("训练未启动")
        self._set_training_progress(
            0,
            "训练启动失败"
        )
        self.status_label.setText("快速训练启动失败")
        ResultDialog(
            self,
            "训练启动失败",
            "没有成功启动后台训练进程。",
            str(error)
        ).exec()

    def start_evaluation(self):
        if not ENABLE_MODEL_TOOLS:
            return

        if self.batch_active:
            batch_title = self._batch_mode_title()
            ResultDialog(
                self,
                f"{batch_title}正在进行",
                f"请结束当前{batch_title}后再评估模型。"
            ).exec()
            return

        evaluation_map = self._active_map_for_task()
        test_directory = (
            SOURCE_DATA_DIR / "test" / evaluation_map
        )

        if not test_directory.exists() or not any(
            path.is_file()
            and path.suffix.lower() in IMAGE_EXTENSIONS
            for path in test_directory.rglob("*")
        ):
            ResultDialog(
                self,
                f"{evaluation_map} 暂无测试集",
                "需要先准备独立测试图片，才能得到可靠评估。",
                f"测试目录：{test_directory}"
            ).exec()
            return

        if (
            self.evaluation_process
            and self.evaluation_process.state()
            != QProcess.NotRunning
        ):
            return

        if (
            self.training_process
            and self.training_process.state()
            != QProcess.NotRunning
        ):
            ResultDialog(
                self,
                "训练正在运行",
                "请等快速训练完成后再评估模型。"
            ).exec()
            return

        self.evaluation_map_name = evaluation_map
        self.evaluation_log_tail = []
        self.evaluate_button.setEnabled(False)
        self.quick_train_button.setEnabled(False)
        self.wrong_cases_button.setEnabled(False)
        self.batch_button.setEnabled(False)
        self.map_combo.setEnabled(False)
        self.evaluate_button.setText("评估中")
        self.model_status_label.setText(
            f"{evaluation_map} 评估中"
        )
        self._set_training_progress(
            0,
            "正在启动模型评估"
        )
        self.status_label.setText("模型评估已开始……")

        process = QProcess(self)
        process.setWorkingDirectory(str(APP_DIR))

        arch_path = Path("/usr/bin/arch")
        evaluate_script = APP_DIR / "evaluate.py"

        if arch_path.exists():
            process.setProgram(str(arch_path))
            process.setArguments([
                "-arm64",
                sys.executable,
                "-u",
                str(evaluate_script),
                "--map",
                evaluation_map
            ])
        else:
            process.setProgram(sys.executable)
            process.setArguments([
                "-u",
                str(evaluate_script),
                "--map",
                evaluation_map
            ])

        process.setProcessChannelMode(
            QProcess.MergedChannels
        )
        process.readyReadStandardOutput.connect(
            self._handle_evaluation_output
        )
        process.finished.connect(
            self._handle_evaluation_finished
        )
        process.errorOccurred.connect(
            self._handle_evaluation_error
        )

        self.evaluation_process = process
        process.start()

    def _handle_evaluation_progress_line(self, line):
        prefix = "__EVALUATION_PROGRESS__"

        if not line.startswith(prefix):
            return False

        try:
            payload = json.loads(
                line[len(prefix):]
            )
        except json.JSONDecodeError:
            return True

        percent = payload.get("percent", 0)
        message = payload.get(
            "message",
            "评估进度更新"
        )
        current = payload.get("current")
        total = payload.get("total")

        if current is not None and total:
            message = (
                f"{message} · "
                f"{current}/{total}"
            )

        self._set_training_progress(
            percent,
            message
        )
        self.status_label.setText(message)
        self.evaluation_log_tail.append(message)
        self.evaluation_log_tail = (
            self.evaluation_log_tail[-10:]
        )
        return True

    def _handle_evaluation_output(self):
        if not self.evaluation_process:
            return

        output = bytes(
            self.evaluation_process.readAllStandardOutput()
        ).decode(
            "utf-8",
            errors="replace"
        )
        lines = [
            line.strip()
            for line in output.splitlines()
            if line.strip()
        ]

        if not lines:
            return

        for line in lines:
            if self._handle_evaluation_progress_line(line):
                continue

            self.evaluation_log_tail.append(line)
            self.evaluation_log_tail = (
                self.evaluation_log_tail[-10:]
            )
            self.status_label.setText(line)

            if "使用设备" in line:
                self._set_training_progress(
                    15,
                    "正在载入测试集和模型"
                )
            elif "整体测试结果" in line:
                self._set_training_progress(
                    80,
                    "正在汇总评估结果"
                )
            elif "整体准确率" in line:
                self._set_training_progress(
                    92,
                    line
                )

    def _handle_evaluation_finished(
        self,
        exit_code,
        exit_status
    ):
        if self.evaluation_process is None:
            return

        log_tail = "\n".join(
            self.evaluation_log_tail[-6:]
        )
        evaluation_map = (
            self.evaluation_map_name
            or self._active_map_for_task()
        )
        summary_path, _ = self._evaluation_paths(
            evaluation_map
        )
        self.evaluation_process = None
        self.evaluate_button.setEnabled(True)
        self.quick_train_button.setEnabled(True)
        self._refresh_wrong_cases_availability()
        self.batch_button.setEnabled(True)
        self.map_combo.setEnabled(True)
        self.evaluate_button.setText("评估")

        if (
            exit_status != QProcess.NormalExit
            or exit_code != 0
        ):
            self.evaluation_map_name = None
            self.model_status_label.setText("评估失败")
            self._set_training_progress(
                self.training_progress_bar.value(),
                "模型评估失败"
            )
            self.status_label.setText("模型评估失败")
            ResultDialog(
                self,
                "评估失败",
                f"退出代码：{exit_code}",
                log_tail or "没有收到评估日志。"
            ).exec()
            return

        try:
            summary = json.loads(
                summary_path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception as error:
            self.evaluation_map_name = None
            self.model_status_label.setText("评估完成")
            self._set_training_progress(
                100,
                "评估完成，但摘要读取失败"
            )
            QMessageBox.critical(
                self,
                "读取评估摘要失败",
                str(error)
            )
            return

        accuracy = float(summary.get("accuracy", 0))
        wrong = int(summary.get("wrong", 0))
        message = (
            f"整体准确率 {accuracy:.2f}% · "
            f"错误 {wrong} 张"
        )

        try:
            wrong_cases = self._load_evaluation_wrong_cases(
                evaluation_map
            )
        except Exception:
            wrong_cases = []

        self.wrong_cases_button.setEnabled(
            bool(wrong_cases)
        )
        self.model_status_label.setText("评估完成")
        self._set_training_progress(
            100,
            message
        )
        self.status_label.setText(message)
        self.evaluation_map_name = None
        dialog = EvaluationDialog(
            self,
            summary,
            len(wrong_cases)
        )
        dialog.exec()

        if dialog.start_review_requested:
            self.start_wrong_case_review(evaluation_map)

    def _handle_evaluation_error(self, error):
        self.evaluation_process = None
        self.evaluation_map_name = None
        self.evaluate_button.setEnabled(True)
        self.quick_train_button.setEnabled(True)
        self._refresh_wrong_cases_availability()
        self.batch_button.setEnabled(True)
        self.map_combo.setEnabled(True)
        self.evaluate_button.setText("评估")
        self.model_status_label.setText("评估未启动")
        self._set_training_progress(
            0,
            "模型评估启动失败"
        )
        self.status_label.setText("模型评估启动失败")
        ResultDialog(
            self,
            "评估启动失败",
            "没有成功启动后台评估进程。",
            str(error)
        ).exec()

    def _format_evaluation_summary(self, summary):
        map_name = summary.get(
            "map_name",
            self._active_map_for_task()
        )
        summary_path, report_path = self._evaluation_paths(
            map_name
        )
        accuracy = float(summary.get("accuracy", 0))
        test_images = int(summary.get("test_images", 0))
        correct = int(summary.get("correct", 0))
        wrong = int(summary.get("wrong", 0))

        class_results = summary.get(
            "class_results",
            {}
        )
        ranked_classes = []

        for class_name, result in class_results.items():
            total = int(result.get("total", 0))
            class_accuracy = result.get("accuracy")

            if total <= 0 or class_accuracy is None:
                continue

            ranked_classes.append((
                float(class_accuracy),
                -total,
                class_name,
                int(result.get("correct", 0)),
                total
            ))

        ranked_classes.sort()

        detail_lines = [
            f"测试图片：{test_images}",
            f"正确：{correct}",
            f"错误：{wrong}",
            "",
            "最需要补强的区域："
        ]

        if ranked_classes:
            for index, item in enumerate(
                ranked_classes[:5],
                start=1
            ):
                (
                    class_accuracy,
                    _negative_total,
                    class_name,
                    class_correct,
                    total
                ) = item
                detail_lines.append(
                    f"{index}. {class_name}  "
                    f"{class_correct}/{total}  "
                    f"{class_accuracy:.2f}%"
                )
        else:
            detail_lines.append("暂无可排序的区域结果。")

        detail_lines.extend([
            "",
            f"摘要：{summary_path}",
            f"明细：{report_path}"
        ])

        return (
            "评估完成",
            f"整体准确率：{accuracy:.2f}%  /  错误 {wrong} 张",
            "\n".join(detail_lines)
        )

    def _load_evaluation_wrong_cases(self, map_name=None):
        map_name = map_name or self._active_map_for_task()
        _, report_path = self._evaluation_paths(map_name)

        if not report_path.exists():
            return []

        wrong_cases = []
        seen_paths = set()

        with report_path.open(
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as report_file:
            for row in csv.DictReader(report_file):
                is_correct = str(
                    row.get("correct", "")
                ).strip().lower() in {
                    "true",
                    "1",
                    "yes"
                }

                if is_correct:
                    continue

                raw_path = str(
                    row.get("image", "")
                ).strip()
                true_class = str(
                    row.get("true_class", "")
                ).strip()
                row_map = row.get("map_name", map_name)

                try:
                    row_map = canonical_map_name(row_map)
                except ValueError:
                    continue

                if row_map != map_name:
                    continue

                if not raw_path or true_class not in (
                    self.model_service.get_class_names(map_name)
                ):
                    continue

                image_path = Path(raw_path).expanduser()

                if not image_path.is_absolute():
                    image_path = APP_DIR / image_path

                if (
                    not image_path.exists()
                    or image_path.suffix.lower()
                    not in IMAGE_EXTENSIONS
                ):
                    continue

                resolved_path = str(image_path.resolve())

                if resolved_path in seen_paths:
                    continue

                try:
                    confidence = float(
                        row.get("confidence", 0)
                    )
                except (TypeError, ValueError):
                    confidence = 0.0

                seen_paths.add(resolved_path)
                wrong_cases.append({
                    "image": resolved_path,
                    "map_name": map_name,
                    "true_class": true_class,
                    "confidence": confidence
                })

        wrong_cases.sort(
            key=lambda case: case["confidence"],
            reverse=True
        )
        return wrong_cases

    def start_wrong_case_review(self, map_name=None):
        if not ENABLE_MODEL_TOOLS:
            return

        if self.batch_active:
            ResultDialog(
                self,
                "批量纠错正在进行",
                "请先结束当前队列，再打开评估错题。"
            ).exec()
            return

        map_name = map_name or self._active_map_for_task()
        map_name = canonical_map_name(map_name)
        _, report_path = self._evaluation_paths(map_name)

        try:
            wrong_cases = self._load_evaluation_wrong_cases(
                map_name
            )
        except Exception as error:
            ResultDialog(
                self,
                "错题报告读取失败",
                "无法读取最近一次评估明细。",
                str(error)
            ).exec()
            return

        if not report_path.exists():
            ResultDialog(
                self,
                "还没有评估报告",
                "请先运行一次模型评估。"
            ).exec()
            return

        if not wrong_cases:
            ResultDialog(
                self,
                "没有需要纠错的图片",
                "最近一次评估没有可载入的错误记录。"
            ).exec()
            return

        expected_classes = {
            case["image"]: case["true_class"]
            for case in wrong_cases
        }
        map_index = self.map_combo.findData(map_name)

        if map_index >= 0:
            self.map_combo.setCurrentIndex(map_index)

        self.start_batch_correction(
            [case["image"] for case in wrong_cases],
            expected_classes=expected_classes,
            batch_kind="evaluation"
        )

    def show_history(self):
        records, skipped_count = self._load_feedback_history()
        dialog = HistoryDialog(
            self,
            records,
            skipped_count,
            self.clear_feedback_history
        )
        dialog.exec()

        if dialog.history_cleared:
            removed_count = getattr(
                self,
                "last_history_clear_removed_count",
                0
            )
            correction_count = getattr(
                self,
                "last_history_clear_correction_count",
                0
            )
            ResultDialog(
                self,
                "历史记录已整理",
                f"已清空 {removed_count} 条预测正确记录。",
                f"保留 {correction_count} 条纠错记录，地图图片文件没有被删除。"
            ).exec()

    def clear_feedback_history(self):
        try:
            FEEDBACK_LOG.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            kept_lines = []
            removed_count = 0
            correction_count = 0

            if FEEDBACK_LOG.exists():
                with FEEDBACK_LOG.open(
                    "r",
                    encoding="utf-8"
                ) as file:
                    for raw_line in file:
                        line = raw_line.rstrip("\n")

                        if not line.strip():
                            continue

                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            kept_lines.append(line)
                            continue

                        if record.get("was_correct") is True:
                            removed_count += 1
                            continue

                        if record.get("was_correct") is False:
                            correction_count += 1

                        kept_lines.append(line)

            text = "\n".join(kept_lines)
            if text:
                text += "\n"

            FEEDBACK_LOG.write_text(
                text,
                encoding="utf-8"
            )
        except Exception as error:
            QMessageBox.critical(
                self,
                "清空历史失败",
                str(error)
            )
            return False

        self.last_history_clear_removed_count = removed_count
        self.last_history_clear_correction_count = correction_count
        self.status_label.setText(
            "已清空正确记录，纠错记录已保留"
        )
        return True

    def _load_feedback_history(self):
        records = []
        skipped_count = 0

        if not FEEDBACK_LOG.exists():
            return records, skipped_count

        try:
            with FEEDBACK_LOG.open(
                "r",
                encoding="utf-8"
            ) as file:
                for line in file:
                    line = line.strip()

                    if not line:
                        continue

                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        skipped_count += 1
                        continue

                    if isinstance(record, dict):
                        records.append(record)
                    else:
                        skipped_count += 1

        except Exception as error:
            QMessageBox.critical(
                self,
                "读取历史失败",
                str(error)
            )
            return [], skipped_count

        records.reverse()
        return records, skipped_count

    def _refresh_dynamic_style(self, widget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _selected_map_mode(self):
        map_name = self.map_combo.currentData()
        return map_name or AUTO_MAP

    def _active_map_for_task(self):
        selected_map = self._selected_map_mode()

        if selected_map != AUTO_MAP:
            return selected_map

        if self.current_prediction:
            predicted_map = self.current_prediction.get(
                "map_name"
            )

            if predicted_map in self.model_service.map_names:
                return predicted_map

        return self.model_service.default_map

    def _evaluation_paths(self, map_name=None):
        map_name = map_name or self._active_map_for_task()
        output_directory = evaluation_dir(map_name)
        return (
            output_directory / "summary.json",
            output_directory / "report.csv"
        )

    def _refresh_wrong_cases_availability(self):
        if not ENABLE_MODEL_TOOLS:
            self.wrong_cases_button.setEnabled(False)
            return

        _, report_path = self._evaluation_paths()
        self.wrong_cases_button.setEnabled(
            report_path.exists()
        )

    def _set_class_options(self, map_name):
        class_names = self.model_service.get_class_names(
            map_name
        )
        current_class = self.class_combo.currentText()
        self.class_combo.blockSignals(True)
        self.class_combo.clear()
        self.class_combo.addItems(class_names)

        current_index = self.class_combo.findText(
            current_class
        )

        if current_index >= 0:
            self.class_combo.setCurrentIndex(current_index)

        self.class_combo.blockSignals(False)

    def _refresh_map_selector(self):
        selected_map = self._selected_map_mode()
        self.map_combo.blockSignals(True)
        self.map_combo.clear()
        self.map_combo.addItem("自动地图", AUTO_MAP)

        for map_name in self.model_service.map_names:
            self.map_combo.addItem(map_name, map_name)

        selected_index = self.map_combo.findData(
            selected_map
        )
        self.map_combo.setCurrentIndex(
            selected_index if selected_index >= 0 else 0
        )
        self.map_combo.blockSignals(False)
        self._set_class_options(
            self._selected_map_mode()
        )

    def _handle_map_mode_changed(self):
        selected_map = self._selected_map_mode()
        self._set_class_options(selected_map)
        self.current_prediction = None
        self.current_map_name = None
        self._set_rejection_ui(False)
        self.result_caption_label.setText("最高匹配区域")
        self.best_result_label.setText("等待预测")
        self.confidence_caption_label.setText("可信度")
        self.confidence_label.setText("--")
        self.result_rank_label.setText("#1")
        self._set_top_prediction_cards([])
        self.correct_button.setEnabled(False)
        self.wrong_button.setEnabled(False)
        self.class_combo.setEnabled(False)
        self.predict_button.setEnabled(
            bool(self.current_image_path)
        )

        mode_text = (
            "自动地图识别"
            if selected_map == AUTO_MAP
            else f"已锁定 {selected_map}"
        )
        self.status_label.setText(mode_text)
        self._refresh_wrong_cases_availability()

    def _set_rejection_ui(self, rejected):
        self.rejection_action_frame.setVisible(rejected)
        self.top_three_title.setVisible(not rejected)
        self.top_cards_container.setVisible(not rejected)
        self.correct_button.setVisible(not rejected)
        self.class_hint_label.setVisible(not rejected)
        self.class_combo.setVisible(not rejected)
        self.wrong_button.setVisible(not rejected)
        self.feedback_title.setText(
            "图片是否属于支持地图？"
            if rejected
            else "AI 判断是否正确？"
        )

        state = "rejected" if rejected else "normal"
        self.result_card.setProperty("state", state)
        self.best_result_label.setProperty("state", state)
        self.result_rank_label.setProperty("state", state)

        for widget in (
            self.result_card,
            self.best_result_label,
            self.result_rank_label
        ):
            self._refresh_dynamic_style(widget)

    def _set_batch_mode_visuals(self, active):
        self.upload_bar.setProperty(
            "mode",
            "batch" if active else "single"
        )
        self.upload_accent.setProperty(
            "mode",
            "batch" if active else "single"
        )
        self.single_mode_button.setProperty(
            "active",
            not active
        )
        self.batch_button.setProperty("active", active)
        self.batch_button.setText(
            "结束复核"
            if active and self.batch_kind == "evaluation"
            else "结束批量"
            if active
            else "批量纠错"
        )
        self.batch_button.setToolTip(
            f"点击结束当前{self._batch_mode_title()}"
            if active
            else "选择多张图片连续预测并纠错"
        )
        self.select_button.setEnabled(not active)
        self.map_combo.setEnabled(not active)

        for widget in (
            self.upload_bar,
            self.upload_accent,
            self.single_mode_button,
            self.batch_button
        ):
            self._refresh_dynamic_style(widget)

    def activate_single_mode(self):
        if self.batch_active:
            self.toggle_batch_correction()

    def toggle_batch_correction(self):
        if self.batch_active:
            batch_title = self._batch_mode_title()
            dialog = ConfirmDialog(
                self,
                f"结束{batch_title}？",
                "当前队列会停止，已经保存的反馈会保留。",
                confirm_text=(
                    "结束复核"
                    if self.batch_kind == "evaluation"
                    else "结束批量"
                ),
                cancel_text=(
                    "继续复核"
                    if self.batch_kind == "evaluation"
                    else "继续纠错"
                )
            )

            if dialog.exec() == QDialog.Accepted:
                self._finish_batch_correction(
                    cancelled=True
                )

            return

        image_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择多张地图截图",
            "",
            (
                "图片文件 "
                "(*.jpg *.jpeg *.png *.bmp *.webp)"
            )
        )

        if not image_paths:
            return

        self.start_batch_correction(image_paths)

    def start_batch_correction(
        self,
        image_paths,
        expected_classes=None,
        batch_kind="manual"
    ):
        if (
            self.training_process
            and self.training_process.state()
            != QProcess.NotRunning
        ):
            ResultDialog(
                self,
                "训练正在运行",
                "请等快速训练完成后再开始批量纠错。"
            ).exec()
            return

        if (
            self.evaluation_process
            and self.evaluation_process.state()
            != QProcess.NotRunning
        ):
            ResultDialog(
                self,
                "评估正在运行",
                "请等模型评估完成后再开始批量纠错。"
            ).exec()
            return

        expected_classes = expected_classes or {}
        unique_paths = []
        normalized_expected_classes = {}
        seen_paths = set()

        for image_path in image_paths:
            path = Path(image_path)

            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue

            resolved = str(path.resolve())

            if resolved in seen_paths:
                continue

            seen_paths.add(resolved)
            unique_paths.append(resolved)

            expected_class = expected_classes.get(
                resolved
            )

            if expected_class in self.model_service.class_names:
                normalized_expected_classes[
                    resolved
                ] = expected_class

        if not unique_paths:
            QMessageBox.warning(
                self,
                "没有可用图片",
                "请选择 JPG / PNG / WEBP / BMP 图片。"
            )
            return

        self.batch_image_paths = unique_paths
        self.batch_index = 0
        self.batch_active = True
        self.batch_correct_count = 0
        self.batch_correction_count = 0
        self.batch_skipped_count = 0
        self.batch_irrelevant_count = 0
        self.batch_expected_classes = (
            normalized_expected_classes
        )
        self.batch_kind = batch_kind

        self._set_batch_mode_visuals(True)
        self.quick_train_button.setEnabled(False)
        self.evaluate_button.setEnabled(False)
        self.wrong_cases_button.setEnabled(False)
        self._load_current_batch_image()

    def _batch_mode_title(self):
        if self.batch_kind == "evaluation":
            return "错题复核"

        return "批量纠错"

    def _current_expected_class(self):
        if not self.current_image_path:
            return None

        resolved_path = str(
            Path(self.current_image_path).resolve()
        )
        return self.batch_expected_classes.get(
            resolved_path
        )

    def _batch_total(self):
        return len(self.batch_image_paths)

    def _batch_completed(self):
        return (
            self.batch_correct_count
            + self.batch_correction_count
            + self.batch_skipped_count
            + self.batch_irrelevant_count
        )

    def _update_batch_progress(self, message):
        total = self._batch_total()

        if total <= 0:
            return

        current = min(
            self.batch_index + 1,
            total
        )
        percent = int(
            self._batch_completed() / total * 100
        )
        self._set_training_progress(
            percent,
            (
                f"{message} · "
                f"{current}/{total} · "
                f"纠错 {self.batch_correction_count} / "
                f"正确 {self.batch_correct_count} / "
                f"无关 {self.batch_irrelevant_count}"
            )
        )

    def _load_current_batch_image(self):
        while (
            self.batch_active
            and self.batch_index < self._batch_total()
        ):
            image_path = self.batch_image_paths[
                self.batch_index
            ]

            if self.load_image(
                image_path,
                from_batch=True
            ):
                self._update_batch_progress(
                    "正在自动预测"
                )
                QApplication.processEvents()
                self.run_prediction()
                return

            self.batch_skipped_count += 1
            self.batch_index += 1

        if self.batch_active:
            self._finish_batch_correction()

    def _advance_batch_after_feedback(self):
        self.batch_index += 1

        if self.batch_index >= self._batch_total():
            self._finish_batch_correction()
            return

        self._load_current_batch_image()

    def _finish_batch_correction(self, cancelled=False):
        total = self._batch_total()
        completed = self._batch_completed()
        batch_title = self._batch_mode_title()
        detail = (
            f"总图片：{total}\n"
            f"已处理：{completed}\n"
            f"预测正确确认：{self.batch_correct_count}\n"
            f"纠错保存：{self.batch_correction_count}\n"
            f"无关图片：{self.batch_irrelevant_count}\n"
            f"跳过：{self.batch_skipped_count}"
        )

        self.batch_active = False
        self.batch_image_paths = []
        self.batch_index = -1
        self.batch_expected_classes = {}
        self.batch_kind = "manual"
        self.batch_irrelevant_count = 0
        self._set_batch_mode_visuals(False)
        self.quick_train_button.setEnabled(True)
        self.evaluate_button.setEnabled(True)
        self._refresh_wrong_cases_availability()

        self._prepare_next_image(
            f"{batch_title}已结束"
            if cancelled
            else f"{batch_title}完成"
        )
        self._set_training_progress(
            100 if total else 0,
            f"{batch_title}已结束"
            if cancelled
            else f"{batch_title}完成"
        )

        ResultDialog(
            self,
            f"{batch_title}已结束"
            if cancelled
            else f"{batch_title}完成",
            "已经保存的反馈记录会保留在本机，供后续模型改进使用。",
            detail
        ).exec()

    def select_image(self):
        if self.batch_active:
            self._finish_batch_correction(
                cancelled=True
            )

        image_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择测试图片",
            "",
            (
                "图片文件 "
                "(*.jpg *.jpeg *.png *.bmp *.webp)"
            )
        )

        if not image_path:
            return

        self.load_image(image_path)

    def load_image(self, image_path, from_batch=False):
        if not self.show_image(image_path):
            return False

        if self.batch_active and not from_batch:
            self._finish_batch_correction(
                cancelled=True
            )

        self.current_image_path = image_path
        self.current_prediction = None
        self.current_map_name = None
        self._set_class_options(
            self._selected_map_mode()
        )
        self._set_rejection_ui(False)

        self.predict_button.setEnabled(True)
        self.correct_button.setEnabled(False)
        self.wrong_button.setEnabled(False)
        self.class_combo.setEnabled(False)

        if self.batch_active:
            self.upload_title_label.setText(
                f"{self._batch_mode_title()} "
                f"{self.batch_index + 1}/{self._batch_total()}"
            )
        else:
            self.upload_title_label.setText("地图截图已载入")

        self.upload_file_label.setText(
            Path(image_path).name
        )
        self.best_result_label.setText("等待预测")
        self.result_caption_label.setText("最高匹配区域")
        self.confidence_caption_label.setText("可信度")
        self.confidence_label.setText("--")
        self.result_rank_label.setText("#1")
        self._set_top_prediction_cards([])
        self.status_label.setText(
            f"已选择：{Path(image_path).name}"
        )
        return True

    def show_image(self, image_path):
        pixmap = QPixmap(image_path)

        if pixmap.isNull():
            QMessageBox.warning(
                self,
                "图片错误",
                "无法显示这张图片。"
            )
            return False

        original_width = pixmap.width()
        original_height = pixmap.height()
        scaled_pixmap = pixmap.scaled(
            self.image_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        if self.batch_active:
            badge_title = (
                "错题"
                if self.batch_kind == "evaluation"
                else "批量"
            )
            badge = (
                f"{badge_title} "
                f"{self.batch_index + 1}/{self._batch_total()}"
            )
        else:
            badge = "单张识别"
        self.image_label.set_preview_image(
            scaled_pixmap,
            Path(image_path).name,
            f"{original_width} × {original_height}",
            badge
        )
        return True

    def run_prediction(self):
        if not self.current_image_path:
            return

        try:
            self.predict_button.setEnabled(False)
            self.upload_title_label.setText(
                "正在识别区域"
            )
            self.status_label.setText("正在预测……")
            QApplication.processEvents()

            result = self.model_service.predict(
                self.current_image_path,
                top_k=3,
                map_name=self._selected_map_mode()
            )

            self.current_prediction = result
            self.current_map_name = result.get("map_name")

            if not result.get("is_relevant", True):
                self._display_rejection_result(result)
                return

            self._display_prediction_result(result)

        except Exception as error:
            self.predict_button.setEnabled(
                bool(self.current_image_path)
            )
            QMessageBox.critical(
                self,
                "预测失败",
                str(error)
            )

            self.status_label.setText("预测失败")

    def _display_rejection_result(self, result):
        self._set_rejection_ui(True)
        candidate_map = result.get("map_name")
        self.result_caption_label.setText(
            f"{candidate_map} · 相关性检测"
            if candidate_map
            else "地图相关性检测"
        )
        self.best_result_label.setText("无法确认")
        self.confidence_caption_label.setText(
            "综合匹配度"
        )
        self.confidence_label.setText(
            f"{result.get('relevance_confidence', 0) * 100:.1f}%"
        )
        self.result_rank_label.setText("!")
        self._set_top_prediction_cards([])

        self.correct_button.setEnabled(False)
        self.wrong_button.setEnabled(False)
        self.class_combo.setEnabled(False)
        self.force_predict_button.setEnabled(True)
        self.irrelevant_button.setEnabled(True)
        self.predict_button.setEnabled(True)

        if self.batch_active:
            self.upload_title_label.setText(
                f"{self._batch_mode_title()} "
                f"{self.batch_index + 1}/{self._batch_total()}"
            )
            self._update_batch_progress(
                "图片未通过相关性检查"
            )
        else:
            self.upload_title_label.setText(
                "无法确认图片内容"
            )

        reason = result.get(
            "rejection_reason",
            "图片未通过地图相关性检查"
        )
        similarity = result.get(
            "prototype_similarity",
            0
        )
        relevance_score = result.get(
            "relevance_score",
            0
        )
        self.status_label.setText(
            f"{reason} · 相关性 {relevance_score * 100:.1f}% · "
            f"特征 {similarity * 100:.1f}%"
        )

    def _display_prediction_result(
        self,
        result,
        forced=False
    ):
        self._set_rejection_ui(False)
        map_name = result.get(
            "map_name",
            self.model_service.default_map
        )
        self.current_map_name = map_name
        self._set_class_options(map_name)
        self.result_caption_label.setText(
            f"{map_name} · 最高匹配区域"
        )
        self.confidence_caption_label.setText("可信度")

        best_class = result["best_class"]
        best_confidence = result["best_confidence"]

        self.best_result_label.setText(best_class)

        self.confidence_label.setText(
            f"{best_confidence * 100:.2f}%"
        )
        self.result_rank_label.setText("#1")
        self._set_top_prediction_cards(
            result["top_predictions"]
        )

        predicted_index = self.class_combo.findText(
            best_class
        )

        if predicted_index >= 0:
            self.class_combo.setCurrentIndex(
                predicted_index
            )

        expected_class = self._current_expected_class()

        if expected_class:
            expected_index = self.class_combo.findText(
                expected_class
            )

            if expected_index >= 0:
                self.class_combo.setCurrentIndex(
                    expected_index
                )

        self.correct_button.setEnabled(True)
        self.wrong_button.setEnabled(True)
        self.class_combo.setEnabled(True)
        self.predict_button.setEnabled(True)

        if self.batch_active:
            self.upload_title_label.setText(
                f"{self._batch_mode_title()} "
                f"{self.batch_index + 1}/{self._batch_total()}"
            )
            self._update_batch_progress(
                "预测完成，等待确认"
            )

            if forced:
                self.status_label.setText(
                    "已跳过相关性检查，请人工核对区域"
                )
            elif expected_class:
                self.status_label.setText(
                    "评估标签已预选，请核对后保存纠错"
                )
            else:
                self.status_label.setText(
                    "预测完成，请确认或选择正确区域"
                )
        else:
            self.upload_title_label.setText(
                f"{map_name} 预测完成，等待反馈确认"
            )

            if forced:
                self.status_label.setText(
                    "已跳过相关性检查，请人工核对区域"
                )
            else:
                self.status_label.setText(
                    "预测完成，请确认 AI 判断是否正确"
                )

    def force_current_prediction(self):
        if not self.current_prediction:
            return

        self._display_prediction_result(
            self.current_prediction,
            forced=True
        )

    def _prepare_next_image(self, status_message):
        self.current_image_path = None
        self.current_prediction = None
        self.current_map_name = None
        self._set_rejection_ui(False)

        self.image_label.set_empty_state(
            "预测完成",
            "请拖入或选择下一张图片"
        )

        self.upload_title_label.setText(
            "地图截图"
        )
        self.upload_file_label.setText(
            "JPG · PNG · WEBP · BMP"
        )
        self.best_result_label.setText("等待地图")
        self.result_caption_label.setText("最高匹配区域")
        self.confidence_caption_label.setText("可信度")
        self.confidence_label.setText("--")
        self.result_rank_label.setText("#1")
        self._set_top_prediction_cards([])

        self.predict_button.setEnabled(False)
        self.correct_button.setEnabled(False)
        self.wrong_button.setEnabled(False)
        self.class_combo.setEnabled(False)

        self.status_label.setText(status_message)

    def mark_irrelevant(self):
        if not self.current_image_path:
            return

        result = self.current_prediction or {}
        self.force_predict_button.setEnabled(False)
        self.irrelevant_button.setEnabled(False)

        try:
            saved_path = save_irrelevant_feedback(
                image_path=self.current_image_path,
                relevance_score=result.get(
                    "relevance_score",
                    0
                ),
                prototype_similarity=result.get(
                    "prototype_similarity",
                    0
                ),
                map_name=result.get("map_name")
            )

            if self.batch_active:
                self.batch_irrelevant_count += 1
                self._update_batch_progress(
                    "无关图片已记录"
                )
                self._advance_batch_after_feedback()
            else:
                self._prepare_next_image(
                    "无关图片已记录，请选择下一张图片"
                )
                ResultDialog(
                    self,
                    "无关图片已记录",
                    "这张图片已保存为无关图片反馈。",
                    (
                        f"保存位置：{saved_path}\n\n"
                        "该记录可用于后续改进图片过滤器。"
                    )
                ).exec()

        except Exception as error:
            self.force_predict_button.setEnabled(True)
            self.irrelevant_button.setEnabled(True)
            QMessageBox.critical(
                self,
                "保存失败",
                str(error)
            )

    def mark_correct(self):
        if not self.current_prediction:
            return

        predicted_class = self.current_prediction[
            "best_class"
        ]

        confidence = self.current_prediction[
            "best_confidence"
        ]

        try:
            saved_path = save_feedback(
                image_path=self.current_image_path,
                predicted_class=predicted_class,
                correct_class=predicted_class,
                confidence=confidence,
                was_correct=True,
                map_name=self.current_prediction.get(
                    "map_name",
                    self.model_service.default_map
                )
            )

            self.status_label.setText(
                f"正确反馈已保存：{saved_path}"
            )

            if self.batch_active:
                self.batch_correct_count += 1
                self._update_batch_progress(
                    "正确反馈已保存"
                )
                self._advance_batch_after_feedback()
            else:
                self._prepare_next_image(
                    "正确反馈已保存，请选择下一张图片"
                )

                ResultDialog(
                    self,
                    "反馈已保存",
                    "已记录这次正确预测。",
                    f"保存位置：{saved_path}"
                ).exec()

        except Exception as error:
            QMessageBox.critical(
                self,
                "保存失败",
                str(error)
            )

    def mark_wrong(self):
        if not self.current_prediction:
            return

        correct_class = self.class_combo.currentText()
        predicted_class = self.current_prediction[
            "best_class"
        ]
        confidence = self.current_prediction[
            "best_confidence"
        ]

        if correct_class == predicted_class:
            reply = QMessageBox.question(
                self,
                "类别相同",
                "你选择的正确类别和预测类别相同，"
                "仍然保存为错误反馈吗？"
            )

            if reply != QMessageBox.Yes:
                return

        try:
            saved_path = save_feedback(
                image_path=self.current_image_path,
                predicted_class=predicted_class,
                correct_class=correct_class,
                confidence=confidence,
                was_correct=False,
                map_name=self.current_prediction.get(
                    "map_name",
                    self.model_service.default_map
                )
            )

            self.status_label.setText(
                f"纠错数据已保存：{saved_path}"
            )

            if self.batch_active:
                self.batch_correction_count += 1
                self._update_batch_progress(
                    "纠错数据已保存"
                )
                self._advance_batch_after_feedback()
            else:
                self._prepare_next_image(
                    "纠错数据已保存，请选择下一张图片"
                )

                ResultDialog(
                    self,
                    "纠错完成",
                    "已保存这次纠错数据。",
                    (
                        f"预测：{predicted_class}\n"
                        f"正确：{correct_class}\n\n"
                        "图片已保存到 feedback 数据集。"
                    )
                ).exec()

        except Exception as error:
            QMessageBox.critical(
                self,
                "保存失败",
                str(error)
            )


def main():
    smoke_test = (
        os.environ.get("ASCENT_RECOGNIZER_SMOKE_TEST")
        == "1"
    )
    smoke_image = os.environ.get(
        "ASCENT_RECOGNIZER_SMOKE_IMAGE"
    )

    if sys.platform == "win32":
        QFont.insertSubstitution(
            "PingFang SC",
            "Microsoft YaHei UI"
        )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("GameSceneDesk")
    app.setFont(ui_font(12))
    if APP_ICON_PATH.exists():
        app.setWindowIcon(
            QIcon(str(APP_ICON_PATH))
        )

    try:
        window = MainWindow()
        window.show()

        if smoke_test:
            smoke_result = None

            if smoke_image:
                smoke_result = window.model_service.predict(
                    smoke_image
                )

            if sys.stdout is not None:
                prediction_text = (
                    " "
                    f"prediction={smoke_result['map_name']}/"
                    f"{smoke_result['best_class']}"
                    if smoke_result
                    else ""
                )
                print(
                    "SMOKE_TEST_READY "
                    f"maps={','.join(window.model_service.map_names)} "
                    f"data={APP_DATA_ROOT}"
                    f"{prediction_text}",
                    flush=True
                )
            QTimer.singleShot(250, app.quit)

        sys.exit(app.exec())

    except Exception as error:
        if sys.stderr is not None:
            print(
                f"程序启动失败：{error}",
                file=sys.stderr,
                flush=True
            )

        if not smoke_test:
            QMessageBox.critical(
                None,
                "程序启动失败",
                str(error)
            )

        sys.exit(1)


if __name__ == "__main__":
    main()
