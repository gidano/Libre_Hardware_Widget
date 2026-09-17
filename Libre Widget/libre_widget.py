import ctypes
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from ctypes import wintypes

import psutil
from PySide6.QtCore import Qt, QTimer, QPoint, QSize, QSettings
from PySide6.QtGui import QFont, QAction, QIcon, QCursor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QSizeGrip,
    QSizePolicy,
    QStyle,
    QSystemTrayIcon,
    QToolTip,
    QVBoxLayout,
    QWidget,
)


LHM_HTTP_URLS = (
    "http://127.0.0.1:8085/data.json",
)
LHM_WMI_NAMESPACE = r"root\LibreHardwareMonitor"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
kernel32.GetDriveTypeW.restype = wintypes.UINT

kernel32.GetVolumeInformationW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPWSTR,
    wintypes.DWORD,
]
kernel32.GetVolumeInformationW.restype = wintypes.BOOL


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL


def windows_physical_memory_values():
    """
    A Windows által ténylegesen használható fizikai RAM adatai MB-ban.

    A teljes RAM-ot szándékosan nem a Libre "Memory Used" +
    "Memory Available" szenzoraiból számoljuk, mert azok egyes verziókban
    eltérő egység/összesítés miatt hibás teljes értéket adhatnak.
    """
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)

    if kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        total_mb = status.ullTotalPhys / (1024 ** 2)
        available_mb = status.ullAvailPhys / (1024 ** 2)
        used_mb = max(0.0, total_mb - available_mb)
        load = (used_mb / total_mb * 100.0) if total_mb > 0 else None
        return used_mb, available_mb, total_mb, load

    # Ritka API-hiba esetén a psutil ugyanennek a Windows-adatnak
    # a hordozható elérését biztosítja.
    try:
        vm = psutil.virtual_memory()
        total_mb = vm.total / (1024 ** 2)
        available_mb = vm.available / (1024 ** 2)
        used_mb = max(0.0, total_mb - available_mb)
        load = (used_mb / total_mb * 100.0) if total_mb > 0 else float(vm.percent)
        return used_mb, available_mb, total_mb, load
    except Exception:
        return None, None, None, None


def fmt(value, decimals=1, fallback="N/A"):
    if value is None:
        return fallback
    return f"{value:.{decimals}f}"


def fmt_net_speed(value, fallback="N/A"):
    """
    Hálózati sebesség kijelzése kB/s alapértékből.
    1000 kB/s felett MB/s-ra vált.
    """
    if value is None:
        return fallback

    try:
        value = float(value)
    except Exception:
        return fallback

    if abs(value) > 1000:
        return f"{value / 1000.0:.2f} MB/s"

    return f"{value:.1f} KB/s"


def gb_from_mb(value_mb: float) -> float:
    return value_mb / 1024.0


def resource_path(filename):
    """
    Ikon és egyéb mellékelt fájlok elérése .pyw és PyInstaller .exe esetén is.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, filename)

    return os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), filename)


def load_app_icon():
    ico = resource_path("app_icon.ico")
    png = resource_path("icon.png")

    if os.path.exists(ico):
        icon = QIcon(ico)
        if not icon.isNull():
            return icon

    if os.path.exists(png):
        icon = QIcon(png)
        if not icon.isNull():
            return icon

    return QIcon()


def set_windows_app_id():
    """
    Windows tálcaikon javítás .pyw futtatásnál.
    Enélkül a tálca sokszor a pythonw.exe / .pyw fájltípus ikonját mutatja.
    EXE esetén a --icon adja a végleges ikont, de ez ott sem árt.
    """
    try:
        app_id = "gidano.LibreHardwareWidget.1"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def temp_color(value, kind="cpu"):
    """
    System-monitor jellegű hőfokszínezés.
    CPU:   zöld <65°C, narancs 65-79°C, piros >=80°C
    DRIVE: zöld <50°C, narancs 50-59°C, piros >=60°C
    """
    if value is None:
        return "#b0b0b0"

    try:
        value = float(value)
    except Exception:
        return "#b0b0b0"

    if kind == "drive":
        if value < 50:
            return "#50d050"
        if value < 60:
            return "#ffb000"
        return "#ff5050"

    if value < 65:
        return "#50d050"
    if value < 80:
        return "#ffb000"
    return "#ff5050"


def cmos_voltage_color(value):
    """
    BIOS/CMOS elem feszültségszínezése az ESP32-monitorral azonos határokkal.
    Zöld: >= 2.95 V, narancs: 2.80-2.94 V, piros: < 2.80 V.
    """
    if value is None:
        return "#b0b0b0"

    try:
        value = float(value)
    except Exception:
        return "#b0b0b0"

    if value >= 2.95:
        return "#50d050"
    if value >= 2.80:
        return "#ffb000"
    return "#ff5050"


def usage_color(percent):
    """
    Meghajtó/RAM telítettség színezése.
    Zöld <75%, narancs 75-89%, piros >=90%.
    """
    if percent is None:
        return "#50d050"

    try:
        percent = float(percent)
    except Exception:
        return "#50d050"

    if percent < 75:
        return "#50d050"
    if percent < 90:
        return "#ffb000"
    return "#ff5050"


def label_style(color):
    return (
        "background: #050505; "
        f"color: {color}; "
        "font-weight: bold;"
    )


def neutral_label_style():
    return (
        "background: #050505; "
        "color: #eeeeee; "
        "font-weight: bold;"
    )


TRANSLATIONS = {
    "hu": {
        "app_title": "Libre Hardver Widget",
        "tray_tooltip": "Libre Hardver Widget",
        "tray_ok": "OK",
        "section_cpu": "CPU-RAM",
        "section_drives": "MEGHAJTÓK",
        "section_network": "HÁLÓZAT",
        "label_cpu_temp": "CPU hőmérséklet:",
        "label_cpu_usage": "CPU használat:",
        "label_cpu_clock": "CPU órajel:",
        "label_cpu_fan": "CPU vent.:",
        "label_mb_fan": "Alaplapi vent.:",
        "label_ram": "RAM:",
        "label_cmos": "CMOS elem:",
        "label_external_ip": "Külső IP:",
        "label_internal_ip": "Belső IP:",
        "label_ssid": "SSID:",
        "label_signal": "Jelerősség:",
        "label_down": "Letöltés:",
        "label_up": "Feltöltés:",
        "status_tooltip": "Állapot / riasztások",
        "menu_show_hide": "Mutatás / elrejtés",
        "menu_always_on_top": "Mindig felül",
        "menu_position": "Pozíció",
        "menu_top_left": "Bal felső",
        "menu_top_right": "Jobb felső",
        "menu_bottom_left": "Bal alsó",
        "menu_bottom_right": "Jobb alsó",
        "menu_left_center": "Bal közép",
        "menu_right_center": "Jobb közép",
        "menu_top_center": "Felső közép",
        "menu_bottom_center": "Alsó közép",
        "menu_center": "Középre",
        "menu_exit": "Kilépés",
        "menu_frameless": "Fejléc elrejtése (widget mód)",
        "menu_show_network": "Hálózat widget megjelenítése",
        "menu_show_drives": "Meghajtók widget megjelenítése",
        "menu_usb_only": "Csak USB meghajtók",
        "menu_compact": "Kompakt mód",
        "menu_alerts": "Riasztások megjelenítése",
        "menu_udp": "UDP küldés ESP32-re",
        "menu_startup": "Indítás a rendszerrel",
        "menu_hide_to_tray": "Elrejtés a Tálcára",
        "menu_refresh_ip": "Külső IP frissítése",
        "menu_reset_size": "Méret visszaállítása",
        "menu_opacity": "Átlátszóság",
        "menu_language": "Nyelv / Language",
        "lang_hu": "Magyar",
        "lang_en": "English",
        "status_udp": "UDP",
        "status_always_on_top_inactive": "inaktív a Mindig felül",
        "status_libre_off": "Libre Hardware Monitor nincs csatlakozva – újrapróbálkozás...",
        "cpu_tip_temp": "CPU hőfok: {value}",
        "cpu_tip_usage": "CPU terhelés: {value}",
        "cpu_tip_clock": "CPU órajel: {value}",
        "cpu_tip_cpu_fan": "CPU ventilátor: {value}",
        "cpu_tip_mb_fan": "Alaplapi/ház ventilátor: {value}",
        "cpu_tip_power": "CPU Package Power: {value}",
        "drive_label": "Meghajtó",
        "drive_type": "Típus",
        "drive_type_usb": "USB",
        "drive_type_fixed": "Fix",
        "drive_physical": "Fizikai lemez",
        "drive_used": "Használt",
        "drive_total": "Teljes",
        "drive_usage": "Telítettség",
        "drive_temp": "Hőfok",
        "drive_life": "SSD élettartam",
        "drive_warning": "Drive warning",
        "drive_failure": "Drive failure",
        "yes": "YES",
        "no": "NO",
        "drive_open_hint": "Kattints a meghajtónévre a megnyitáshoz.",
        "open_in_explorer": "Megnyitás fájlkezelőben: {path}",
        "host_reads": "Host reads",
        "host_reads_boot": "Host reads (boot óta)",
        "host_writes": "Host writes",
        "host_writes_boot": "Host writes (boot óta)",
        "not_available": "N/A",
        "no_drive": "nincs meghajtó",
        "drive_unavailable": "{letter}: nem elérhető",
        "libre_off_tip1": "A Libre Hardware Monitor nem ad friss szenzoradatot.",
        "libre_off_tip2": "Indítsd el a LibreHardwareMonitor.exe-t, lehetőleg rendszergazdaként.",
        "libre_off_tip3": "A biztos kapcsolathoz: Options > Remote Web Server > Run (port 8085).",
        "ram_used": "RAM használt",
        "ram_available": "RAM elérhető",
        "ram_total": "RAM teljes (Windows által használható)",
        "ram_load": "Terhelés",
        "source": "Forrás",
        "source_windows_memory": "Windows fizikai memória",
        "cmos_battery": "BIOS/CMOS elem",
        "identifier": "Azonosító",
        "coloring": "Színezés",
        "green_threshold": "zöld: >= 2.95 V",
        "orange_threshold": "narancs: 2.80-2.94 V",
        "red_threshold": "piros: < 2.80 V",
        "cmos_missing_1": "A Libre Hardware Monitor nem publikált felismerhető CMOS/VBAT értéket.",
        "cmos_missing_2": "A widget a VBAT/CMOS/RTC Battery neveket és a Nuvoton in8 / Voltage #8 nyers csatornát is keresi.",
        "net_tip_external": "Külső IP: {value}",
        "net_tip_internal": "Belső IP: {value}",
        "net_tip_ssid": "SSID: {value}",
        "net_tip_signal": "Jelerősség: {value}",
        "net_tip_down": "Letöltés: {value}",
        "net_tip_up": "Feltöltés: {value}",
        "net_tip_down_na": "Letöltés/feltöltés: N/A – nincs friss Libre Hardware Monitor adat",
        "alert_cpu_hot": "CPU meleg: {value}",
        "alert_cpu_high": "CPU magas: {value}",
        "alert_ram_high": "RAM magas: {value}",
        "alert_cmos_low": "CMOS elem alacsony: {value}",
        "alert_cmos_weak": "CMOS elem gyengül: {value}",
        "alert_drive_full": "{letter}: tele: {value}",
        "alert_drive_hot": "{letter}: meleg: {value}",
        "startup_error_title": "Startup hiba",
        "startup_error_body": "Nem sikerült módosítani az automatikus indítást:\n{error}",
    },
    "en": {
        "app_title": "Libre Hardware Widget",
        "tray_tooltip": "Libre Hardware Widget",
        "tray_ok": "OK",
        "section_cpu": "CPU-RAM",
        "section_drives": "DRIVES",
        "section_network": "NETWORK",
        "label_cpu_temp": "CPU temperature:",
        "label_cpu_usage": "CPU usage:",
        "label_cpu_clock": "CPU clock:",
        "label_cpu_fan": "CPU fan:",
        "label_mb_fan": "Motherboard fan:",
        "label_ram": "RAM:",
        "label_cmos": "CMOS battery:",
        "label_external_ip": "External IP:",
        "label_internal_ip": "Internal IP:",
        "label_ssid": "SSID:",
        "label_signal": "Signal strength:",
        "label_down": "Download:",
        "label_up": "Upload:",
        "status_tooltip": "Status / alerts",
        "menu_show_hide": "Show / hide",
        "menu_always_on_top": "Always on top",
        "menu_position": "Position",
        "menu_top_left": "Top left",
        "menu_top_right": "Top right",
        "menu_bottom_left": "Bottom left",
        "menu_bottom_right": "Bottom right",
        "menu_left_center": "Left center",
        "menu_right_center": "Right center",
        "menu_top_center": "Top center",
        "menu_bottom_center": "Bottom center",
        "menu_center": "Center",
        "menu_exit": "Exit",
        "menu_frameless": "Hide title bar (widget mode)",
        "menu_show_network": "Show network widget",
        "menu_show_drives": "Show drives widget",
        "menu_usb_only": "USB drives only",
        "menu_compact": "Compact mode",
        "menu_alerts": "Show alerts",
        "menu_udp": "Send UDP to ESP32",
        "menu_startup": "Start with system",
        "menu_hide_to_tray": "Hide to tray",
        "menu_refresh_ip": "Refresh external IP",
        "menu_reset_size": "Reset size",
        "menu_opacity": "Opacity",
        "menu_language": "Language / Nyelv",
        "lang_hu": "Magyar",
        "lang_en": "English",
        "status_udp": "UDP",
        "status_always_on_top_inactive": "Always on top inactive",
        "status_libre_off": "Libre Hardware Monitor is not connected – retrying...",
        "cpu_tip_temp": "CPU temperature: {value}",
        "cpu_tip_usage": "CPU usage: {value}",
        "cpu_tip_clock": "CPU clock: {value}",
        "cpu_tip_cpu_fan": "CPU fan: {value}",
        "cpu_tip_mb_fan": "Motherboard/case fan: {value}",
        "cpu_tip_power": "CPU package power: {value}",
        "drive_label": "Drive",
        "drive_type": "Type",
        "drive_type_usb": "USB",
        "drive_type_fixed": "Fixed",
        "drive_physical": "Physical disk",
        "drive_used": "Used",
        "drive_total": "Total",
        "drive_usage": "Usage",
        "drive_temp": "Temperature",
        "drive_life": "SSD life",
        "drive_warning": "Drive warning",
        "drive_failure": "Drive failure",
        "yes": "YES",
        "no": "NO",
        "drive_open_hint": "Click the drive name to open it.",
        "open_in_explorer": "Open in File Explorer: {path}",
        "host_reads": "Host reads",
        "host_reads_boot": "Host reads (since boot)",
        "host_writes": "Host writes",
        "host_writes_boot": "Host writes (since boot)",
        "not_available": "N/A",
        "no_drive": "drive unavailable",
        "drive_unavailable": "{letter}: unavailable",
        "libre_off_tip1": "Libre Hardware Monitor is not providing fresh sensor data.",
        "libre_off_tip2": "Start LibreHardwareMonitor.exe, preferably as administrator.",
        "libre_off_tip3": "For a reliable connection: Options > Remote Web Server > Run (port 8085).",
        "ram_used": "RAM used",
        "ram_available": "RAM available",
        "ram_total": "RAM total (Windows usable)",
        "ram_load": "Load",
        "source": "Source",
        "source_windows_memory": "Windows physical memory",
        "cmos_battery": "BIOS/CMOS battery",
        "identifier": "Identifier",
        "coloring": "Coloring",
        "green_threshold": "green: >= 2.95 V",
        "orange_threshold": "orange: 2.80-2.94 V",
        "red_threshold": "red: < 2.80 V",
        "cmos_missing_1": "Libre Hardware Monitor did not publish a recognizable CMOS/VBAT value.",
        "cmos_missing_2": "The widget also looks for VBAT/CMOS/RTC Battery names and the raw Nuvoton in8 / Voltage #8 channel.",
        "net_tip_external": "External IP: {value}",
        "net_tip_internal": "Internal IP: {value}",
        "net_tip_ssid": "SSID: {value}",
        "net_tip_signal": "Signal strength: {value}",
        "net_tip_down": "Download: {value}",
        "net_tip_up": "Upload: {value}",
        "net_tip_down_na": "Download/upload: N/A – no fresh Libre Hardware Monitor data",
        "alert_cpu_hot": "CPU hot: {value}",
        "alert_cpu_high": "CPU high: {value}",
        "alert_ram_high": "RAM high: {value}",
        "alert_cmos_low": "CMOS battery low: {value}",
        "alert_cmos_weak": "CMOS battery weakening: {value}",
        "alert_drive_full": "{letter}: full: {value}",
        "alert_drive_hot": "{letter}: hot: {value}",
        "startup_error_title": "Startup error",
        "startup_error_body": "Could not modify startup setting:\n{error}",
    },
}


def tr_text(lang, key, **kwargs):
    table = TRANSLATIONS.get(lang, TRANSLATIONS["hu"])
    text = table.get(key, TRANSLATIONS["hu"].get(key, key))
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


def colored_span(text, color):
    return f'<span style="color:{color}; font-weight:700;">{text}</span>'


def usage_text_color(percent):
    # A százalékos terhelés/telítettség színe külön, nem a teljes soré.
    return usage_color(percent)


def bar_style(color):
    return f"""
        QProgressBar {{
            background: #202020;
            border: 1px solid #444444;
            min-height: 5px;
            max-height: 5px;
            text-align: center;
        }}

        QProgressBar::chunk {{
            background: {color};
        }}
    """


def get_internal_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "N/A"


def get_external_ip():
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=2) as r:
            return r.read().decode("utf-8").strip()
    except Exception:
        return "N/A"


def get_wifi_info():
    try:
        out = subprocess.check_output(
            ["netsh", "wlan", "show", "interfaces"],
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=2,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return "N/A", 0

    ssid = "N/A"
    signal = 0
    connected = False

    for line in out.splitlines():
        line = line.strip()
        lower = line.lower()

        if lower.startswith("state") or lower.startswith("állapot"):
            connected = "connected" in lower or "csatlakoztatva" in lower

        elif lower.startswith("ssid") and "bssid" not in lower:
            parts = line.split(":", 1)
            if len(parts) == 2:
                ssid = parts[1].strip()

        elif lower.startswith("signal") or lower.startswith("jel"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                raw = parts[1].strip().replace("%", "")
                try:
                    signal = int(raw)
                except ValueError:
                    signal = 0

    if not connected:
        return "N/A", 0

    return ssid or "Connected", signal


def volume_label(root):
    try:
        name_buf = ctypes.create_unicode_buffer(261)
        fs_buf = ctypes.create_unicode_buffer(261)
        serial = wintypes.DWORD()
        max_comp_len = wintypes.DWORD()
        flags = wintypes.DWORD()

        ok = kernel32.GetVolumeInformationW(
            root,
            name_buf,
            len(name_buf),
            ctypes.byref(serial),
            ctypes.byref(max_comp_len),
            ctypes.byref(flags),
            fs_buf,
            len(fs_buf),
        )
        if ok and name_buf.value.strip():
            return name_buf.value.strip()
    except Exception:
        pass
    return ""


_DRIVE_META_CACHE = {"timestamp": 0.0, "mapping": {}}


def _run_powershell_json(script, timeout=6):
    command = [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
    ]
    output = subprocess.check_output(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    ).strip()
    if not output:
        return None
    return json.loads(output.lstrip("\ufeff"))


def _physical_drive_mapping(force=False):
    """Logical drive letter -> physical disk metadata, cached for 30 seconds."""
    now = time.monotonic()
    if not force and now - _DRIVE_META_CACHE["timestamp"] < 30:
        return _DRIVE_META_CACHE["mapping"]

    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$result = @()
Get-CimInstance Win32_DiskDrive | ForEach-Object {
    $disk = $_
    Get-CimAssociatedInstance -InputObject $disk -Association Win32_DiskDriveToDiskPartition | ForEach-Object {
        $part = $_
        Get-CimAssociatedInstance -InputObject $part -Association Win32_LogicalDiskToPartition | ForEach-Object {
            $logical = $_
            $result += [pscustomobject]@{
                Letter = $logical.DeviceID.Substring(0, 1)
                Model = [string]$disk.Model
                Serial = [string]$disk.SerialNumber
                Index = [int]$disk.Index
                InterfaceType = [string]$disk.InterfaceType
                PNPDeviceID = [string]$disk.PNPDeviceID
            }
        }
    }
}
$result | ConvertTo-Json -Depth 4 -Compress
"""

    mapping = {}
    try:
        data = _run_powershell_json(script, timeout=8)
        if isinstance(data, dict):
            data = [data]
        for item in data or []:
            letter = str(item.get("Letter", "")).upper().strip()
            if not letter:
                continue
            mapping[letter] = {
                "physical_model": str(item.get("Model", "")).strip(),
                "physical_serial": str(item.get("Serial", "")).strip(),
                "disk_index": item.get("Index"),
                "interface_type": str(item.get("InterfaceType", "")).strip(),
                "pnp_device_id": str(item.get("PNPDeviceID", "")).strip(),
            }
    except Exception:
        mapping = _DRIVE_META_CACHE.get("mapping", {})

    _DRIVE_META_CACHE["timestamp"] = now
    _DRIVE_META_CACHE["mapping"] = mapping
    return mapping


