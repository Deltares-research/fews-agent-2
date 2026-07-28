import * as vscode from "vscode";
import { SessionManager } from "./sessionManager";
import { SCHEME } from "./fewsFileSystemProvider";

/** Diff a generated file's current content against its content before the
 * most recent build (`?rev=prev`, resolved server-side to HEAD~1 in the
 * session's own git repo). Both sides resolve through
 * FewsFileSystemProvider.readFile, so no client-side diffing is
 * implemented here — VS Code's native diff editor does the comparison.
 * A brand-new file (nothing existed at `prev`) renders as an empty left
 * pane; the provider throws FileNotFound for that side, which vscode.diff
 * handles gracefully. */
export async function showDiffSinceLastBuild(sessions: SessionManager, relpath: string): Promise<void> {
  const sessionId = sessions.current();
  if (!sessionId) {
    vscode.window.showWarningMessage("No FEWS agent session yet.");
    return;
  }
  const current = vscode.Uri.parse(`${SCHEME}://${sessionId}/${relpath}`);
  const previous = vscode.Uri.parse(`${SCHEME}://${sessionId}/${relpath}?rev=prev`);
  await vscode.commands.executeCommand(
    "vscode.diff",
    previous,
    current,
    `${relpath} (before last build ↔ current)`,
  );
}
