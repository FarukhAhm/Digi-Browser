import sys
import os
import json
import ctypes
import uuid
import requests
from urllib.parse import quote_plus

from PySide6.QtCore import (
    QUrl, Qt, QSize, QTimer, QEvent,
    QAbstractNativeEventFilter, QStandardPaths,
    QObject, Signal
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QTabBar, QWidget,
    QVBoxLayout, QMenu, QLineEdit, QPushButton, QToolButton,
    QMessageBox, QToolBar, QSlider, QLabel, QSizePolicy, QStyle,
    QDialog, QFormLayout, QDialogButtonBox
)
from PySide6.QtGui import (
    QAction, QKeySequence, QIcon, QPainter, QPainterPath,
    QPen, QColor
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import (
    QWebEngineProfile, QWebEnginePage, QWebEnginePermission
)

# ============================================================
# PLATFORM DETECTION
# ============================================================
IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

if IS_WINDOWS:
    from ctypes import wintypes


# ============================================================
# SUPABASE CONFIGURATION
# ============================================================
SUPABASE_URL = "https://tbmueljdcwbcttelwydk.supabase.co"

SUPABASE_PUBLISHABLE_KEY = (
    "sb_publishable_NGhigplj_xuLgRJl5gumkw_Jvrmh4e-"
)

AUTH_LOGIN_URL = (
    f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
)

AUTH_REFRESH_URL = (
    f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token"
)

VERIFY_SUBSCRIPTION_URL = (
    f"{SUPABASE_URL}/functions/v1/verify-subscription"
)

SUBSCRIPTION_CHECK_INTERVAL_MS = 5 * 60 * 1000


# ============================================================
# APPLICATION PATHS
# ============================================================
APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "Digi Browser"

QApplication.setOrganizationName("Digi")
QApplication.setApplicationName(APP_NAME)

DATA_DIR = QStandardPaths.writableLocation(
    QStandardPaths.StandardLocation.AppLocalDataLocation
)

if not DATA_DIR:
    DATA_DIR = os.path.join(
        os.path.expanduser("~"),
        ".digi_browser"
    )

os.makedirs(DATA_DIR, exist_ok=True)

BOOKMARK_FILE = os.path.join(DATA_DIR, "bookmarks.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")

WEB_STORAGE_DIR = os.path.join(DATA_DIR, "storage")
WEB_CACHE_DIR = os.path.join(DATA_DIR, "cache")

os.makedirs(WEB_STORAGE_DIR, exist_ok=True)
os.makedirs(WEB_CACHE_DIR, exist_ok=True)


# ============================================================
# WINDOWS CONSTANTS
# ============================================================
if IS_WINDOWS:
    WDA_NONE = 0x00000000
    WDA_EXCLUDEFROMCAPTURE = 0x00000011

    WM_HOTKEY = 0x0312

    HOTKEY_ID_B = 1001
    HOTKEY_ID_N = 1002

    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004


# ============================================================
# WINDOWS TASKBAR HELPER
# ============================================================
if IS_WINDOWS:

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_uint32),
            ("Data2", ctypes.c_uint16),
            ("Data3", ctypes.c_uint16),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    def make_guid(value):
        return GUID.from_buffer_copy(
            uuid.UUID(value).bytes_le
        )

    def remove_from_windows_taskbar(hwnd):

        ole32 = ctypes.OleDLL("ole32")

        clsid = make_guid(
            "56FDF344-FD6D-11D0-958A-006097C9A090"
        )

        iid = make_guid(
            "56FDF342-FD6D-11D0-958A-006097C9A090"
        )

        ole32.CoInitialize.argtypes = [ctypes.c_void_p]
        ole32.CoInitialize.restype = ctypes.c_long

        ole32.CoCreateInstance.argtypes = [
            ctypes.POINTER(GUID),
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(GUID),
            ctypes.POINTER(ctypes.c_void_p)
        ]

        ole32.CoCreateInstance.restype = ctypes.c_long
        ole32.CoUninitialize.argtypes = []

        init_result = ole32.CoInitialize(None)
        should_uninitialize = init_result in (0, 1)

        obj = ctypes.c_void_p()
        vtable = None

        try:
            result = ole32.CoCreateInstance(
                ctypes.byref(clsid),
                None,
                1,
                ctypes.byref(iid),
                ctypes.byref(obj)
            )

            if result != 0:
                return False

            vtable = ctypes.cast(
                obj,
                ctypes.POINTER(
                    ctypes.POINTER(ctypes.c_void_p)
                )
            ).contents

            hr_init = ctypes.WINFUNCTYPE(
                ctypes.c_long,
                ctypes.c_void_p
            )(vtable[3])

            if hr_init(obj) != 0:
                return False

            delete_tab = ctypes.WINFUNCTYPE(
                ctypes.c_long,
                ctypes.c_void_p,
                wintypes.HWND
            )(vtable[5])

            return delete_tab(
                obj,
                wintypes.HWND(hwnd)
            ) == 0

        finally:
            if obj.value and vtable is not None:
                release = ctypes.WINFUNCTYPE(
                    wintypes.ULONG,
                    ctypes.c_void_p
                )(vtable[2])

                release(obj)

            if should_uninitialize:
                ole32.CoUninitialize()