_DISK_IO_CACHE = {"timestamp": 0.0, "counters": {}}


def physical_disk_io_since_boot_gb(drive):
    """Windows fizikai lemez I/O számlálói a rendszerindítás óta, GB-ban."""
    disk_index = drive.get("disk_index")
    if disk_index is None:
        return None, None

    now = time.monotonic()
    if now - _DISK_IO_CACHE["timestamp"] > 1.0:
        try:
            _DISK_IO_CACHE["counters"] = psutil.disk_io_counters(perdisk=True) or {}
            _DISK_IO_CACHE["timestamp"] = now
        except Exception:
            return None, None

    wanted = int(disk_index)
    match = None
    for key, counter in _DISK_IO_CACHE["counters"].items():
        normalized = re.sub(r"[^a-z0-9]+", "", str(key).lower())
        if normalized == f"physicaldrive{wanted}":
            match = counter
            break

    if match is None:
        # Egyes psutil/Windows verziók kissé más néven adják vissza a kulcsot.
        pattern = re.compile(rf"(?:physicaldrive|disk)0*{wanted}(?:$|[^0-9])", re.I)
        for key, counter in _DISK_IO_CACHE["counters"].items():
            if pattern.search(str(key)):
                match = counter
                break

    if match is None:
        return None, None

    try:
        read_gb = float(getattr(match, "read_bytes")) / (1024 ** 3)
    except Exception:
        read_gb = None
    try:
        write_gb = float(getattr(match, "write_bytes")) / (1024 ** 3)
    except Exception:
        write_gb = None
    return read_gb, write_gb


def connected_local_drives():
    drives = {}
    physical_map = _physical_drive_mapping()

    for part in psutil.disk_partitions(all=False):
        device = part.device or ""
        if len(device) < 2 or device[1] != ":":
            continue

        letter = device[0].upper()
        root = f"{letter}:\\"
        drive_type = int(kernel32.GetDriveTypeW(root))

        if drive_type not in (DRIVE_FIXED, DRIVE_REMOVABLE):
            continue

        try:
            psutil.disk_usage(root)
        except Exception:
            continue

        label = volume_label(root)
        kind = "USB" if drive_type == DRIVE_REMOVABLE else "FIX"
        drive = {
            "letter": letter,
            "root": root,
            "label": label,
            "kind": kind,
            "drive_type": drive_type,
        }
        drive.update(physical_map.get(letter, {}))
        drives[letter] = drive

    return sorted(
        drives.values(),
        key=lambda d: (0 if d["drive_type"] == DRIVE_FIXED else 1, d["letter"]),
    )


