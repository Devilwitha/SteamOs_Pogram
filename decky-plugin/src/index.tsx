import {
  ButtonItem,
  DialogButton,
  DropdownItem,
  Field,
  Focusable,
  PanelSection,
  PanelSectionRow,
  ToggleField,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useEffect, useState, useCallback, useRef } from "react";
import {
  FaLightbulb,
  FaMusic,
  FaGamepad,
  FaTags,
  FaTools,
  FaInfoCircle,
} from "react-icons/fa";

/**
 * Frontend fuer die SteamOS-Konsole im Quick-Access-Menu.
 *
 * Spricht ueber die zwei generischen Backend-Methoden api_get/api_post
 * (main.py) dieselbe JSON-API wie dashboard.html und native_console.py
 * an (siehe steamOs/gui/gui_server.py::API_ROUTES) - Kategorien,
 * Zeilen-Modell und Aktionen sind bewusst ein 1:1-Port von
 * native_console.py, damit sich alle drei Oberflaechen identisch
 * anfuehlen.
 */

// -- Backend-Anbindung ------------------------------------------------------
const apiGet = callable<[path: string], any>("api_get");
const apiPost = callable<[path: string, body: Record<string, unknown>], any>(
  "api_post"
);

async function fetchState(): Promise<AppStateData | null> {
  const r = await apiGet("/api/state");
  if (!r || typeof r.led_enabled === "undefined") return null;
  return r as AppStateData;
}

async function post(
  path: string,
  body: Record<string, unknown>
): Promise<{ ok?: boolean; message?: string }> {
  const r = await apiPost(path, body);
  if (r && typeof r.message === "string") {
    toaster.toast({
      title: r.ok === false ? "Fehler" : "SteamOS Konsole",
      body: r.message,
    });
  }
  return r || {};
}

// -- Typen (Spiegelbild von gui_server.py::_state_payload) ------------------
interface GameInfo {
  uid: string;
  name: string;
  color: string;
  installed: boolean;
  has_audio: boolean;
  audio_enabled: boolean;
}

interface TagInfo {
  uid: string;
  game_uid?: string | null;
}

interface AppStateData {
  led_enabled: boolean;
  idle_led_color: string;
  blink_on_sleep: boolean;
  download_pulse: boolean;
  download_gradient_enabled: boolean;
  download_gradient_start: string;
  download_gradient_mid: string;
  download_gradient_end: string;
  audio_mode: string;
  has_boot_sound: boolean;
  boot_sound_name?: string;
  has_video: boolean;
  video_name?: string;
  games: GameInfo[];
  tags: TagInfo[];
  app_version?: string;
}

const PALETTE = [
  "#ff4d6d", "#ff8800", "#ffb238", "#ffe14d", "#39ff8c", "#00e5ff",
  "#0891a8", "#3b82f6", "#7c5cff", "#ff2e97", "#ffffff", "#7686a0",
];

const AUDIO_MODE_LABELS: Record<string, string> = {
  songs: "Einzelne Songs je Spiel",
  boot_sound: "Ein Boot-Sound fuer alle Spiele",
  video: "Ein Video (Vollbild) fuer alle Spiele",
};

const CATEGORIES = [
  { id: "leds", label: "LEDs", icon: <FaLightbulb /> },
  { id: "sound", label: "Sound", icon: <FaMusic /> },
  { id: "games", label: "Spiele", icon: <FaGamepad /> },
  { id: "tags", label: "Tags", icon: <FaTags /> },
  { id: "tools", label: "Werkzeuge", icon: <FaTools /> },
  { id: "info", label: "Info", icon: <FaInfoCircle /> },
] as const;

type CategoryId = (typeof CATEGORIES)[number]["id"];

function shortUid(uid: string): string {
  return uid.length > 14 ? `${uid.slice(0, 6)}...${uid.slice(-4)}` : uid;
}

// -- kleine Bausteine, Pendant zu den *Row()-Funktionen in native_console.py
const smallBtnStyle = { minWidth: 0, padding: "4px 12px" };

