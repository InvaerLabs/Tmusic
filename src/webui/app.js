import "./src/style.css";
import brandLogo from "../../Logo.jpeg";
import { icon } from "@fortawesome/fontawesome-svg-core";
import {
  faArrowUpRightFromSquare,
  faBackwardStep,
  faCloudArrowDown,
  faCompactDisc,
  faDownload,
  faFileArrowUp,
  faFolder,
  faFolderPlus,
  faForwardStep,
  faGear,
  faImage,
  faMagnifyingGlass,
  faMinus,
  faMusic,
  faPause,
  faPlay,
  faPlus,
  faQuoteLeft,
  faRepeat,
  faRotate,
  faShuffle,
  faStar,
  faVolumeHigh,
  faWandMagicSparkles,
  faXmark,
  faCircleInfo,
  faFloppyDisk,
} from "@fortawesome/free-solid-svg-icons";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
$("#brand-logo").src = brandLogo;
const faIcons = {
  upRightFromSquare: faArrowUpRightFromSquare,
  arrowUpRightFromSquare: faArrowUpRightFromSquare,
  backwardStep: faBackwardStep,
  cloudArrowDown: faCloudArrowDown,
  compactDisc: faCompactDisc,
  download: faDownload,
  fileArrowUp: faFileArrowUp,
  folder: faFolder,
  folderPlus: faFolderPlus,
  forwardStep: faForwardStep,
  gear: faGear,
  image: faImage,
  magnifyingGlass: faMagnifyingGlass,
  minus: faMinus,
  music: faMusic,
  pause: faPause,
  play: faPlay,
  plus: faPlus,
  quoteLeft: faQuoteLeft,
  repeat: faRepeat,
  arrowsRotate: faRotate,
  shuffle: faShuffle,
  sparkles: faWandMagicSparkles,
  star: faStar,
  volumeHigh: faVolumeHigh,
  xmark: faXmark,
  circleInfo: faCircleInfo,
  floppyDisk: faFloppyDisk,
};

function faSvg(name) {
  const definition = faIcons[name];
  if (!definition) throw new Error(`Unknown Font Awesome icon: ${name}`);
  return icon(definition, { attributes: { "aria-hidden": "true" } })
    .html.join("")
    .replace(/class="([^"]*)"/, 'class="$1 fa-icon"');
}

document.querySelectorAll("[data-fa]").forEach((element) => {
  element.innerHTML = faSvg(element.dataset.fa);
});
const state = { snapshot: null, trackSignature: "", folderSignature: "", lyricsSignature: "", activeLyric: null, lastPlaying: null, lastRepeat: null, draggingSeek: false, editorPath: null, coverPath: null, editorDirty: false, toastTimer: 0, refreshTimer: 0, refreshing: false, windowHidden: false };
let windowDrag = null;
let windowDragDelta = { x: 0, y: 0 };
let windowDragTimer = 0;

function bridge() {
  if (!window.pywebview?.api) throw new Error("The Tmusic desktop bridge is not ready yet.");
  return window.pywebview.api;
}

function escapeHtml(value = "") {
  return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

function formatTime(seconds) {
  if (seconds == null || !Number.isFinite(Number(seconds))) return "--:--";
  const whole = Math.max(0, Math.floor(Number(seconds)));
  return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
}

function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.toggle("error", error);
  element.classList.add("show");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => element.classList.remove("show"), 2800);
}

function renderTracks(snapshot) {
  const query = $("#search").value.trim().toLocaleLowerCase();
  const signature = JSON.stringify([snapshot.libraryRevision, snapshot.currentPath, snapshot.playing, query]);
  if (signature === state.trackSignature) return;
  state.trackSignature = signature;
  const tracks = snapshot.tracks.filter((track) =>
    `${track.title} ${track.artist} ${track.path}`.toLocaleLowerCase().includes(query)
  );
  $("#track-count").textContent = snapshot.tracks.length;
  $("#track-list").innerHTML = tracks.map((track, index) => `
    <div class="track-row ${track.active ? "active" : ""}" data-path="${escapeHtml(track.path)}" role="button" tabindex="0">
      <span class="track-name"><span class="track-number">${track.active && snapshot.playing ? faSvg("music") : String(index + 1).padStart(2, "0")}</span><span class="track-title-text">${escapeHtml(track.title)}</span></span>
      <span class="track-artist-text">${escapeHtml(track.artist)}</span>
      <span class="track-format">${escapeHtml(track.path.split(".").pop()?.toUpperCase() || "")}</span>
      ${track.path.toLocaleLowerCase().endsWith(".mp3") ? `<button class="row-edit" data-edit="${escapeHtml(track.path)}" title="Edit MP3 metadata" aria-label="Edit ${escapeHtml(track.title)}">${faSvg("gear")}</button>` : "<span></span>"}
    </div>`).join("");
  $("#empty-library").hidden = tracks.length > 0;
  $("#track-list").hidden = tracks.length === 0;
}

