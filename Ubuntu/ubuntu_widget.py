#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Linux Hardver Widget (Ubuntu, KDE / GNOME)

A libre_widget.py Linuxos változata: azonos kinézet és funkciók,
de a szenzoradatokat a Linux saját forrásaiból (psutil, /sys/class/hwmon,
lm-sensors) olvassa, nincs szükség LibreHardwareMonitorra.

Függőségek:
    sudo apt install python3-psutil python3-pyside6.qtwidgets lm-sensors
    (vagy: pip install psutil PySide6)
"""

import glob
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request

import psutil
from PySide6.QtCore import Qt, QTimer, QPoint, QSize, QSettings, QUrl
from PySide6.QtGui import QFont, QAction, QActionGroup, QIcon, QCursor, QDesktopServices
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


AUTOSTART_FILE = "linux_hardware_widget.desktop"

PSEUDO_FS = {
    "squashfs", "tmpfs", "devtmpfs", "overlay", "ramfs", "proc", "sysfs",
    "cgroup", "cgroup2", "fuse.gvfsd-fuse", "fuse.portal", "efivarfs",
    "autofs", "binfmt_misc", "bpf", "tracefs", "debugfs", "securityfs",
}

HWMON_ROOT = "/sys/class/hwmon"

SKIP_MOUNT_PREFIXES = (
    "/snap", "/var/snap", "/boot/efi", "/var/lib/docker", "/var/lib/snapd",
    "/sys", "/proc", "/dev", "/run",
)


def prefer_x11_if_wayland():
    """
    Wayland alatt az ablakok nem mozgathatók programból, nincs ablak-átlátszóság
    és "mindig felül" sem. Ezért ha lehet, XWayland (xcb) módban indulunk.
    Kikapcsolás: HWIDGET_WAYLAND=1 python3 ubuntu_widget.py
    """
    if "QT_QPA_PLATFORM" in os.environ or os.environ.get("HWIDGET_WAYLAND"):
        return
    on_wayland = (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        or os.environ.get("WAYLAND_DISPLAY")
    )
    if not on_wayland or not os.environ.get("DISPLAY"):
        return

    try:
        env = dict(os.environ, QT_QPA_PLATFORM="xcb")
        result = subprocess.run(
            [sys.executable, "-c",
             "from PySide6.QtWidgets import QApplication; a = QApplication([])"],
            env=env, timeout=20,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            os.environ["QT_QPA_PLATFORM"] = "xcb"
        else:
            print("Az X11 (xcb) mód nem indul el. Próbáld: sudo apt install libxcb-cursor0",
                  file=sys.stderr)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Általános segédfüggvények
# ---------------------------------------------------------------------------

def fmt(value, decimals=1, fallback="N/A"):
    if value is None:
        return fallback
    return f"{value:.{decimals}f}"


def fmt_net_speed(value, fallback="N/A"):
    """
    Hálózati sebesség kijelzése KB/s alapértékből.
    1000 KB/s felett MB/s-ra vált.
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


def read_text(path, default=""):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except Exception:
        return default


def resource_path(filename):
    return os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), filename)


def load_app_icon():
    for name in ("app_icon.png", "icon.png", "app_icon.ico"):
        path = resource_path(name)
        if os.path.exists(path):
            icon = QIcon(path)
            if not icon.isNull():
                return icon

    icon = QIcon.fromTheme("utilities-system-monitor")
    if not icon.isNull():
        return icon
    return QIcon()


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
    BIOS/CMOS elem feszültségszínezése.
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


def fan_color(rpm, cpu=True):
    """
    Ventilátor színezés: csak az eltérést jelöli.
    Álló CPU-ventilátor piros, nagyon lassú narancs; az alaplapi/ház
    ventilátornál a 0 fordulat csak narancs (lehet üres csatlakozó is).
    """
    if rpm is None:
        return None
    if rpm <= 0:
        return "#ff5050" if cpu else "#ffb000"
    if rpm < 300:
        return "#ffb000"
    return None


def signal_color(percent):
    """Wi-Fi jelerősség: csak a gyenge jelet színezi."""
    if percent is None:
        return None
    if percent < 30:
        return "#ff5050"
    if percent < 50:
        return "#ffb000"
    return None


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


def colored_span(text, color):
    return f'<span style="color:{color}; font-weight:700;">{text}</span>'


def usage_text_color(percent):
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


# ---------------------------------------------------------------------------
# Fordítások
# ---------------------------------------------------------------------------