# ============================================================
# GLOBAL HOTKEY SIGNAL
# ============================================================
class HotkeySignals(QObject):
    restore_signal = Signal()


# ============================================================
# WINDOWS GLOBAL HOTKEY FILTER
# ============================================================
if IS_WINDOWS:

    class GlobalHotkeyFilter(QAbstractNativeEventFilter):

        def __init__(self, browser):
            super().__init__()
            self.browser = browser

        def nativeEventFilter(self, eventType, message):

            try:
                msg = ctypes.cast(
                    int(message),
                    ctypes.POINTER(wintypes.MSG)
                ).contents

                if (
                    msg.message == WM_HOTKEY
                    and msg.wParam in (
                        HOTKEY_ID_B,
                        HOTKEY_ID_N
                    )
                ):
                    self.browser.restore_signal.restore_signal.emit()
                    return True, 0

            except Exception as error:
                print("Windows hotkey error:", error)

            return False, 0


# ============================================================
# MAC GLOBAL HOTKEY LISTENER
# ============================================================
if IS_MACOS:

    class MacGlobalHotkeys:

        def __init__(self, signal):
            self.signal = signal
            self.listener = None
            self.pressed = set()
            self.triggered = set()

        def on_press(self, key):

            from pynput.keyboard import Key

            if key in (Key.cmd, Key.cmd_l, Key.cmd_r):
                self.pressed.add("cmd")
                return

            if key in (Key.shift, Key.shift_l, Key.shift_r):
                self.pressed.add("shift")
                return

            try:
                char = key.char.lower() if key.char else None
            except (AttributeError, TypeError):
                char = None

            if char in ("b", "n"):

                if (
                    "cmd" in self.pressed
                    and "shift" in self.pressed
                    and char not in self.triggered
                ):
                    self.triggered.add(char)
                    self.signal.emit()

        def on_release(self, key):

            from pynput.keyboard import Key

            if key in (Key.cmd, Key.cmd_l, Key.cmd_r):
                self.pressed.discard("cmd")

            elif key in (Key.shift, Key.shift_l, Key.shift_r):
                self.pressed.discard("shift")

            try:
                char = key.char.lower() if key.char else None
            except (AttributeError, TypeError):
                char = None

            if char in ("b", "n"):
                self.triggered.discard(char)

        def start(self):

            try:
                from pynput import keyboard

                self.listener = keyboard.Listener(
                    on_press=self.on_press,
                    on_release=self.on_release
                )

                self.listener.start()

                print(
                    "Mac shortcuts started: "
                    "Command + Shift + B / N"
                )

                return True

            except Exception as error:
                print(
                    "Mac global hotkey startup failed:",
                    error
                )
                return False

        def stop(self):

            if self.listener:
                self.listener.stop()
                self.listener = None


# ============================================================
# JSON HELPERS
# ============================================================
def load_json(path, default):

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)

    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def save_json(path, data):

    with open(path, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            indent=4,
            ensure_ascii=False
        )


# ============================================================
# CROSS-PLATFORM CAPTURE EXCLUSION
# ============================================================
def set_capture_exclusion(hwnd, enabled):

    if IS_WINDOWS:

        user32 = ctypes.WinDLL(
            "user32",
            use_last_error=True
        )

        func = user32.SetWindowDisplayAffinity

        func.argtypes = [
            wintypes.HWND,
            wintypes.DWORD
        ]

        func.restype = wintypes.BOOL

        affinity = (
            WDA_EXCLUDEFROMCAPTURE
            if enabled
            else WDA_NONE
        )

        ctypes.set_last_error(0)

        result = func(
            wintypes.HWND(hwnd),
            wintypes.DWORD(affinity)
        )

        if not result:
            raise ctypes.WinError(
                ctypes.get_last_error()
            )

        return True

    elif IS_MACOS:

        raise RuntimeError(
            "macOS does not provide a supported system-wide "
            "equivalent to Windows Capture Exclusion. "
            "This feature is Windows-only."
        )

    else:
        raise OSError(
            "Capture Exclusion is not implemented for this OS."
        )
