import * as vscode from "vscode";
import { ApiClient } from "./apiClient";

const STORAGE_KEY = "fewsAgent.sessionId";

/** Tracks the current FEWS agent session id in workspace state (survives a
 * window reload, scoped per-workspace). `ensure()` mints a session on first
 * use via POST /sessions; nothing else in the extension creates sessions
 * directly, so there is exactly one place session lifetime is decided. */
export class SessionManager {
  private pending: Promise<string> | undefined;

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly api: ApiClient,
  ) {}

  /** The current session id, or undefined if none exists yet — never
   * creates one (use `ensure()` when a session is required). */
  current(): string | undefined {
    return this.context.workspaceState.get<string>(STORAGE_KEY);
  }

  async ensure(): Promise<string> {
    const existing = this.current();
    if (existing) {
      return existing;
    }
    // Coalesce concurrent callers (e.g. a chat turn and a refresh firing
    // together) onto a single POST /sessions.
    if (!this.pending) {
      this.pending = this.create();
    }
    try {
      return await this.pending;
    } finally {
      this.pending = undefined;
    }
  }

  private async create(): Promise<string> {
    const folder = vscode.workspace.workspaceFolders?.[0]?.name;
    const created = await this.api.createSession(folder);
    await this.context.workspaceState.update(STORAGE_KEY, created.session_id);
    return created.session_id;
  }

  async reset(): Promise<void> {
    await this.context.workspaceState.update(STORAGE_KEY, undefined);
  }
}