TRANSLATIONS = {
    "hu": {
        "app_title": "Linux Hardver Widget",
        "tray_tooltip": "Linux Hardver Widget",
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
        "cpu_tip_temp": "CPU hőfok: {value}",
        "cpu_tip_usage": "CPU terhelés: {value}",
        "cpu_tip_clock": "CPU órajel: {value}",
        "cpu_tip_cpu_fan": "CPU ventilátor: {value}",
        "cpu_tip_mb_fan": "Alaplapi/ház ventilátor: {value}",
        "cpu_tip_power": "CPU Package Power: {value}",
        "sensor_missing_1": "Nem érhető el minden hőmérséklet- vagy ventilátoradat.",
        "sensor_missing_2": "Telepítsd: sudo apt install lm-sensors, futtasd: sudo sensors-detect (mindenre igen), majd indítsd újra a gépet.",
        "sensor_chips": "Talált szenzorchipek: {value}",
        "drive_label": "Meghajtó",
        "drive_type": "Típus",
        "drive_type_usb": "USB",
        "drive_type_fixed": "Fix",
        "drive_device": "Eszköz",
        "drive_physical": "Fizikai lemez",
        "drive_used": "Használt",
        "drive_total": "Teljes",
        "drive_usage": "Telítettség",
        "drive_temp": "Hőfok",
        "drive_open_hint": "Kattints a meghajtónévre a megnyitáshoz.",
        "open_in_fm": "Megnyitás fájlkezelőben: {path}",
        "host_reads_boot": "Olvasás (boot óta)",
        "host_writes_boot": "Írás (boot óta)",
        "not_available": "N/A",
        "no_drive": "nincs meghajtó",
        "drive_unavailable": "{mount}: nem elérhető",
        "ram_used": "RAM használt",
        "ram_available": "RAM elérhető",
        "ram_total": "RAM teljes (rendszer által használható)",
        "ram_load": "Terhelés",
        "source": "Forrás",
        "source_linux_memory": "Linux fizikai memória (/proc/meminfo)",
        "cmos_battery": "BIOS/CMOS elem",
        "identifier": "Azonosító",
        "coloring": "Színezés",
        "green_threshold": "zöld: >= 2.95 V",
        "orange_threshold": "narancs: 2.80-2.94 V",
        "red_threshold": "piros: < 2.80 V",
        "cmos_missing_1": "Nem található felismerhető CMOS/VBAT feszültségszenzor.",
        "cmos_missing_2": "Az alaplapi szenzorchip driverét be kell tölteni (pl. sudo modprobe nct6775 vagy it87).",
        "net_tip_external": "Külső IP: {value}",
        "net_tip_internal": "Belső IP: {value}",
        "net_tip_ssid": "SSID: {value}",
        "net_tip_signal": "Jelerősség: {value}",
        "net_tip_down": "Letöltés: {value}",
        "net_tip_up": "Feltöltés: {value}",
        "alert_cpu_hot": "CPU meleg: {value}",
        "alert_cpu_high": "CPU magas: {value}",
        "alert_ram_high": "RAM magas: {value}",
        "alert_cmos_low": "CMOS elem alacsony: {value}",
        "alert_cmos_weak": "CMOS elem gyengül: {value}",
        "alert_drive_full": "{mount}: tele: {value}",
        "alert_drive_hot": "{mount}: meleg: {value}",
        "startup_error_title": "Startup hiba",
        "startup_error_body": "Nem sikerült módosítani az automatikus indítást:\n{error}",
    },
    "en": {
        "app_title": "Linux Hardware Widget",
        "tray_tooltip": "Linux Hardware Widget",
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
        "cpu_tip_temp": "CPU temperature: {value}",
        "cpu_tip_usage": "CPU usage: {value}",
        "cpu_tip_clock": "CPU clock: {value}",
        "cpu_tip_cpu_fan": "CPU fan: {value}",
        "cpu_tip_mb_fan": "Motherboard/case fan: {value}",
        "cpu_tip_power": "CPU package power: {value}",
        "sensor_missing_1": "Not all temperature or fan data is available.",
        "sensor_missing_2": "Install: sudo apt install lm-sensors, run: sudo sensors-detect (answer yes to all), then reboot.",
        "sensor_chips": "Detected sensor chips: {value}",
        "drive_label": "Drive",
        "drive_type": "Type",
        "drive_type_usb": "USB",
        "drive_type_fixed": "Fixed",
        "drive_device": "Device",
        "drive_physical": "Physical disk",
        "drive_used": "Used",
        "drive_total": "Total",
        "drive_usage": "Usage",
        "drive_temp": "Temperature",
        "drive_open_hint": "Click the drive name to open it.",
        "open_in_fm": "Open in file manager: {path}",
        "host_reads_boot": "Reads (since boot)",
        "host_writes_boot": "Writes (since boot)",
        "not_available": "N/A",
        "no_drive": "drive unavailable",
        "drive_unavailable": "{mount}: unavailable",
        "ram_used": "RAM used",
        "ram_available": "RAM available",
        "ram_total": "RAM total (usable by the system)",
        "ram_load": "Load",
        "source": "Source",
        "source_linux_memory": "Linux physical memory (/proc/meminfo)",
        "cmos_battery": "BIOS/CMOS battery",
        "identifier": "Identifier",
        "coloring": "Coloring",
        "green_threshold": "green: >= 2.95 V",
        "orange_threshold": "orange: 2.80-2.94 V",
        "red_threshold": "red: < 2.80 V",
        "cmos_missing_1": "No recognizable CMOS/VBAT voltage sensor was found.",
        "cmos_missing_2": "The motherboard sensor chip driver must be loaded (e.g. sudo modprobe nct6775 or it87).",
        "net_tip_external": "External IP: {value}",
        "net_tip_internal": "Internal IP: {value}",
        "net_tip_ssid": "SSID: {value}",
        "net_tip_signal": "Signal strength: {value}",
        "net_tip_down": "Download: {value}",
        "net_tip_up": "Upload: {value}",
        "alert_cpu_hot": "CPU hot: {value}",
        "alert_cpu_high": "CPU high: {value}",
        "alert_ram_high": "RAM high: {value}",
        "alert_cmos_low": "CMOS battery low: {value}",
        "alert_cmos_weak": "CMOS battery weakening: {value}",
        "alert_drive_full": "{mount}: full: {value}",
        "alert_drive_hot": "{mount}: hot: {value}",
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


# ---------------------------------------------------------------------------
# Hálózat
# ---------------------------------------------------------------------------

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


def _run(cmd, timeout=2):
    env = dict(os.environ, LC_ALL="C")
    return subprocess.check_output(
        cmd,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
        stderr=subprocess.DEVNULL,
        env=env,
    )


def _proc_wireless_signal():
    """Jelerősség % a /proc/net/wireless alapján."""
    try:
        lines = read_text("/proc/net/wireless").splitlines()[2:]
        for line in lines:
            parts = line.replace(":", " ").split()
            if len(parts) >= 3:
                quality = float(parts[2].rstrip("."))
                return max(0, min(100, int(round(quality / 70.0 * 100.0))))
    except Exception:
        pass
    return 0


def get_wifi_info():
    ssid = None
    signal = 0

    try:
        out = _run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi", "list", "--rescan", "no"])
        for line in out.splitlines():
            m = re.match(r"^yes:((?:\\.|[^:\\])*):(\d+)\s*$", line)
            if m:
                ssid = re.sub(r"\\(.)", r"\1", m.group(1)) or "Connected"
                signal = int(m.group(2))
                break
    except Exception:
        pass

    if ssid is None:
        try:
            name = _run(["iwgetid", "-r"]).strip()
            if name:
                ssid = name
                signal = _proc_wireless_signal()
        except Exception:
            pass

    if not ssid:
        return "N/A", 0
    return ssid, signal


_VIRTUAL_NIC_PREFIXES = ("lo", "docker", "veth", "br-", "virbr")


def network_counters():
    """Összesített fizikai hálózati forgalom (rx, tx bájtban)."""
    try:
        rx = tx = 0
        for name, c in psutil.net_io_counters(pernic=True).items():
            if name.startswith(_VIRTUAL_NIC_PREFIXES):
                continue
            rx += c.bytes_recv
            tx += c.bytes_sent
        return rx, tx
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CPU, ventilátor, feszültség, RAM
# ---------------------------------------------------------------------------

_SENSORS_TEXT_CACHE = {"timestamp": -1000.0, "text": ""}


def sensors_text():
    """Az lm-sensors `sensors` parancs kimenete (3 mp-es gyorsítótárral)."""
    now = time.monotonic()
    if now - _SENSORS_TEXT_CACHE["timestamp"] < 3:
        return _SENSORS_TEXT_CACHE["text"]
    try:
        text = _run(["sensors"], timeout=3)
    except Exception:
        text = ""
    _SENSORS_TEXT_CACHE["timestamp"] = now
    _SENSORS_TEXT_CACHE["text"] = text
    return text


def hwmon_chip_names():
    names = []
    for hw in sorted(glob.glob(os.path.join(HWMON_ROOT, "hwmon*"))):
        name = read_text(os.path.join(hw, "name"))
        if name and name not in names:
            names.append(name)
    return names


def _sensors_cli_temperature():
    """Tartalék: CPU-hőfok az lm-sensors kimenetéből."""
    out = sensors_text()
    if not out:
        return None

    m = re.search(r"Package id\s*0:\s*\+?(-?\d+(?:\.\d+)?)\s*°?C", out, re.I)
    if m:
        return float(m.group(1))
    for pattern in (r"Tdie:\s*\+?(-?\d+(?:\.\d+)?)", r"Tctl:\s*\+?(-?\d+(?:\.\d+)?)"):
        m = re.search(pattern, out, re.I)
        if m:
            return float(m.group(1))
    vals = re.findall(r"Core\s+\d+:\s*\+?(-?\d+(?:\.\d+)?)\s*°?C", out, re.I)
    if vals:
        return sum(map(float, vals)) / len(vals)
    return None


def cpu_temperature():
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        temps = {}

    entries = temps.get("coretemp")
    if entries:
        for e in entries:
            if (e.label or "").lower().startswith("package"):
                return float(e.current)
        cores = [e.current for e in entries if (e.label or "").lower().startswith("core")]
        if cores:
            return float(max(cores))
        return float(entries[0].current)

    for chip in ("k10temp", "zenpower"):
        entries = temps.get(chip)
        if entries:
            for wanted in ("tdie", "tctl"):
                for e in entries:
                    if (e.label or "").lower() == wanted:
                        return float(e.current)
            return float(entries[0].current)

    for chip in ("cpu_thermal", "cpu-thermal", "soc_thermal", "thinkpad", "acpitz"):
        entries = temps.get(chip)
        if entries:
            return float(max(e.current for e in entries))

    return _sensors_cli_temperature()


def cpu_frequency_mhz():
    try:
        freq = psutil.cpu_freq()
        if freq and freq.current:
            return float(freq.current)
    except Exception:
        pass

    try:
        vals = [
            float(m.group(1))
            for m in re.finditer(r"^cpu MHz\s*:\s*([\d.]+)", read_text("/proc/cpuinfo"), re.M)
        ]
        if vals:
            return sum(vals) / len(vals)
    except Exception:
        pass
    return None


def _natural_key(text):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", text)]


def _all_fans():
    """Minden ventilátor: [{'label': ..., 'value': RPM}] (sysfs, majd lm-sensors tartalék)."""
    fans = []

    for hw in sorted(glob.glob(os.path.join(HWMON_ROOT, "hwmon*")), key=_natural_key):
        chip = read_text(os.path.join(hw, "name"))
        for path in sorted(glob.glob(os.path.join(hw, "fan*_input")), key=_natural_key):
            m = re.search(r"fan(\d+)_input$", path)
            if not m:
                continue
            idx = m.group(1)
            try:
                value = float(int(read_text(path)))
            except Exception:
                continue
            label = read_text(os.path.join(hw, f"fan{idx}_label")).strip()
            fans.append({"label": (label or f"{chip} fan{idx}").lower(), "value": value})

    if fans:
        return fans

    out = sensors_text()
    for m in re.finditer(r"^([^:\n]+):\s+(\d+)\s*RPM", out, re.M | re.I):
        fans.append({"label": m.group(1).strip().lower(), "value": float(m.group(2))})
    return fans


def fan_values():
    """(CPU ventilátor, alaplapi/ház ventilátor) RPM-ben."""
    fans = _all_fans()
    if not fans:
        return None, None

    running = [f for f in fans if f["value"] > 0]

    cpu = next((f for f in fans if "cpu" in f["label"]), None)
    if cpu is None:
        cpu = running[0] if running else fans[0]

    mb = None
    for token in ("chassis", "system", "sys", "cha", "case"):
        for f in fans:
            if f is not cpu and token in f["label"]:
                mb = f
                break
        if mb:
            break
    if mb is None:
        mb = next((f for f in running if f is not cpu), None)
    if mb is None:
        mb = next((f for f in fans if f is not cpu), None)

    return cpu["value"], (mb["value"] if mb else None)


def _cmos_from_sysfs():
    """
    A CMOS/RTC elem feszültségszenzorának felismerése a /sys/class/hwmon alatt.

    Elsőként a név szerint jelölt vbat/cmos/rtc battery szenzorokat választja.
    Tartalék: a Nuvoton/ITE szuper-I/O chipeken szokásos in8 csatorna.
    """
    exact_names = {
        "vbat", "vbat voltage", "cmos", "cmos battery", "cmos battery voltage",
        "rtc battery", "rtc battery voltage", "bios battery",
        "bios battery voltage", "3v battery", "battery voltage",
    }
    strong_tokens = ("vbat", "cmos battery", "rtc battery", "bios battery")

    best = None
    for hw in sorted(glob.glob(os.path.join(HWMON_ROOT, "hwmon*")), key=_natural_key):
        chip = read_text(os.path.join(hw, "name")).lower()
        for path in sorted(glob.glob(os.path.join(hw, "in*_input"))):
            m = re.search(r"in(\d+)_input$", path)
            if not m:
                continue
            idx = m.group(1)
            label = read_text(os.path.join(hw, f"in{idx}_label")).strip().lower()

            try:
                volts = int(read_text(path)) / 1000.0
            except Exception:
                continue

            score = 0
            if label in exact_names:
                score = 120
            elif any(token in label for token in strong_tokens):
                score = 100
            elif "battery" in label and not any(t in label for t in ("gpu", "laptop", "ups")):
                score = 90
            elif idx == "8" and chip.startswith(("nct", "it87", "it86", "it85", "w83", "f71")):
                score = 70

            if score <= 0:
                continue

            if any(token in label for token in ("+3.3v", "3.3v", "3vsb", "avcc")) and "vbat" not in label:
                score -= 80

            if 2.4 <= volts <= 3.6:
                score += 5
            else:
                score -= 20

            if score > 0 and (best is None or score > best["score"]):
                best = {
                    "score": score,
                    "value": volts,
                    "label": label or f"in{idx}",
                    "id": f"{chip}/in{idx}",
                }

    return best


def _cmos_from_sensors_cli():
    """Tartalék: VBat / CMOS érték az lm-sensors kimenetéből."""
    out = sensors_text()
    if not out:
        return None

    names = ("vbat", "cmos", "rtc battery", "bios battery", "3v battery", "battery")
    fallback = None

    for block in re.split(r"\n\s*\n", out):
        lines = block.strip().splitlines()
        if not lines:
            continue
        chip = lines[0].strip().lower()
        for line in lines[1:]:
            m = re.match(r"^([^:\n]+):\s+\+?(-?\d+(?:\.\d+)?)\s*V\b", line.strip())
            if not m:
                continue
            label = m.group(1).strip().lower()
            volts = float(m.group(2))
            if not 2.4 <= volts <= 3.6:
                continue
            if any(label.startswith(n) for n in names):
                return {"value": volts, "label": m.group(1).strip(), "id": f"{chip}/{label}"}
            if label == "in8" and chip.startswith(("nct", "it87", "it86", "it85", "w83", "f71")):
                fallback = {"value": volts, "label": m.group(1).strip(), "id": f"{chip}/{label}"}

    return fallback


def cmos_battery_reading():
    return _cmos_from_sysfs() or _cmos_from_sensors_cli()


class CpuPowerReader:
    """CPU Package Power a RAPL számlálóból (ha az olvasható)."""

    def __init__(self):
        candidates = sorted(glob.glob("/sys/class/powercap/intel-rapl:[0-9]*/energy_uj"))
        candidates = [p for p in candidates if p.count("intel-rapl:") == 1 and p.split("intel-rapl:")[1].count(":") == 0]
        self.path = candidates[0] if candidates else None
        self.max_range = None
        self.prev = None
        if self.path:
            try:
                self.max_range = int(read_text(os.path.join(os.path.dirname(self.path), "max_energy_range_uj")))
            except Exception:
                self.max_range = None

    def read(self):
        if not self.path:
            return None
        try:
            energy = int(read_text(self.path))
        except Exception:
            return None

        now = time.monotonic()
        prev = self.prev
        self.prev = (now, energy)
        if prev is None:
            return None

        dt = now - prev[0]
        if dt <= 0.2:
            return None

        delta = energy - prev[1]
        if delta < 0:
            if not self.max_range:
                return None
            delta += self.max_range
        return delta / 1_000_000.0 / dt


def physical_memory_values():
    """Fizikai RAM adatai MB-ban: (használt, elérhető, teljes, terhelés %)."""
    try:
        vm = psutil.virtual_memory()
        total_mb = vm.total / (1024 ** 2)
        available_mb = vm.available / (1024 ** 2)
        used_mb = max(0.0, total_mb - available_mb)
        load = (used_mb / total_mb * 100.0) if total_mb > 0 else float(vm.percent)
        return used_mb, available_mb, total_mb, load
    except Exception:
        return None, None, None, None


# ---------------------------------------------------------------------------
# Meghajtók
# ---------------------------------------------------------------------------

def _base_disk(dev_name, depth=0):
    """Partícióhoz / LVM / LUKS kötethez tartozó fizikai lemez neve (pl. nvme0n1)."""
    sys_path = f"/sys/class/block/{dev_name}"
    if not os.path.exists(sys_path):
        return dev_name

    real = os.path.realpath(sys_path)
    if os.path.exists(os.path.join(real, "partition")):
        return os.path.basename(os.path.dirname(real))

    slaves = os.path.join(real, "slaves")
    if depth < 4 and os.path.isdir(slaves):
        try:
            subs = sorted(os.listdir(slaves))
        except OSError:
            subs = []
        if subs:
            return _base_disk(subs[0], depth + 1)

    return dev_name


def _filesystem_label(real_dev):
    by_label = "/dev/disk/by-label"
    try:
        for name in os.listdir(by_label):
            link = os.path.join(by_label, name)
            if os.path.realpath(link) == real_dev:
                return re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), name).strip()
    except OSError:
        pass
    return ""