# ============================================================
# SUPABASE LOGIN DIALOG
# ============================================================
class LoginDialog(QDialog):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Digi Browser Login")
        self.setFixedSize(420, 260)

        self.access_token = None
        self.refresh_token = None
        self.user_email = None

        layout = QVBoxLayout(self)

        heading = QLabel("Digi Browser Login")
        heading.setStyleSheet(
            "font-size: 22px; font-weight: bold; padding: 8px;"
        )
        layout.addWidget(heading)

        form = QFormLayout()

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("Enter your email")

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter password")
        self.password_input.setEchoMode(
            QLineEdit.EchoMode.Password
        )

        form.addRow("Email:", self.email_input)
        form.addRow("Password:", self.password_input)

        layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )

        buttons.button(
            QDialogButtonBox.StandardButton.Ok
        ).setText("Login")

        buttons.accepted.connect(self.login)
        buttons.rejected.connect(self.reject)

        layout.addWidget(buttons)

    def login(self):

        email = self.email_input.text().strip()
        password = self.password_input.text()

        if not email or not password:
            self.status_label.setText(
                "Please enter email and password."
            )
            return

        if not SUPABASE_PUBLISHABLE_KEY.startswith(
            "sb_publishable_"
        ):
            self.status_label.setText(
                "Please configure your Supabase publishable key."
            )
            return

        self.status_label.setText(
            "Signing in and checking subscription..."
        )

        QApplication.processEvents()

        try:

            auth = requests.post(
                AUTH_LOGIN_URL,
                headers={
                    "apikey": SUPABASE_PUBLISHABLE_KEY,
                    "Content-Type": "application/json"
                },
                json={
                    "email": email,
                    "password": password
                },
                timeout=25
            )

            if auth.status_code != 200:

                try:
                    error_data = auth.json()
                    detail = (
                        error_data.get("msg")
                        or error_data.get("message")
                    )
                except Exception:
                    detail = None

                self.status_label.setText(
                    detail or "Invalid email/password or login failed."
                )
                return

            auth_data = auth.json()

            token = auth_data.get("access_token")
            refresh = auth_data.get("refresh_token")

            if not token or not refresh:
                self.status_label.setText(
                    "Supabase did not return the required login tokens."
                )
                return

            ok, message = self.verify_subscription(
                token,
                email
            )

            if not ok:
                self.status_label.setText(message)
                return

            self.access_token = token
            self.refresh_token = refresh
            self.user_email = email

            self.accept()

        except requests.exceptions.Timeout:
            self.status_label.setText(
                "Server timeout. Please try again."
            )

        except requests.exceptions.RequestException as error:
            self.status_label.setText(
                f"Connection error: {error}"
            )

        except Exception as error:
            self.status_label.setText(
                f"Unexpected error: {error}"
            )

    @staticmethod
    def verify_subscription(token, email):

        response = requests.post(
            VERIFY_SUBSCRIPTION_URL,
            headers={
                "apikey": SUPABASE_PUBLISHABLE_KEY,
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={"email": email},
            timeout=25
        )

        try:
            data = response.json()
        except ValueError:
            data = {}

        if response.status_code != 200:
            return (
                False,
                data.get("message")
                or f"Subscription check failed (HTTP {response.status_code})."
            )

        if (
            data.get("success") is True
            and data.get("access") is True
        ):
            return True, "Subscription active."

        return (
            False,
            data.get("message")
            or "Your subscription is inactive or expired."
        )


# ============================================================
# CHROME STYLE ICONS
# ============================================================
def create_chevron_icon(direction):

    from PySide6.QtGui import QPixmap

    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)

    painter.setRenderHint(
        QPainter.RenderHint.Antialiasing
    )

    pen = QPen(Qt.GlobalColor.black)
    pen.setWidthF(2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

    painter.setPen(pen)

    path = QPainterPath()

    if direction == "back":
        path.moveTo(14, 5)
        path.lineTo(7, 12)
        path.lineTo(14, 19)

    else:
        path.moveTo(10, 5)
        path.lineTo(17, 12)
        path.lineTo(10, 19)

    painter.drawPath(path)
    painter.end()

    return QIcon(pixmap)


# ============================================================
# LOADING / RELOAD BUTTON
# ============================================================
class LoadingButton(QToolButton):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.loading = False
        self.angle = 0

        self.setFixedSize(36, 36)
        self.setIconSize(QSize(20, 20))
        self.setEnabled(True)
        self.setToolTip("Reload")

        self.reload_icon = self.style().standardIcon(
            QStyle.StandardPixmap.SP_BrowserReload
        )

        self.setIcon(self.reload_icon)

        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.rotate_loader)

    def set_loading(self, loading):

        self.loading = loading

        if loading:
            self.setIcon(QIcon())
            self.setToolTip("Stop loading")

            if not self.timer.isActive():
                self.timer.start()

        else:
            self.timer.stop()
            self.setIcon(self.reload_icon)
            self.setToolTip("Reload")

        self.update()

    def rotate_loader(self):
        self.angle = (self.angle + 12) % 360
        self.update()

    def paintEvent(self, event):

        if not self.loading:
            super().paintEvent(event)
            return

        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )

        rect = self.rect().adjusted(7, 7, -7, -7)

        cx = self.width() / 2
        cy = self.height() / 2

        painter.setPen(
            QPen(QColor("#DADCE0"), 2.5)
        )

        painter.setBrush(
            Qt.BrushStyle.NoBrush
        )

        painter.drawEllipse(rect)

        loader_pen = QPen(
            QColor("#4285F4"),
            2.5
        )

        loader_pen.setCapStyle(
            Qt.PenCapStyle.RoundCap
        )

        painter.setPen(loader_pen)

        painter.drawArc(
            rect,
            self.angle * 16,
            240 * 16
        )

        cross_pen = QPen(
            QColor("#202124"),
            2.0
        )

        cross_pen.setCapStyle(
            Qt.PenCapStyle.RoundCap
        )

        painter.setPen(cross_pen)

        painter.drawLine(
            int(cx - 4), int(cy - 4),
            int(cx + 4), int(cy + 4)
        )

        painter.drawLine(
            int(cx + 4), int(cy - 4),
            int(cx - 4), int(cy + 4)
        )

        painter.end()