function renderFolders(folders) {
  const signature = JSON.stringify(folders);
  if (signature === state.folderSignature) return;
  state.folderSignature = signature;
  $("#folder-chips").innerHTML = folders.map((folder) => `
    <button class="folder-chip" title="${escapeHtml(folder)}" data-folder="${escapeHtml(folder)}"><i>${faSvg("folder")}</i><span>${escapeHtml(folder.split(/[\\/]/).filter(Boolean).pop() || folder)}</span></button>`).join("");
  $("#settings-folders").innerHTML = folders.map((folder) => `
    <div class="settings-folder"><span title="${escapeHtml(folder)}">${escapeHtml(folder)}</span><button data-remove-folder="${escapeHtml(folder)}" title="Remove folder" aria-label="Remove ${escapeHtml(folder)}">${faSvg("xmark")}</button></div>`).join("");
}

function renderLyrics(snapshot) {
  const lines = snapshot.lyrics || [];
  const index = snapshot.activeLyric;
  const signature = `${snapshot.libraryRevision}:${snapshot.currentPath}:${snapshot.lyricsSynced}`;
  if (signature !== state.lyricsSignature) {
    state.lyricsSignature = signature;
    state.activeLyric = null;
    $("#lyrics-title").textContent = snapshot.title || "Lyrics";
    $("#lyrics-list").innerHTML = lines.length ? lines.map((line, i) => `
      <button class="lyric-line" data-seek="${line.timestamp}">
        ${snapshot.lyricsSynced ? `<span class="lyric-time">${formatTime(line.timestamp)} · </span>` : ""}${escapeHtml(line.text)}
      </button>`).join("") : `<p class="empty-state">No lyrics found for this track.</p>`;
  }
  if (index !== state.activeLyric) {
    $("#lyrics-list").querySelector(".lyric-line.active")?.classList.remove("active");
    if (index != null) $("#lyrics-list").children[index]?.classList.add("active");
    state.activeLyric = index;
  }
  const currentLine = index != null ? lines[index] : lines[0];
  const currentText = currentLine?.text || "No lyrics attached to this track yet.";
  if ($("#current-lyric").textContent !== currentText) {
    $("#current-lyric").textContent = currentText;
  }
}