def _disk_info(disk):
    """Fizikai lemez adatai a /sys alól."""
    info = {"model": "", "serial": "", "usb": False}
    sys_block = f"/sys/class/block/{disk}"
    if not os.path.exists(sys_block):
        return info

    real = os.path.realpath(sys_block)
    info["usb"] = "/usb" in real or read_text(f"/sys/block/{disk}/removable") == "1"

    dev = f"/sys/block/{disk}/device"
    vendor = read_text(os.path.join(dev, "vendor"))
    model = read_text(os.path.join(dev, "model"))
    info["model"] = " ".join(x for x in (vendor, model) if x).strip()
    info["serial"] = read_text(os.path.join(dev, "serial"))
    return info


def _skip_mount(mount):
    if mount.startswith("/run/media/"):
        return False
    for prefix in SKIP_MOUNT_PREFIXES:
        if mount == prefix or mount.startswith(prefix + "/"):
            return True
    return False


def connected_local_drives():
    by_device = {}

    for part in psutil.disk_partitions(all=False):
        device = part.device or ""
        mount = part.mountpoint or ""

        if not device.startswith("/dev/") or not mount:
            continue
        if device.startswith(("/dev/loop", "/dev/ram", "/dev/zram")):
            continue
        if part.fstype in PSEUDO_FS or _skip_mount(mount):
            continue

        real_dev = os.path.realpath(device)
        current = by_device.get(real_dev)
        if current is not None and len(current["mount"]) <= len(mount):
            continue

        try:
            psutil.disk_usage(mount)
        except Exception:
            continue

        disk = _base_disk(os.path.basename(real_dev))
        info = _disk_info(disk)

        by_device[real_dev] = {
            "mount": mount,
            "root": mount,
            "device": device,
            "disk": disk,
            "label": _filesystem_label(real_dev),
            "kind": "USB" if info["usb"] else "FIX",
            "physical_model": info["model"],
            "physical_serial": info["serial"],
        }

    return sorted(
        by_device.values(),
        key=lambda d: (0 if d["kind"] == "FIX" else 1, d["mount"] != "/", d["mount"]),
    )


