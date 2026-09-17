# <div style="text-align: center; color: #60a5fa; font-family: sans-serif; padding: 10px 0; border-bottom: 2px solid #3b82f6;">Libre Hardware Widget</div>

<div style="text-align: center; font-size: 1.1em; color: #94a3b8; font-family: sans-serif; margin-bottom: 25px;">
  <b>Teljes Funkciólista és Műszaki Doku / Full Feature List & Technical Docs</b>
</div>

---

## <span style="color: #60a5fa;">1. Magyar Nyelvű Leírás (Hungarian)</span>

### <span style="color: #38bdf8;">Összefoglaló és Architektúra</span>
A **Libre Hardware Widget** egy Python (PySide6 / Qt) alapú, asztali rendszermonitorozó kisalkalmazás (widget), amely a Libre Hardware Monitor (HTTP JSON webszerver vagy WMI interfész) adatait, valamint a Windows rendszerszintű API-jait (`ctypes`, `psutil`, `PowerShell`, `netsh`) ötvözi. Modern, sötét tónusú, testreszabható felületen jelenít meg valós idejű hardver- és hálózati diagnosztikai adatokat.

<div style="background-color: #1e293b; border-left: 4px solid #3b82f6; padding: 12px 16px; margin: 15px 0; border-radius: 0 8px 8px 0; color: #e2e8f0;">
  <b>Működési elv és Adatforrások:</b>
  <ul style="margin-top: 8px; margin-bottom: 0;">
    <li><b>Libre Hardware Monitor csatlakozás:</b> Elsődlegesen a helyi HTTP JSON végpontot (<code>http://127.0.0.1:8085/data.json</code>) használja, tartalékként WMI / COM interfészt (<code>root\LibreHardwareMonitor</code>).</li>
    <li><b>Fail-safe működés:</b> Ha a Libre Hardware Monitor leáll, a widget automatikusan átvált <i>LIBRE OFF</i> módba, és a natív Windows API-kból elérhető adatokat továbbra is frissíti fagyás nélkül.</li>
    <li><b>RAM adatok:</b> A pontos érték érdekében közvetlenül a Windows <code>GlobalMemoryStatusEx</code> API-t hívja meg <code>ctypes</code> segítségével.</li>
    <li><b>Meghajtók feltérképezése:</b> A <code>Win32_DiskDrive</code>, <code>Win32_DiskPartition</code> és <code>Win32_LogicalDiskToPartition</code> CIM lekérdezésekkel kapcsolja össze a logikai betűjeleket (C:, D:, stb.) a fizikai lemezek típusaival és modelljeivel.</li>
    <li><b>Wi-Fi adatok:</b> A <code>netsh wlan show interfaces</code> parancs kinyert adatai alapján.</li>
  </ul>
</div>

---

### <span style="color: #38bdf8;">Fő funkciók és Kijelzett Hardveres Adatok</span>

#### <span style="color: #818cf8;">A. CPU és Alaplap (CPU-RAM szekció)</span>

<table style="width: 100%; border-collapse: collapse; background-color: #0f172a; color: #f8fafc; margin: 15px 0; font-family: sans-serif; font-size: 0.95em;">
  <thead>
    <tr style="background-color: #1e293b; color: #38bdf8; text-align: left; border-bottom: 2px solid #334155;">
      <th style="padding: 10px;">Metrika / Parameter</th>
      <th style="padding: 10px;">Leírás / Description</th>
      <th style="padding: 10px;">Színkód / Szabály (Thresholds)</th>
    </tr>
  </thead>
  <tbody>
    <tr style="border-bottom: 1px solid #1e293b;">
      <td style="padding: 8px 10px; font-weight: bold; color: #f43f5e;">CPU Hőmérséklet</td>
      <td style="padding: 8px 10px;">Core Max / CPU Package hőfok (°C)</td>
      <td style="padding: 8px 10px;">
        <span style="color: #4ade80;">&lt; 65°C Zöld</span> | 
        <span style="color: #fbbf24;">65–79°C Narancs</span> | 
        <span style="color: #f87171;">&ge; 80°C Piros</span>
      </td>
    </tr>
    <tr style="border-bottom: 1px solid #1e293b; background-color: #111827;">
      <td style="padding: 8px 10px; font-weight: bold; color: #f59e0b;">CPU Terhelés</td>
      <td style="padding: 8px 10px;">Százalékos használat (%)</td>
      <td style="padding: 8px 10px;">
        <span style="color: #4ade80;">&lt; 75% Zöld</span> | 
        <span style="color: #fbbf24;">75–89% Narancs</span> | 
        <span style="color: #f87171;">&ge; 90% Piros</span>
      </td>
    </tr>
    <tr style="border-bottom: 1px solid #1e293b;">
      <td style="padding: 8px 10px; font-weight: bold;">CPU Órajel</td>
      <td style="padding: 8px 10px;">Átlagos effektív magórajel MHz-ben</td>
      <td style="padding: 8px 10px; color: #94a3b8;">Normál érték kijelzés</td>
    </tr>
    <tr style="border-bottom: 1px solid #1e293b; background-color: #111827;">
      <td style="padding: 8px 10px; font-weight: bold;">Ventilátorok (RPM)</td>
      <td style="padding: 8px 10px;">CPU hűtő és Chassis/System ventilátor fordulatszám</td>
      <td style="padding: 8px 10px; color: #94a3b8;">Valós idejű RPM érték</td>
    </tr>
    <tr style="border-bottom: 1px solid #1e293b;">
      <td style="padding: 8px 10px; font-weight: bold; color: #38bdf8;">RAM Használat</td>
      <td style="padding: 8px 10px;">Használt / Teljes GB érték + sáv</td>
      <td style="padding: 8px 10px; color: #94a3b8;">Dinamikus folyamatjelző sáv</td>
    </tr>
    <tr style="border-bottom: 1px solid #1e293b; background-color: #111827;">
      <td style="padding: 8px 10px; font-weight: bold; color: #10b981;">BIOS / CMOS Elem</td>
      <td style="padding: 8px 10px;">VBAT / CMOS / RTC elem feszültség (V)</td>
      <td style="padding: 8px 10px;">
        <span style="color: #4ade80;">&ge; 2.95V Zöld</span> | 
        <span style="color: #fbbf24;">2.80–2.94V Narancs</span> | 
        <span style="color: #f87171;">&lt; 2.80V Piros</span>
      </td>
    </tr>
  </tbody>
</table>

- **Tooltip funkció:** A CPU szekcióra mutatva felbukkanó ablakban megjelenik a **CPU Package Power** (fogyasztás Wattban).

---

#### <span style="color: #818cf8;">B. Meghajtók (MEGHAJTÓK szekció)</span>

<div style="background-color: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 15px; margin: 15px 0;">
  <h4 style="margin-top: 0; color: #f59e0b;">Kijelzett elemek és interakciók:</h4>
  <ul>
    <li><b>Logikai betűjel és címke:</b> pl. <code>(C:) Rendszer</code>, <code>(D:) Adat USB</code></li>
    <li><b>Telítettség & Hőmérséklet:</b> Használt/Teljes kapacitás, Hőmérséklet (°C) színkóddal:
      <span style="color: #4ade80; margin-left: 10px;">● &lt; 50°C (Zöld)</span>
      <span style="color: #fbbf24; margin-left: 10px;">● 50–59°C (Narancs)</span>
      <span style="color: #f87171; margin-left: 10px;">● &ge; 60°C (Piros)</span>
    </li>
    <li><b>Egérkattintási akció:</b> Bármelyik meghajtó nevére kattintva a gyökérmappa (<code>C:\</code>, <code>D:\</code>) azonnal megnyílik a <b>Windows Fájlkezelőben</b>.</li>
    <li><b>Bővített Hover Tooltip:</b> Csatlakozás típusa (Fix/USB), Fizikai lemez pontos gyári modellje és sorozatszáma, SSD hátralévő élettartam %, Összes írt/olvasott adat (Host Writes/Reads GB), SMART riasztások.</li>
  </ul>
</div>

---

#### <span style="color: #818cf8;">C. Hálózat (HÁLÓZAT szekció)</span>

<div style="display: table; width: 100%; table-layout: fixed; margin: 15px 0;">
  <div style="display: table-cell; background-color: #1e293b; padding: 12px; border-radius: 6px; border: 1px solid #334155;">
    <span style="color: #38bdf8; font-weight: bold;">Külső & Belső IP</span><br/>
    <span style="font-size: 0.9em; color: #cbd5e1;">Public IP (ipify) és helyi LAN IP cím</span>
  </div>
  <div style="display: table-cell; width: 10px;"></div>
  <div style="display: table-cell; background-color: #1e293b; padding: 12px; border-radius: 6px; border: 1px solid #334155;">
    <span style="color: #38bdf8; font-weight: bold;">Wi-Fi Infó</span><br/>
    <span style="font-size: 0.9em; color: #cbd5e1;">SSID név és jelerősség (%)</span>
  </div>
  <div style="display: table-cell; width: 10px;"></div>
  <div style="display: table-cell; background-color: #1e293b; padding: 12px; border-radius: 6px; border: 1px solid #334155;">
    <span style="color: #38bdf8; font-weight: bold;">Hálózati Sebesség</span><br/>
    <span style="font-size: 0.9em; color: #cbd5e1;">Download/Upload KB/s (1000 felett aut. MB/s)</span>
  </div>
</div>

---

### <span style="color: #38bdf8;">GUI, Riasztások és ESP32 Integráció</span>

<div style="background-color: #1e1b4b; border-left: 4px solid #6366f1; padding: 12px 16px; margin: 15px 0; border-radius: 0 8px 8px 0; color: #e0e7ff;">
  <b style="color: #a5b4fc;">Speciális Funkciók:</b>
  <ul>
    <li><b>Frameless & Snapping:</b> Fejléc nélküli widget mód, egyedi SizeGrip átméretezővel és képernyő-szélhez való tapadással (Snap to Edges).</li>
    <li><b>Multi-language:</b> Futás közbeni azonnali magyar/angol nyelvválasztás.</li>
    <li><b>Status Line Alerts:</b> Vizuális hibaüzenetek kritikus CPU hőfok, alacsony RAM, gyenge CMOS elem vagy teli lemez esetén.</li>
    <li><b>UDP Broadcast (ESP32 Support):</b> Telemetriai adatok folyamatos sugárzása a helyi hálózaton (port 4210) külső OLED/TFT mikrokontrolleres kijelzők meghajtásához.</li>
  </ul>
</div>

---

<br/>

## <span style="color: #60a5fa;">2. English Description</span>

### <span style="color: #38bdf8;">Overview & Architecture</span>
**Libre Hardware Widget** is a lightweight Python-based desktop monitoring widget built with PySide6 (Qt). It aggregates system telemetry from Libre Hardware Monitor (via HTTP JSON or WMI) and native Windows APIs (`ctypes`, `psutil`, `PowerShell`, `netsh`).

<div style="background-color: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 15px; margin: 15px 0; color: #cbd5e1;">
  <h4 style="margin-top: 0; color: #38bdf8;">Key English Summary Specs:</h4>
  <ul>
    <li><b>CPU & Power:</b> CPU Core Max Temp, Usage %, Clock Speed (MHz), CPU & System Fan RPM, CMOS RTC Voltage (V), CPU Package Power (W).</li>
    <li><b>Storage:</b> Volume labels, space utilization, drive temp (°C), <b>single-click Explorer launcher</b>, and advanced tooltips (Drive serial, model, SSD remaining life %, total reads/writes, SMART health).</li>
    <li><b>Network:</b> Public/LAN IP, Wi-Fi SSID & Signal Quality, Live Speedometer with automatic KB/s to MB/s unit scaling.</li>
    <li><b>Display Hardware Integration:</b> UDP Broadcast engine (port 4210) targeting external ESP32 / Arduino TFT/OLED displays.</li>
  </ul>
</div>
