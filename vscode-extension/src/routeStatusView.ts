import * as vscode from "vscode";
import { ApiClient } from "./apiClient";
import { SessionManager } from "./sessionManager";
import { LegModel, ModuleStatusModel } from "./types";

type Node =
  | { kind: "empty"; message: string }
  | { kind: "group"; id: "route" | "modules"; label: string }
  | { kind: "leg"; leg: LegModel }
  | { kind: "module"; module: ModuleStatusModel };

const MODULE_STATUS_COLOR: Record<string, string> = {
  built: "charts.green",
  stale: "charts.yellow",
  forced: "charts.yellow",
  none: "charts.foreground",
};

/** The "Project Route" sidebar view — the GPS journey stepper (GET /route)
 * plus the green/amber/grey module build signal (GET /modules), grouped
 * under two top-level nodes. Reuses the same TreeDataProvider shape as
 * ExplorerTreeView; sequenced last because it's the least novel piece. */
export class RouteStatusView implements vscode.TreeDataProvider<Node> {
  private readonly _onDidChangeTreeData = new vscode.EventEmitter<Node | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private legs: LegModel[] = [];
  private modules: ModuleStatusModel[] = [];
  private hasSession = false;

  constructor(
    private readonly api: ApiClient,
    private readonly sessions: SessionManager,
  ) {}

  async refresh(): Promise<void> {
    const sessionId = this.sessions.current();
    this.hasSession = !!sessionId;
    if (sessionId) {
      const [route, modules] = await Promise.all([this.api.getRoute(sessionId), this.api.getModules(sessionId)]);
      this.legs = route.legs;
      this.modules = modules.modules;
    } else {
      this.legs = [];
      this.modules = [];
    }
    this._onDidChangeTreeData.fire(undefined);
  }

  getTreeItem(element: Node): vscode.TreeItem {
    if (element.kind === "empty") {
      return new vscode.TreeItem(element.message, vscode.TreeItemCollapsibleState.None);
    }
    if (element.kind === "group") {
      const item = new vscode.TreeItem(element.label, vscode.TreeItemCollapsibleState.Expanded);
      item.contextValue = "fewsGroup";
      return item;
    }
    if (element.kind === "leg") {
      const leg = element.leg;
      const item = new vscode.TreeItem(leg.title, vscode.TreeItemCollapsibleState.None);
      item.description = leg.done ? "done" : leg.active ? leg.kind : "n/a";
      item.tooltip = leg.guidance || leg.detail || undefined;
      const iconId = leg.done ? "check" : leg.active ? (leg.kind === "blocking" ? "circle-filled" : "circle-outline") : "dash";
      const color = leg.done
        ? "charts.green"
        : leg.active && leg.kind === "blocking"
          ? "charts.red"
          : "charts.yellow";
      item.iconPath = new vscode.ThemeIcon(iconId, new vscode.ThemeColor(color));
      return item;
    }
    const m = element.module;
    const item = new vscode.TreeItem(m.label, vscode.TreeItemCollapsibleState.None);
    item.description = m.focused ? `${m.status} · focused` : m.status;
    const iconId = m.status === "built" ? "check" : m.status === "none" ? "circle-large-outline" : "warning";
    item.iconPath = new vscode.ThemeIcon(
      iconId,
      new vscode.ThemeColor(MODULE_STATUS_COLOR[m.status] ?? "charts.foreground"),
    );
    return item;
  }

  getChildren(element?: Node): Node[] {
    if (!this.hasSession) {
      return [{ kind: "empty", message: "No session yet — say hello to @fews in Copilot Chat." }];
    }
    if (!element) {
      return [
        { kind: "group", id: "route", label: "Route" },
        { kind: "group", id: "modules", label: "Modules" },
      ];
    }
    if (element.kind === "group" && element.id === "route") {
      return this.legs.map((leg) => ({ kind: "leg", leg }));
    }
    if (element.kind === "group" && element.id === "modules") {
      return this.modules.map((module) => ({ kind: "module", module }));
    }
    return [];
  }
}