def drive_temperature(drive):
    """Lemezhőfok °C-ban (NVMe, illetve SATA drivetemp modullal)."""
    disk = drive.get("disk") or ""
    if not disk:
        return None

    patterns = [
        f"/sys/block/{disk}/device/hwmon/hwmon*/temp1_input",
        f"/sys/block/{disk}/device/hwmon*/temp1_input",
    ]
    m = re.match(r"nvme(\d+)n\d+", disk)
    if m:
        patterns.append(f"/sys/class/nvme/nvme{m.group(1)}/hwmon*/temp1_input")

    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            try:
                return int(read_text(path)) / 1000.0
            except Exception:
                continue
    return None


_DISK_IO_CACHE = {"timestamp": 0.0, "counters": {}}


def physical_disk_io_since_boot_gb(drive):
    """Fizikai lemez I/O számlálói a rendszerindítás óta, GB-ban."""
    disk = drive.get("disk")
    if not disk:
        return None, None

    now = time.monotonic()
    if now - _DISK_IO_CACHE["timestamp"] > 1.0:
        try:
            _DISK_IO_CACHE["counters"] = psutil.disk_io_counters(perdisk=True) or {}
            _DISK_IO_CACHE["timestamp"] = now
        except Exception:
            return None, None

    counter = _DISK_IO_CACHE["counters"].get(disk)
    if counter is None:
        return None, None

    try:
        read_gb = float(counter.read_bytes) / (1024 ** 3)
    except Exception:
        read_gb = None
    try:
        write_gb = float(counter.write_bytes) / (1024 ** 3)
    except Exception:
        write_gb = None
    return read_gb, write_gb


