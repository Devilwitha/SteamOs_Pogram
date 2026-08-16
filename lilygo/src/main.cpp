/*
 * LilyGo T-Display-S3 - Statusdisplay fuer CPU-/GPU-Auslastung + Temperatur.
 *
 * Empfaengt die Werte per WLAN von SteamOS (steamOs/stats_monitor.py ueber
 * steamOs/lilygo_link.py) und zeigt sie auf dem eingebauten Display an.
 * Bewusst analog zum Protokoll/Aufbau von ../Led_Pico/led_server.py
 * gehalten, nur eben in C++/Arduino statt MicroPython (siehe README.md,
 * warum: paralleler statt SPI-Displaybus).
 *
 * Ablauf:
 *   1. WiFiManager verbindet mit dem gespeicherten Heim-WLAN, oder oeffnet
 *      bei Fehlschlag automatisch einen Access Point "LilyGo-Setup"
 *      (Passwort "picosetup123", identisches Schema wie Pico/Led_Pico) -
 *      unter http://192.168.4.1/ verbinden und WLAN einrichten.
 *   2. TCP-Steuer-Server (Port 5009), zeilenbasiert:
 *        PING                     -> "erreichbar"
 *        STATS:<cpu>:<gpu>:<temp> -> "OK:STATS" (Werte oder "-" bei fehlendem Sensor)
 *   3. UDP-Discovery-Server (Port 5010): antwortet auf "DISCOVER_LILYGO"
 *      mit "LILYGO:<eigene-ip>", damit SteamOS das Geraet automatisch findet.
 */
#include <TFT_eSPI.h>
#include <WiFi.h>
#include <WiFiManager.h>
#include <WiFiUdp.h>

// An die eigene Einbaulage anpassen (0-3, siehe TFT_eSPI setRotation()).
// 3 = Landschaft, USB-C-Anschluss links.
static const uint8_t ROTATION = 3;

// T-Display-S3-Eigenheit: ohne dieses Pin auf HIGH bleibt das Display aus
// (schaltet die Stromversorgung fuer Display + manche Peripherie), siehe
// LilyGos offizielles Beispiel/pin_config.h.
static const uint8_t PIN_POWER_ON = 15;

static const char *AP_SSID = "LilyGo-Setup";
static const char *AP_PASSWORD = "picosetup123";  // mind. 8 Zeichen (WPA2-Vorgabe)

static const uint16_t STATS_TCP_PORT = 5009;
static const uint16_t DISCOVERY_UDP_PORT = 5010;
static const char *DISCOVERY_MESSAGE = "DISCOVER_LILYGO";

TFT_eSPI tft = TFT_eSPI();
WiFiServer statsServer(STATS_TCP_PORT);
WiFiUDP discoveryUdp;

// Zuletzt angezeigte Werte - nur bei Aenderung neu zeichnen, um Flackern zu
// vermeiden (analog _last_led_color in steamOs/pico_client.py).
String lastCpu = "";
String lastGpu = "";
String lastTemp = "";
bool haveStats = false;

void drawLabels() {
    tft.fillScreen(TFT_BLACK);
    tft.setTextDatum(TL_DATUM);
    tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
    tft.setTextFont(4);
    tft.drawString("CPU", 10, 10);
    tft.drawString("GPU", 10, 70);
    tft.drawString("TEMP", 10, 130);
}

void drawValue(int y, const String &text, uint16_t color) {
    // Wertebereich (rechts neben dem Label) vor dem Neuzeichnen leeren,
    // damit kuerzere Texte keine Reste des vorherigen Werts stehen lassen.
    tft.fillRect(90, y, 320 - 90, 50, TFT_BLACK);
    tft.setTextDatum(TL_DATUM);
    tft.setTextColor(color, TFT_BLACK);
    tft.setTextFont(6);
    tft.drawString(text, 90, y);
}