function render(snapshot) {
  const coverChanged = Object.prototype.hasOwnProperty.call(snapshot, "cover");
  snapshot = {
    ...state.snapshot,
    ...snapshot,
    tracks: snapshot.tracks ?? state.snapshot?.tracks ?? [],
    lyrics: snapshot.lyrics ?? state.snapshot?.lyrics ?? [],
    cover: coverChanged ? snapshot.cover : state.snapshot?.cover ?? null,
  };
  state.snapshot = snapshot;
  document.documentElement.dataset.theme = snapshot.resolvedTheme;
  const currentError = snapshot.error || snapshot.settingsError;
  if (currentError && state.lastError !== currentError) toast(currentError, true);
  state.lastError = currentError || null;
  renderTracks(snapshot);
  renderFolders(snapshot.folders);
  $("#track-title").textContent = snapshot.title;
  $("#track-artist").textContent = snapshot.artist;
  $("#track-album").textContent = snapshot.album || "";
  $("#record").classList.toggle("is-playing", snapshot.playing);
  if (state.lastPlaying !== snapshot.playing) {
    state.lastPlaying = snapshot.playing;
    $("#play").innerHTML = faSvg(snapshot.playing ? "pause" : "play");
    $("#play").title = snapshot.playing ? "Pause" : "Play";
  }
  $("#shuffle").classList.toggle("active", snapshot.shuffle);
  $("#repeat").classList.toggle("active", snapshot.repeat !== "off");
  if (state.lastRepeat !== snapshot.repeat) {
    state.lastRepeat = snapshot.repeat;
    $("#repeat").innerHTML = `${faSvg("repeat")}${snapshot.repeat === "one" ? '<sup class="repeat-one">1</sup>' : ""}`;
  }
  $("#elapsed").textContent = formatTime(snapshot.position);
  $("#duration").textContent = formatTime(snapshot.duration);
  if (!state.draggingSeek) {
    const progress = snapshot.duration ? snapshot.position / snapshot.duration : 0;
    $("#seek").value = String(Math.round(progress * 1000));
    $("#seek").style.background = `linear-gradient(90deg,var(--acid) ${progress * 100}%,#465148 ${progress * 100}%)`;
  }
  $("#volume").value = String(snapshot.volume);
  $("#volume").style.background = `linear-gradient(90deg,var(--acid) ${snapshot.volume * 100}%,#465148 ${snapshot.volume * 100}%)`;
  if (coverChanged) {
    if (snapshot.cover) {
      $("#record-cover").src = snapshot.cover;
      $("#record-cover").hidden = false;
      $("#cover-sleeve").innerHTML = `<img src="${snapshot.cover}" alt="Album cover" />`;
      $("#cover-sleeve").classList.add("pulled");
    } else {
      $("#record-cover").removeAttribute("src");
      $("#record-cover").hidden = true;
      $("#cover-sleeve").innerHTML = `<div class="sleeve-placeholder"><span>${faSvg("music")}</span><small>NO COVER<br />JUST VIBES</small></div>`;
      $("#cover-sleeve").classList.remove("pulled");
    }
  }
  renderLyrics(snapshot);
  $("#download-url").setAttribute("aria-label", "Video or playlist link");
  $("#bitrate").value = String(snapshot.bitrate);
  $("#choose-download-folder").textContent = snapshot.downloadDirectory;
  const download = snapshot.download;
  $("#download-progress-wrap").hidden = !download.active;
  if (download.active) {
    const percent = Number(String(download.progress._percent_str || "").replace("%", "")) || 0;
    $("#download-progress").style.width = `${Math.max(0, Math.min(100, percent))}%`;
    $("#download-progress-label").textContent = download.progress.status || download.progress._percent_str || "Downloading…";
  }
  if (download.error) {
    $("#download-message").textContent = download.error;
    $("#download-message").classList.add("error");
  } else if (download.finished) {
    $("#download-message").textContent = `Saved ${download.finished.split(/[\\/]/).pop()}`;
    $("#download-message").classList.remove("error");
  }
  if (snapshot.update.checking) $("#update-result").textContent = "Checking GitHub releases…";
  else if (snapshot.update.result) showUpdateResult(snapshot.update.result);
  if (snapshot.error) $("#download-message").textContent = snapshot.error;
}

function showUpdateResult(result) {
  const message = $("#update-result");
  const openButton = $("#open-release");
  if (result.kind === "error") {
    message.textContent = `Could not check for updates: ${result.message}`;
    openButton.hidden = true;
  } else if (result.kind === "current") {
    message.textContent = `You're up to date · ${result.tag}`;
    openButton.hidden = true;
  } else {
    message.textContent = `A new release is ready · ${result.tag}`;
    openButton.hidden = false;
    openButton.dataset.url = result.url;
  }
}

async function refresh() {
  if (state.refreshing) return;
  state.refreshing = true;
  try {
    render(await bridge().get_state());
  } catch (error) {
    if (window.pywebview?.api) toast(error.message, true);
  } finally {
    state.refreshing = false;
    clearTimeout(state.refreshTimer);
    if (!document.hidden && !state.windowHidden) state.refreshTimer = setTimeout(refresh, 1000);
  }
}

async function call(method, ...args) {
  try {
    const value = await bridge()[method](...args);
    if (value === false) toast("That action could not be completed.", true);
    await refresh();
    return value;
  } catch (error) {
    toast(error.message || String(error), true);
    return null;
  }
}

async function closeWindow() {
  const downloading = state.snapshot?.download?.active;
  if (downloading && !window.confirm("A download is running. Closing the window will cancel it. Continue?")) return;
  state.windowHidden = true;
  clearTimeout(state.refreshTimer);
  try {
    if (downloading) await bridge().cancel_download();
    await bridge().hide_window();
  } catch (error) {
    state.windowHidden = false;
    toast(error.message || String(error), true);
  }
}

function showModal(id) {
  $(id).hidden = false;
}

function closeModal(id) {
  $(id).hidden = true;
}

