import * as vscode from "vscode";
import { ApiClient, ApiError } from "./apiClient";
import { BuildFileResult } from "./types";

export const SCHEME = "fews-gen";

interface TreeNode {
  children: Map<string, TreeNode>;
  file?: BuildFileResult;
}

function buildTree(files: BuildFileResult[]): TreeNode {
  const root: TreeNode = { children: new Map() };
  for (const f of files) {
    const parts = f.path.split("/").filter(Boolean);
    let node = root;
    parts.forEach((part, i) => {
      let next = node.children.get(part);
      if (!next) {
        next = { children: new Map() };
        node.children.set(part, next);
      }
      if (i === parts.length - 1) {
        next.file = f;
      }
      node = next;
    });
  }
  return root;
}

function findNode(root: TreeNode, relpath: string): TreeNode | undefined {
  if (!relpath) {
    return root;
  }
  let node = root;
  for (const part of relpath.split("/").filter(Boolean)) {
    const next = node.children.get(part);
    if (!next) {
      return undefined;
    }
    node = next;
  }
  return node;
}

function parseUri(uri: vscode.Uri): { sessionId: string; relpath: string; rev?: string } {
  const sessionId = uri.authority;
  const relpath = uri.path.replace(/^\/+/, "");
  const query = new URLSearchParams(uri.query);
  const rev = query.get("rev") ?? undefined;
  return { sessionId, relpath, rev };
}

/** Read-only virtual filesystem over the container's generated/ tree,
 * backed entirely by GET /files + GET /files/{path}. No real files are
 * ever written to the user's disk/workspace, so the user's own git repo
 * is never touched — the per-session git repo in project_git.py stays
 * server-side.
 *
 * There is no per-file backend watch: `setManifest` (driven by
 * `refresh()`, called after every extension-initiated /turn or /build) is
 * the entire "container regenerated, IDE updates automatically" mechanism
 * for v1 — it diffs the new manifest against the cached one and fires
 * onDidChangeFile for anything that changed, so already-open editors
 * update in place. */
export class FewsFileSystemProvider implements vscode.FileSystemProvider {
  private readonly _onDidChangeFile = new vscode.EventEmitter<vscode.FileChangeEvent[]>();
  readonly onDidChangeFile = this._onDidChangeFile.event;

  private manifests = new Map<string, BuildFileResult[]>();
  private trees = new Map<string, TreeNode>();
  private generations = new Map<string, number>();

  constructor(private readonly api: ApiClient) {}

  private generation(sessionId: string): number {
    return this.generations.get(sessionId) ?? 0;
  }

  getManifest(sessionId: string): BuildFileResult[] {
    return this.manifests.get(sessionId) ?? [];
  }

  /** Fetch the latest manifest for `sessionId` and update the cache
   * (firing change events for anything that differs). */
  async refresh(sessionId: string): Promise<BuildFileResult[]> {
    let files: BuildFileResult[];
    try {
      const res = await this.api.listFiles(sessionId);
      files = res.files;
    } catch {
      files = [];
    }
    this.setManifest(sessionId, files);
    return files;
  }

  /** Update the cache from an already-fetched manifest (used by
   * ExplorerTreeView.refresh() so a single /files call feeds both the
   * tree view and this provider — no duplicate fetch). */
  setManifest(sessionId: string, files: BuildFileResult[]): void {
    const previous = this.manifests.get(sessionId) ?? [];
    const previousPaths = new Set(previous.map((f) => f.path));
    const nextPaths = new Set(files.map((f) => f.path));

    const uri = (relpath: string) => vscode.Uri.parse(`${SCHEME}://${sessionId}/${relpath}`);
    const events: vscode.FileChangeEvent[] = [];
    for (const f of files) {
      const type = previousPaths.has(f.path) ? vscode.FileChangeType.Changed : vscode.FileChangeType.Created;
      events.push({ type, uri: uri(f.path) });
    }
    for (const path of previousPaths) {
      if (!nextPaths.has(path)) {
        events.push({ type: vscode.FileChangeType.Deleted, uri: uri(path) });
      }
    }

    this.manifests.set(sessionId, files);
    this.trees.set(sessionId, buildTree(files));
    this.generations.set(sessionId, this.generation(sessionId) + 1);
    if (events.length) {
      this._onDidChangeFile.fire(events);
    }
  }

  watch(): vscode.Disposable {
    // No polling/SSE for v1 — refresh()/setManifest() (driven by the
    // extension's own turn/build calls) is the entire update mechanism.
    return new vscode.Disposable(() => {});
  }

  stat(uri: vscode.Uri): vscode.FileStat {
    const { sessionId, relpath } = parseUri(uri);
    const tree = this.trees.get(sessionId) ?? buildTree(this.manifests.get(sessionId) ?? []);
    const node = findNode(tree, relpath);
    if (!node) {
      throw vscode.FileSystemError.FileNotFound(uri);
    }
    const time = this.generation(sessionId);
    if (node.file) {
      return { type: vscode.FileType.File, size: 0, mtime: time, ctime: time };
    }
    return { type: vscode.FileType.Directory, size: 0, mtime: time, ctime: time };
  }

  readDirectory(uri: vscode.Uri): [string, vscode.FileType][] {
    const { sessionId, relpath } = parseUri(uri);
    const tree = this.trees.get(sessionId) ?? buildTree(this.manifests.get(sessionId) ?? []);
    const node = findNode(tree, relpath);
    if (!node) {
      throw vscode.FileSystemError.FileNotFound(uri);
    }
    return [...node.children.entries()].map(([name, child]) => [
      name,
      child.file ? vscode.FileType.File : vscode.FileType.Directory,
    ]);
  }

  /** Always fetches live from GET /files/{path} (optionally `?rev=`) —
   * never served from the directory-listing cache — so content is never
   * stale even if a caller reads without refreshing the tree first. */
  async readFile(uri: vscode.Uri): Promise<Uint8Array> {
    const { sessionId, relpath, rev } = parseUri(uri);
    try {
      const res = await this.api.getFileContent(sessionId, relpath, rev);
      return Buffer.from(res.content, "utf-8");
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        throw vscode.FileSystemError.FileNotFound(uri);
      }
      throw e;
    }
  }

  createDirectory(uri: vscode.Uri): void {
    throw vscode.FileSystemError.NoPermissions(uri);
  }

  writeFile(uri: vscode.Uri): void {
    throw vscode.FileSystemError.NoPermissions(uri);
  }

  delete(uri: vscode.Uri): void {
    throw vscode.FileSystemError.NoPermissions(uri);
  }

  rename(oldUri: vscode.Uri): void {
    throw vscode.FileSystemError.NoPermissions(oldUri);
  }
}