class LibreHardwareMonitorReader:
    SENSOR_TYPE_MAP = {
        "temperature": "TEMP",
        "voltage": "VOLT",
        "fan": "FAN",
        "flow": "FLOW",
        "clock": "CLOCK",
        "load": "USAGE",
        "control": "CONTROL",
        "level": "LEVEL",
        "factor": "OTHER",
        "power": "POWER",
        "data": "DATA",
        "smalldata": "SMALLDATA",
        "throughput": "THROUGHPUT",
        "time": "TIME",
        "energy": "ENERGY",
        "noise": "NOISE",
        "conductivity": "CONDUCTIVITY",
        "humidity": "HUMIDITY",
    }

    TYPE_DEFAULT_UNIT = {
        "TEMP": "°C",
        "VOLT": "V",
        "FAN": "RPM",
        "FLOW": "L/h",
        "CLOCK": "MHz",
        "USAGE": "%",
        "CONTROL": "%",
        "LEVEL": "%",
        "POWER": "W",
        "DATA": "GB",
        "SMALLDATA": "MB",
        "THROUGHPUT": "B/s",
        "TIME": "s",
        "ENERGY": "mWh",
        "NOISE": "dBA",
        "CONDUCTIVITY": "µS/cm",
        "HUMIDITY": "%",
    }

    HARDWARE_ICONS = {
        "cpu.png": "cpu",
        "ram.png": "memory",
        "memory.png": "memory",
        "mainboard.png": "motherboard",
        "chip.png": "motherboard",
        "hdd.png": "storage",
        "ssd.png": "storage",
        "nvme.png": "storage",
        "nic.png": "network",
        "network.png": "network",
        "gpu.png": "gpu",
    }

    def __init__(self):
        self.mode = None
        self.endpoint = None
        self.last_error = ""
        self.last_success_ts = 0.0
        self._cached_readings = None
        self._cache_ts = 0.0
        self._wmi_service = None
        self._pythoncom = None

    def is_open(self):
        return self.mode is not None

    def try_open(self):
        try:
            readings = self._fetch_readings(probe=True)
            self._cached_readings = readings
            self._cache_ts = time.monotonic()
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self.close()
            return False

    def close(self):
        self.mode = None
        self.endpoint = None
        self._cached_readings = None
        self._cache_ts = 0.0
        self._wmi_service = None

    @staticmethod
    def _lhm_process_running():
        try:
            for proc in psutil.process_iter(["name"]):
                name = (proc.info.get("name") or "").lower()
                if "librehardwaremonitor" in name:
                    return True
        except Exception:
            pass
        return False

    def read_all(self):
        now = time.monotonic()
        if self._cached_readings is not None and now - self._cache_ts < 0.75:
            readings = self._cached_readings
            self._cached_readings = None
            return readings

        readings = self._fetch_readings(probe=False)
        self.last_success_ts = now
        return readings

    def _fetch_readings(self, probe=False):
        errors = []

        if self.mode == "http" and self.endpoint:
            try:
                return self._read_http(self.endpoint)
            except Exception as exc:
                errors.append(f"HTTP: {exc}")
                self.mode = None
                self.endpoint = None

        if self.mode == "wmi-com":
            try:
                return self._read_wmi_com()
            except Exception as exc:
                errors.append(f"WMI COM: {exc}")
                self.mode = None
                self._wmi_service = None

        if self.mode == "wmi-powershell":
            try:
                return self._read_wmi_powershell()
            except Exception as exc:
                errors.append(f"WMI PowerShell: {exc}")
                self.mode = None

        # The web server is the most reliable source on current LHM versions.
        for url in LHM_HTTP_URLS:
            try:
                readings = self._read_http(url)
                self.mode = "http"
                self.endpoint = url
                self.last_success_ts = time.monotonic()
                return readings
            except Exception as exc:
                errors.append(f"{url}: {exc}")

        # WMI remains useful when the remote web server is not enabled.
        try:
            readings = self._read_wmi_com()
            self.mode = "wmi-com"
            self.last_success_ts = time.monotonic()
            return readings
        except Exception as exc:
            errors.append(f"WMI COM: {exc}")
            self._wmi_service = None

        try:
            readings = self._read_wmi_powershell()
            self.mode = "wmi-powershell"
            self.last_success_ts = time.monotonic()
            return readings
        except Exception as exc:
            errors.append(f"WMI PowerShell: {exc}")

        detail = " | ".join(errors[-3:])
        raise RuntimeError(
            "Nem érem el a Libre Hardware Monitort. Indítsd el a "
            "LibreHardwareMonitor.exe-t, lehetőleg rendszergazdaként. "
            "A biztos adatkapcsolathoz kapcsold be: Options > Remote Web Server > Run "
            "(alapértelmezett port: 8085)."
            + (f"\n\nRészlet: {detail}" if detail else "")
        )

    @staticmethod
    def _parse_number_and_unit(raw):
        if raw is None:
            return None, ""
        if isinstance(raw, (int, float)):
            return float(raw), ""

        value_text = str(raw).replace("\u00a0", " ").strip()
        if not value_text:
            return None, ""

        match = re.search(r"[-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+)", value_text)
        if not match:
            return None, ""

        try:
            value = float(match.group(0).replace(",", "."))
        except ValueError:
            return None, ""
        unit = value_text[match.end():].strip()
        return value, unit

    @classmethod
    def _normalise_type(cls, raw_type, category=""):
        key = str(raw_type or "").replace(" ", "").lower()
        if key in cls.SENSOR_TYPE_MAP:
            return cls.SENSOR_TYPE_MAP[key]

        category_key = str(category or "").strip().lower()
        if category_key.endswith("s"):
            category_key = category_key[:-1]
        return cls.SENSOR_TYPE_MAP.get(category_key.replace(" ", ""), "OTHER")

    @staticmethod
    def _kind_from_identifier(identifier, hardware_type="", image_url=""):
        hay = f"{identifier} {hardware_type} {image_url}".lower()
        if any(token in hay for token in ("intelcpu", "amdcpu", "cpu")):
            return "cpu"
        if any(token in hay for token in ("memory", "/ram", " ram")):
            return "memory"
        if any(token in hay for token in ("mainboard", "superio", "/lpc", "motherboard")):
            return "motherboard"
        if any(token in hay for token in ("storage", "/hdd", "/nvme", " harddisk", " ssd")):
            return "storage"
        if any(token in hay for token in ("network", "/nic", "ethernet", "wireless")):
            return "network"
        if "gpu" in hay:
            return "gpu"
        return str(hardware_type or "").strip().lower()

    @classmethod
    def _is_hardware_node(cls, node):
        if node.get("HardwareId"):
            return True
        image_name = os.path.basename(str(node.get("ImageURL", "")).replace("\\", "/")).lower()
        return image_name in cls.HARDWARE_ICONS

    @classmethod
    def _hardware_from_node(cls, node):
        hardware_id = str(node.get("HardwareId", "")).strip()
        image_url = str(node.get("ImageURL", "")).strip()
        image_name = os.path.basename(image_url.replace("\\", "/")).lower()
        kind = cls.HARDWARE_ICONS.get(image_name) or cls._kind_from_identifier(hardware_id, "", image_url)
        return {
            "name": str(node.get("Text", "")).strip(),
            "id": hardware_id,
            "kind": kind,
            "image": image_url,
        }

    @classmethod
    def _flatten_http(cls, data):
        readings = []

        def walk(node, path=None, hardware=None):
            if not isinstance(node, dict):
                return
            path = list(path or [])
            text = str(node.get("Text", "")).strip()

            current_hardware = hardware
            if cls._is_hardware_node(node):
                current_hardware = cls._hardware_from_node(node)

            children = node.get("Children") or []
            sensor_id = str(node.get("SensorId", "")).strip()
            raw_type = node.get("Type")
            is_sensor = bool(sensor_id or raw_type) and not children

            if is_sensor:
                category = path[-1] if path else ""
                type_name = cls._normalise_type(raw_type, category)
                raw_value = node.get("RawValue")
                if raw_value in (None, ""):
                    raw_value = node.get("Value")
                value, unit = cls._parse_number_and_unit(raw_value)
                if not unit:
                    _, unit = cls._parse_number_and_unit(node.get("Value"))
                if not unit:
                    unit = cls.TYPE_DEFAULT_UNIT.get(type_name, "")

                if value is not None:
                    hw = current_hardware or {"name": "", "id": "", "kind": "", "image": ""}
                    readings.append(
                        {
                            "type": type_name,
                            "sensor": hw.get("name", ""),
                            "label": text,
                            "unit": unit,
                            "value": float(value),
                            "sensor_id": sensor_id,
                            "hardware_id": hw.get("id", ""),
                            "hardware_type": hw.get("kind", ""),
                            "path": path + ([text] if text else []),
                            "min": node.get("Min"),
                            "max": node.get("Max"),
                        }
                    )

            next_path = path + ([text] if text else [])
            for child in children:
                walk(child, next_path, current_hardware)

        walk(data)
        return readings

    def _read_http(self, url):
        request = urllib.request.Request(
            url,
            headers={
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "User-Agent": "LibreHardwareWidget/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=1.8) as response:
            raw = response.read()
        data = json.loads(raw.decode("utf-8-sig", errors="replace"))
        readings = self._flatten_http(data)
        if not readings:
            raise RuntimeError("a data.json nem tartalmaz szenzorértékeket")
        return readings

    @staticmethod
    def _safe_attr(obj, name, default=""):
        try:
            value = getattr(obj, name)
            return default if value is None else value
        except Exception:
            return default

    @classmethod
    def _flatten_wmi_objects(cls, hardware_items, sensor_items):
        if isinstance(hardware_items, dict):
            hardware_items = [hardware_items]
        if isinstance(sensor_items, dict):
            sensor_items = [sensor_items]

        hardware = {}
        for item in hardware_items:
            if isinstance(item, dict):
                get = item.get
            else:
                get = lambda key, default="", obj=item: cls._safe_attr(obj, key, default)
            identifier = str(get("Identifier", "")).strip()
            hardware[identifier] = {
                "id": identifier,
                "name": str(get("Name", "")).strip(),
                "type": str(get("HardwareType", "")).strip(),
                "parent": str(get("Parent", "")).strip(),
            }

        def resolve_hardware(parent):
            current = str(parent or "").strip()
            seen = set()
            chosen = None
            while current and current not in seen:
                seen.add(current)
                item = hardware.get(current)
                if not item:
                    break
                chosen = item
                if item.get("name"):
                    break
                current = item.get("parent", "")
            return chosen or {"id": str(parent or ""), "name": "", "type": "", "parent": ""}

        readings = []
        for item in sensor_items:
            if isinstance(item, dict):
                get = item.get
            else:
                get = lambda key, default="", obj=item: cls._safe_attr(obj, key, default)

            raw_value = get("Value", None)
            if raw_value is None:
                continue
            try:
                value = float(raw_value)
            except Exception:
                continue

            raw_type = str(get("SensorType", "")).strip()
            type_name = cls._normalise_type(raw_type)
            parent = str(get("Parent", "")).strip()
            hw = resolve_hardware(parent)
            kind = cls._kind_from_identifier(hw.get("id", ""), hw.get("type", ""), "")
            readings.append(
                {
                    "type": type_name,
                    "sensor": hw.get("name", ""),
                    "label": str(get("Name", "")).strip(),
                    "unit": cls.TYPE_DEFAULT_UNIT.get(type_name, ""),
                    "value": value,
                    "sensor_id": str(get("Identifier", "")).strip(),
                    "hardware_id": hw.get("id", ""),
                    "hardware_type": kind,
                    "path": [hw.get("name", ""), raw_type, str(get("Name", "")).strip()],
                    "min": get("Min", None),
                    "max": get("Max", None),
                }
            )
        return readings

    def _read_wmi_com(self):
        if not self._lhm_process_running():
            raise RuntimeError("a Libre Hardware Monitor folyamata nem fut")

        try:
            import pythoncom
            import win32com.client
        except Exception as exc:
            raise RuntimeError("a pywin32 modul nem érhető el") from exc

        if self._wmi_service is None:
            pythoncom.CoInitialize()
            self._pythoncom = pythoncom
            self._wmi_service = win32com.client.GetObject(
                r"winmgmts:\\.\root\LibreHardwareMonitor"
            )

        hardware_items = list(
            self._wmi_service.ExecQuery(
                "SELECT Identifier, Name, HardwareType, Parent FROM Hardware"
            )
        )
        sensor_items = list(
            self._wmi_service.ExecQuery(
                "SELECT Identifier, Name, SensorType, Parent, Value, Min, Max FROM Sensor"
            )
        )
        readings = self._flatten_wmi_objects(hardware_items, sensor_items)
        if not readings:
            raise RuntimeError("a WMI névtér 0 szenzort adott vissza")
        return readings

    def _read_wmi_powershell(self):
        if not self._lhm_process_running():
            raise RuntimeError("a Libre Hardware Monitor folyamata nem fut")

        script = rf"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$hardware = @(Get-CimInstance -Namespace '{LHM_WMI_NAMESPACE}' -ClassName Hardware | Select-Object Identifier,Name,HardwareType,Parent)
$sensors = @(Get-CimInstance -Namespace '{LHM_WMI_NAMESPACE}' -ClassName Sensor | Where-Object {{ $null -ne $_.Value }} | Select-Object Identifier,Name,SensorType,Parent,Value,Min,Max)
[pscustomobject]@{{ Hardware = $hardware; Sensors = $sensors }} | ConvertTo-Json -Depth 6 -Compress
"""
        data = _run_powershell_json(script, timeout=6)
        if not isinstance(data, dict):
            raise RuntimeError("érvénytelen WMI-válasz")
        readings = self._flatten_wmi_objects(data.get("Hardware") or [], data.get("Sensors") or [])
        if not readings:
            raise RuntimeError("a WMI névtér 0 szenzort adott vissza")
        return readings

    @staticmethod
    def _normalise_unit(unit):
        return (
            str(unit or "")
            .strip()
            .replace("/sec", "/s")
            .replace("/Sec", "/s")
            .replace("KiB", "KB")
            .replace("MiB", "MB")
            .replace("GiB", "GB")
        )

    @classmethod
    def value_in(cls, reading, target_unit=None):
        if reading is None:
            return None
        value = reading.get("value")
        if value is None or target_unit is None:
            return value

        unit = cls._normalise_unit(reading.get("unit", ""))
        source = unit.upper().replace(" ", "")
        target = cls._normalise_unit(target_unit).upper().replace(" ", "")

        if source == target or not source:
            return float(value)

        if target == "MHZ":
            factors = {"HZ": 1 / 1_000_000, "KHZ": 1 / 1000, "MHZ": 1, "GHZ": 1000}
            if source in factors:
                return float(value) * factors[source]

        if target == "MB":
            factors = {"B": 1 / (1024 ** 2), "KB": 1 / 1024, "MB": 1, "GB": 1024, "TB": 1024 ** 2}
            if source in factors:
                return float(value) * factors[source]

        if target == "GB":
            factors = {"B": 1 / (1024 ** 3), "KB": 1 / (1024 ** 2), "MB": 1 / 1024, "GB": 1, "TB": 1024}
            if source in factors:
                return float(value) * factors[source]

        if target in ("KB/S", "KBYTE/S"):
            factors = {
                "B/S": 1 / 1000,
                "KB/S": 1,
                "MB/S": 1000,
                "GB/S": 1_000_000,
            }
            if source in factors:
                return float(value) * factors[source]

        return float(value)

    @staticmethod
    def _text(reading):
        return " ".join(
            [
                str(reading.get("sensor", "")),
                str(reading.get("label", "")),
                str(reading.get("sensor_id", "")),
                str(reading.get("hardware_id", "")),
                " ".join(str(x) for x in reading.get("path", [])),
            ]
        ).lower()

    @classmethod
    def _is_kind(cls, reading, kind):
        if str(reading.get("hardware_type", "")).lower() == kind:
            return True
        hay = cls._text(reading)
        if kind == "cpu":
            return any(token in hay for token in ("intelcpu", "amdcpu", "intel core", "amd ryzen", "/cpu/"))
        if kind == "memory":
            return any(token in hay for token in ("/ram", "memory", "physical memory"))
        if kind == "motherboard":
            return any(token in hay for token in ("mainboard", "motherboard", "superio", "/lpc", "nuvoton", "ite ", "fintek"))
        if kind == "storage":
            return any(token in hay for token in ("/hdd", "/nvme", "storage", "hard disk", "ssd", "nvme"))
        if kind == "network":
            return any(token in hay for token in ("/nic", "network", "ethernet", "wireless", "wi-fi", "wifi"))
        return False

    @classmethod
    def _candidates(cls, readings, type_names=None, kind=None):
        type_names = {str(x).upper() for x in (type_names or [])}
        result = []
        for reading in readings:
            if type_names and str(reading.get("type", "")).upper() not in type_names:
                continue
            if kind and not cls._is_kind(reading, kind):
                continue
            result.append(reading)
        return result

    @staticmethod
    def _preferred_reading(candidates, exact=(), contains=(), fallback=True):
        for wanted in exact:
            wanted_lower = wanted.lower()
            for reading in candidates:
                if str(reading.get("label", "")).lower() == wanted_lower:
                    return reading
        for wanted in contains:
            wanted_lower = wanted.lower()
            for reading in candidates:
                if wanted_lower in str(reading.get("label", "")).lower():
                    return reading
        return candidates[0] if fallback and candidates else None

    def cpu_temperature(self, readings):
        candidates = self._candidates(readings, ["TEMP"], "cpu")
        reading = self._preferred_reading(
            candidates,
            exact=("CPU Package", "Package", "Core Max", "CPU Core Max", "Core Average", "CPU Core Average"),
            contains=("package", "core max", "tctl", "tdie"),
            fallback=False,
        )
        if reading:
            return self.value_in(reading, "°C")
        values = [self.value_in(r, "°C") for r in candidates]
        values = [v for v in values if v is not None]
        return max(values) if values else None

    def cpu_usage(self, readings):
        candidates = self._candidates(readings, ["USAGE"], "cpu")
        reading = self._preferred_reading(
            candidates,
            exact=("CPU Total", "Total CPU", "CPU Usage", "Total CPU Usage"),
            contains=("total", "cpu total"),
            fallback=False,
        )
        if reading:
            return self.value_in(reading, "%")
        values = [self.value_in(r, "%") for r in candidates if "core" in str(r.get("label", "")).lower()]
        values = [v for v in values if v is not None]
        return sum(values) / len(values) if values else None

    def cpu_clock(self, readings):
        candidates = self._candidates(readings, ["CLOCK"], "cpu")
        reading = self._preferred_reading(
            candidates,
            exact=("CPU Core Average", "Core Average", "Average Effective Clock", "CPU Package"),
            contains=("average", "effective clock"),
            fallback=False,
        )
        if reading:
            return self.value_in(reading, "MHz")

        core_readings = [
            r for r in candidates
            if "core" in str(r.get("label", "")).lower()
            and "bus" not in str(r.get("label", "")).lower()
        ]
        values = [self.value_in(r, "MHz") for r in core_readings]
        values = [v for v in values if v is not None and v > 0]
        return sum(values) / len(values) if values else None

    def fan_values(self, readings):
        fans = self._candidates(readings, ["FAN"], "motherboard")
        if not fans:
            fans = self._candidates(readings, ["FAN"])

        fans = sorted(fans, key=lambda r: (str(r.get("hardware_id", "")), str(r.get("sensor_id", "")), str(r.get("label", ""))))
        cpu = self._preferred_reading(
            fans,
            exact=("CPU Fan", "CPU", "CPU FAN"),
            contains=("cpu",),
            fallback=False,
        )

        mb = None
        for token in ("chassis", "system", "sys fan", "cha_fan", "case", "fan #2"):
            for reading in fans:
                if reading is cpu:
                    continue
                if token in str(reading.get("label", "")).lower():
                    mb = reading
                    break
            if mb:
                break

        if cpu is None and fans:
            cpu = fans[0]
        if mb is None:
            mb = next((r for r in fans if r is not cpu), None)

        return self.value_in(cpu, "RPM"), self.value_in(mb, "RPM")

    def cmos_battery_reading(self, readings):
        """
        A CMOS/RTC elem feszültségszenzorának felismerése.

        Elsőként a név szerint jelölt VBAT/CMOS/RTC Battery szenzorokat
        választja. Tartalékként a korábbi Nuvoton gépen bevált nyers
        in8 / Voltage #8 csatornát fogadja el. Más, pusztán 3 V körüli
        feszültséget szándékosan nem találgat CMOS-értéknek.
        """
        candidates = self._candidates(readings, ["VOLT"], "motherboard")
        if not candidates:
            candidates = self._candidates(readings, ["VOLT"])

        if not candidates:
            return None

        exact_names = {
            "vbat",
            "vbat voltage",
            "cmos",
            "cmos battery",
            "cmos battery voltage",
            "rtc battery",
            "rtc battery voltage",
            "bios battery",
            "bios battery voltage",
            "3v battery",
            "battery voltage",
        }
        strong_tokens = (
            "vbat",
            "cmos battery",
            "rtc battery",
            "bios battery",
        )
        raw_in8_patterns = (
            r"(?:^|[^a-z0-9])in[\s_#-]*8(?:$|[^0-9])",
            r"(?:^|[^a-z0-9])vin[\s_#-]*8(?:$|[^0-9])",
            r"(?:^|[^a-z0-9])voltage[\s_#-]*8(?:$|[^0-9])",
            r"/voltage/8(?:$|/)",
        )

        ranked = []
        for reading in candidates:
            label = str(reading.get("label", "")).strip().lower()
            hay = self._text(reading)
            score = 0

            if label in exact_names:
                score = 120
            elif any(token in hay for token in strong_tokens):
                score = 100
            elif "battery voltage" in hay and not any(token in hay for token in ("gpu", "laptop", "ups")):
                score = 90
            elif any(re.search(pattern, hay, flags=re.IGNORECASE) for pattern in raw_in8_patterns):
                score = 70

            # A 3.3 V-os tápág, AVCC és 3VSB nem a CMOS elem.
            if any(token in hay for token in ("+3.3v", "3.3v", "3vsb", "avcc")) and "vbat" not in hay:
                score -= 80

            if self._is_kind(reading, "motherboard"):
                score += 10

            value = self.value_in(reading, "V")
            if value is not None and 2.4 <= value <= 3.6:
                score += 5
            elif value is not None:
                score -= 20

            if score > 0:
                ranked.append((score, reading))

        if not ranked:
            return None

        ranked.sort(
            key=lambda item: (
                item[0],
                str(item[1].get("hardware_id", "")),
                str(item[1].get("sensor_id", "")),
            ),
            reverse=True,
        )
        return ranked[0][1]

    def cmos_voltage(self, readings):
        return self.value_in(self.cmos_battery_reading(readings), "V")

    def cpu_power(self, readings):
        candidates = self._candidates(readings, ["POWER"], "cpu")
        reading = self._preferred_reading(
            candidates,
            exact=("CPU Package", "CPU Package Power", "Package"),
            contains=("package",),
            fallback=False,
        )
        if reading is None and candidates:
            reading = candidates[0]
        return self.value_in(reading, "W")

    def memory_values(self, readings):
        candidates = self._candidates(readings, ["USAGE", "DATA", "SMALLDATA"], "memory")
        if not candidates:
            candidates = [r for r in readings if "memory" in self._text(r)]

        used = self._preferred_reading(
            [r for r in candidates if r.get("type") in ("DATA", "SMALLDATA")],
            exact=("Memory Used", "Used Memory", "Physical Memory Used"),
            contains=("memory used", "used memory"),
            fallback=False,
        )
        available = self._preferred_reading(
            [r for r in candidates if r.get("type") in ("DATA", "SMALLDATA")],
            exact=("Memory Available", "Available Memory", "Physical Memory Available"),
            contains=("memory available", "available memory"),
            fallback=False,
        )
        load = self._preferred_reading(
            [r for r in candidates if r.get("type") == "USAGE"],
            exact=("Memory", "Memory Load", "Physical Memory Load"),
            contains=("memory",),
            fallback=False,
        )
        return self.value_in(used, "MB"), self.value_in(available, "MB"), self.value_in(load, "%")

    def network_rates(self, readings):
        network = self._candidates(readings, ["THROUGHPUT"], "network")
        network += [
            r for r in self._candidates(readings, ["OTHER"], "network")
            if any(token in str(r.get("label", "")).lower() for token in ("speed", "rate", "throughput"))
        ]

        groups = {}
        for reading in network:
            key = reading.get("hardware_id") or reading.get("sensor") or "network"
            groups.setdefault(key, []).append(reading)

        best = (None, None, -1.0)
        for group in groups.values():
            down = self._preferred_reading(
                group,
                exact=("Download Speed", "Current DL rate"),
                contains=("download speed", "receive speed", "download rate", "dl rate", "rx rate"),
                fallback=False,
            )
            up = self._preferred_reading(
                group,
                exact=("Upload Speed", "Current UP rate"),
                contains=("upload speed", "transmit speed", "upload rate", "up rate", "tx rate"),
                fallback=False,
            )
            down_value = self.value_in(down, "KB/s")
            up_value = self.value_in(up, "KB/s")
            score = abs(down_value or 0) + abs(up_value or 0)
            if score > best[2]:
                best = (down_value, up_value, score)

        return best[0], best[1]

    @staticmethod
    def _normalise_model(value):
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    def _drive_readings(self, readings, drive):
        storage = self._candidates(readings, kind="storage")
        if not storage:
            return []

        letter = str(drive.get("letter", "")).upper()
        model = self._normalise_model(drive.get("physical_model"))
        serial = self._normalise_model(drive.get("physical_serial"))
        disk_index = drive.get("disk_index")

        matched = []
        for reading in storage:
            hay = self._text(reading)
            norm_hay = self._normalise_model(hay)
            if model and (model in norm_hay or norm_hay in model):
                matched.append(reading)
                continue
            if serial and serial in norm_hay:
                matched.append(reading)
                continue
            if letter and any(token in hay for token in (f"[{letter}:]".lower(), f"{letter}:\\".lower(), f" {letter}:".lower())):
                matched.append(reading)
                continue
            if disk_index is not None:
                hid = str(reading.get("hardware_id", "")).lower()
                if re.search(rf"/(?:hdd|storage|nvme)/{int(disk_index)}(?:/|$)", hid):
                    matched.append(reading)

        if matched:
            return matched

        hardware_keys = {
            (r.get("hardware_id") or r.get("sensor")) for r in storage
        }
        if len(hardware_keys) == 1:
            return storage
        return []

    def drive_metric(self, readings, drive, labels, type_names=None, target_unit=None):
        candidates = self._drive_readings(readings, drive)
        if type_names:
            allowed = {str(x).upper() for x in type_names}
            candidates = [r for r in candidates if str(r.get("type", "")).upper() in allowed]
        reading = self._preferred_reading(candidates, exact=labels, contains=labels, fallback=False)
        return self.value_in(reading, target_unit)

    def drive_total_io(self, readings, drive, direction):
        """Élettartam alatti host read/write érték többféle Libre/SMART névvel."""
        direction = str(direction or "").lower()
        is_read = direction.startswith("r")
        labels = (
            (
                "Total Host Reads", "Host Reads", "Lifetime Host Reads",
                "Data Read", "Total Data Read", "Data Units Read",
                "Total Reads", "Lifetime Reads", "Total LBAs Read",
                "Total LBA Read", "Read Data", "Bytes Read",
            )
            if is_read
            else (
                "Total Host Writes", "Host Writes", "Lifetime Host Writes",
                "Data Written", "Total Data Written", "Data Units Written",
                "Total Writes", "Lifetime Writes", "Total LBAs Written",
                "Total LBA Written", "Written Data", "Bytes Written",
            )
        )

        value = self.drive_metric(
            readings,
            drive,
            labels=labels,
            type_names=("DATA", "SMALLDATA", "OTHER"),
            target_unit="GB",
        )
        if value is not None:
            return value

        # Gyártónként eltérhet a SMART-szenzor neve. Csak összesített
        # adatmennyiséget fogadunk el; pillanatnyi sebességet/aktivitást és
        # parancsszámlálót nem, mert azok nem összevethetők a Host Reads-szel.
        candidates = self._drive_readings(readings, drive)
        allowed_types = {"DATA", "SMALLDATA", "OTHER"}
        scored = []
        wanted = "read" if is_read else "writ"
        opposite = "writ" if is_read else "read"
        excluded = (
            "activity", "rate", "speed", "throughput", "command", "error",
            "latency", "time", "pending", "cache", "operation", "iops",
        )
        for reading in candidates:
            if str(reading.get("type", "")).upper() not in allowed_types:
                continue
            label = str(reading.get("label", "")).strip().lower()
            if wanted not in label or opposite in label:
                continue
            if any(token in label for token in excluded):
                continue

            score = 0
            for token, points in (
                ("host", 8), ("total", 7), ("lifetime", 7),
                ("data unit", 6), ("lba", 6), ("data", 4), ("byte", 3),
            ):
                if token in label:
                    score += points
            if score:
                scored.append((score, reading))

        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        return self.value_in(scored[0][1], "GB")

    def drive_temp(self, readings, drive):
        return self.drive_metric(
            readings,
            drive,
            labels=("Drive Temperature", "Temperature", "Composite Temperature", "Temperature 1"),
            type_names=("TEMP",),
            target_unit="°C",
        )



class DriveHoverMixin:
    """Azonnal megjelenő, stabil információs buborék a meghajtósor elemein."""

    def set_drive_tooltip(self, text):
        self._drive_tooltip = text or ""
        self.setToolTip(self._drive_tooltip)
        self.setToolTipDuration(15000)

    def enterEvent(self, event):
        tip = getattr(self, "_drive_tooltip", "") or self.toolTip()
        if tip:
            QToolTip.showText(QCursor.pos() + QPoint(12, 12), tip, self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)


class ClickableDriveLabel(DriveHoverMixin, QLabel):
    def __init__(self, text, root, tooltip=""):
        super().__init__(text)
        self.root = root
        self.setObjectName("keyLabel")
        self.setMinimumWidth(92)
        self.setFixedHeight(18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_drive_tooltip(tooltip)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            try:
                os.startfile(self.root)
            except Exception:
                subprocess.Popen(
                    ["explorer", self.root],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            event.accept()
            return

        super().mousePressEvent(event)


class DriveValueLabel(DriveHoverMixin, QLabel):
    def __init__(self, text="N/A", tooltip=""):
        super().__init__(text)
        self.set_drive_tooltip(tooltip)


class DriveProgressBar(DriveHoverMixin, QProgressBar):
    def __init__(self, tooltip=""):
        super().__init__()
        self.set_drive_tooltip(tooltip)


class Section(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("section")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("sectionTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setFixedHeight(19)
        layout.addWidget(self.title_label)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(2)
        layout.addLayout(self.grid)

        self.row = 0
        self.key_labels = []

    def set_title(self, title):
        self.title_label.setText(title)

    def add_row(self, key_text, value_label):
        k = QLabel(key_text)
        k.setObjectName("keyLabel")
        k.setMinimumWidth(92)
        k.setFixedHeight(18)
        self.key_labels.append(k)

        v = value_label
        v.setObjectName("valueLabel")
        v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        v.setFixedHeight(18)

        self.grid.addWidget(k, self.row, 0)
        self.grid.addWidget(v, self.row, 1)
        self.row += 1
        return k


class WidgetWindow(QWidget):
    DEFAULT_WIDTH = 340

    def __init__(self, reader):
        super().__init__()

        self.reader = reader
        self.external_ip = get_external_ip()
        self.wifi_ssid = "N/A"
        self.wifi_signal = 0
        self.tick = 0
        self._snap_active = False
        self._restoring_geometry = False

        self.settings = QSettings("gidano", "HWiNFOPythonWidgetV27")  # régi elrendezés/beállítások megtartása
        self.language = self.settings.value("language", "hu", type=str)
        if self.language not in ("hu", "en"):
            self.language = "hu"

        self.show_network = self.settings.value("show_network", True, type=bool)
        self.show_drives = self.settings.value("show_drives", True, type=bool)
        self.usb_only = self.settings.value("usb_only", False, type=bool)
        self.compact_mode = self.settings.value("compact_mode", False, type=bool)
        self.always_on_top = self.settings.value("always_on_top", True, type=bool)
        self.frameless_mode = self.settings.value("frameless_mode", False, type=bool)
        self._drag_pos = None
        self.alerts_enabled = self.settings.value("alerts_enabled", True, type=bool)
        self.tray_enabled = self.settings.value("tray_enabled", True, type=bool)
        self.startup_enabled = self.is_startup_enabled()
        self.udp_enabled = self.settings.value("udp_enabled", False, type=bool)
        self.opacity_value = float(self.settings.value("opacity", 1.0))
        self.last_payload = ""
        self.last_alerts = []

        self.tray = None
        self.labels = {}
        self.key_widgets = {}
        self.bars = {}
        self.drive_widgets = {}
        self.drive_signature = None

        self.setWindowTitle(self.t("app_title"))
        self.app_icon = load_app_icon()
        if not self.app_icon.isNull():
            self.setWindowIcon(self.app_icon)
        self.setMinimumSize(230, 280)

        saved_size = self.settings.value("size")
        self._restoring_geometry = True
        if isinstance(saved_size, QSize):
            self.resize(saved_size)
        else:
            self.resize(self.DEFAULT_WIDTH, 410)

        # Natív Windows keret marad, hogy az egérrel méretezés stabil legyen.
        self.apply_window_flags()

        pos = self.settings.value("pos")
        if isinstance(pos, QPoint):
            self.move(pos)
        self._restoring_geometry = False

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(5)

        # Saját méretezőfogantyú, mert fejléc nélküli módban a natív
        # átméretezés megszűnik.
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(16, 16)
        self.size_grip.setVisible(self.frameless_mode)
        self.size_grip.move(self.width() - 16, self.height() - 16)
        self.size_grip.raise_()

        self.cpu_section = Section(self.t("section_cpu"))
        self.add_value(self.cpu_section, "cpu_temp", self.t("label_cpu_temp"))
        self.add_value(self.cpu_section, "cpu_usage", self.t("label_cpu_usage"))
        self.add_value(self.cpu_section, "cpu_clock", self.t("label_cpu_clock"))
        self.add_value(self.cpu_section, "cpu_fan", self.t("label_cpu_fan"))
        self.add_value(self.cpu_section, "mb_fan", self.t("label_mb_fan"))
        self.add_value(self.cpu_section, "ram", self.t("label_ram"))
        self.add_bar(self.cpu_section, "ram_bar")
        self.add_value(self.cpu_section, "cmos", self.t("label_cmos"))
        self.main_layout.addWidget(self.cpu_section)

        self.drives_section = Section(self.t("section_drives"))
        self.main_layout.addWidget(self.drives_section)

        self.net_section = Section(self.t("section_network"))
        self.add_value(self.net_section, "external_ip", self.t("label_external_ip"))
        self.add_value(self.net_section, "internal_ip", self.t("label_internal_ip"))
        self.add_value(self.net_section, "ssid", self.t("label_ssid"))
        self.add_value(self.net_section, "signal", self.t("label_signal"))
        self.add_value(self.net_section, "down", self.t("label_down"))
        self.add_value(self.net_section, "up", self.t("label_up"))
        self.main_layout.addWidget(self.net_section)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        self.status_label.setToolTip(self.t("status_tooltip"))
        self.status_label.setVisible(False)
        self.main_layout.addWidget(self.status_label)

        self.main_layout.addStretch(1)

        self.setStyleSheet("""
            QWidget {
                background: #080808;
                color: #d8d8d8;
                font-family: Segoe UI;
                font-size: 10px;
            }

            QFrame#section {
                background: #101010;
                border: 1px solid #555555;
                border-radius: 5px;
            }

            QLabel#sectionTitle {
                background: #050505;
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
            }

            QLabel#keyLabel {
                background: #050505;
                color: #eeeeee;
                font-weight: bold;
            }

            QLabel#valueLabel {
                background: #050505;
                color: #eeeeee;
                font-weight: bold;
            }

            QProgressBar {
                background: #202020;
                border: 1px solid #444444;
                min-height: 5px;
                max-height: 5px;
                text-align: center;
            }

            QProgressBar::chunk {
                background: #50d050;
            }

            QToolTip {
                background: #202020;
                color: #ffffff;
                border: 1px solid #777777;
                padding: 5px;
            }
        """)

        self.apply_visibility()
        self.apply_compact_mode()
        self.setWindowOpacity(self.opacity_value)
        self.setup_tray()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_values)
        self.timer.start(2000)

        self.snap_timer = QTimer(self)
        self.snap_timer.setSingleShot(True)
        self.snap_timer.timeout.connect(self.snap_to_screen_edges)

        self.update_values()
        self.apply_language()
        QTimer.singleShot(150, self.fit_height_to_content)

    def t(self, key, **kwargs):
        return tr_text(self.language, key, **kwargs)

    def apply_language(self):
        self.setWindowTitle(self.t("app_title"))
        self.cpu_section.set_title(self.t("section_cpu"))
        self.drives_section.set_title(self.t("section_drives"))
        self.net_section.set_title(self.t("section_network"))
        mapping = {
            "cpu_temp": "label_cpu_temp",
            "cpu_usage": "label_cpu_usage",
            "cpu_clock": "label_cpu_clock",
            "cpu_fan": "label_cpu_fan",
            "mb_fan": "label_mb_fan",
            "ram": "label_ram",
            "cmos": "label_cmos",
            "external_ip": "label_external_ip",
            "internal_ip": "label_internal_ip",
            "ssid": "label_ssid",
            "signal": "label_signal",
            "down": "label_down",
            "up": "label_up",
        }
        for key, tr_key in mapping.items():
            if key in self.key_widgets:
                self.key_widgets[key].setText(self.t(tr_key))
        self.status_label.setToolTip(self.t("status_tooltip"))
        if self.tray is not None:
            self.setup_tray()

    def set_language(self, lang):
        if lang not in ("hu", "en") or self.language == lang:
            return
        self.language = lang
        self.settings.setValue("language", self.language)
        self.drive_signature = None
        self.apply_language()
        self.update_values()
        self.fit_height_to_content()

    def add_value(self, section, key, caption):
        label = QLabel("N/A")
        label.setTextFormat(Qt.TextFormat.RichText)
        self.labels[key] = label
        key_label = section.add_row(caption, label)
        self.key_widgets[key] = key_label

    def add_bar(self, section, key):
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        self.bars[key] = bar

        section.grid.addWidget(bar, section.row, 0, 1, 2)
        section.row += 1

    def rebuild_drives_if_needed(self, drives):
        signature = tuple((d["letter"], d["kind"], d["label"]) for d in drives)
        if signature == self.drive_signature:
            return

        self.drive_signature = signature

        idx = self.main_layout.indexOf(self.drives_section)
        self.main_layout.removeWidget(self.drives_section)
        self.drives_section.setParent(None)
        self.drives_section.deleteLater()

        self.drives_section = Section(self.t("section_drives"))
        self.drive_widgets.clear()

        for d in drives:
            letter = d["letter"]
            label = d["label"]
            kind = d["kind"]

            # A meghajtónevek visszakapcsolva.
            caption = f"({letter}:)"
            if label:
                caption += f" {label}"
            if kind == "USB":
                caption += f" {self.t('drive_type_usb')}"

            tooltip = f"Megnyitás fájlkezelőben: {letter}:\\"
            if label:
                tooltip += f"  ({label})"

            key_label = ClickableDriveLabel(caption, d["root"], tooltip)

            value_label = DriveValueLabel("N/A", tooltip)
            value_label.setTextFormat(Qt.TextFormat.RichText)
            value_label.setObjectName("valueLabel")
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value_label.setFixedHeight(18)
            value_label.setToolTip(tooltip)

            self.drive_widgets[letter] = {"label": value_label, "key": key_label}

            self.drives_section.grid.addWidget(key_label, self.drives_section.row, 0)
            self.drives_section.grid.addWidget(value_label, self.drives_section.row, 1)
            self.drives_section.row += 1

            bar = DriveProgressBar(tooltip)
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(False)
            self.drive_widgets[letter]["bar"] = bar

            self.drives_section.grid.addWidget(bar, self.drives_section.row, 0, 1, 2)
            self.drives_section.row += 1

        self.main_layout.insertWidget(idx, self.drives_section)
        self.apply_visibility()
        self.apply_compact_mode()
        QTimer.singleShot(80, self.fit_height_to_content)

    def fit_height_to_content(self):
        self.main_layout.activate()
        QApplication.processEvents()

        wanted = self.sizeHint().height()
        wanted = max(self.minimumHeight(), wanted)
        self.resize(self.width(), wanted)

    def set_label(self, key, text):
        self.labels[key].setText(text)

    def set_label_color(self, key, color):
        if key in self.labels:
            self.labels[key].setStyleSheet(label_style(color))

    def set_drive_label_color(self, letter, color):
        if letter in self.drive_widgets:
            self.drive_widgets[letter]["label"].setStyleSheet(label_style(color))

    def set_bar_color(self, key, color):
        if key in self.bars:
            self.bars[key].setStyleSheet(bar_style(color))

    def set_drive_bar_color(self, letter, color):
        if letter in self.drive_widgets:
            self.drive_widgets[letter]["bar"].setStyleSheet(bar_style(color))

    def set_drive_tooltip(self, letter, text):
        widgets = self.drive_widgets.get(letter)
        if not widgets:
            return
        for name in ("key", "label", "bar"):
            widget = widgets.get(name)
            if widget is None:
                continue
            if hasattr(widget, "set_drive_tooltip"):
                widget.set_drive_tooltip(text)
            else:
                widget.setToolTip(text)
                widget.setToolTipDuration(15000)

    def set_bar(self, key, percent):
        try:
            value = max(0, min(100, int(round(percent))))
        except Exception:
            value = 0
        self.bars[key].setValue(value)

    def startup_cmd_path(self):
        startup_dir = os.path.join(
            os.environ.get("APPDATA", ""),
            r"Microsoft\Windows\Start Menu\Programs\Startup",
        )
        return os.path.join(startup_dir, "Libre_Hardware_Widget.cmd")

    def legacy_startup_cmd_path(self):
        startup_dir = os.path.join(
            os.environ.get("APPDATA", ""),
            r"Microsoft\Windows\Start Menu\Programs\Startup",
        )
        return os.path.join(startup_dir, "HWiNFO_Python_Widget.cmd")

    def launch_command(self):
        if getattr(sys, "frozen", False):
            return f'start "" "{sys.executable}"'

        script_path = os.path.abspath(sys.argv[0])
        exe = sys.executable

        if exe.lower().endswith("python.exe"):
            pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if os.path.exists(pyw):
                exe = pyw

        return f'start "" "{exe}" "{script_path}"'

    def is_startup_enabled(self):
        return os.path.exists(self.startup_cmd_path()) or os.path.exists(self.legacy_startup_cmd_path())

    def set_startup_enabled(self, enabled):
        path = self.startup_cmd_path()

        legacy_path = self.legacy_startup_cmd_path()

        try:
            if enabled:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write("@echo off\n")
                    f.write(self.launch_command() + "\n")
                if os.path.exists(legacy_path):
                    os.remove(legacy_path)
            else:
                for candidate in (path, legacy_path):
                    if os.path.exists(candidate):
                        os.remove(candidate)
        except Exception as e:
            QMessageBox.warning(self, "Startup hiba", f"Nem sikerült módosítani az automatikus indítást:\n{e}")

        self.startup_enabled = self.is_startup_enabled()
        self.settings.setValue("startup_enabled", self.startup_enabled)

    def set_alerts_enabled(self, enabled):
        self.alerts_enabled = bool(enabled)
        self.settings.setValue("alerts_enabled", self.alerts_enabled)
        self.update_status_line(self.last_alerts)

    def set_udp_enabled(self, enabled):
        self.udp_enabled = bool(enabled)
        self.settings.setValue("udp_enabled", self.udp_enabled)
        self.update_status_line(self.last_alerts)

    def send_udp_payload(self, payload):
        if not self.udp_enabled:
            return

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(0.05)
            sock.sendto(payload.encode("utf-8", errors="ignore"), ("255.255.255.255", 4210))
            sock.close()
        except Exception:
            pass

    def set_opacity_value(self, value):
        self.opacity_value = float(value)
        self.settings.setValue("opacity", self.opacity_value)
        self.setWindowOpacity(self.opacity_value)

    def toggle_visible_from_tray(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def build_language_menu(self, parent=None):
        menu = QMenu(self.t("menu_language"), parent or self)
        hu_action = QAction(self.t("lang_hu"), self)
        hu_action.setCheckable(True)
        hu_action.setChecked(self.language == "hu")
        hu_action.triggered.connect(lambda checked=False: self.set_language("hu"))
        en_action = QAction(self.t("lang_en"), self)
        en_action.setCheckable(True)
        en_action.setChecked(self.language == "en")
        en_action.triggered.connect(lambda checked=False: self.set_language("en"))
        menu.addAction(hu_action)
        menu.addAction(en_action)
        return menu

    def setup_tray(self):
        if self.tray is not None:
            try:
                self.tray.hide()
                self.tray.deleteLater()
            except Exception:
                pass
            self.tray = None
        if not self.tray_enabled or not QSystemTrayIcon.isSystemTrayAvailable():
            return

        icon = self.app_icon
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip(self.t("tray_tooltip"))

        menu = QMenu()
        show_action = QAction(self.t("menu_show_hide"), self)
        show_action.triggered.connect(self.toggle_visible_from_tray)
        always_action = QAction(self.t("menu_always_on_top"), self)
        always_action.setCheckable(True)
        always_action.setChecked(self.always_on_top)
        always_action.toggled.connect(self.set_always_on_top)
        pos_menu = QMenu(self.t("menu_position"), self)
        for title, key in (
            (self.t("menu_top_left"), "top_left"),
            (self.t("menu_top_right"), "top_right"),
            (self.t("menu_bottom_left"), "bottom_left"),
            (self.t("menu_bottom_right"), "bottom_right"),
            (self.t("menu_left_center"), "left_center"),
            (self.t("menu_right_center"), "right_center"),
            (self.t("menu_center"), "center"),
        ):
            act = QAction(title, self)
            act.triggered.connect(lambda checked=False, k=key: self.move_to_position(k))
            pos_menu.addAction(act)
        exit_action = QAction(self.t("menu_exit"), self)
        exit_action.triggered.connect(QApplication.quit)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(always_action)
        menu.addMenu(pos_menu)
        menu.addMenu(self.build_language_menu(menu))
        menu.addSeparator()
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

    def on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.toggle_visible_from_tray()

    def update_status_line(self, alerts=None, libre_ok=True):
        alerts = alerts or []
        self.last_alerts = alerts

        extras = []
        if self.udp_enabled:
            extras.append(self.t("status_udp"))
        if not self.always_on_top:
            extras.append(self.t("status_always_on_top_inactive"))

        if not libre_ok:
            text = self.t("status_libre_off")
            color = "#ffb000"
        elif self.alerts_enabled and alerts:
            text = " | ".join(alerts[:4])
            color = "#ff5050"
        elif extras:
            text = " | ".join(extras)
            color = "#50d050"
        else:
            # Normál állapotban nincs külön OK sáv az ablak alján.
            self.status_label.setVisible(False)
            if self.tray:
                self.tray.setToolTip(self.t("tray_tooltip") + "\n" + self.t("tray_ok"))
            return

        self.status_label.setVisible(True)
        self.status_label.setText(colored_span(text, color))
        if self.tray:
            self.tray.setToolTip(self.t("tray_tooltip") + "\n" + text)

    def build_cpu_tooltip(self, cpu_temp, cpu_usage, cpu_clock, cpu_fan, mb_fan, cpu_power):
        power = f"{cpu_power:.1f} W" if cpu_power is not None else self.t("not_available")
        return (
            self.t("cpu_tip_temp", value=f"{fmt(cpu_temp, 0)} °C") + "\n"
            + self.t("cpu_tip_usage", value=f"{fmt(cpu_usage, 1)} %") + "\n"
            + self.t("cpu_tip_clock", value=f"{fmt(cpu_clock, 0)} MHz") + "\n"
            + self.t("cpu_tip_cpu_fan", value=f"{fmt(cpu_fan, 0)} rpm") + "\n"
            + self.t("cpu_tip_mb_fan", value=f"{fmt(mb_fan, 0)} rpm") + "\n"
            + self.t("cpu_tip_power", value=power)
        )

    def drive_extra_tooltip(self, readings, drive, used_gb, total_gb, pct, temp):
        letter = drive["letter"]

        life = self.reader.drive_metric(
            readings,
            drive,
            labels=("Drive Remaining Life", "Remaining Life", "Life"),
            type_names=("USAGE", "LEVEL", "OTHER"),
            target_unit="%",
        )
        warning = self.reader.drive_metric(
            readings,
            drive,
            labels=("Drive Warning", "Warning"),
        )
        failure = self.reader.drive_metric(
            readings,
            drive,
            labels=("Drive Failure", "Failure"),
        )
        writes = self.reader.drive_total_io(readings, drive, "write")
        reads = self.reader.drive_total_io(readings, drive, "read")
        boot_reads, boot_writes = physical_disk_io_since_boot_gb(drive)

        label = drive.get("label") or ""
        model = drive.get("physical_model") or ""
        lines = [
            f"Meghajtó: {letter}:\\ {label}",
            f"{self.t('drive_type')}: {self.t('drive_type_usb') if drive.get('kind') == 'USB' else self.t('drive_type_fixed')}",
        ]
        if model:
            lines.append(f"{self.t('drive_physical')}: {model}")
        lines.extend(
            [
                f"{self.t('drive_used')}: {used_gb:.1f} GB",
                f"{self.t('drive_total')}: {total_gb:.1f} GB",
                f"{self.t('drive_usage')}: {pct:.1f} %",
                f"{self.t('drive_temp')}: {fmt(temp, 0)} °C" if temp is not None else f"{self.t('drive_temp')}: {self.t('not_available')}",
            ]
        )

        if life is not None:
            lines.append(f"{self.t('drive_life')}: {life:.0f} %")
        if writes is not None:
            lines.append(f"{self.t('host_writes')}: {writes:.0f} GB")
        elif boot_writes is not None:
            lines.append(f"{self.t('host_writes_boot')}: {boot_writes:.2f} GB")
        else:
            lines.append(f"{self.t('host_writes')}: {self.t('not_available')}")

        if reads is not None:
            lines.append(f"{self.t('host_reads')}: {reads:.0f} GB")
        elif boot_reads is not None:
            lines.append(f"{self.t('host_reads_boot')}: {boot_reads:.2f} GB")
        else:
            lines.append(f"{self.t('host_reads')}: {self.t('not_available')}")
        if warning is not None:
            lines.append(f"{self.t('drive_warning')}: {self.t('yes') if warning else self.t('no')}")
        if failure is not None:
            lines.append(f"{self.t('drive_failure')}: {self.t('yes') if failure else self.t('no')}")

        lines.append(self.t("drive_open_hint"))
        return "\n".join(lines)

    def disk_text_and_percent(self, drive, temp=None):
        root = drive["root"]
        try:
            du = psutil.disk_usage(root)
            used_gb = du.used / (1024 ** 3)
            total_gb = du.total / (1024 ** 3)
            temp_text = f"{temp:.0f}°C" if temp is not None else "N/A"
            text = f"{used_gb:.1f}/{total_gb:.1f} GB   {du.percent:.0f}%   {temp_text}"
            return text, du.percent
        except Exception:
            return "nincs meghajtó", 0

    def show_libre_offline(self, reason=""):
        """
        Libre Hardware Monitor leállásakor ne maradjanak kint az utolsó
        szenzorértékek. A Windowsból olvasható adatok továbbra is frissülnek.
        """
        self.set_label("cpu_temp", colored_span("LIBRE OFF", "#ffb000"))
        self.set_label("cpu_usage", colored_span("N/A", "#ffb000"))
        self.set_label("cpu_clock", "N/A")
        self.set_label("cpu_fan", "N/A")
        self.set_label("mb_fan", "N/A")
        self.set_label("cmos", colored_span("N/A", "#b0b0b0"))

        libre_tip = (
            self.t("libre_off_tip1") + "\n"
            + self.t("libre_off_tip2") + "\n"
            + self.t("libre_off_tip3")
        )
        if reason:
            libre_tip += f"\n\nHiba: {reason}"

        for key in ("cpu_temp", "cpu_usage", "cpu_clock", "cpu_fan", "mb_fan", "cmos"):
            if key in self.labels:
                self.labels[key].setToolTip(libre_tip)

        self.set_label("ram", "N/A")
        self.set_bar("ram_bar", 0)
        self.set_bar_color("ram_bar", "#ffb000")

        drives = connected_local_drives()
        if self.usb_only:
            drives = [d for d in drives if d["kind"] == "USB"]
        self.rebuild_drives_if_needed(drives)

        for drive in drives:
            letter = drive["letter"]
            if letter not in self.drive_widgets:
                continue

            try:
                du = psutil.disk_usage(drive["root"])
                used_gb = du.used / (1024 ** 3)
                total_gb = du.total / (1024 ** 3)
                pct_text = colored_span(f"{du.percent:.0f}%", usage_text_color(du.percent))
                rich_text = f'{pct_text}   {used_gb:.1f}/{total_gb:.1f} GB   <span style="color:#ffb000;">N/A</span>'
                tip = (
                    f"Meghajtó: {letter}:\\ {drive.get('label') or ''}\n"
                    f"{self.t('drive_usage')}: {du.percent:.1f} %\n"
                    f"{self.t('drive_temp')}: {self.t('not_available')} – {self.t('status_libre_off')}"
                )
                pct = du.percent
            except Exception:
                rich_text = self.t("no_drive")
                tip = f"{letter}: nem elérhető"
                pct = 0

            self.drive_widgets[letter]["label"].setText(rich_text)
            self.drive_widgets[letter]["label"].setStyleSheet(neutral_label_style())
            self.set_drive_tooltip(letter, tip)
            self.drive_widgets[letter]["bar"].setValue(max(0, min(100, int(round(pct)))))
            self.set_drive_bar_color(letter, usage_color(pct))

        if self.show_network and (self.tick == 1 or self.tick % 5 == 0):
            self.wifi_ssid, self.wifi_signal = get_wifi_info()

        internal_ip = get_internal_ip()
        self.set_label("external_ip", self.external_ip)
        self.set_label("internal_ip", internal_ip)
        self.set_label("ssid", self.wifi_ssid)
        self.set_label("signal", self.t("not_available") if self.wifi_ssid == "N/A" else f"{self.wifi_signal}%")
        self.set_label("down", self.t("not_available"))
        self.set_label("up", self.t("not_available"))

        net_tip = (
            self.t("net_tip_external", value=self.external_ip) + "\n"
            + self.t("net_tip_internal", value=internal_ip) + "\n"
            + self.t("net_tip_ssid", value=self.wifi_ssid) + "\n"
            + self.t("net_tip_signal", value=(self.t("not_available") if self.wifi_ssid == "N/A" else str(self.wifi_signal) + "%")) + "\n"
            + self.t("net_tip_down_na")
        )
        for key in ("external_ip", "internal_ip", "ssid", "signal", "down", "up"):
            if key in self.labels:
                self.labels[key].setToolTip(net_tip)

        self.update_status_line([], libre_ok=False)

        payload_items = {
            "ver": "pywidget-libre-v1",
            "libre": "0",
            "hwinfo": "0",  # régi ESP32 parser kompatibilitás
            "cpu": "0",
            "cput": "0",
            "clock": "0",
            "fan": "0",
            "mbfan": "0",
            "vbat": "0",
            "ram": "0",
            "ip": internal_ip,
            "pubip": self.external_ip,
            "ssid": self.wifi_ssid,
            "sig": str(self.wifi_signal),
            "down": "0",
            "up": "0",
        }
        self.last_payload = ";".join(f"{k}={v}" for k, v in payload_items.items())
        self.send_udp_payload(self.last_payload)

    def update_values(self):
        self.tick += 1

        if not self.reader.is_open():
            if not self.reader.try_open():
                self.show_libre_offline(self.reader.last_error)
                return

        try:
            readings = self.reader.read_all()
        except Exception as e:
            self.reader.last_error = str(e)
            self.reader.close()
            self.show_libre_offline(str(e))
            return

        cpu_temp = self.reader.cpu_temperature(readings)
        cpu_usage = self.reader.cpu_usage(readings)
        cpu_clock = self.reader.cpu_clock(readings)
        cpu_fan, mb_fan = self.reader.fan_values(readings)
        cmos_reading = self.reader.cmos_battery_reading(readings)
        cmos_voltage = self.reader.value_in(cmos_reading, "V")
        cpu_power = self.reader.cpu_power(readings)
        libre_ram_used_mb, libre_ram_avail_mb, libre_ram_load = self.reader.memory_values(readings)
        net_down, net_up = self.reader.network_rates(readings)

        # A RAM-nál a Windows fizikai memóriakezelője a hiteles forrás.
        # Így a kijelzett teljes memória a ténylegesen használható fizikai RAM,
        # nem pedig két Libre-szenzor esetleg hibás összege.
        ram_used_mb, ram_avail_mb, ram_total_mb, ram_load = windows_physical_memory_values()

        # Csak akkor használjuk a Libre memóriaértékeit, ha a Windows API és
        # a psutil egyaránt sikertelen lenne.
        if ram_total_mb is None:
            ram_used_mb = libre_ram_used_mb
            ram_avail_mb = libre_ram_avail_mb
            ram_load = libre_ram_load
            if ram_used_mb is not None and ram_avail_mb is not None:
                ram_total_mb = ram_used_mb + ram_avail_mb

        if self.show_network and (self.tick == 1 or self.tick % 5 == 0):
            self.wifi_ssid, self.wifi_signal = get_wifi_info()

        drives = connected_local_drives()
        if self.usb_only:
            drives = [d for d in drives if d["kind"] == "USB"]
        self.rebuild_drives_if_needed(drives)

        internal_ip = get_internal_ip()

        self.set_label(
            "cpu_temp",
            colored_span(f"{fmt(cpu_temp, 0)}°C", temp_color(cpu_temp, "cpu")),
        )
        self.set_label("cpu_usage", colored_span(f"{fmt(cpu_usage, 1)}%", usage_text_color(cpu_usage)))
        self.set_label("cpu_clock", f"{fmt(cpu_clock, 0)} MHz")
        self.set_label("cpu_fan", f"{fmt(cpu_fan, 0)} rpm")
        self.set_label("mb_fan", f"{fmt(mb_fan, 0)} rpm")
        cpu_tip = self.build_cpu_tooltip(cpu_temp, cpu_usage, cpu_clock, cpu_fan, mb_fan, cpu_power)
        for key in ("cpu_temp", "cpu_usage", "cpu_clock", "cpu_fan", "mb_fan"):
            self.labels[key].setToolTip(cpu_tip)

        if ram_used_mb is not None and ram_avail_mb is not None and ram_total_mb is not None:
            ram_text = (
                f"{gb_from_mb(ram_used_mb):.1f}/{gb_from_mb(ram_total_mb):.1f} GB   "
                + colored_span(f"{fmt(ram_load, 0)}%", usage_text_color(ram_load))
            )
            self.set_label("ram", ram_text)
            self.labels["ram"].setToolTip(
                f"{self.t('ram_used')}: {gb_from_mb(ram_used_mb):.1f} GB\n"
                f"{self.t('ram_available')}: {gb_from_mb(ram_avail_mb):.1f} GB\n"
                f"{self.t('ram_total')}: {gb_from_mb(ram_total_mb):.1f} GB\n"
                f"{self.t('ram_load')}: {fmt(ram_load, 1)} %\n"
                f"{self.t('source')}: {self.t('source_windows_memory')}"
            )
            self.set_bar("ram_bar", ram_load or 0)
            self.set_bar_color("ram_bar", usage_color(ram_load))
        else:
            self.set_label("ram", "N/A")
            self.set_bar("ram_bar", 0)
            self.set_bar_color("ram_bar", usage_color(0))

        if cmos_voltage is not None:
            self.set_label(
                "cmos",
                colored_span(f"{cmos_voltage:.2f} V", cmos_voltage_color(cmos_voltage)),
            )
            source_name = str(cmos_reading.get("label", "")).strip() or "Libre voltage sensor"
            source_id = str(cmos_reading.get("sensor_id", "")).strip()
            cmos_tip = (
                f"{self.t('cmos_battery')}: {cmos_voltage:.3f} V\n"
                f"{self.t('source')}: {source_name}"
                + (f"\n{self.t('identifier')}: {source_id}" if source_id else "")
                + f"\n\n{self.t('coloring')}:\n"
                + self.t("green_threshold") + "\n"
                + self.t("orange_threshold") + "\n"
                + self.t("red_threshold")
            )
        else:
            self.set_label("cmos", colored_span("N/A", "#b0b0b0"))
            cmos_tip = (
                self.t("cmos_missing_1") + "\n" + self.t("cmos_missing_2")
            )
        self.labels["cmos"].setToolTip(cmos_tip)

        for drive in drives:
            letter = drive["letter"]
            temp = self.reader.drive_temp(readings, drive)
            text, pct = self.disk_text_and_percent(drive, temp)
            if letter in self.drive_widgets:
                try:
                    du = psutil.disk_usage(drive["root"])
                    used_gb = du.used / (1024 ** 3)
                    total_gb = du.total / (1024 ** 3)
                    pct_text = colored_span(f"{du.percent:.0f}%", usage_text_color(du.percent))
                    temp_text = colored_span(f"{temp:.0f}°C", temp_color(temp, "drive")) if temp is not None else '<span style="color:#b0b0b0;">N/A</span>'
                    rich_text = f"{pct_text}   {used_gb:.1f}/{total_gb:.1f} GB   {temp_text}"
                    drive_tip = self.drive_extra_tooltip(readings, drive, used_gb, total_gb, du.percent, temp)
                except Exception:
                    rich_text = self.t("no_drive")
                    drive_tip = self.t("drive_unavailable", letter=letter)

                # Csak a százalék és a hőfok színes. A kapacitás szövege semleges marad.
                self.drive_widgets[letter]["label"].setText(rich_text)
                self.drive_widgets[letter]["label"].setStyleSheet(neutral_label_style())
                self.set_drive_tooltip(letter, drive_tip)

                # A csík továbbra is a telítettséget jelzi.
                self.drive_widgets[letter]["bar"].setValue(max(0, min(100, int(round(pct)))))
                self.set_drive_bar_color(letter, usage_color(pct))

        self.set_label("external_ip", self.external_ip)
        self.set_label("internal_ip", internal_ip)
        self.set_label("ssid", self.wifi_ssid)
        self.set_label("signal", self.t("not_available") if self.wifi_ssid == "N/A" else f"{self.wifi_signal}%")
        self.set_label("down", fmt_net_speed(net_down))
        self.set_label("up", fmt_net_speed(net_up))

        net_tip = (
            self.t("net_tip_external", value=self.external_ip) + "\n"
            + self.t("net_tip_internal", value=internal_ip) + "\n"
            + self.t("net_tip_ssid", value=self.wifi_ssid) + "\n"
            + self.t("net_tip_signal", value=(self.t("not_available") if self.wifi_ssid == "N/A" else str(self.wifi_signal) + "%")) + "\n"
            + self.t("net_tip_down", value=fmt_net_speed(net_down)) + "\n"
            + self.t("net_tip_up", value=fmt_net_speed(net_up))
        )
        for key in ("external_ip", "internal_ip", "ssid", "signal", "down", "up"):
            self.labels[key].setToolTip(net_tip)

        alerts = []
        if cpu_temp is not None and cpu_temp >= 80:
            alerts.append(self.t("alert_cpu_hot", value=f"{cpu_temp:.0f}°C"))
        if cpu_usage is not None and cpu_usage >= 90:
            alerts.append(self.t("alert_cpu_high", value=f"{cpu_usage:.0f}%"))
        if ram_load is not None and ram_load >= 90:
            alerts.append(self.t("alert_ram_high", value=f"{ram_load:.0f}%"))
        if cmos_voltage is not None and cmos_voltage < 2.95:
            if cmos_voltage < 2.80:
                alerts.append(self.t("alert_cmos_low", value=f"{cmos_voltage:.2f} V"))
            else:
                alerts.append(self.t("alert_cmos_weak", value=f"{cmos_voltage:.2f} V"))

        for drive in drives:
            letter = drive["letter"]
            temp = self.reader.drive_temp(readings, drive)
            try:
                du = psutil.disk_usage(drive["root"])
                if du.percent >= 90:
                    alerts.append(self.t("alert_drive_full", letter=letter, value=f"{du.percent:.0f}%"))
            except Exception:
                pass
            if temp is not None and temp >= 60:
                alerts.append(self.t("alert_drive_hot", letter=letter, value=f"{temp:.0f}°C"))

        self.update_status_line(alerts, libre_ok=True)

        payload_items = {
            "ver": "pywidget-libre-v1",
            "libre": "1",
            "hwinfo": "1",  # régi ESP32 parser kompatibilitás
            "cpu": fmt(cpu_usage, 1, "0"),
            "cput": fmt(cpu_temp, 0, "0"),
            "clock": fmt(cpu_clock, 0, "0"),
            "fan": fmt(cpu_fan, 0, "0"),
            "mbfan": fmt(mb_fan, 0, "0"),
            "vbat": fmt(cmos_voltage, 2, "0"),
            "ram": fmt(ram_load, 0, "0"),
            "ip": internal_ip,
            "pubip": self.external_ip,
            "ssid": self.wifi_ssid,
            "sig": str(self.wifi_signal),
            "down": fmt(net_down, 1, "0"),
            "up": fmt(net_up, 1, "0"),
        }
        self.last_payload = ";".join(f"{k}={v}" for k, v in payload_items.items())
        self.send_udp_payload(self.last_payload)

    def schedule_snap(self):
        if self._restoring_geometry or self._snap_active:
            return
        if hasattr(self, "snap_timer"):
            self.snap_timer.start(180)

    def moveEvent(self, event):
        self.settings.setValue("pos", self.pos())
        self.schedule_snap()
        super().moveEvent(event)

    def resizeEvent(self, event):
        self.settings.setValue("size", self.size())
        self.schedule_snap()
        if hasattr(self, "size_grip"):
            self.size_grip.move(
                self.width() - self.size_grip.width(),
                self.height() - self.size_grip.height(),
            )
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        if self.frameless_mode and event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.frameless_mode and self._drag_pos is not None and (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def snap_to_screen_edges(self):
        if self._snap_active:
            return

        screen = QApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return

        area = screen.availableGeometry()
        frame = self.frameGeometry()
        threshold = 24

        new_x = self.x()
        new_y = self.y()

        # Bal / jobb oldal
        if abs(frame.left() - area.left()) <= threshold:
            new_x = area.left()
        elif abs(frame.right() - area.right()) <= threshold:
            new_x = area.right() - frame.width() + 1

        # Felső / alsó oldal
        if abs(frame.top() - area.top()) <= threshold:
            new_y = area.top()
        elif abs(frame.bottom() - area.bottom()) <= threshold:
            new_y = area.bottom() - frame.height() + 1

        if new_x != self.x() or new_y != self.y():
            self._snap_active = True
            self.move(new_x, new_y)
            self._snap_active = False
            self.settings.setValue("pos", self.pos())

    def apply_window_flags(self):
        flags = Qt.WindowType.Tool
        if self.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if self.frameless_mode:
            flags |= Qt.WindowType.FramelessWindowHint
        self.setWindowFlags(flags)

    def set_always_on_top(self, enabled):
        self.always_on_top = bool(enabled)
        self.settings.setValue("always_on_top", self.always_on_top)

        geom = self.geometry()
        visible = self.isVisible()
        self.apply_window_flags()
        self.setGeometry(geom)
        if visible:
            self.show()
            self.raise_()

    def set_frameless_mode(self, enabled):
        self.frameless_mode = bool(enabled)
        self.settings.setValue("frameless_mode", self.frameless_mode)

        geom = self.geometry()
        visible = self.isVisible()
        self.apply_window_flags()
        self.setGeometry(geom)
        if hasattr(self, "size_grip"):
            self.size_grip.setVisible(self.frameless_mode)
            self.size_grip.raise_()
        if visible:
            self.show()
            self.raise_()

    def screen_available_geometry(self):
        screen = QApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen.availableGeometry() if screen else None

    def move_to_position(self, where):
        area = self.screen_available_geometry()
        if area is None:
            return

        margin = 12
        frame = self.frameGeometry()
        w = frame.width()
        h = frame.height()

        positions = {
            "top_left": (area.left() + margin, area.top() + margin),
            "top_right": (area.right() - w - margin + 1, area.top() + margin),
            "bottom_left": (area.left() + margin, area.bottom() - h - margin + 1),
            "bottom_right": (area.right() - w - margin + 1, area.bottom() - h - margin + 1),
            "left_center": (area.left() + margin, area.top() + (area.height() - h) // 2),
            "right_center": (area.right() - w - margin + 1, area.top() + (area.height() - h) // 2),
            "top_center": (area.left() + (area.width() - w) // 2, area.top() + margin),
            "bottom_center": (area.left() + (area.width() - w) // 2, area.bottom() - h - margin + 1),
            "center": (area.left() + (area.width() - w) // 2, area.top() + (area.height() - h) // 2),
        }

        x, y = positions.get(where, positions["center"])
        self.move(x, y)
        self.settings.setValue("pos", self.pos())

    def set_show_network(self, enabled):
        self.show_network = bool(enabled)
        self.settings.setValue("show_network", self.show_network)
        self.apply_visibility()
        self.fit_height_to_content()

    def set_show_drives(self, enabled):
        self.show_drives = bool(enabled)
        self.settings.setValue("show_drives", self.show_drives)
        self.apply_visibility()
        self.fit_height_to_content()

    def set_usb_only(self, enabled):
        self.usb_only = bool(enabled)
        self.settings.setValue("usb_only", self.usb_only)
        self.drive_signature = None
        self.update_values()
        self.fit_height_to_content()

    def set_compact_mode(self, enabled):
        self.compact_mode = bool(enabled)
        self.settings.setValue("compact_mode", self.compact_mode)
        self.apply_compact_mode()
        self.fit_height_to_content()

    def apply_visibility(self):
        if hasattr(self, "net_section"):
            self.net_section.setVisible(self.show_network)
        if hasattr(self, "drives_section"):
            self.drives_section.setVisible(self.show_drives)

    def apply_compact_mode(self):
        if self.compact_mode:
            main_margins = (4, 4, 4, 4)
            main_spacing = 3
            row_h = 16
            title_h = 17
            key_w = 82
            font_px = 9
            title_px = 12
            bar_h = 4
        else:
            main_margins = (5, 5, 5, 5)
            main_spacing = 5
            row_h = 18
            title_h = 19
            key_w = 92
            font_px = 10
            title_px = 13
            bar_h = 5

        self.main_layout.setContentsMargins(*main_margins)
        self.main_layout.setSpacing(main_spacing)

        self.setStyleSheet(f"""
            QWidget {{
                background: #080808;
                color: #d8d8d8;
                font-family: Segoe UI;
                font-size: {font_px}px;
            }}

            QFrame#section {{
                background: #101010;
                border: 1px solid #555555;
                border-radius: 5px;
            }}

            QLabel#sectionTitle {{
                background: #050505;
                color: #ffffff;
                font-weight: bold;
                font-size: {title_px}px;
            }}

            QLabel#keyLabel {{
                background: #050505;
                color: #eeeeee;
                font-weight: bold;
            }}

            QLabel#valueLabel {{
                background: #050505;
                color: #eeeeee;
                font-weight: bold;
            }}

            QLabel#statusLabel {{
                background: #101010;
                border: 1px solid #555555;
                border-radius: 5px;
                color: #50d050;
                font-weight: bold;
            }}

            QProgressBar {{
                background: #202020;
                border: 1px solid #444444;
                min-height: {bar_h}px;
                max-height: {bar_h}px;
                text-align: center;
            }}

            QProgressBar::chunk {{
                background: #50d050;
            }}
        """)

        for lab in self.findChildren(QLabel):
            if lab.objectName() == "sectionTitle":
                lab.setFixedHeight(title_h)
            elif lab.objectName() in ("keyLabel", "valueLabel"):
                lab.setFixedHeight(row_h)
                if lab.objectName() == "keyLabel":
                    lab.setMinimumWidth(key_w)
            elif lab.objectName() == "statusLabel":
                lab.setFixedHeight(row_h + 4)

        for bar in self.findChildren(QProgressBar):
            bar.setMinimumHeight(bar_h)
            bar.setMaximumHeight(bar_h)

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        always_action = QAction(self.t("menu_always_on_top"), self)
        always_action.setCheckable(True)
        always_action.setChecked(self.always_on_top)
        always_action.toggled.connect(self.set_always_on_top)

        frameless_action = QAction(self.t("menu_frameless"), self)
        frameless_action.setCheckable(True)
        frameless_action.setChecked(self.frameless_mode)
        frameless_action.toggled.connect(self.set_frameless_mode)

        network_action = QAction(self.t("menu_show_network"), self)
        network_action.setCheckable(True)
        network_action.setChecked(self.show_network)
        network_action.toggled.connect(self.set_show_network)

        drives_action = QAction(self.t("menu_show_drives"), self)
        drives_action.setCheckable(True)
        drives_action.setChecked(self.show_drives)
        drives_action.toggled.connect(self.set_show_drives)

        usb_only_action = QAction(self.t("menu_usb_only"), self)
        usb_only_action.setCheckable(True)
        usb_only_action.setChecked(self.usb_only)
        usb_only_action.toggled.connect(self.set_usb_only)

        compact_action = QAction(self.t("menu_compact"), self)
        compact_action.setCheckable(True)
        compact_action.setChecked(self.compact_mode)
        compact_action.toggled.connect(self.set_compact_mode)

        alerts_action = QAction(self.t("menu_alerts"), self)
        alerts_action.setCheckable(True)
        alerts_action.setChecked(self.alerts_enabled)
        alerts_action.toggled.connect(self.set_alerts_enabled)

        udp_action = QAction(self.t("menu_udp"), self)
        udp_action.setCheckable(True)
        udp_action.setChecked(self.udp_enabled)
        udp_action.toggled.connect(self.set_udp_enabled)

        startup_action = QAction(self.t("menu_startup"), self)
        startup_action.setCheckable(True)
        startup_action.setChecked(self.is_startup_enabled())
        startup_action.toggled.connect(self.set_startup_enabled)

        hide_action = QAction(self.t("menu_hide_to_tray"), self)
        hide_action.triggered.connect(self.hide)

        refresh_ip_action = QAction(self.t("menu_refresh_ip"), self)
        refresh_ip_action.triggered.connect(self.refresh_external_ip)

        reset_action = QAction(self.t("menu_reset_size"), self)
        reset_action.triggered.connect(self.reset_size)

        exit_action = QAction(self.t("menu_exit"), self)
        exit_action.triggered.connect(QApplication.quit)

        opacity_menu = QMenu(self.t("menu_opacity"), self)
        for label, value in (("100%", 1.0), ("90%", 0.90), ("75%", 0.75), ("60%", 0.60)):
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(abs(self.opacity_value - value) < 0.01)
            act.triggered.connect(lambda checked=False, v=value: self.set_opacity_value(v))
            opacity_menu.addAction(act)

        pos_menu = QMenu(self.t("menu_position"), self)
        for title, key in (
            (self.t("menu_top_left"), "top_left"),
            (self.t("menu_top_right"), "top_right"),
            (self.t("menu_bottom_left"), "bottom_left"),
            (self.t("menu_bottom_right"), "bottom_right"),
            (self.t("menu_left_center"), "left_center"),
            (self.t("menu_right_center"), "right_center"),
            (self.t("menu_top_center"), "top_center"),
            (self.t("menu_bottom_center"), "bottom_center"),
            (self.t("menu_center"), "center"),
        ):
            act = QAction(title, self)
            act.triggered.connect(lambda checked=False, k=key: self.move_to_position(k))
            pos_menu.addAction(act)

        menu.addAction(always_action)
        menu.addAction(frameless_action)
        menu.addMenu(pos_menu)
        menu.addMenu(self.build_language_menu(menu))
        menu.addAction(alerts_action)
        menu.addSeparator()
        menu.addAction(network_action)
        menu.addAction(drives_action)
        menu.addAction(usb_only_action)
        menu.addSeparator()
        menu.addAction(compact_action)
        menu.addMenu(opacity_menu)
        menu.addSeparator()
        menu.addAction(udp_action)
        menu.addAction(startup_action)
        menu.addSeparator()
        menu.addAction(refresh_ip_action)
        menu.addAction(reset_action)
        menu.addSeparator()
        menu.addAction(hide_action)
        menu.addAction(exit_action)
        menu.exec(event.globalPos())

    def refresh_external_ip(self):
        self.external_ip = get_external_ip()
        self.update_values()

    def reset_size(self):
        self.resize(self.DEFAULT_WIDTH, self.height())
        self.fit_height_to_content()
        self.settings.setValue("size", self.size())

    def closeEvent(self, event):
        self.settings.setValue("pos", self.pos())
        self.settings.setValue("size", self.size())
        self.settings.setValue("show_network", self.show_network)
        self.settings.setValue("show_drives", self.show_drives)
        self.settings.setValue("usb_only", self.usb_only)
        self.settings.setValue("compact_mode", self.compact_mode)
        self.settings.setValue("always_on_top", self.always_on_top)
        self.settings.setValue("frameless_mode", self.frameless_mode)
        self.settings.setValue("alerts_enabled", self.alerts_enabled)
        self.settings.setValue("udp_enabled", self.udp_enabled)
        self.settings.setValue("opacity", self.opacity_value)
        self.settings.setValue("language", self.language)
        super().closeEvent(event)


def main():
    set_windows_app_id()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    font = QFont("Segoe UI", 8)
    app.setFont(font)

    app_icon = load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    reader = LibreHardwareMonitorReader()
    reader.try_open()

    win = WidgetWindow(reader)
    win.show()

    result = app.exec()

    reader.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