void showStats(const String &cpu, const String &gpu, const String &temp) {
    if (!haveStats) {
        drawLabels();
        haveStats = true;
    }
    if (cpu != lastCpu) {
        drawValue(0, cpu == "-" ? "--%" : cpu + "%", TFT_GREEN);
        lastCpu = cpu;
    }
    if (gpu != lastGpu) {
        drawValue(60, gpu == "-" ? "--%" : gpu + "%", TFT_CYAN);
        lastGpu = gpu;
    }
    if (temp != lastTemp) {
        drawValue(120, temp == "-" ? "--C" : temp + "C", TFT_ORANGE);
        lastTemp = temp;
    }
}

// Zerlegt "STATS:<cpu>:<gpu>:<temp>" in die drei Werte. Gibt false zurueck,
// wenn das Format nicht passt (zu wenige Doppelpunkte).
bool parseStats(const String &line, String &cpu, String &gpu, String &temp) {
    int first = line.indexOf(':');
    if (first < 0) return false;
    int second = line.indexOf(':', first + 1);
    if (second < 0) return false;
    int third = line.indexOf(':', second + 1);
    if (third < 0) return false;

    cpu = line.substring(first + 1, second);
    gpu = line.substring(second + 1, third);
    temp = line.substring(third + 1);
    return true;
}

void handleClient(WiFiClient &client) {
    client.setTimeout(2000);
    String line = client.readStringUntil('\n');
    line.trim();

    if (line == "PING") {
        client.print("erreichbar\n");
    } else if (line.startsWith("STATS:")) {
        String cpu, gpu, temp;
        if (parseStats(line, cpu, gpu, temp)) {
            showStats(cpu, gpu, temp);
            client.print("OK:STATS\n");
        } else {
            client.print("ERROR:bad_format\n");
        }
    } else if (line.length() > 0) {
        client.print("ERROR:unknown_command\n");
    }
    client.stop();
}

void handleDiscovery() {
    int packetSize = discoveryUdp.parsePacket();
    if (packetSize <= 0) return;

    char buf[64];
    int len = discoveryUdp.read(buf, sizeof(buf) - 1);
    if (len < 0) len = 0;
    buf[len] = '\0';

    if (String(buf) == DISCOVERY_MESSAGE) {
        String reply = "LILYGO:" + WiFi.localIP().toString();
        discoveryUdp.beginPacket(discoveryUdp.remoteIP(), discoveryUdp.remotePort());
        discoveryUdp.write((const uint8_t *)reply.c_str(), reply.length());
        discoveryUdp.endPacket();
    }
}

void setup() {
    Serial.begin(115200);

    pinMode(PIN_POWER_ON, OUTPUT);
    digitalWrite(PIN_POWER_ON, HIGH);
    delay(10);

    tft.init();
    tft.setRotation(ROTATION);
    tft.fillScreen(TFT_BLACK);
    pinMode(TFT_BL, OUTPUT);
    digitalWrite(TFT_BL, HIGH);

    tft.setTextDatum(MC_DATUM);
    tft.setTextFont(4);
    tft.drawString("WLAN-Einrichtung...", tft.width() / 2, tft.height() / 2);

    WiFiManager wm;
    // Nach WLAN_SETUP_TIMEOUT_SEK ohne Einrichtung im AP-Modus neu starten
    // und es beim naechsten Boot erneut versuchen, statt endlos im
    // Setup-AP haengen zu bleiben (analog AP_START_TIMEOUT_SEK in
    // Pico/wlan.py).
    wm.setConfigPortalTimeout(180);
    if (!wm.autoConnect(AP_SSID, AP_PASSWORD)) {
        Serial.println("WLAN-Einrichtung fehlgeschlagen/Timeout - Neustart.");
        delay(1000);
        ESP.restart();
    }

    Serial.print("Verbunden, IP: ");
    Serial.println(WiFi.localIP());

    tft.fillScreen(TFT_BLACK);
    tft.setTextFont(2);
    tft.drawString(WiFi.localIP().toString(), tft.width() / 2, tft.height() / 2);
    delay(1500);

    statsServer.begin();
    discoveryUdp.begin(DISCOVERY_UDP_PORT);

    drawLabels();
}

void loop() {
    WiFiClient client = statsServer.available();
    if (client) {
        handleClient(client);
    }
    handleDiscovery();
}
