# <div style="text-align: center; color: #60a5fa; font-family: sans-serif; padding: 10px 0; border-bottom: 2px solid #3b82f6;">Libre Hardware Widget</div>

<div style="text-align: center; font-size: 1.1em; color: #94a3b8; font-family: sans-serif; margin-bottom: 25px;">
  <b>Teljes Műszaki Doku / Full Technical Documentation & Feature List</b>
</div>

---

## <span style="color: #60a5fa;">1. Magyar Nyelvű Leírás (Hungarian)</span>

### <span style="color: #38bdf8;">Összefoglaló és Architektúra</span>
A **Libre Hardware Widget** egy Python (PySide6 / Qt) alapú, asztali rendszermonitorozó kisalkalmazás (widget), amely a Libre Hardware Monitor (HTTP JSON webszerver vagy WMI interfész) adatait, valamint a Windows rendszerszintű API-jait (`ctypes`, `psutil`, `PowerShell`, `netsh`) ötvözi. Modern, sötét tónusú, testreszabható felületen jelenít meg valós idejű hardver- és hálózati diagnosztikai adatokat.

<div style="background-color: #1e293b; border-left: 4px solid #3b82f6; padding: 12px 16px; margin: 15px 0; border-radius: 0 8px 8px 0; color: #e2e8f0;">
  <b style="color: #60a5fa;">Működési elv és Adatforrások:</b>
  <ul style="margin-top: 8px; margin-bottom: 0;">
    <li><b>Libre Hardware Monitor csatlakozás:</b> Elsődlegesen a helyi HTTP JSON végpontot (<code>http://127.0.0.1:8085/data.json</code>) használja, tartalékként WMI / COM interfészt (<code>root\LibreHardwareMonitor</code>) vagy PowerShell CIM lekérdezést.</li>
    <li><b>Fail-safe működés:</b> Ha a Libre Hardware Monitor leáll, a widget automatikusan átvált <span style="color: #f87171; font-weight: bold;">LIBRE OFF</span> módba, és a natív Windows API-kból elérhető adatokat továbbra is frissíti fagyás nélkül.</li>
    <li><b>RAM adatok:</b> A pontos érték érdekében közvetlenül a Windows <code>GlobalMemoryStatusEx</code> API-t hívja meg <code>ctypes</code> segítségével (tartalékként <code>psutil.virtual_memory()</code>).</li>
    <li><b>Meghajtók feltérképezése:</b> A <code>Win32_DiskDrive</code>, <code>Win32_DiskPartition</code> és <code>Win32_LogicalDiskToPartition</code> CIM lekérdezésekkel kapcsolja össze a logikai betűjeleket (C:, D:, stb.) a fizikai lemezek típusaival, sorozatszámaival és modelljeivel (30 másodperces gyorsítótárazással).</li>
    <li><b>I/O számlálók:</b> Boot óta mért lemezolvasás és -írás a <code>psutil.disk_io_counters(perdisk=True)</code> segítségével.</li>
    <li><b>Wi-Fi adatok:</b> A <code>netsh wlan show interfaces</code> parancs kinyert adatai alapján (SSID és jelerősség).</li>
  </ul>
</div>

---

### <span style="color: #38bdf8;">Fő funkciók és Kijelzett Hardveres Adatok</span>

#### <span style="color: #818cf8;">A. CPU és Alaplap (CPU-RAM szekció)</span>

<table style="width: 100%; border-collapse: collapse; background-color: #0f172a; color: #f8fafc; margin: 15px 0; font-family: sans-serif; font-size: 0.95em;">
  <thead>
    <tr style="background-color: #1e293b; color: #38bdf8; text-align: left; border-bottom: 2px solid #334155;">
      <th style="padding: 10px;">Metrika</th>
      <th style="padding: 10px;">Leírás</th>
      <th style="padding: 10px;">Szabályok és Színkódok</th>
    </tr>
  </thead>
  <tbody>
    <tr style="border-bottom: 1px solid #1e293b;">
      <td style="padding: 8px 10px; font-weight: bold; color: #f43f5e;">CPU Hőmérséklet</td>
      <td style="padding: 8px 10px;">Core Max / CPU Package hőfok (°C)</td>
      <td style="padding: 8px 10px;">
        <span style="color: #4ade80;">● &lt; 65°C Zöld</span> | 
        <span style="color: #fbbf24;">● 65–79°C Narancs</span> | 
        <span style="color: #f87171;">● &ge; 80°C Piros</span>
      </td>
    </tr>
    <tr style="border-bottom: 1px solid #1e293b; background-color: #111827;">
      <td style="padding: 8px 10px; font-weight: bold; color: #f59e0b;">CPU Terhelés</td>
      <td style="padding: 8px 10px;">Százalékos használat (%)</td>
      <td style="padding: 8px 10px;">
        <span style="color: #4ade80;">● &lt; 75% Zöld</span> | 
        <span style="color: #fbbf24;">● 75–89% Narancs</span> | 
        <span style="color: #f87171;">● &ge; 90% Piros</span>
      </td>
    </tr>
    <tr style="border-bottom: 1px solid #1e293b;">
      <td style="padding: 8px 10px; font-weight: bold;">CPU Órajel</td>
      <td style="padding: 8px 10px;">Átlagos effektív magórajel MHz-ben</td>
      <td style="padding: 8px 10px; color: #94a3b8;">Folyamatos érték kijelzés</td>
    </tr>
    <tr style="border-bottom: 1px solid #1e293b; background-color: #111827;">
      <td style="padding: 8px 10px; font-weight: bold;">Ventilátorok (RPM)</td>
      <td style="padding: 8px 10px;">CPU hűtő és Chassis/System ventilátor fordulatszám</td>
      <td style="padding: 8px 10px; color: #94a3b8;">Valós idejű RPM érték</td>
    </tr>
    <tr style="border-bottom: 1px solid #1e293b;">
      <td style="padding: 8px 10px; font-weight: bold; color: #38bdf8;">RAM Használat</td>
      <td style="padding: 8px 10px;">Használt / Teljes GB érték és százalék</td>
      <td style="padding: 8px 10px; color: #94a3b8;">Dinamikus folyamatjelző sáv (QProgressBar)</td>
    </tr>
    <tr style="border-bottom: 1px solid #1e293b; background-color: #111827;">
      <td style="padding: 8px 10px; font-weight: bold; color: #10b981;">BIOS / CMOS Elem</td>
      <td style="padding: 8px 10px;">VBAT / CMOS / RTC elem feszültség (V)</td>
      <td style="padding: 8px 10px;">
        <span style="color: #4ade80;">● &ge; 2.95V Zöld</span> | 
        <span style="color: #fbbf24;">● 2.80–2.94V Narancs</span> | 
        <span style="color: #f87171;">● &lt; 2.80V Piros</span>
      </td>
    </tr>
  </tbody>
</table>

- **Tooltip funkció:** A CPU szekcióra mutatva felbukkanó ablakban megjelenik a **CPU Package Power** (fogyasztás Wattban).

---

#### <span style="color: #818cf8;">B. Meghajtók (MEGHAJTÓK szekció)</span>

<div style="background-color: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 15px; margin: 15px 0;">
  <h4 style="margin-top: 0; color: #f59e0b;">Kijelzett adatok és interakciók:</h4>
  <ul>
    <li><b>Logikai betűjel és kötetcímke:</b> pl. <code>(C:) Rendszer</code>, <code>(D:) Adat USB</code></li>
    <li><b>Telítettség és Hőmérséklet:</b> Használt / Teljes kapacitás GB-ban és százalékban, Hőmérséklet (°C) színkóddal:
      <br/>
      <span style="color: #4ade80;">● &lt; 50°C (Zöld)</span> &nbsp;|&nbsp;
      <span style="color: #fbbf24;">● 50–59°C (Narancs)</span> &nbsp;|&nbsp;
      <span style="color: #f87171;">● &ge; 60°C (Piros)</span>
    </li>
    <li><b>Százalékos telítettség sáv:</b> Vizuális folyamatjelző sáv (<code>QProgressBar</code>).</li>
    <li><b>Kattintási interakció (Fájlkezelő):</b> Bármelyik meghajtó nevére vagy sorára kattintva a gyökérmappa (<code>C:\</code>, <code>D:\</code>) azonnal megnyílik a <b>Windows Fájlkezelőben</b> (<code>os.startfile</code> / <code>explorer.exe</code>).</li>
    <li><b>Gazdag Hover Tooltip:</b> Csatlakozás típusa (Fix belső lemez / Cserélhető USB), Fizikai lemez pontos gyári modellneve és sorozatszáma, SSD hátralévő élettartam (Remaining Life %), Összes írt adatmennyiség (Host Writes GB), Összes olvasott adatmennyiség (Host Reads GB), SMART figyelmeztetések és meghibásodási státuszok (Drive Warning / Drive Failure: YES/NO).</li>
  </ul>
</div>

---

#### <span style="color: #818cf8;">C. Hálózat (HÁLÓZAT szekció)</span>

<div style="display: table; width: 100%; table-layout: fixed; margin: 15px 0;">
  <div style="display: table-cell; background-color: #1e293b; padding: 12px; border-radius: 6px; border: 1px solid #334155;">
    <span style="color: #38bdf8; font-weight: bold;">Külső & Belső IP</span><br/>
    <span style="font-size: 0.9em; color: #cbd5e1;">Public IP (<code>api.ipify.org</code>) és helyi LAN IP cím.</span>
  </div>
  <div style="display: table-cell; width: 10px;"></div>
  <div style="display: table-cell; background-color: #1e293b; padding: 12px; border-radius: 6px; border: 1px solid #334155;">
    <span style="color: #38bdf8; font-weight: bold;">Wi-Fi Infó</span><br/>
    <span style="font-size: 0.9em; color: #cbd5e1;">Vezeték nélküli hálózat neve (SSID) és jelerőssége (%).</span>
  </div>
  <div style="display: table-cell; width: 10px;"></div>
  <div style="display: table-cell; background-color: #1e293b; padding: 12px; border-radius: 6px; border: 1px solid #334155;">
    <span style="color: #38bdf8; font-weight: bold;">Hálózati Sebesség</span><br/>
    <span style="font-size: 0.9em; color: #cbd5e1;">Download / Upload sebesség. 1000 KB/s felett aut. <b style="color: #4ade80;">MB/s</b> kijelzés.</span>
  </div>
</div>

---

### <span style="color: #38bdf8;">Felhasználói Felület (GUI) és Kényelmi Funkciók</span>
- **Fejléc nélküli Widget Mód (Frameless):** A tálca/jobb-klikk menüből kikapcsolható a hagyományos Windows ablakkeret. Ekkor egy kompakt, lekerekített sarokrendszerű widgetté alakul, amit az egérrel bárhová át lehet húzni az asztalon.
- **Egyedi SizeGrip:** Fejléc nélküli módban a jobb alsó sarokban egyedi átméretező fogantyú jelenik meg.
- **Mindig felül (Always on Top):** Rögzíthető az ablak más alkalmazások felett.
- **Képernyő-szélhez igazítás (Snap to Edges):** Elmozdítás után automatikusan a képernyő legközelebbi széléhez/sarkához igazodik (top-left, top-right, bottom-left, bottom-right, center, stb.).
- **Átlátszóság (Opacity):** Beállítható ablak-átlátszóság.
- **Rendszertálca (System Tray) integráció:** Tálcaikon kontextusmenüvel (Elrejtés/Megjelenítés, Pozicionálás, Nyelvválasztás, Kilépés). Dupla kattintásra elrejti / előhozza a widgetet.
- **Kompakt mód & Szekció elrejtés:** Külön-külön ki/be kapcsolható a Hálózat és a Meghajtók szekció, vagy beállítható a *Csak USB meghajtók* nézet.
- **Többnyelvűség (HU / EN):** Futás közben azonnal átváltható felületi nyelv (újraindítás nélkül).
- **Automatikus indítás (Startup with System):** Egy kattintással beállítható a Windows Indítópultba (`.cmd` szkript generálásával).

---

### <span style="color: #38bdf8;">Riasztások és ESP32 / Hardware Kijelző Integráció</span>

<div style="background-color: #1e1b4b; border-left: 4px solid #6366f1; padding: 12px 16px; margin: 15px 0; border-radius: 0 8px 8px 0; color: #e0e7ff;">
  <b style="color: #a5b4fc;">Riasztások és UDP Broadcast Engine:</b>
  <ul style="margin-top: 8px; margin-bottom: 0;">
    <li><b>Vizuális Riasztások (Status Line):</b> Magas CPU hőfok / terhelés riasztás, kritikusan alacsony RAM szabad kapacitás, gyenge CMOS elem feszültség riasztás, megtelt / túlmelegedett lemez figyelmeztetés.</li>
    <li><b>UDP Broadcast küldés (ESP32 Smart Display support):</b> A widget képes a mért adatokat egyetlen tömörített szöveges füzérben (<code>ver=pywidget-libre-v1;cpu=...;cput=...;ip=...;down=...;up=...</code>) folyamatosan sugározni a helyi hálózaton (UDP broadcast port 4210). Ez közvetlenül meghajthat külső ESP32/Arduino alapú TFT vagy OLED kijelzőket.</li>
  </ul>
</div>

---

<br/>
<hr style="border: 1px solid #334155; margin: 30px 0;"/>
<br/>

## <span style="color: #60a5fa;">2. English Description</span>

### <span style="color: #38bdf8;">Overview & Architecture</span>
**Libre Hardware Widget** is a lightweight Python-based desktop monitoring widget built with PySide6 (Qt). It aggregates system telemetry from Libre Hardware Monitor (via HTTP JSON web server or WMI interface) and native Windows APIs (`ctypes`, `psutil`, `PowerShell`, `netsh`). It features a sleek, customizable dark UI delivering real-time hardware diagnostics and network performance metrics.

<div style="background-color: #1e293b; border-left: 4px solid #3b82f6; padding: 12px 16px; margin: 15px 0; border-radius: 0 8px 8px 0; color: #e2e8f0;">
  <b style="color: #60a5fa;">Operating Principle & Data Sources:</b>
  <ul style="margin-top: 8px; margin-bottom: 0;">
    <li><b>Libre Hardware Monitor Connection:</b> Primarily uses local HTTP JSON endpoint (<code>http://127.0.0.1:8085/data.json</code>), with fallback to WMI / COM interface (<code>root\LibreHardwareMonitor</code>) or PowerShell CIM queries.</li>
    <li><b>Fail-safe Operation:</b> If Libre Hardware Monitor closes or stops running, the widget automatically switches to <span style="color: #f87171; font-weight: bold;">LIBRE OFF</span> mode, continuing to update data from native Windows OS APIs without freezing.</li>
    <li><b>RAM Telemetry:</b> Directly invokes the Windows <code>GlobalMemoryStatusEx</code> API via <code>ctypes</code> for true usable physical memory values (with <code>psutil.virtual_memory()</code> as fallback).</li>
    <li><b>Disk Mapping:</b> Associates drive letters (C:, D:, etc.) with physical hardware drive models, serial numbers, and bus interfaces using <code>Win32_DiskDrive</code>, <code>Win32_DiskPartition</code>, and <code>Win32_LogicalDiskToPartition</code> CIM queries (cached for 30s).</li>
    <li><b>I/O Counters:</b> Monitors lifetime / boot-time read and write counters via <code>psutil.disk_io_counters(perdisk=True)</code>.</li>
    <li><b>Wi-Fi Telemetry:</b> Extracts SSID and signal quality percentage via <code>netsh wlan show interfaces</code> subprocess calls.</li>
  </ul>
</div>

---

### <span style="color: #38bdf8;">Core Features & Kinds of Metrics</span>

#### <span style="color: #818cf8;">A. CPU & Motherboard (CPU-RAM Section)</span>

<table style="width: 100%; border-collapse: collapse; background-color: #0f172a; color: #f8fafc; margin: 15px 0; font-family: sans-serif; font-size: 0.95em;">
  <thead>
    <tr style="background-color: #1e293b; color: #38bdf8; text-align: left; border-bottom: 2px solid #334155;">
      <th style="padding: 10px;">Metric</th>
      <th style="padding: 10px;">Description</th>
      <th style="padding: 10px;">Rules and Thresholds</th>
    </tr>
  </thead>
  <tbody>
    <tr style="border-bottom: 1px solid #1e293b;">
      <td style="padding: 8px 10px; font-weight: bold; color: #f43f5e;">CPU Temperature</td>
      <td style="padding: 8px 10px;">Core Max / CPU Package temperature (°C)</td>
      <td style="padding: 8px 10px;">
        <span style="color: #4ade80;">● &lt; 65°C Green</span> | 
        <span style="color: #fbbf24;">● 65–79°C Orange</span> | 
        <span style="color: #f87171;">● &ge; 80°C Red</span>
      </td>
    </tr>
    <tr style="border-bottom: 1px solid #1e293b; background-color: #111827;">
      <td style="padding: 8px 10px; font-weight: bold; color: #f59e0b;">CPU Usage</td>
      <td style="padding: 8px 10px;">Total utilization percentage (%)</td>
      <td style="padding: 8px 10px;">
        <span style="color: #4ade80;">● &lt; 75% Green</span> | 
        <span style="color: #fbbf24;">● 75–89% Orange</span> | 
        <span style="color: #f87171;">● &ge; 90% Red</span>
      </td>
    </tr>
    <tr style="border-bottom: 1px solid #1e293b;">
      <td style="padding: 8px 10px; font-weight: bold;">CPU Clock Speed</td>
      <td style="padding: 8px 10px;">Average effective core clock speed in MHz</td>
      <td style="padding: 8px 10px; color: #94a3b8;">Continuous value display</td>
    </tr>
    <tr style="border-bottom: 1px solid #1e293b; background-color: #111827;">
      <td style="padding: 8px 10px; font-weight: bold;">Fan Speeds (RPM)</td>
      <td style="padding: 8px 10px;">CPU cooler fan and Chassis/System fan RPM</td>
      <td style="padding: 8px 10px; color: #94a3b8;">Real-time RPM value</td>
    </tr>
    <tr style="border-bottom: 1px solid #1e293b;">
      <td style="padding: 8px 10px; font-weight: bold; color: #38bdf8;">RAM Usage</td>
      <td style="padding: 8px 10px;">Used / Usable Physical Total GB and percentage</td>
      <td style="padding: 8px 10px; color: #94a3b8;">Dynamic progress bar (QProgressBar)</td>
    </tr>
    <tr style="border-bottom: 1px solid #1e293b; background-color: #111827;">
      <td style="padding: 8px 10px; font-weight: bold; color: #10b981;">BIOS / CMOS Battery</td>
      <td style="padding: 8px 10px;">VBAT / CMOS / RTC battery voltage (V)</td>
      <td style="padding: 8px 10px;">
        <span style="color: #4ade80;">● &ge; 2.95V Green</span> | 
        <span style="color: #fbbf24;">● 2.80–2.94V Orange</span> | 
        <span style="color: #f87171;">● &lt; 2.80V Red</span>
      </td>
    </tr>
  </tbody>
</table>

- **Tooltip Feature:** Hovering over the CPU stats section reveals **CPU Package Power** (consumption in Watts).

---

#### <span style="color: #818cf8;">B. Storage Devices (DRIVES Section)</span>

<div style="background-color: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 15px; margin: 15px 0;">
  <h4 style="margin-top: 0; color: #f59e0b;">Displayed Metrics & Interactions:</h4>
  <ul>
    <li><b>Logical Drive Letter & Volume Label:</b> e.g., <code>(C:) System</code>, <code>(D:) Data USB</code></li>
    <li><b>Space Utilization & Temperature:</b> Used / Total capacity in GB and percentage, Temperature (°C) color-coded:
      <br/>
      <span style="color: #4ade80;">● &lt; 50°C (Green)</span> &nbsp;|&nbsp;
      <span style="color: #fbbf24;">● 50–59°C (Orange)</span> &nbsp;|&nbsp;
      <span style="color: #f87171;">● &ge; 60°C (Red)</span>
    </li>
    <li><b>Visual Capacity Bar:</b> Integrated visual capacity progress bar (<code>QProgressBar</code>).</li>
    <li><b>Click Action (File Explorer Launch):</b> Clicking on any drive label or row immediately opens that drive's root folder (<code>C:\</code>, <code>D:\</code>) in <b>Windows File Explorer</b> (<code>os.startfile</code> / <code>explorer.exe</code>).</li>
    <li><b>Comprehensive Hover Tooltip:</b> Drive interface type (Fixed internal / Removable USB), Physical hardware model and serial number, SSD Remaining Health / Life percentage, Total Host Writes (GB), Total Host Reads (GB), SMART health alerts and failure status (Drive Warning / Drive Failure: YES/NO).</li>
  </ul>
</div>

---

#### <span style="color: #818cf8;">C. Network Diagnostics (NETWORK Section)</span>

<div style="display: table; width: 100%; table-layout: fixed; margin: 15px 0;">
  <div style="display: table-cell; background-color: #1e293b; padding: 12px; border-radius: 6px; border: 1px solid #334155;">
    <span style="color: #38bdf8; font-weight: bold;">Public & Internal IP</span><br/>
    <span style="font-size: 0.9em; color: #cbd5e1;">External Public IP (<code>api.ipify.org</code>) and local LAN IPv4 address.</span>
  </div>
  <div style="display: table-cell; width: 10px;"></div>
  <div style="display: table-cell; background-color: #1e293b; padding: 12px; border-radius: 6px; border: 1px solid #334155;">
    <span style="color: #38bdf8; font-weight: bold;">Wi-Fi Info</span><br/>
    <span style="font-size: 0.9em; color: #cbd5e1;">Active wireless network name (SSID) and signal quality percentage (%).</span>
  </div>
  <div style="display: table-cell; width: 10px;"></div>
  <div style="display: table-cell; background-color: #1e293b; padding: 12px; border-radius: 6px; border: 1px solid #334155;">
    <span style="color: #38bdf8; font-weight: bold;">Bandwidth Speed</span><br/>
    <span style="font-size: 0.9em; color: #cbd5e1;">Live Download / Upload rate. Switches aut. to <b style="color: #4ade80;">MB/s</b> above 1000 KB/s.</span>
  </div>
</div>

---

### <span style="color: #38bdf8;">UI/UX & Customization Features</span>
- **Frameless Widget Mode:** Option to hide the standard Windows title bar for a floating desktop gadget experience. Converts into a compact, rounded widget movable anywhere on screen.
- **Custom SizeGrip:** Integrated custom corner handle for resizing in frameless mode.
- **Always-on-Top Toggle:** Keep the widget pinned above all other windows.
- **Screen Edge Snapping:** Automatically snaps to screen boundaries or corners upon moving (top-left, top-right, bottom-left, bottom-right, center, etc.).
- **Adjustable Opacity:** Window transparency slider control.
- **System Tray Integration:** Full tray icon menu (Show/Hide, Position, Language, Exit). Double-clicking tray icon toggles widget visibility.
- **Modular Sections & USB-Only Mode:** Toggle visibility for Network or Drives sections independently, or switch to *USB Drives Only* view.
- **Bilingual Interface (HU / EN):** Instant live language switching without restarting the application.
- **Windows Startup Integration:** Toggle auto-start with Windows via generated startup scripts (`.cmd`).

---

### <span style="color: #38bdf8;">Alerts & ESP32 / Hardware Display Integration</span>

<div style="background-color: #1e1b4b; border-left: 4px solid #6366f1; padding: 12px 16px; margin: 15px 0; border-radius: 0 8px 8px 0; color: #e0e7ff;">
  <b style="color: #a5b4fc;">Alert System & UDP Broadcast Engine:</b>
  <ul style="margin-top: 8px; margin-bottom: 0;">
    <li><b>Visual Status Alerts (Status Line):</b> Real-time warning banners for high CPU temperature / load, critically low free RAM capacity, low CMOS RTC battery voltage, or full / overheating drives.</li>
    <li><b>UDP Broadcast Transmission (ESP32 Smart Display support):</b> Continuously broadcasts formatted system telemetry telemetry strings (<code>ver=pywidget-libre-v1;cpu=...;cput=...;ip=...;down=...;up=...</code>) over local LAN via UDP broadcast port 4210. Directly powers external ESP32 / Arduino TFT or OLED hardware monitors.</li>
  </ul>
</div>
