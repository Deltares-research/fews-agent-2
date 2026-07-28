import * as vscode from "vscode";
import { ApiClient } from "./apiClient";
import { SessionManager } from "./sessionManager";
import { FewsFileSystemProvider, SCHEME } from "./fewsFileSystemProvider";
import { BuildFileResult } from "./types";

type Node =
  | { kind: "empty"; message: string }
  | { kind: "dir"; sessionId: string; relpath: string; name: string }
  | { kind: "file"; sessionId: string; entry: BuildFileResult; name: string };

/** The "Generated Files" sidebar view — one leaf per generated-file manifest
 * entry (GET /files), with an XSD badge and a right-click "Show diff since
 * last build". This is the ONLY thing that backs the persistent tree: a
 * live pre-build /preview render is a separate, transient chat affordance
 * (see chatParticipant's "Preview <label>" button), never mixed in here —
 * this tree is specifically "what's really on disk in the container". */
export class ExplorerTreeView implements vscode.TreeDataProvider<Node> {
  private readonly _onDidChangeTreeData = new vscode.EventEmitter<Node | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private built = false;

  constructor(
    private readonly api: ApiClient,
    private readonly sessions: SessionManager,
    private readonly fs: FewsFileSystemProvider,
  ) {}

  async refresh(): Promise<void> {
    const sessionId = this.sessions.current();
    if (!sessionId) {
      this.built = false;
      this._onDidChangeTreeData.fire(undefined);
      return;
    }
    const res = await this.api.listFiles(sessionId);
    this.built = res.built;
    // Feed the same fetch into the FS provider's cache — one /files call
    // per refresh serves both the tree and the virtual filesystem.
    this.fs.setManifest(sessionId, res.files);
    this._onDidChangeTreeData.fire(undefined);
  }

  getTreeItem(element: Node): vscode.TreeItem {
    if (element.kind === "empty") {
      return new vscode.TreeItem(element.message, vscode.TreeItemCollapsibleState.None);
    }
    if (element.kind === "dir") {
      const item = new vscode.TreeItem(element.name, vscode.TreeItemCollapsibleState.Collapsed);
      item.contextValue = "fewsDir";
      item.iconPath = vscode.ThemeIcon.Folder;
      return item;
    }
    const item = new vscode.TreeItem(element.name, vscode.TreeItemCollapsibleState.None);
    item.resourceUri = vscode.Uri.parse(`${SCHEME}://${element.sessionId}/${element.entry.path}`);
    item.contextValue = "fewsFile";
    item.command = {
      command: "vscode.open",
      title: "Open",
      arguments: [item.resourceUri],
    };
    if (element.entry.path.toLowerCase().endsWith(".xml")) {
      item.description = element.entry.xsd_ok ? "✓" : `✗ ${element.entry.xsd_msg ?? ""}`;
      item.iconPath = new vscode.ThemeIcon(
        element.entry.xsd_ok ? "check" : "error",
        new vscode.ThemeColor(element.entry.xsd_ok ? "charts.green" : "charts.red"),
      );
    } else {
      item.iconPath = vscode.ThemeIcon.File;
    }
    return item;
  }

  getChildren(element?: Node): Node[] {
    const sessionId = this.sessions.current();
    if (!sessionId) {
      return [{ kind: "empty", message: "No session yet — say hello to @fews in Copilot Chat." }];
    }
    if (!this.built) {
      return [
        {
          kind: "empty",
          message: "No build yet — run a build from chat, or FEWS Agent: Build.",
        },
      ];
    }

    const manifest = this.fs.getManifest(sessionId);
    const prefix = element && element.kind === "dir" ? element.relpath : "";
    const prefixParts = prefix ? prefix.split("/") : [];

    const dirNames = new Set<string>();
    const files: BuildFileResult[] = [];
    for (const f of manifest) {
      const parts = f.path.split("/");
      if (prefixParts.length && !prefixParts.every((p, i) => parts[i] === p)) {
        continue;
      }
      if (parts.length === prefixParts.length + 1) {
        files.push(f);
      } else if (parts.length > prefixParts.length + 1) {
        dirNames.add(parts[prefixParts.length]);
      }
    }

    const dirNodes: Node[] = [...dirNames].sort().map((name) => ({
      kind: "dir",
      sessionId,
      relpath: prefix ? `${prefix}/${name}` : name,
      name,
    }));
    const fileNodes: Node[] = files
      .sort((a, b) => a.path.localeCompare(b.path))
      .map((entry) => ({
        kind: "file",
        sessionId,
        entry,
        name: entry.path.split("/").pop() as string,
      }));
    return [...dirNodes, ...fileNodes];
  }
}
