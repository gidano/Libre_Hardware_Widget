# Libre Hardware Monitor & Widget Setup Guide

[Magyar (HU)](#magyar) | [English (EN)](#english)

---

</div>

<p align="center">
  <img src="https://github.com/gidano/Libre_Hardware_Widget/blob/main/Libre%20Widget/Photos/Libre%20Widget.png" width="345">
</p>

<a name="magyar"></a>
## 🇭🇺 Magyar

### Libre Hardware Monitor használata
1. **Kicsomagolás és indítás:**  
   A [LibreHardwareMonitor](https://github.com/LibreHardwaRemonitor/LibreHardwareMonitor) hordozható (portable) formátumban, könyvtárral együtt van csomagolva. Bontsd ki egy tetszőleges helyre, majd indítsd el a programot.

2. **Webszerver beállítása:**  
   - Nyisd meg a menüben az **Options -> Remote Web Server -> Interface / Port** opciót, és állítsd be a kívánt IP-címet.
   - A port maradhat az alapértelmezett értéken (ha szabad).
   - Lépj vissza egy szintet, majd a **Run** gombra kattintva indítsd el a webszervert.

3. **Alapvető opciók:**  
   Az **Options** menüben az első 4 lehetőséget ajánlott bepipálni (*Start Minimized, Minimize To Tray, Minimize On Close, Run On Windows Startup*).

![Libre Hardware Monitor Beállítások](IMAGE_URL_1_HERE)

---

### Libre Hardware Widget
- Futtatható a `Libre Widget v0.1.6.exe` fájl.
- A forráskódot is mellékeltem (`libre_widget.py`), ha esetleg módosítani szeretnéd a működését.

![Libre Hardware Widget Menü](IMAGE_URL_2_HERE)

### Automatikus indítás (Windows Startup)
- A **Libre Hardware Monitor** automatikus indítását az **Options** menüben már engedélyezted.
- A **Libre Widget** esetében kattints a widgetre a jobb egérgombbal, majd válaszd az **Indítás Windows-al** (*Start with system*) opciót.

> **Megjegyzés (Hibaelhárítás):**  
> Ha az automatikus indítás makacskodna:
> 1. Módosítsd az útvonalat a `Libre_Widget.cmd` fájlban.
> 2. Mentés után másold át a fájlt a következő indítómappába:  
>    `C:\Users\<felhasználónév>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\`

Használd örömmel! 😁

---

<a name="english"></a>
## 🇬🇧 English

### Using Libre Hardware Monitor
1. **Extraction and Launch:**  
   LibreHardwareMonitor comes packaged as a portable folder. Extract it to your preferred location and launch the executable.

2. **Remote Web Server Setup:**  
   - Go to **Options -> Remote Web Server -> Interface / Port** and set your desired IP address.
   - Leave the port as default (if available).
   - Go back one level and click **Run** to start the web server.

3. **Recommended Options:**  
   In the **Options** menu, enable the first 4 options (*Start Minimized, Minimize To Tray, Minimize On Close, Run On Windows Startup*).

![Libre Hardware Monitor Settings](IMAGE_URL_1_HERE)

---

### Libre Hardware Widget
- You can directly run the `Libre Widget v0.1.6.exe` file.
- The Python source code (`libre_widget.py`) is also included if you need to make any modifications.

![Libre Hardware Widget Menu](IMAGE_URL_2_HERE)

### Autostart Setup (Windows Startup)
- **Libre Hardware Monitor:** Already set to start automatically via its **Options** menu.
- **Libre Widget:** Right-click on the running widget and check **Start with system**.

> **Note (Troubleshooting):**  
> If the widget autostart fails to work properly:
> 1. Edit the path inside `Libre_Widget.cmd`.
> 2. Save and place the file into your Windows Startup folder:  
>    `C:\Users\<username>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\`

Enjoy using it! 😁