# ============================================================
# CHROME STYLE TAB BAR
# ============================================================
class ChromeTabBar(QTabBar):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.plus_index = -1
        self.add_tab_callback = None

        self.setExpanding(False)
        self.setUsesScrollButtons(True)
        self.setMovable(True)
        self.setElideMode(
            Qt.TextElideMode.ElideRight
        )
        self.setMouseTracking(True)

    def set_plus_index(self, index):
        self.plus_index = index
        self.update()

    def tabSizeHint(self, index):

        if index == self.plus_index:
            return QSize(42, 34)

        return super().tabSizeHint(index)

    def mousePressEvent(self, event):

        index = self.tabAt(
            event.position().toPoint()
        )

        if (
            index == self.plus_index
            and event.button() == Qt.MouseButton.LeftButton
        ):

            if self.add_tab_callback:
                self.add_tab_callback()

            event.accept()
            return

        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):

        if (
            self.tabAt(event.position().toPoint())
            == self.plus_index
        ):
            event.accept()
            return

        super().mouseDoubleClickEvent(event)


# ============================================================
# BROWSER PAGE
# ============================================================
class BrowserPage(QWebEnginePage):

    def __init__(self, profile, browser, parent=None):
        super().__init__(profile, parent)

        self.browser = browser

        self.permissionRequested.connect(
            self.handle_permission_request
        )

    def handle_permission_request(self, permission):

        permission_type = permission.permissionType()

        audio = (
            QWebEnginePermission.PermissionType.MediaAudioCapture
        )

        audio_video = (
            QWebEnginePermission.PermissionType.MediaAudioVideoCapture
        )

        if permission_type in (audio, audio_video):

            origin = permission.origin().toString()

            answer = QMessageBox.question(
                self.browser,
                "Microphone Permission",
                f"{origin} wants to access your microphone.\n\n"
                "Allow microphone access?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No
            )

            if answer == QMessageBox.StandardButton.Yes:
                permission.grant()
            else:
                permission.deny()

        else:
            permission.deny()


# ============================================================
# BROWSER TAB
# ============================================================
class BrowserTab(QWidget):

    def __init__(self, browser, profile):
        super().__init__()

        self.browser = browser
        self.is_loading = False

        self.view = QWebEngineView(self)

        self.page = BrowserPage(
            profile,
            browser,
            self.view
        )

        self.view.setPage(self.page)

        self.view.loadStarted.connect(
            self.on_load_started
        )

        self.view.loadFinished.connect(
            self.on_load_finished
        )

        layout = QVBoxLayout(self)

        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self.view.urlChanged.connect(
            self.update_address
        )

        self.view.titleChanged.connect(
            self.update_title
        )

        self.view.urlChanged.connect(
            self.save_history
        )

    def on_load_started(self):

        self.is_loading = True

        self.browser.update_loading_indicator(
            self,
            True
        )

    def on_load_finished(self, success):

        self.is_loading = False

        self.browser.update_loading_indicator(
            self,
            False
        )

    def update_address(self, url):

        if self.browser.current_view() == self.view:
            self.browser.address_bar.setText(
                url.toString()
            )

    def update_title(self, title):

        index = self.browser.tabs.indexOf(self)

        if index != -1:
            self.browser.tabs.setTabText(
                index,
                title[:20] if title else "New Tab"
            )

    def save_history(self, url):

        text = url.toString()

        if not text or text == "about:blank":
            return

        history = load_json(HISTORY_FILE, [])

        if not history or history[-1] != text:
            history.append(text)

        save_json(
            HISTORY_FILE,
            history[-500:]
        )