function ColorCycleField({
  label,
  color,
  onChange,
}: {
  label: string;
  color: string;
  onChange: (c: string) => void;
}) {
  const idx = PALETTE.indexOf((color || "").toLowerCase());
  const cycle = (dir: number) => {
    const next = idx < 0 ? PALETTE[0] : PALETTE[(idx + dir + PALETTE.length) % PALETTE.length];
    onChange(next);
  };
  return (
    <Field label={label}>
      <Focusable style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <DialogButton style={smallBtnStyle} onClick={() => cycle(-1)}>
          &lsaquo;
        </DialogButton>
        <div
          style={{
            width: 16,
            height: 16,
            borderRadius: 4,
            background: color || "#7686a0",
            border: "1px solid #333",
            flexShrink: 0,
          }}
        />
        <span style={{ minWidth: 68, textAlign: "center", fontSize: "13px" }}>
          {(color || "#7686a0").toUpperCase()}
        </span>
        <DialogButton style={smallBtnStyle} onClick={() => cycle(1)}>
          &rsaquo;
        </DialogButton>
      </Focusable>
    </Field>
  );
}

function ListRow({
  label,
  sub,
  color,
  badge,
  onActivate,
}: {
  label: string;
  sub?: string;
  color?: string;
  badge?: string | null;
  onActivate: () => void;
}) {
  return (
    <PanelSectionRow>
      <Focusable
        onActivate={onActivate}
        style={{
          display: "flex",
          alignItems: "center",
          width: "100%",
          padding: "8px 4px",
          gap: "10px",
        }}
      >
        {color && (
          <div
            style={{
              width: 14,
              height: 14,
              borderRadius: 4,
              background: color,
              border: "1px solid #333",
              flexShrink: 0,
            }}
          />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {label}
            {badge && (
              <span style={{ marginLeft: 8, fontSize: "11px", color: "#ffb238" }}>
                {badge.toUpperCase()}
              </span>
            )}
          </div>
          {sub && (
            <div style={{ fontSize: "12px", color: "#7686a0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {sub}
            </div>
          )}
        </div>
        <span style={{ color: "#7686a0" }}>&rsaquo;</span>
      </Focusable>
    </PanelSectionRow>
  );
}

// -- Kategorien ---------------------------------------------------------
function LedsPage({ state, refresh }: { state: AppStateData; refresh: () => void }) {
  const set = async (path: string, body: Record<string, unknown>) => {
    await post(path, body);
    refresh();
  };
  return (
    <PanelSection title="LEDs">
      <PanelSectionRow>
        <ToggleField
          label="LED-Synchronisation"
          checked={state.led_enabled}
          onChange={(v) => set("/api/set_led_enabled", { enabled: v })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ColorCycleField
          label='Leerlauf-Farbe ("Konsole an")'
          color={state.idle_led_color}
          onChange={(c) => set("/api/set_idle_led_color", { color: c })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Blinken bei Sleep/Shutdown"
          checked={state.blink_on_sleep}
          onChange={(v) => set("/api/set_blink_on_sleep", { enabled: v })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Download-Pulsieren"
          checked={state.download_pulse}
          onChange={(v) => set("/api/set_download_pulse", { enabled: v })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Farbverlauf im Leerlauf"
          checked={state.download_gradient_enabled}
          onChange={(v) => set("/api/set_download_gradient_enabled", { enabled: v })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ColorCycleField
          label="Verlauf-Startfarbe (0%)"
          color={state.download_gradient_start}
          onChange={(c) => set("/api/set_download_gradient_start", { color: c })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ColorCycleField
          label="Verlauf-Mittelfarbe (50%)"
          color={state.download_gradient_mid}
          onChange={(c) => set("/api/set_download_gradient_mid", { color: c })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ColorCycleField
          label="Verlauf-Endfarbe (100%)"
          color={state.download_gradient_end}
          onChange={(c) => set("/api/set_download_gradient_end", { color: c })}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}

function SoundPage({ state, refresh }: { state: AppStateData; refresh: () => void }) {
  const setMode = async (mode: string) => {
    await post("/api/set_audio_mode", { mode });
    refresh();
  };
  return (
    <PanelSection title="Sound">
      <PanelSectionRow>
        <DropdownItem
          label="Sound-Modus"
          rgOptions={Object.entries(AUDIO_MODE_LABELS).map(([data, label]) => ({ data, label }))}
          selectedOption={state.audio_mode}
          onChange={(opt) => setMode(String(opt.data))}
        />
      </PanelSectionRow>
      {state.audio_mode === "boot_sound" &&
        (state.has_boot_sound ? (
          <>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => post("/api/play_boot_sound", {})}>
                &#9658; Boot-Sound abspielen ({state.boot_sound_name})
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => post("/api/stop_boot_sound", {})}>
                &#9632; Wiedergabe stoppen
              </ButtonItem>
            </PanelSectionRow>
          </>
        ) : (
          <PanelSectionRow>
            <div style={{ fontSize: "13px", color: "#7686a0" }}>
              Kein Boot-Sound hinterlegt - Upload unter /admin.
            </div>
          </PanelSectionRow>
        ))}
      {state.audio_mode === "video" &&
        (state.has_video ? (
          <>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => post("/api/play_video", {})}>
                &#9658; Video abspielen ({state.video_name})
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => post("/api/stop_video", {})}>
                &#9632; Wiedergabe stoppen
              </ButtonItem>
            </PanelSectionRow>
          </>
        ) : (
          <PanelSectionRow>
            <div style={{ fontSize: "13px", color: "#7686a0" }}>
              Kein Video hinterlegt - Upload unter /admin.
            </div>
          </PanelSectionRow>
        ))}
      {state.audio_mode === "songs" && (
        <PanelSectionRow>
          <div style={{ fontSize: "13px", color: "#7686a0" }}>
            Sound pro Spiel: siehe Kategorie "Spiele".
          </div>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

function GameDetail({
  game,
  onBack,
  refresh,
}: {
  game: GameInfo;
  onBack: () => void;
  refresh: () => void;
}) {
  const set = async (path: string, body: Record<string, unknown>) => {
    await post(path, body);
    refresh();
  };
  return (
    <PanelSection title={`Spiel: ${game.name}`}>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={onBack}>
          &larr; Zurueck
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ColorCycleField
          label="Farbe"
          color={game.color}
          onChange={(c) => set("/api/set_game_color", { uid: game.uid, color: c })}
        />
      </PanelSectionRow>
      {game.has_audio ? (
        <>
          <PanelSectionRow>
            <ToggleField
              label={game.audio_enabled ? "Sound: Aktiv" : "Sound: Inaktiv"}
              checked={game.audio_enabled}
              onChange={(v) => set("/api/toggle_game_audio", { uid: game.uid, enabled: v })}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => post("/api/play_game_audio", { uid: game.uid })}>
              &#9658; Sound testen
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => post("/api/stop_game_audio", {})}>
              &#9632; Wiedergabe stoppen
            </ButtonItem>
          </PanelSectionRow>
        </>
      ) : (
        <PanelSectionRow>
          <div style={{ fontSize: "13px", color: "#7686a0" }}>
            Kein Sound hinterlegt - Upload unter /admin.
          </div>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => post("/api/select_game", { uid: game.uid })}>
          Fuer naechsten Tag vormerken
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

function GamesPage({
  state,
  refresh,
  selectedUid,
  setSelectedUid,
}: {
  state: AppStateData;
  refresh: () => void;
  selectedUid: string | null;
  setSelectedUid: (uid: string | null) => void;
}) {
  const selectedGame = selectedUid ? state.games.find((g) => g.uid === selectedUid) : undefined;
  useEffect(() => {
    if (selectedUid && !selectedGame) setSelectedUid(null);
  }, [selectedUid, selectedGame, setSelectedUid]);

  if (selectedUid) {
    if (!selectedGame) return null;
    return <GameDetail game={selectedGame} onBack={() => setSelectedUid(null)} refresh={refresh} />;
  }
  if (!state.games.length) {
    return (
      <PanelSection title="Spiele">
        <PanelSectionRow>
          <div style={{ fontSize: "13px", color: "#7686a0" }}>
            Keine Spiele gefunden. Zuerst game_scanner.py ausfuehren.
          </div>
        </PanelSectionRow>
      </PanelSection>
    );
  }
  return (
    <PanelSection title="Spiele">
      {state.games.map((g) => (
        <ListRow
          key={g.uid}
          label={g.name}
          sub={g.has_audio ? `Sound: ${g.audio_enabled ? "aktiv" : "inaktiv"}` : "Kein Sound"}
          color={g.color}
          badge={g.installed ? null : "nicht installiert"}
          onActivate={() => setSelectedUid(g.uid)}
        />
      ))}
    </PanelSection>
  );
}

function GamePicker({
  tag,
  state,
  onDone,
  refresh,
}: {
  tag: TagInfo;
  state: AppStateData;
  onDone: () => void;
  refresh: () => void;
}) {
  const linkedElsewhere = new Set(
    state.tags.filter((t) => t.game_uid && t.uid !== tag.uid).map((t) => t.game_uid)
  );
  const pickable = state.games.filter((g) => !linkedElsewhere.has(g.uid));
  return (
    <PanelSection title={`Verknuepfen: ${shortUid(tag.uid)}`}>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={onDone}>
          &larr; Zurueck
        </ButtonItem>
      </PanelSectionRow>
      {pickable.length === 0 && (
        <PanelSectionRow>
          <div style={{ fontSize: "13px", color: "#7686a0" }}>
            Keine verfuegbaren Spiele (alle bereits verknuepft).
          </div>
        </PanelSectionRow>
      )}
      {pickable.map((g) => (
        <ListRow
          key={g.uid}
          label={g.name}
          color={g.color}
          onActivate={async () => {
            await post("/api/link_tag", { uid: tag.uid, game_uid: g.uid });
            refresh();
            onDone();
          }}
        />
      ))}
    </PanelSection>
  );
}

function TagDetail({
  tag,
  state,
  onBack,
  refresh,
  openPicker,
}: {
  tag: TagInfo;
  state: AppStateData;
  onBack: () => void;
  refresh: () => void;
  openPicker: () => void;
}) {
  const gameName = tag.game_uid
    ? state.games.find((g) => g.uid === tag.game_uid)?.name ?? tag.game_uid
    : null;
  return (
    <PanelSection title={`Tag: ${shortUid(tag.uid)}`}>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={onBack}>
          &larr; Zurueck
        </ButtonItem>
      </PanelSectionRow>
      {gameName && (
        <PanelSectionRow>
          <div style={{ fontSize: "13px", color: "#7686a0" }}>Verknuepft mit: {gameName}</div>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={openPicker}>
          Verknuepfen mit...
        </ButtonItem>
      </PanelSectionRow>
      {tag.game_uid && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={async () => {
              await post("/api/unlink_tag", { uid: tag.uid });
              refresh();
            }}
          >
            Trennen
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={async () => {
            const r = await post("/api/forget_tag", {});
            if (r.ok) {
              toaster.toast({
                title: "SteamOS Konsole",
                body: "Loeschmodus aktiv - jetzt den Tag an den RC522 halten.",
              });
            }
            onBack();
          }}
        >
          Loeschen...
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

function TagsPage({
  state,
  refresh,
  selectedUid,
  setSelectedUid,
  pickerFor,
  setPickerFor,
}: {
  state: AppStateData;
  refresh: () => void;
  selectedUid: string | null;
  setSelectedUid: (uid: string | null) => void;
  pickerFor: string | null;
  setPickerFor: (uid: string | null) => void;
}) {
  const pickerTag = pickerFor ? state.tags.find((t) => t.uid === pickerFor) : undefined;
  const selectedTag = selectedUid ? state.tags.find((t) => t.uid === selectedUid) : undefined;
  useEffect(() => {
    if (pickerFor && !pickerTag) setPickerFor(null);
  }, [pickerFor, pickerTag, setPickerFor]);
  useEffect(() => {
    if (selectedUid && !selectedTag) setSelectedUid(null);
  }, [selectedUid, selectedTag, setSelectedUid]);

  if (pickerFor) {
    if (!pickerTag) return null;
    return (
      <GamePicker tag={pickerTag} state={state} onDone={() => setPickerFor(null)} refresh={refresh} />
    );
  }
  if (selectedUid) {
    if (!selectedTag) return null;
    return (
      <TagDetail
        tag={selectedTag}
        state={state}
        onBack={() => setSelectedUid(null)}
        refresh={refresh}
        openPicker={() => setPickerFor(selectedTag.uid)}
      />
    );
  }
  if (!state.tags.length) {
    return (
      <PanelSection title="Tags">
        <PanelSectionRow>
          <div style={{ fontSize: "13px", color: "#7686a0" }}>
            Noch keine Tags erkannt. Einen Tag an den RC522 halten.
          </div>
        </PanelSectionRow>
      </PanelSection>
    );
  }
  const gameNames = new Map(state.games.map((g) => [g.uid, g.name]));
  const gameColors = new Map(state.games.map((g) => [g.uid, g.color]));
  return (
    <PanelSection title="Tags">
      {state.tags.map((t) => (
        <ListRow
          key={t.uid}
          label={shortUid(t.uid)}
          sub={t.game_uid ? `-> ${gameNames.get(t.game_uid) ?? t.game_uid}` : "nicht verknuepft"}
          color={t.game_uid ? gameColors.get(t.game_uid) : undefined}
          onActivate={() => setSelectedUid(t.uid)}
        />
      ))}
    </PanelSection>
  );
}

function ToolsPage({ refresh }: { refresh: () => void }) {
  const [confirmArmed, setConfirmArmed] = useState(false);
  return (
    <PanelSection title="Werkzeuge">
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={async () => {
            if (!confirmArmed) {
              setConfirmArmed(true);
              return;
            }
            setConfirmArmed(false);
            await post("/api/reset_all_colors", {});
            refresh();
          }}
        >
          {confirmArmed ? "Wirklich ALLE Spielfarben zuruecksetzen? (nochmal klicken)" : "Farben zuruecksetzen..."}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

function InfoPage({ state }: { state: AppStateData }) {
  return (
    <PanelSection title="Info">
      <PanelSectionRow>
        <Field label="Version">{state.app_version || "-"}</Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <Field label="Hersteller">BolliSoft</Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <Field label="Code">Nico Bollhalder</Field>
      </PanelSectionRow>
    </PanelSection>
  );
}

// -- Hauptkomponente --------------------------------------------------------
function Content() {
  const [state, setState] = useState<AppStateData | null>(null);
  const [category, setCategory] = useState<CategoryId>("leds");
  const [selectedGameUid, setSelectedGameUid] = useState<string | null>(null);
  const [selectedTagUid, setSelectedTagUid] = useState<string | null>(null);
  const [pickerForTagUid, setPickerForTagUid] = useState<string | null>(null);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    const s = await fetchState();
    if (mounted.current && s) setState(s);
  }, []);

  useEffect(() => {
    mounted.current = true;
    refresh();
    const interval = setInterval(refresh, 5000);
    return () => {
      mounted.current = false;
      clearInterval(interval);
    };
  }, [refresh]);

  const changeCategory = (id: CategoryId) => {
    setCategory(id);
    setSelectedGameUid(null);
    setSelectedTagUid(null);
    setPickerForTagUid(null);
  };

  if (!state) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <div style={{ fontSize: "13px", color: "#7686a0" }}>
            Verbinde mit steamos-gui.service...
          </div>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <Focusable style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
            {CATEGORIES.map((c) => (
              <DialogButton
                key={c.id}
                style={{
                  minWidth: 0,
                  padding: "6px 10px",
                  fontSize: "12px",
                  opacity: category === c.id ? 1 : 0.6,
                }}
                onClick={() => changeCategory(c.id)}
              >
                {c.label}
              </DialogButton>
            ))}
          </Focusable>
        </PanelSectionRow>
      </PanelSection>

      {category === "leds" && <LedsPage state={state} refresh={refresh} />}
      {category === "sound" && <SoundPage state={state} refresh={refresh} />}
      {category === "games" && (
        <GamesPage
          state={state}
          refresh={refresh}
          selectedUid={selectedGameUid}
          setSelectedUid={setSelectedGameUid}
        />
      )}
      {category === "tags" && (
        <TagsPage
          state={state}
          refresh={refresh}
          selectedUid={selectedTagUid}
          setSelectedUid={setSelectedTagUid}
          pickerFor={pickerForTagUid}
          setPickerFor={setPickerForTagUid}
        />
      )}
      {category === "tools" && <ToolsPage refresh={refresh} />}
      {category === "info" && <InfoPage state={state} />}
    </>
  );
}

export default definePlugin(() => {
  return {
    name: "SteamOS Konsole",
    titleView: <div className={staticClasses.Title}>SteamOS Konsole</div>,
    content: <Content />,
    icon: <FaGamepad />,
    onDismount() {},
  };
});