# ---------------------------------------------------------------------------
# Felület
# ---------------------------------------------------------------------------

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
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(self.root)):
                try:
                    subprocess.Popen(["xdg-open", self.root])
                except Exception:
                    pass
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

    def __init__(self):
        super().__init__()

        self.power_reader = CpuPowerReader()
        self.external_ip = get_external_ip()
        self.wifi_ssid = "N/A"
        self.wifi_signal = 0
        self.tick = 0
        self._snap_active = False
        self._restoring_geometry = False
        self._net_prev = None

        self.settings = QSettings("gidano", "LinuxHardwareWidget")
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
        self.tray_menu = None
        self.tray_always_action = None
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

    # ----- nyelv -----

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
        self.retranslate_tray()

    def set_language(self, lang):
        if lang not in ("hu", "en") or self.language == lang:
            return
        # A menü bezárulása után hajtjuk végre, hogy ne épüljön át semmi a menü alatt.
        QTimer.singleShot(0, lambda l=lang: self._do_set_language(l))

    def _do_set_language(self, lang):
        if lang not in ("hu", "en") or self.language == lang:
            return
        self.language = lang
        self.settings.setValue("language", self.language)
        self.drive_signature = None
        self.apply_language()
        self.update_values()
        self.fit_height_to_content()

    # ----- elemek felépítése -----

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

    @staticmethod
    def drive_caption(drive):
        mount = drive["mount"]
        short = mount if len(mount) <= 14 else (os.path.basename(mount.rstrip("/")) or mount)
        caption = f"({short})"
        label = drive.get("label") or ""
        if label and label != short:
            caption += f" {label}"
        return caption

    def rebuild_drives_if_needed(self, drives):
        signature = tuple((d["mount"], d["kind"], d["label"]) for d in drives)
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
            mount = d["mount"]
            label = d["label"]

            caption = self.drive_caption(d)
            if d["kind"] == "USB":
                caption += f" {self.t('drive_type_usb')}"

            tooltip = self.t("open_in_fm", path=mount)
            if label:
                tooltip += f"  ({label})"

            key_label = ClickableDriveLabel(caption, d["root"], tooltip)

            value_label = DriveValueLabel("N/A", tooltip)
            value_label.setTextFormat(Qt.TextFormat.RichText)
            value_label.setObjectName("valueLabel")
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value_label.setFixedHeight(18)
            value_label.setToolTip(tooltip)

            self.drive_widgets[mount] = {"label": value_label, "key": key_label}

            self.drives_section.grid.addWidget(key_label, self.drives_section.row, 0)
            self.drives_section.grid.addWidget(value_label, self.drives_section.row, 1)
            self.drives_section.row += 1

            bar = DriveProgressBar(tooltip)
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(False)
            self.drive_widgets[mount]["bar"] = bar

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

    # ----- kis segédek -----

    def set_label(self, key, text):
        self.labels[key].setText(text)

    def set_label_color(self, key, color):
        if key in self.labels:
            self.labels[key].setStyleSheet(label_style(color))

    def set_bar_color(self, key, color):
        if key in self.bars:
            self.bars[key].setStyleSheet(bar_style(color))

    def set_drive_bar_color(self, mount, color):
        if mount in self.drive_widgets:
            self.drive_widgets[mount]["bar"].setStyleSheet(bar_style(color))

    def set_drive_tooltip(self, mount, text):
        widgets = self.drive_widgets.get(mount)
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

    # ----- automatikus indítás -----

    def autostart_path(self):
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        return os.path.join(base, "autostart", AUTOSTART_FILE)

    def launch_command(self):
        script_path = os.path.abspath(sys.argv[0])
        return f'"{sys.executable}" "{script_path}"'

    def is_startup_enabled(self):
        return os.path.exists(self.autostart_path())

    def set_startup_enabled(self, enabled):
        path = self.autostart_path()

        try:
            if enabled:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write("[Desktop Entry]\n")
                    f.write("Type=Application\n")
                    f.write("Name=Linux Hardware Widget\n")
                    f.write(f"Exec={self.launch_command()}\n")
                    f.write("Terminal=false\n")
                    f.write("X-GNOME-Autostart-enabled=true\n")
            else:
                if os.path.exists(path):
                    os.remove(path)
        except Exception as e:
            QMessageBox.warning(
                self,
                self.t("startup_error_title"),
                self.t("startup_error_body", error=e),
            )

        self.startup_enabled = self.is_startup_enabled()
        self.settings.setValue("startup_enabled", self.startup_enabled)

    # ----- beállítások -----

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
        parent = parent or self
        menu = QMenu(self.t("menu_language"), parent)
        group = QActionGroup(menu)
        group.setExclusive(True)
        for code, key in (("hu", "lang_hu"), ("en", "lang_en")):
            action = QAction(self.t(key), menu)
            action.setCheckable(True)
            action.setChecked(self.language == code)
            group.addAction(action)
            action.triggered.connect(lambda checked=False, c=code: self.set_language(c))
            menu.addAction(action)
        return menu

    def setup_tray(self):
        if self.tray is not None:
            self.retranslate_tray()
            return
        if not self.tray_enabled or not QSystemTrayIcon.isSystemTrayAvailable():
            return

        icon = self.app_icon
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

        self.tray = QSystemTrayIcon(icon, self)

        # A tálcamenü egyszer épül fel, és végig él (nem épül újra nyelvváltáskor).
        menu = QMenu(self)
        self.tray_menu = menu

        self.tray_show_action = QAction(menu)
        self.tray_show_action.triggered.connect(self.toggle_visible_from_tray)

        self.tray_always_action = QAction(menu)
        self.tray_always_action.setCheckable(True)
        self.tray_always_action.setChecked(self.always_on_top)
        self.tray_always_action.toggled.connect(self.set_always_on_top)

        self.tray_pos_menu = QMenu(menu)
        self.tray_pos_actions = []
        for key in ("top_left", "top_right", "bottom_left", "bottom_right",
                    "left_center", "right_center", "center"):
            act = QAction(self.tray_pos_menu)
            act.triggered.connect(lambda checked=False, k=key: self.move_to_position(k))
            self.tray_pos_menu.addAction(act)
            self.tray_pos_actions.append((act, "menu_" + key))

        self.tray_lang_menu = self.build_language_menu(menu)

        self.tray_exit_action = QAction(menu)
        self.tray_exit_action.triggered.connect(QApplication.quit)

        menu.addAction(self.tray_show_action)
        menu.addSeparator()
        menu.addAction(self.tray_always_action)
        menu.addMenu(self.tray_pos_menu)
        menu.addMenu(self.tray_lang_menu)
        menu.addSeparator()
        menu.addAction(self.tray_exit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.retranslate_tray()
        self.tray.show()

    def retranslate_tray(self):
        if self.tray is None:
            return
        self.tray.setToolTip(self.t("tray_tooltip"))
        self.tray_show_action.setText(self.t("menu_show_hide"))
        self.tray_always_action.setText(self.t("menu_always_on_top"))
        self.tray_pos_menu.setTitle(self.t("menu_position"))
        for act, key in self.tray_pos_actions:
            act.setText(self.t(key))
        self.tray_lang_menu.setTitle(self.t("menu_language"))
        for act, key, code in zip(self.tray_lang_menu.actions(), ("lang_hu", "lang_en"), ("hu", "en")):
            act.setText(self.t(key))
            act.setChecked(self.language == code)
        self.tray_exit_action.setText(self.t("menu_exit"))

    def sync_tray_always_on_top(self):
        action = self.tray_always_action
        if action is None:
            return
        action.blockSignals(True)
        action.setChecked(self.always_on_top)
        action.blockSignals(False)

    def on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.toggle_visible_from_tray()

    def update_status_line(self, alerts=None):
        alerts = alerts or []
        self.last_alerts = alerts

        extras = []
        if self.udp_enabled:
            extras.append(self.t("status_udp"))
        if not self.always_on_top:
            extras.append(self.t("status_always_on_top_inactive"))

        if self.alerts_enabled and alerts:
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

    # ----- buborékok -----

    def build_cpu_tooltip(self, cpu_temp, cpu_usage, cpu_clock, cpu_fan, mb_fan, cpu_power):
        na = self.t("not_available")

        def with_unit(value, decimals, unit):
            return f"{value:.{decimals}f} {unit}" if value is not None else na

        text = (
            self.t("cpu_tip_temp", value=with_unit(cpu_temp, 0, "°C")) + "\n"
            + self.t("cpu_tip_usage", value=with_unit(cpu_usage, 1, "%")) + "\n"
            + self.t("cpu_tip_clock", value=with_unit(cpu_clock, 0, "MHz")) + "\n"
            + self.t("cpu_tip_cpu_fan", value=with_unit(cpu_fan, 0, "rpm")) + "\n"
            + self.t("cpu_tip_mb_fan", value=with_unit(mb_fan, 0, "rpm")) + "\n"
            + self.t("cpu_tip_power", value=with_unit(cpu_power, 1, "W"))
        )
        if cpu_temp is None or (cpu_fan is None and mb_fan is None):
            chips = ", ".join(hwmon_chip_names()) or na
            text += (
                "\n\n" + self.t("sensor_missing_1") + "\n" + self.t("sensor_missing_2")
                + "\n" + self.t("sensor_chips", value=chips)
            )
        return text

    def drive_extra_tooltip(self, drive, used_gb, total_gb, pct, temp):
        boot_reads, boot_writes = physical_disk_io_since_boot_gb(drive)

        label = drive.get("label") or ""
        model = drive.get("physical_model") or ""
        lines = [
            f"{self.t('drive_label')}: {drive['mount']} {label}".rstrip(),
            f"{self.t('drive_type')}: {self.t('drive_type_usb') if drive.get('kind') == 'USB' else self.t('drive_type_fixed')}",
            f"{self.t('drive_device')}: {drive.get('device', '')}",
        ]
        if model:
            lines.append(f"{self.t('drive_physical')}: {model}")
        lines.extend(
            [
                f"{self.t('drive_used')}: {used_gb:.1f} GB",
                f"{self.t('drive_total')}: {total_gb:.1f} GB",
                f"{self.t('drive_usage')}: {pct:.1f} %",
                f"{self.t('drive_temp')}: {temp:.0f} °C" if temp is not None else f"{self.t('drive_temp')}: {self.t('not_available')}",
            ]
        )

        lines.append(
            f"{self.t('host_writes_boot')}: {boot_writes:.2f} GB" if boot_writes is not None
            else f"{self.t('host_writes_boot')}: {self.t('not_available')}"
        )
        lines.append(
            f"{self.t('host_reads_boot')}: {boot_reads:.2f} GB" if boot_reads is not None
            else f"{self.t('host_reads_boot')}: {self.t('not_available')}"
        )

        lines.append(self.t("drive_open_hint"))
        return "\n".join(lines)

    # ----- hálózati sebesség -----

    def network_rates(self):
        """(letöltés, feltöltés) KB/s-ban."""
        counters = network_counters()
        now = time.monotonic()
        if counters is None:
            return None, None

        prev = self._net_prev
        self._net_prev = (now, counters[0], counters[1])
        if prev is None:
            return None, None

        dt = now - prev[0]
        if dt <= 0:
            return None, None

        down = max(0.0, (counters[0] - prev[1]) / dt / 1024.0)
        up = max(0.0, (counters[1] - prev[2]) / dt / 1024.0)
        return down, up

    # ----- frissítés -----

    def update_values(self):
        self.tick += 1

        cpu_temp = cpu_temperature()
        cpu_usage = psutil.cpu_percent(interval=None)
        cpu_clock = cpu_frequency_mhz()
        cpu_fan, mb_fan = fan_values()
        cmos = cmos_battery_reading()
        cmos_voltage = cmos["value"] if cmos else None
        cpu_power = self.power_reader.read()
        ram_used_mb, ram_avail_mb, ram_total_mb, ram_load = physical_memory_values()
        net_down, net_up = self.network_rates()

        if self.show_network and (self.tick == 1 or self.tick % 5 == 0):
            self.wifi_ssid, self.wifi_signal = get_wifi_info()

        drives = connected_local_drives()
        if self.usb_only:
            drives = [d for d in drives if d["kind"] == "USB"]
        self.rebuild_drives_if_needed(drives)

        internal_ip = get_internal_ip()

        if cpu_temp is not None:
            self.set_label("cpu_temp", colored_span(f"{cpu_temp:.0f}°C", temp_color(cpu_temp, "cpu")))
        else:
            self.set_label("cpu_temp", colored_span("N/A", "#b0b0b0"))
        self.set_label("cpu_usage", colored_span(f"{fmt(cpu_usage, 1)}%", usage_text_color(cpu_usage)))
        self.set_label("cpu_clock", f"{cpu_clock:.0f} MHz" if cpu_clock is not None else "N/A")
        for key, val, is_cpu in (("cpu_fan", cpu_fan, True), ("mb_fan", mb_fan, False)):
            text = f"{val:.0f} rpm" if val is not None else "N/A"
            color = fan_color(val, is_cpu)
            self.set_label(key, colored_span(text, color) if color else text)
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
                f"{self.t('source')}: {self.t('source_linux_memory')}"
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
            cmos_tip = (
                f"{self.t('cmos_battery')}: {cmos_voltage:.3f} V\n"
                f"{self.t('source')}: {cmos['label']}\n"
                f"{self.t('identifier')}: {cmos['id']}"
                + f"\n\n{self.t('coloring')}:\n"
                + self.t("green_threshold") + "\n"
                + self.t("orange_threshold") + "\n"
                + self.t("red_threshold")
            )
        else:
            self.set_label("cmos", colored_span("N/A", "#b0b0b0"))
            cmos_tip = (
                self.t("cmos_missing_1") + "\n" + self.t("cmos_missing_2") + "\n"
                + self.t("sensor_chips", value=", ".join(hwmon_chip_names()) or self.t("not_available"))
            )
        self.labels["cmos"].setToolTip(cmos_tip)

        drive_alerts = []
        for drive in drives:
            mount = drive["mount"]
            if mount not in self.drive_widgets:
                continue

            temp = drive_temperature(drive)
            try:
                du = psutil.disk_usage(drive["root"])
                used_gb = du.used / (1024 ** 3)
                total_gb = du.total / (1024 ** 3)
                pct = du.percent
                pct_text = colored_span(f"{pct:.0f}%", usage_text_color(pct))
                temp_text = (
                    colored_span(f"{temp:.0f}°C", temp_color(temp, "drive"))
                    if temp is not None
                    else '<span style="color:#b0b0b0;">N/A</span>'
                )
                rich_text = f"{pct_text}   {used_gb:.1f}/{total_gb:.1f} GB   {temp_text}"
                drive_tip = self.drive_extra_tooltip(drive, used_gb, total_gb, pct, temp)
                if pct >= 90:
                    drive_alerts.append(self.t("alert_drive_full", mount=mount, value=f"{pct:.0f}%"))
            except Exception:
                rich_text = self.t("no_drive")
                drive_tip = self.t("drive_unavailable", mount=mount)
                pct = 0

            if temp is not None and temp >= 60:
                drive_alerts.append(self.t("alert_drive_hot", mount=mount, value=f"{temp:.0f}°C"))

            # Csak a százalék és a hőfok színes. A kapacitás szövege semleges marad.
            self.drive_widgets[mount]["label"].setText(rich_text)
            self.drive_widgets[mount]["label"].setStyleSheet(neutral_label_style())
            self.set_drive_tooltip(mount, drive_tip)

            # A csík továbbra is a telítettséget jelzi.
            self.drive_widgets[mount]["bar"].setValue(max(0, min(100, int(round(pct)))))
            self.set_drive_bar_color(mount, usage_color(pct))

        self.set_label("external_ip", self.external_ip)
        self.set_label("internal_ip", internal_ip)
        self.set_label("ssid", self.wifi_ssid)
        if self.wifi_ssid == "N/A":
            self.set_label("signal", self.t("not_available"))
        else:
            sig_text = f"{self.wifi_signal}%"
            sig_color = signal_color(self.wifi_signal)
            self.set_label("signal", colored_span(sig_text, sig_color) if sig_color else sig_text)
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
        alerts.extend(drive_alerts)

        self.update_status_line(alerts)

        payload_items = {
            "ver": "pywidget-linux-v1",
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

    # ----- ablak viselkedés -----

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
            # Wayland alatt is működő, rendszer általi mozgatás.
            handle = self.windowHandle()
            if handle is not None:
                try:
                    if handle.startSystemMove():
                        event.accept()
                        return
                except Exception:
                    pass
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
        self.sync_tray_always_on_top()

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

        always_action = QAction(self.t("menu_always_on_top"), menu)
        always_action.setCheckable(True)
        always_action.setChecked(self.always_on_top)
        always_action.toggled.connect(self.set_always_on_top)

        frameless_action = QAction(self.t("menu_frameless"), menu)
        frameless_action.setCheckable(True)
        frameless_action.setChecked(self.frameless_mode)
        frameless_action.toggled.connect(self.set_frameless_mode)

        network_action = QAction(self.t("menu_show_network"), menu)
        network_action.setCheckable(True)
        network_action.setChecked(self.show_network)
        network_action.toggled.connect(self.set_show_network)

        drives_action = QAction(self.t("menu_show_drives"), menu)
        drives_action.setCheckable(True)
        drives_action.setChecked(self.show_drives)
        drives_action.toggled.connect(self.set_show_drives)

        usb_only_action = QAction(self.t("menu_usb_only"), menu)
        usb_only_action.setCheckable(True)
        usb_only_action.setChecked(self.usb_only)
        usb_only_action.toggled.connect(self.set_usb_only)

        compact_action = QAction(self.t("menu_compact"), menu)
        compact_action.setCheckable(True)
        compact_action.setChecked(self.compact_mode)
        compact_action.toggled.connect(self.set_compact_mode)

        alerts_action = QAction(self.t("menu_alerts"), menu)
        alerts_action.setCheckable(True)
        alerts_action.setChecked(self.alerts_enabled)
        alerts_action.toggled.connect(self.set_alerts_enabled)

        udp_action = QAction(self.t("menu_udp"), menu)
        udp_action.setCheckable(True)
        udp_action.setChecked(self.udp_enabled)
        udp_action.toggled.connect(self.set_udp_enabled)

        startup_action = QAction(self.t("menu_startup"), menu)
        startup_action.setCheckable(True)
        startup_action.setChecked(self.is_startup_enabled())
        startup_action.toggled.connect(self.set_startup_enabled)

        hide_action = QAction(self.t("menu_hide_to_tray"), menu)
        hide_action.triggered.connect(self.hide)

        refresh_ip_action = QAction(self.t("menu_refresh_ip"), menu)
        refresh_ip_action.triggered.connect(self.refresh_external_ip)

        reset_action = QAction(self.t("menu_reset_size"), menu)
        reset_action.triggered.connect(self.reset_size)

        exit_action = QAction(self.t("menu_exit"), menu)
        exit_action.triggered.connect(QApplication.quit)

        opacity_menu = QMenu(self.t("menu_opacity"), menu)
        for label, value in (("100%", 1.0), ("90%", 0.90), ("75%", 0.75), ("60%", 0.60)):
            act = QAction(label, menu)
            act.setCheckable(True)
            act.setChecked(abs(self.opacity_value - value) < 0.01)
            act.triggered.connect(lambda checked=False, v=value: self.set_opacity_value(v))
            opacity_menu.addAction(act)

        pos_menu = QMenu(self.t("menu_position"), menu)
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
            act = QAction(title, menu)
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
        # Tálcaikon nélkül (pl. GNOME kiegészítő nélkül) az elrejtett widget nem hozható vissza.
        if self.tray is not None:
            menu.addAction(hide_action)
        menu.addAction(exit_action)
        menu.exec(event.globalPos())
        menu.deleteLater()

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
    prefer_x11_if_wayland()
    app = QApplication(sys.argv)
    app.setApplicationName("Linux Hardware Widget")
    app.setQuitOnLastWindowClosed(False)

    font = QFont()
    font.setFamilies(["Ubuntu", "Noto Sans", "DejaVu Sans"])
    font.setPointSize(8)
    app.setFont(font)

    app_icon = load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    # A CPU-terhelés első mérése mindig 0, ezért előre "bemelegítjük".
    psutil.cpu_percent(interval=None)

    win = WidgetWindow()
    win.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
