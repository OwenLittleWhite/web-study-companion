from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


def main() -> None:
    manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert int(manifest["minimum_chrome_version"]) >= 116
    assert "scripting" in manifest["permissions"], (
        "The pause-aware timeline requires activeTab-scoped media playback observation."
    )
    required = {"background.service_worker", "side_panel.default_path"}
    paths = {
        "background.service_worker": manifest["background"]["service_worker"],
        "side_panel.default_path": manifest["side_panel"]["default_path"],
    }
    for label in required:
        path = EXTENSION / paths[label]
        assert path.exists(), f"{label} points to missing file: {path}"

    html_files = list(EXTENSION.glob("*.html"))
    for html in html_files:
        content = html.read_text(encoding="utf-8")
        for relative in re.findall(r'(?:src|href)="([^"]+)"', content):
            if relative.startswith(("http://", "https://", "data:")):
                continue
            assert (EXTENSION / relative).exists(), f"{html.name} references missing {relative}"

    sidepanel_html = (EXTENSION / "sidepanel.html").read_text(encoding="utf-8")
    sidepanel_js = (EXTENSION / "sidepanel.js").read_text(encoding="utf-8")
    markdown_js = (EXTENSION / "markdown.js").read_text(encoding="utf-8")
    html_ids = set(re.findall(r'id="([^"]+)"', sidepanel_html))
    id_array = re.search(r"Object\.fromEntries\(\[(.*?)\]\.map", sidepanel_js, re.S)
    assert id_array, "Could not find side panel element id registry"
    referenced_ids = set(re.findall(r'"([A-Za-z][A-Za-z0-9]+)"', id_array.group(1)))
    missing_ids = referenced_ids - html_ids
    assert not missing_ids, f"sidepanel.js references missing HTML ids: {sorted(missing_ids)}"

    background_js = (EXTENSION / "background.js").read_text(encoding="utf-8")
    offscreen_js = (EXTENSION / "offscreen.js").read_text(encoding="utf-8")
    assert "chrome.action.onClicked.addListener" in background_js
    assert "chrome.tabCapture.getMediaStreamId" in background_js
    assert "chrome.storage.session.set({ captureAuthorization: authorization })" in background_js

    action_click = re.search(
        r"async function handleActionClick\(tab\) \{(.*?)\n\}", background_js, re.S
    )
    assert action_click, "Could not locate toolbar action handler"
    assert "startAuthorizedCapture" not in action_click.group(1), (
        "Toolbar clicks must only open/authorize the panel, never auto-start a Session."
    )
    assert 'type: "capture.authorized"' in action_click.group(1)

    start_session = re.search(
        r"async function startSession\(\) \{(.*?)\n\}\n\nasync function stopSession", sidepanel_js, re.S
    )
    assert start_session, "Could not locate startSession"
    assert 'type: "capture.start"' in start_session.group(1), (
        "The side-panel start button must explicitly begin capture after configuration."
    )
    assert 'provider: el.provider.value' in start_session.group(1)
    assert 'language: el.language.value' in start_session.group(1)
    assert 'sessionId: state.sessionId || null' in start_session.group(1)
    assert 'startAuthorizedCapture(' in background_js
    assert 'message.type === "capture.start"' in background_js
    assert 'message.sessionId || null' in background_js
    assert 'requestedSessionId ? await loadExistingSession(requestedSessionId) : null' in background_js
    assert "chrome.scripting.executeScript" in background_js
    assert 'message.type === "media.playback"' in background_js
    assert 'type: "media.playback", state: message.state' in background_js
    assert "mediaPlaybackState.known && !mediaPlaybackState.playing" in offscreen_js
    assert "applyMediaPlaybackState(message.mediaState)" in offscreen_js
    assert 'type: "capture.started"' in offscreen_js and "mediaState: mediaPlaybackState" in offscreen_js
    assert "segment.text ?? segment.final_text ?? segment.raw_text" in sidepanel_js, (
        "Restored transcript rows must support the persisted final_text field and never render blank text."
    )
    assert 'id="summaryPanel"' not in sidepanel_html and 'id="summaryButton"' not in sidepanel_html
    assert 'id="includeTranscript"' in sidepanel_html
    assert 'id="llmApiKey"' in sidepanel_html
    assert 'id="asrApiKey"' in sidepanel_html
    assert 'id="localProviderButton"' in sidepanel_html
    assert 'id="qwenProviderButton"' in sidepanel_html
    assert 'id="asrSettingsModal"' in sidepanel_html
    assert 'id="captureConfigSummary"' in sidepanel_html
    assert 'id="captureConfigPanel"' in sidepanel_html
    assert 'id="transcriptViewButton"' in sidepanel_html
    assert 'id="chatViewButton"' in sidepanel_html
    assert 'id="unseenTranscriptBadge"' in sidepanel_html
    assert 'id="newSessionButton"' in sidepanel_html
    assert 'id="paneDivider"' not in sidepanel_html
    assert 'id="balancedButton"' not in sidepanel_html
    assert 'id="chatToggleButton"' not in sidepanel_html
    assert '<dialog id="deleteDialog"' in sidepanel_html
    assert 'id="deleteTargetTitle"' in sidepanel_html
    assert 'id="deleteConfirm"' not in sidepanel_html, (
        "Delete confirmation must be a centered dialog, not an inline panel after the archive list."
    )
    assert '"/api/asr/config/test"' in sidepanel_js
    assert '"/api/asr/config"' in sidepanel_js
    sidepanel_css = (EXTENSION / "sidepanel.css").read_text(encoding="utf-8")
    assert ".help-wrap:hover .context-tooltip" in sidepanel_css
    assert ".delete-dialog::backdrop" in sidepanel_css
    assert ".delete-dialog-actions .button" in sidepanel_css and "flex: 1 1 0" in sidepanel_css
    assert "showModal()" in sidepanel_js
    assert sidepanel_html.index('src="markdown.js"') < sidepanel_html.index('src="sidepanel.js"')
    assert 'window.renderMarkdownSafe(content, message.content)' in sidepanel_js
    assert "innerHTML" not in markdown_js, "Model output must not be injected as raw HTML."
    assert "noopener noreferrer" in markdown_js
    assert ".message.assistant" in sidepanel_css and ".markdown-body pre" in sidepanel_css
    assert "@media (max-width: 620px)" in sidepanel_css
    assert ".capture-strip > *, .content-toolbar > *, .pane-header > * { min-width: 0; }" in sidepanel_css
    assert ".provider-choice small" in sidepanel_css and "text-overflow: ellipsis" in sidepanel_css
    assert "grid-template-rows: minmax(0, 1fr) auto" in sidepanel_css, (
        "The single visible content pane must receive all remaining height above the composer."
    )
    assert 'el.question.addEventListener("focus", () => setActiveView("chat"))' in sidepanel_js
    assert 'event.key !== "Enter"' in sidepanel_js
    assert "event.shiftKey" in sidepanel_js
    assert "event.isComposing" in sidepanel_js
    assert "event.keyCode === 229" in sidepanel_js
    assert "el.chatForm.requestSubmit()" in sidepanel_js
    assert 'state.activeView === "chat"' in sidepanel_js
    assert "state.unseenTranscriptSegments += 1" in sidepanel_js
    assert 'setActiveView("transcript")' in sidepanel_js
    assert 'setActiveView("chat", { focusQuestion: true })' in sidepanel_js
    assert 'chrome.storage.local.remove("lastSessionId")' in sidepanel_js
    assert 'state.sessionId ? "继续采集" : "开始采集"' in sidepanel_js
    assert "setLayout(" not in sidepanel_js
    assert "function scrollTranscriptToLatest()" in sidepanel_js
    assert "requestAnimationFrame" in sidepanel_js
    assert "new MutationObserver(scrollTranscriptToLatest)" in sidepanel_js
    assert 'message.type === "transcript.partial"' in sidepanel_js
    assert "overflow-anchor: none" in sidepanel_css
    assert "min-width: 340px" not in sidepanel_css, (
        "The side panel must shrink with the browser window instead of forcing horizontal overflow."
    )
    assert "include_transcript: includeTranscript" in sidepanel_js
    assert 'chrome.storage.local.set({ llmApiKey' not in sidepanel_js, (
        "API keys must only be sent to the localhost service, never browser extension storage."
    )
    assert 'chrome.storage.local.set({ asrApiKey' not in sidepanel_js, (
        "ASR API keys must only be sent to the localhost service, never browser extension storage."
    )
    assert '(await response.json()).detail' in background_js, (
        "Provider configuration errors should reach the user instead of creating silent empty Sessions."
    )
    assert "DASHSCOPE_API_KEY" not in sidepanel_js and "DASHSCOPE_API_KEY" not in background_js, (
        "DashScope secrets must never be embedded in extension JavaScript."
    )
    print(f"Validated MV3 manifest and {len(html_files)} extension HTML files.")


if __name__ == "__main__":
    main()