function closeEditor() {
  if (state.editorDirty && !window.confirm("Discard your unsaved track changes?")) return;
  state.editorDirty = false;
  closeModal("#editor-modal");
}

async function openEditor(path) {
  if (!path.toLocaleLowerCase().endsWith(".mp3")) return;
  try {
    const data = await bridge().get_editor_data(path);
    state.editorPath = data.path;
    state.coverPath = null;
    state.editorDirty = false;
    $("#edit-title").value = data.title;
    $("#edit-artist").value = data.artist;
    $("#edit-lyrics").value = data.lyrics;
    $("#edit-cover-preview").src = data.cover || "";
    $("#edit-cover-name").textContent = data.cover ? "Using current embedded artwork" : "No embedded cover";
    $("#editor-status").textContent = "Changes are not saved yet.";
    showModal("#editor-modal");
  } catch (error) {
    toast(error.message, true);
  }
}

function setView(name) {
  const isDownload = name === "download";
  $("#library-view").hidden = isDownload;
  $("#download-view").hidden = !isDownload;
  $("#view-title").textContent = isDownload ? "Downloader" : "Library";
  $$(".nav-item[data-view]").forEach((item) => item.classList.toggle("active", item.dataset.view === name));
}

document.addEventListener("click", async (event) => {
  const target = event.target.closest("button,[data-path],[data-seek]");
  if (!target) return;
  if (target.dataset.action === "settings") { $("#theme-select").value = state.snapshot?.theme || "system"; showModal("#settings-modal"); return; }
  if (target.dataset.action === "close-modal") { closeModal("#settings-modal"); closeModal("#lyrics-modal"); return; }
  if (target.dataset.action === "close-editor") { closeEditor(); return; }
  if (target.dataset.action === "minimize" || target.dataset.action === "close") { await closeWindow(); return; }
  if (target.dataset.view) { setView(target.dataset.view); return; }
  if (target.id === "refresh-library") { await call("refresh_library"); return; }
  if (target.id === "add-folder-sidebar" || target.id === "add-folder-main" || target.id === "empty-add-folder" || target.id === "settings-add-folder") {
    const folder = await call("choose_music_folder");
    if (folder) toast("Music folder added.");
    return;
  }
  if (target.dataset.removeFolder) { await call("remove_music_folder", target.dataset.removeFolder); return; }
  if (target.id === "play") { await call("toggle_play"); return; }
  if (target.id === "next") { await call("next_track"); return; }
  if (target.id === "previous") { await call("previous_track"); return; }
  if (target.id === "shuffle") { await call("set_shuffle", !state.snapshot?.shuffle); return; }
  if (target.id === "repeat") {
    const modes = ["off", "all", "one"];
    const next = modes[(modes.indexOf(state.snapshot?.repeat || "off") + 1) % modes.length];
    await call("set_repeat", next); return;
  }
  if (target.id === "open-lyrics") { showModal("#lyrics-modal"); return; }
  if (target.id === "start-download") {
    $("#download-message").textContent = "";
    await call("start_download", $("#download-url").value);
    return;
  }
  if (target.id === "cancel-download") { await call("cancel_download"); return; }
  if (target.id === "choose-download-folder") { await call("choose_download_folder"); return; }
  if (target.id === "check-updates") { await call("check_for_updates"); return; }
  if (target.id === "open-release") {
    if (target.dataset.url) await call("open_release", target.dataset.url);
    return;
  }
  if (target.dataset.edit) { await openEditor(target.dataset.edit); return; }
  if (target.dataset.seek) { await call("seek", Number(target.dataset.seek)); return; }
  if (target.dataset.path) {
    if (target.classList.contains("track-row")) await call("play_track", target.dataset.path);
    return;
  }
  if (target.id === "choose-cover") {
    const cover = await call("choose_cover");
    if (cover) {
      state.coverPath = cover.path;
      state.editorDirty = true;
      $("#edit-cover-name").textContent = cover.path.split(/[\\/]/).pop();
      $("#edit-cover-preview").src = cover.preview;
      $("#editor-status").textContent = "Unsaved changes";
    }
    return;
  }
  if (target.id === "import-lyrics") {
    const content = await call("choose_lyrics");
    if (content != null) {     $("#edit-lyrics").value = content; state.editorDirty = true; $("#editor-status").textContent = "Unsaved changes"; }
    return;
  }
  if (target.id === "save-editor") {
    const result = await call("save_editor", state.editorPath, $("#edit-title").value, $("#edit-artist").value, $("#edit-lyrics").value, state.coverPath);
    if (result) { state.editorDirty = false; closeModal("#editor-modal"); toast("Track details saved."); state.trackSignature = ""; }
    return;
  }
});