# ============================================================
# MAIN BROWSER
# ============================================================
class PrivacyBrowser(QMainWindow):

    def __init__(
        self,
        access_token,
        refresh_token,
        user_email
    ):

        super().__init__()

        self.access_token = access_token
        self.refresh_token = refresh_token
        self.user_email = user_email

        self.subscription_check_in_progress = False
        self._session_closing = False

        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint
        )

        self.setWindowTitle("Digi Browser")
        self.setMinimumSize(1400, 700)

        self.capture_enabled = False
        self._moving_plus_tab = False
        self._taskbar_hide_pending = False

        # Global hotkey variables
        self.hotkey_registered = False
        self.hotkey_registered_1 = False
        self.hotkey_registered_2 = False
        self.hotkey_filter = None
        self.mac_hotkeys = None

        # Qt signal: Mac listener will emit this signal.
        self.restore_signal = HotkeySignals()

        self.restore_signal.restore_signal.connect(
            self.restore_browser
        )

        self.profile = QWebEngineProfile(
            "PrivacyBrowserProfile",
            self
        )

        self.profile.setPersistentStoragePath(
            WEB_STORAGE_DIR
        )

        self.profile.setCachePath(
            WEB_CACHE_DIR
        )

        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )

        self.create_ui()
        self.create_shortcuts()
        self.register_global_hotkey()

        self.subscription_timer = QTimer(self)

        self.subscription_timer.setInterval(
            SUBSCRIPTION_CHECK_INTERVAL_MS
        )

        self.subscription_timer.timeout.connect(
            self.check_subscription_again
        )

        self.subscription_timer.start()

        self.add_tab("https://www.google.com/")

    # ========================================================
    # SUBSCRIPTION
    # ========================================================
    def refresh_access_token(self):

        response = requests.post(
            AUTH_REFRESH_URL,
            headers={
                "apikey": SUPABASE_PUBLISHABLE_KEY,
                "Content-Type": "application/json"
            },
            json={
                "refresh_token": self.refresh_token
            },
            timeout=20
        )

        if response.status_code != 200:
            return False

        data = response.json()

        self.access_token = data.get("access_token")

        self.refresh_token = data.get(
            "refresh_token",
            self.refresh_token
        )

        return bool(self.access_token)

    def check_subscription_again(self):

        if (
            self.subscription_check_in_progress
            or self._session_closing
        ):
            return

        self.subscription_check_in_progress = True

        try:

            response = requests.post(
                VERIFY_SUBSCRIPTION_URL,
                headers={
                    "apikey": SUPABASE_PUBLISHABLE_KEY,
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                },
                json={
                    "email": self.user_email
                },
                timeout=20
            )

            if (
                response.status_code == 401
                and self.refresh_access_token()
            ):

                response = requests.post(
                    VERIFY_SUBSCRIPTION_URL,
                    headers={
                        "apikey": SUPABASE_PUBLISHABLE_KEY,
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "email": self.user_email
                    },
                    timeout=20
                )

            try:
                data = response.json()
            except ValueError:
                data = {}

            if (
                response.status_code != 200
                or not (
                    data.get("success") is True
                    and data.get("access") is True
                )
            ):

                message = (
                    data.get("message")
                    or "Your subscription is inactive, expired, "
                       "or could not be verified."
                )

                self.lock_browser(message)

        except requests.exceptions.RequestException as error:

            self.lock_browser(
                "Subscription server could not be reached.\n"
                f"{error}"
            )

        except Exception as error:

            self.lock_browser(
                f"Subscription verification error.\n{error}"
            )

        finally:
            self.subscription_check_in_progress = False

    def lock_browser(self, message):

        if self._session_closing:
            return

        self._session_closing = True

        if hasattr(self, "subscription_timer"):
            self.subscription_timer.stop()

        QMessageBox.warning(
            self,
            "Digi Browser Access Blocked",
            f"{message}\n\nDigi Browser will now close."
        )

        self.close()

    # ========================================================
    # GLOBAL HOTKEY REGISTRATION
    # ========================================================
    def register_global_hotkey(self):

        # ---------------- WINDOWS ----------------
        if IS_WINDOWS:

            self.hotkey_filter = GlobalHotkeyFilter(self)

            user32 = ctypes.WinDLL(
                "user32",
                use_last_error=True
            )

            user32.RegisterHotKey.argtypes = [
                wintypes.HWND,
                ctypes.c_int,
                wintypes.UINT,
                wintypes.UINT
            ]

            user32.RegisterHotKey.restype = wintypes.BOOL

            # Ctrl + Shift + B
            self.hotkey_registered_1 = bool(
                user32.RegisterHotKey(
                    None,
                    HOTKEY_ID_B,
                    MOD_CONTROL | MOD_SHIFT,
                    ord("B")
                )
            )

            # Ctrl + Shift + N
            self.hotkey_registered_2 = bool(
                user32.RegisterHotKey(
                    None,
                    HOTKEY_ID_N,
                    MOD_CONTROL | MOD_SHIFT,
                    ord("N")
                )
            )

            self.hotkey_registered = (
                self.hotkey_registered_1
                or self.hotkey_registered_2
            )

            if self.hotkey_registered:
                QApplication.instance().installNativeEventFilter(
                    self.hotkey_filter
                )

            print(
                "Ctrl + Shift + B:",
                "Registered"
                if self.hotkey_registered_1
                else "Registration failed"
            )

            print(
                "Ctrl + Shift + N:",
                "Registered"
                if self.hotkey_registered_2
                else "Registration failed"
            )

        # ---------------- MACOS ----------------
        elif IS_MACOS:

            self.mac_hotkeys = MacGlobalHotkeys(
                self.restore_signal.restore_signal
            )

            self.mac_hotkeys.start()

        else:
            print("Global shortcuts are not supported on this OS.")

    # ========================================================
    # RESTORE BROWSER
    # ========================================================
    def restore_browser(self):

        if self._session_closing:
            return

        self.showNormal()

        self.setWindowState(
            self.windowState()
            & ~Qt.WindowState.WindowMinimized
        )

        self.show()
        self.raise_()
        self.activateWindow()

        if IS_WINDOWS:

            try:
                ctypes.windll.user32.SetForegroundWindow(
                    wintypes.HWND(int(self.winId()))
                )

            except Exception as error:
                print(
                    "Foreground activation error:",
                    error
                )

        self.schedule_taskbar_removal()

    # ========================================================
    # UNREGISTER GLOBAL HOTKEY
    # ========================================================
    def unregister_global_hotkey(self):

        # ---------------- WINDOWS ----------------
        if IS_WINDOWS:

            if self.hotkey_filter:
                QApplication.instance().removeNativeEventFilter(
                    self.hotkey_filter
                )

            user32 = ctypes.WinDLL("user32")

            if self.hotkey_registered_1:
                user32.UnregisterHotKey(
                    None,
                    HOTKEY_ID_B
                )
                self.hotkey_registered_1 = False

            if self.hotkey_registered_2:
                user32.UnregisterHotKey(
                    None,
                    HOTKEY_ID_N
                )
                self.hotkey_registered_2 = False

            self.hotkey_registered = False

        # ---------------- MACOS ----------------
        elif IS_MACOS:

            if self.mac_hotkeys:
                self.mac_hotkeys.stop()
                self.mac_hotkeys = None

    # ========================================================
    # WINDOWS TASKBAR
    # ========================================================
    def hide_from_taskbar(self):

        if IS_WINDOWS:

            try:
                remove_from_windows_taskbar(
                    int(self.winId())
                )

            except Exception as error:
                print(
                    "Taskbar removal failed:",
                    error
                )

    def schedule_taskbar_removal(self):

        if (
            not IS_WINDOWS
            or self._taskbar_hide_pending
        ):
            return

        self._taskbar_hide_pending = True

        def remove_entry():

            self._taskbar_hide_pending = False

            if self.isVisible():
                self.hide_from_taskbar()

        QTimer.singleShot(
            700,
            remove_entry
        )

    def showEvent(self, event):

        super().showEvent(event)

        self.schedule_taskbar_removal()

        if self.capture_enabled:
            QTimer.singleShot(
                500,
                self.apply_capture_exclusion
            )

    def changeEvent(self, event):

        super().changeEvent(event)

        if event.type() == QEvent.Type.WindowStateChange:
            self.schedule_taskbar_removal()

    def closeEvent(self, event):

        self._session_closing = True

        if hasattr(self, "subscription_timer"):
            self.subscription_timer.stop()

        self.unregister_global_hotkey()

        event.accept()

    # ========================================================
    # UI
    # ========================================================
    def create_ui(self):

        self.privacy_toolbar = QToolBar("Privacy")

        self.privacy_toolbar.setMovable(False)
        self.privacy_toolbar.setFloatable(False)

        self.addToolBar(
            Qt.ToolBarArea.TopToolBarArea,
            self.privacy_toolbar
        )

        self.create_privacy_menu()

        self.transparency_label = QLabel(
            "Opacity: 100%"
        )

        self.transparency_slider = QSlider(
            Qt.Orientation.Horizontal
        )

        self.transparency_slider.setRange(0, 100)
        self.transparency_slider.setValue(100)
        self.transparency_slider.setFixedWidth(150)

        self.transparency_slider.valueChanged.connect(
            self.change_transparency
        )

        spacer = QWidget()

        spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred
        )

        self.privacy_toolbar.addWidget(spacer)
        self.privacy_toolbar.addWidget(
            self.transparency_label
        )
        self.privacy_toolbar.addWidget(
            self.transparency_slider
        )

        self.addToolBarBreak(
            Qt.ToolBarArea.TopToolBarArea
        )

        toolbar = QToolBar("Navigation")

        toolbar.setMovable(False)
        toolbar.setFloatable(False)

        self.addToolBar(
            Qt.ToolBarArea.TopToolBarArea,
            toolbar
        )

        back = QToolButton()

        back.setIcon(
            create_chevron_icon("back")
        )

        back.setIconSize(QSize(20, 20))
        back.setFixedSize(32, 32)
        back.setToolTip("Back")

        back.clicked.connect(
            lambda: self.current_view().back()
            if self.current_view() else None
        )

        forward = QToolButton()

        forward.setIcon(
            create_chevron_icon("forward")
        )

        forward.setIconSize(QSize(20, 20))
        forward.setFixedSize(32, 32)
        forward.setToolTip("Forward")

        forward.clicked.connect(
            lambda: self.current_view().forward()
            if self.current_view() else None
        )

        self.reload_button = LoadingButton()

        self.reload_button.clicked.connect(
            self.reload_or_stop
        )

        home = QToolButton()
        home.setText("🏠")

        font = home.font()
        font.setPointSize(15)
        home.setFont(font)

        home.setFixedSize(32, 32)
        home.setToolTip("Home")

        home.clicked.connect(
            lambda: self.navigate(
                "https://www.google.com/"
            )
        )

        self.address_bar = QLineEdit()

        self.address_bar.setPlaceholderText(
            "Search Google or enter website address"
        )

        self.address_bar.setMinimumHeight(36)

        self.address_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed
        )

        self.address_bar.setStyleSheet(
            "QLineEdit { font-size: 15px; "
            "padding: 5px 12px; border-radius: 8px; }"
        )

        self.address_bar.returnPressed.connect(
            self.load_address
        )

        bookmark = QToolButton()
        bookmark.setText("☆")

        font = bookmark.font()
        font.setPointSize(15)
        bookmark.setFont(font)

        bookmark.setFixedSize(32, 32)
        bookmark.setToolTip("Bookmark")

        bookmark.clicked.connect(
            self.add_bookmark
        )

        self.capture_button = QPushButton(
            "Capture Exclusion: OFF"
        )

        self.capture_button.setCheckable(True)

        self.capture_button.clicked.connect(
            self.toggle_capture_exclusion
        )

        for widget in (
            back,
            forward,
            self.reload_button,
            home,
            self.address_bar,
            bookmark,
            self.capture_button
        ):
            toolbar.addWidget(widget)

        self.tabs = QTabWidget()

        self.tab_bar = ChromeTabBar()

        self.tabs.setTabBar(self.tab_bar)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)

        self.tabs.currentChanged.connect(
            self.on_tab_changed
        )

        self.tabs.tabCloseRequested.connect(
            self.close_tab
        )

        self.tab_bar.tabMoved.connect(
            self.keep_plus_tab_last
        )

        self.plus_tab = QWidget()

        plus_index = self.tabs.addTab(
            self.plus_tab,
            "+"
        )

        self.tab_bar.set_plus_index(
            plus_index
        )

        self.tab_bar.setTabTextColor(
            plus_index,
            QColor("#202124")
        )

        self.tab_bar.setStyleSheet(
            "QTabBar::tab:last { font-size: 24px; "
            "min-width: 42px; padding: 0px; }"
        )

        self.tab_bar.setTabButton(
            plus_index,
            QTabBar.ButtonPosition.LeftSide,
            None
        )

        self.tab_bar.setTabButton(
            plus_index,
            QTabBar.ButtonPosition.RightSide,
            None
        )

        self.tab_bar.add_tab_callback = (
            self.open_new_google_tab
        )

        self.tabs.setCurrentIndex(-1)

        self.setCentralWidget(self.tabs)

    def update_loading_indicator(self, tab, loading):

        if tab is self.current_tab():
            self.reload_button.set_loading(loading)

    def reload_or_stop(self):

        tab = self.current_tab()

        if not tab:
            return

        if tab.is_loading:
            tab.view.stop()
            tab.is_loading = False
            self.reload_button.set_loading(False)
        else:
            tab.view.reload()

    # ========================================================
    # PLUS TAB
    # ========================================================
    def get_plus_index(self):
        return self.tabs.indexOf(self.plus_tab)

    def open_new_google_tab(self):
        self.add_tab("https://www.google.com")

    def keep_plus_tab_last(self, from_index, to_index):

        if self._moving_plus_tab:
            return

        plus_index = self.get_plus_index()
        last_index = self.tabs.count() - 1

        if plus_index == last_index:
            return

        self._moving_plus_tab = True

        self.tab_bar.moveTab(
            plus_index,
            last_index
        )

        self._moving_plus_tab = False

        self.tab_bar.set_plus_index(
            self.get_plus_index()
        )

        self.tab_bar.setTabButton(
            self.get_plus_index(),
            QTabBar.ButtonPosition.RightSide,
            None
        )

    # ========================================================
    # TAB CHANGE
    # ========================================================
    def on_tab_changed(self, index):

        if index < 0:
            self.address_bar.clear()
            self.reload_button.set_loading(False)
            return

        widget = self.tabs.widget(index)

        if widget is self.plus_tab:

            previous = index - 1

            if previous >= 0:
                self.tabs.setCurrentIndex(previous)
            else:
                self.address_bar.clear()
                self.reload_button.set_loading(False)

            return

        if isinstance(widget, BrowserTab):

            self.address_bar.setText(
                widget.view.url().toString()
            )

            self.reload_button.set_loading(
                widget.is_loading
            )

    # ========================================================
    # PRIVACY MENU
    # ========================================================
    def create_privacy_menu(self):

        menu_action = self.privacy_toolbar.addAction(
            "Privacy"
        )

        self.privacy_menu = QMenu(self)

        self.capture_action = QAction(
            "Exclude Browser from Screen Capture",
            self
        )

        self.capture_action.setCheckable(True)

        self.capture_action.triggered.connect(
            self.toggle_capture_exclusion
        )

        self.privacy_menu.addAction(
            self.capture_action
        )

        menu_action.setMenu(
            self.privacy_menu
        )

        menu_action.setToolTip(
            "Privacy Settings"
        )

    def toggle_capture_exclusion(self, enabled):

        try:

            if not self.isVisible():
                raise RuntimeError(
                    "Browser window is not visible yet."
                )

            set_capture_exclusion(
                int(self.winId()),
                enabled
            )

            self.capture_enabled = enabled

            self.sync_capture_controls(enabled)

            if enabled:
                print("Capture Exclusion enabled.")
            else:
                print("Capture Exclusion disabled.")

        except Exception as error:

            self.capture_enabled = False

            self.sync_capture_controls(False)

            QMessageBox.warning(
                self,
                "Capture Exclusion Error",
                str(error)
            )

    def apply_capture_exclusion(self):

        if not self.capture_enabled:
            return

        try:

            set_capture_exclusion(
                int(self.winId()),
                True
            )

            print("Capture Exclusion re-applied.")

        except Exception as error:

            self.capture_enabled = False
            self.sync_capture_controls(False)

            QMessageBox.warning(
                self,
                "Capture Exclusion Error",
                str(error)
            )

    def sync_capture_controls(self, enabled):

        self.capture_button.blockSignals(True)
        self.capture_action.blockSignals(True)

        self.capture_button.setChecked(enabled)
        self.capture_action.setChecked(enabled)

        self.capture_button.setText(
            "Capture Exclusion: ON"
            if enabled
            else "Capture Exclusion: OFF"
        )

        self.capture_button.blockSignals(False)
        self.capture_action.blockSignals(False)

    # ========================================================
    # OPACITY
    # ========================================================
    def change_transparency(self, value):

        self.transparency_label.setText(
            f"Opacity: {value}%"
        )

        self.setWindowOpacity(
            value / 100.0
        )

    def restore_opacity(self):
        self.transparency_slider.setValue(100)

    # ========================================================
    # APPLICATION SHORTCUTS
    # ========================================================
    def create_shortcuts(self):

        modifier = "Meta" if IS_MACOS else "Ctrl"

        actions = [
            (f"{modifier}+T", self.open_new_google_tab),
            (
                f"{modifier}+W",
                lambda: self.close_tab(
                    self.tabs.currentIndex()
                )
            ),
            (f"{modifier}+L", self.address_bar.setFocus),
            (
                f"{modifier}+Shift+U",
                self.restore_opacity
            ),
        ]

        for shortcut, callback in actions:

            action = QAction(self)

            action.setShortcut(
                QKeySequence(shortcut)
            )

            action.triggered.connect(callback)

            self.addAction(action)

    # ========================================================
    # TABS
    # ========================================================
    def add_tab(self, url=None):

        tab = BrowserTab(
            self,
            self.profile
        )

        index = self.tabs.insertTab(
            self.get_plus_index(),
            tab,
            "New Tab"
        )

        self.tabs.setCurrentIndex(index)

        self.tab_bar.set_plus_index(
            self.get_plus_index()
        )

        tab.view.setUrl(
            QUrl(url or "https://www.google.com")
        )

        self.tab_bar.setTabButton(
            self.get_plus_index(),
            QTabBar.ButtonPosition.RightSide,
            None
        )

        return tab

    def close_tab(self, index):

        if index < 0:
            return

        widget = self.tabs.widget(index)

        if widget is self.plus_tab:
            return

        current_widget = self.current_tab()
        closing_current = widget is current_widget

        if self.tabs.count() - 1 <= 1:
            self.close()
            return

        self.tabs.removeTab(index)
        widget.deleteLater()

        self.tab_bar.set_plus_index(
            self.get_plus_index()
        )

        self.tab_bar.setTabButton(
            self.get_plus_index(),
            QTabBar.ButtonPosition.RightSide,
            None
        )

        if closing_current:
            self.tabs.setCurrentIndex(
                max(0, index - 1)
            )
        else:
            remaining = self.tabs.indexOf(
                current_widget
            )

            if remaining != -1:
                self.tabs.setCurrentIndex(remaining)

        self.on_tab_changed(
            self.tabs.currentIndex()
        )

    def current_tab(self):

        tab = self.tabs.currentWidget()

        if tab is self.plus_tab:
            return None

        return (
            tab
            if isinstance(tab, BrowserTab)
            else None
        )

    def current_view(self):

        tab = self.current_tab()

        return tab.view if tab else None

    # ========================================================
    # NAVIGATION
    # ========================================================
    def load_address(self):

        text = self.address_bar.text().strip()

        if not text:
            return

        if " " in text or "." not in text:

            url = QUrl(
                "https://www.google.com/search?q="
                + quote_plus(text)
            )

        elif not text.startswith(
            ("http://", "https://")
        ):

            url = QUrl(
                "https://" + text
            )

        else:
            url = QUrl(text)

        self.navigate(
            url.toString()
        )

    def navigate(self, url):

        view = self.current_view()

        if view:
            view.setUrl(QUrl(url))

    # ========================================================
    # BOOKMARKS
    # ========================================================
    def add_bookmark(self):

        view = self.current_view()

        if not view:
            return

        url = view.url().toString()

        if not url:
            return

        bookmarks = load_json(
            BOOKMARK_FILE,
            []
        )

        if url not in bookmarks:
            bookmarks.append(url)

        save_json(
            BOOKMARK_FILE,
            bookmarks
        )

        QMessageBox.information(
            self,
            "Bookmark Saved",
            "Website added to bookmarks."
        )


# ============================================================
# APPLICATION ENTRY POINT
# ============================================================
if __name__ == "__main__":

    app = QApplication(sys.argv)

    app.setOrganizationName("Digi")
    app.setApplicationName(APP_NAME)

    login_dialog = LoginDialog()

    if (
        login_dialog.exec()
        != QDialog.DialogCode.Accepted
    ):
        sys.exit(0)

    browser = PrivacyBrowser(
        access_token=login_dialog.access_token,
        refresh_token=login_dialog.refresh_token,
        user_email=login_dialog.user_email
    )

    browser.showMaximized()

    sys.exit(app.exec())