import * as vscode from "vscode";
import { ApiClient } from "./apiClient";
import { SessionManager } from "./sessionManager";
import { PARTICIPANT_ID, makeChatHandler, formatPreviewMarkdown } from "./chatParticipant";
import { FewsFileSystemProvider, SCHEME } from "./fewsFileSystemProvider";
import { ExplorerTreeView } from "./explorerTreeView";
import { RouteStatusView } from "./routeStatusView";
import { showDiffSinceLastBuild } from "./diffCommand";
import { BuildRequest } from "./types";

function getApiBaseUrl(): string {
  return vscode.workspace.getConfiguration("fewsAgent").get<string>("apiBaseUrl", "http://localhost:8000");
}

export function activate(context: vscode.ExtensionContext): void {
  const api = new ApiClient(getApiBaseUrl);
  const sessions = new SessionManager(context, api);
  // The entire "container regenerated, IDE view updates automatically"
  // mechanism for v1: fired after every /turn or /build call the
  // extension itself made — no polling, no server push (see CLAUDE plan).
  const onProjectChanged = new vscode.EventEmitter<void>();

  const fs = new FewsFileSystemProvider(api);
  context.subscriptions.push(
    vscode.workspace.registerFileSystemProvider(SCHEME, fs, {
      isReadonly: true,
      isCaseSensitive: true,
    }),
  );

  const filesTree = new ExplorerTreeView(api, sessions, fs);
  const routeTree = new RouteStatusView(api, sessions);
  context.subscriptions.push(
    vscode.window.registerTreeDataProvider("fewsAgent.files", filesTree),
    vscode.window.registerTreeDataProvider("fewsAgent.route", routeTree),
  );

  const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 0);
  statusBar.command = "fewsAgent.newSession";
  statusBar.tooltip = "FEWS Agent session — click to start a new one";
  const refreshStatusBar = () => {
    const sid = sessions.current();
    statusBar.text = sid ? `$(circuit-board) FEWS: ${sid}` : "$(circuit-board) FEWS: no session";
    statusBar.show();
  };
  refreshStatusBar();
  context.subscriptions.push(statusBar);

  const participant = vscode.chat.createChatParticipant(
    PARTICIPANT_ID,
    makeChatHandler(api, sessions, onProjectChanged),
  );
  participant.iconPath = vscode.Uri.joinPath(context.extensionUri, "media", "fews-icon.svg");
  context.subscriptions.push(participant);

  context.subscriptions.push(
    onProjectChanged.event(async () => {
      refreshStatusBar();
      await Promise.all([filesTree.refresh(), routeTree.refresh()]);
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("fewsAgent.newSession", async () => {
      await sessions.reset();
      refreshStatusBar();
      await Promise.all([filesTree.refresh(), routeTree.refresh()]);
      vscode.window.showInformationMessage(
        "Started a fresh FEWS agent session — your next @fews message begins it.",
      );
    }),

    vscode.commands.registerCommand("fewsAgent.refreshFiles", () => onProjectChanged.fire()),

    vscode.commands.registerCommand("fewsAgent.openFile", async (relpath: string) => {
      const sessionId = await sessions.ensure();
      const uri = vscode.Uri.parse(`${SCHEME}://${sessionId}/${relpath}`);
      await vscode.window.showTextDocument(uri);
    }),

    vscode.commands.registerCommand(
      "fewsAgent.showDiffSinceLastBuild",
      (item?: { kind?: string; entry?: { path: string } } | string) => {
        const relpath = typeof item === "string" ? item : item?.entry?.path;
        if (relpath) {
          return showDiffSinceLastBuild(sessions, relpath);
        }
        vscode.window.showWarningMessage("Select a generated file first.");
        return;
      },
    ),

    vscode.commands.registerCommand("fewsAgent.build", async (req?: BuildRequest) => {
      const sessionId = await sessions.ensure();
      try {
        const build = await api.build(sessionId, req ?? {});
        vscode.window.showInformationMessage(
          `FEWS build (${build.scope}): ${build.files_xsd_ok}/${build.files_xml} XSD-valid.`,
        );
      } catch (e) {
        vscode.window.showErrorMessage(`FEWS build failed: ${e instanceof Error ? e.message : String(e)}`);
      } finally {
        onProjectChanged.fire();
      }
    }),

    vscode.commands.registerCommand("fewsAgent.previewFromChat", async (target: string) => {
      const sessionId = await sessions.ensure();
      const preview = await api.preview(sessionId, target);
      const doc = await vscode.workspace.openTextDocument({
        content: formatPreviewMarkdown(preview),
        language: "markdown",
      });
      await vscode.window.showTextDocument(doc, { preview: true });
    }),
  );
}

export function deactivate(): void {}