document.addEventListener("dblclick", (event) => {
  const row = event.target.closest(".track-row");
  if (row) openEditor(row.dataset.path);
});

document.addEventListener("contextmenu", (event) => {
  const row = event.target.closest(".track-row");
  if (!row || !row.dataset.path.toLocaleLowerCase().endsWith(".mp3")) return;
  event.preventDefault();
  openEditor(row.dataset.path);
});

$("#search").addEventListener("input", () => { state.trackSignature = ""; if (state.snapshot) renderTracks(state.snapshot); });
$("#search").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    const first = $(".track-row");
    if (first) call("play_track", first.dataset.path);
  }
});
$("#seek").addEventListener("input", () => {
  state.draggingSeek = true;
  const progress = Number($("#seek").value) / 1000;
  $("#seek").style.background = `linear-gradient(90deg,var(--acid) ${progress * 100}%,#465148 ${progress * 100}%)`;
});
$("#seek").addEventListener("change", async () => {
  const duration = state.snapshot?.duration || 0;
  await call("seek", duration * Number($("#seek").value) / 1000);
  state.draggingSeek = false;
});
$("#volume").addEventListener("input", () => call("set_volume", Number($("#volume").value)));
$("#bitrate").addEventListener("change", (event) => call("set_bitrate", event.target.value));
$("#theme-select").addEventListener("change", (event) => call("set_theme", event.target.value));
$("#edit-title").addEventListener("input", () => { state.editorDirty = true; $("#editor-status").textContent = "Unsaved changes"; });
$("#edit-artist").addEventListener("input", () => { state.editorDirty = true; $("#editor-status").textContent = "Unsaved changes"; });
$("#edit-lyrics").addEventListener("input", () => { state.editorDirty = true; $("#editor-status").textContent = "Unsaved changes"; });
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (!$("#editor-modal").hidden) closeEditor();
    else $$(".modal-backdrop").forEach((modal) => { modal.hidden = true; });
  }
  if ((event.ctrlKey || event.metaKey) && ["f", "k"].includes(event.key.toLowerCase())) { event.preventDefault(); $("#search").focus(); }
  if ((event.ctrlKey || event.metaKey) && event.key === "ArrowLeft") { event.preventDefault(); call("previous_track"); }
  if ((event.ctrlKey || event.metaKey) && event.key === "ArrowRight") { event.preventDefault(); call("next_track"); }
  if (event.metaKey && event.key.toLowerCase() === "q") { event.preventDefault(); closeWindow(); }
  if (event.code === "Space" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) { event.preventDefault(); call("toggle_play"); }
  if (event.key === "Enter" && event.target.classList.contains("track-row")) call("play_track", event.target.dataset.path);
});

$(".topbar").addEventListener("pointerdown", (event) => {
  if (!window.pywebview?.api || event.target.closest("button,input,label")) return;
  windowDrag = { x: event.screenX, y: event.screenY };
  bridge().begin_window_drag();
  event.currentTarget.setPointerCapture(event.pointerId);
});
$(".topbar").addEventListener("pointermove", (event) => {
  if (!windowDrag) return;
  windowDragDelta = { x: event.screenX - windowDrag.x, y: event.screenY - windowDrag.y };
  if (!windowDragTimer) {
    windowDragTimer = setTimeout(() => {
      windowDragTimer = 0;
      bridge().move_window_drag(windowDragDelta.x, windowDragDelta.y);
    }, 24);
  }
});
$(".topbar").addEventListener("pointerup", () => { windowDrag = null; });
$(".topbar").addEventListener("pointercancel", () => { windowDrag = null; });

document.addEventListener("visibilitychange", () => {
  clearTimeout(state.refreshTimer);
  if (!document.hidden && window.pywebview?.api) {
    state.windowHidden = false;
    refresh();
  }
});
window.addEventListener("focus", () => {
  state.windowHidden = false;
  if (window.pywebview?.api) refresh();
});

window.addEventListener("pywebviewready", async () => {
  await refresh();
  $("#theme-select").value = state.snapshot.theme;
});
