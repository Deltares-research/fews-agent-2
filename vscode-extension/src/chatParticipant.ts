import * as vscode from "vscode";
import { ApiClient, ApiError } from "./apiClient";
import { SessionManager } from "./sessionManager";
import { BuildResponse, ModulesResponse, PreviewResponse, RouteResponse, TurnResponse } from "./types";

export const PARTICIPANT_ID = "fews-agent.chat";

const STATUS_BADGE: Record<string, string> = {
  built: "🟢",
  stale: "🟠",
  forced: "🟠",
  none: "⚪",
};

function renderStatusMarkdown(route: RouteResponse, modules: ModulesResponse): string {
  const lines: string[] = [];
  lines.push(`**Route** — current step: ${route.current ?? "_(none — ready to assemble)_"}`);
  if (route.blocking_open.length) {
    lines.push(`- Blocking: ${route.blocking_open.join(", ")}`);
  }
  if (route.advisory_open.length) {
    lines.push(`- Advisory: ${route.advisory_open.join(", ")}`);
  }
  lines.push(route.ready_to_assemble ? "Ready to assemble." : "Not ready to assemble yet.");
  lines.push("");
  lines.push("**Modules**");
  for (const m of modules.modules) {
    const badge = STATUS_BADGE[m.status] ?? "⚪";
    lines.push(`${badge} ${m.label}${m.focused ? " _(focused)_" : ""}`);
  }
  return lines.join("\n");
}

function renderBuildMarkdown(build: BuildResponse): string {
  const status = build.ok ? "✅" : "⚠️";
  const lines = [
    `${status} Built (${build.scope}) — ${build.files_xsd_ok}/${build.files_xml} XSD-valid` +
      (build.files_non_xml ? `, ${build.files_non_xml} non-XML` : "") +
      ".",
  ];
  for (const e of build.errors) {
    lines.push(`- ⚠️ ${e}`);
  }
  return lines.join("\n");
}

/** Chat-ready markdown for a live/last-build preview — mirrors
 * fews_agent/agent/preview.py's format_previews so the extension renders
 * previews the same way chat replies in the other shells do. */
export function formatPreviewMarkdown(preview: PreviewResponse): string {
  if (!preview.files.length) {
    return (
      `Nothing in the project matches **${preview.target}** — nothing to preview. ` +
      "(Configured sources render live; files produced only at assembly appear " +
      "here after a build.)"
    );
  }
  const parts: string[] = [`# Preview: ${preview.target}`];
  for (const f of preview.files) {
    const badge = f.xsd_ok === true ? "✅ XSD-valid" : f.xsd_ok === false ? "❌ XSD-INVALID" : "(not XML)";
    parts.push(`**\`${f.relpath}\`** · ${badge} · _${f.source}_`);
    const lang = f.relpath.toLowerCase().endsWith(".xml") ? "xml" : "";
    parts.push("```" + lang + "\n" + f.content + "\n```");
  }
  return parts.join("\n\n");
}

/** The @fews chat participant's request handler. Every reply comes from
 * this repo's own agent via POST /turn — Copilot's model is never used for
 * generation, only VS Code's chat transport (stream, request.prompt) is
 * reused. */
export function makeChatHandler(
  api: ApiClient,
  sessions: SessionManager,
  onProjectChanged: vscode.EventEmitter<void>,
): vscode.ChatRequestHandler {
  return async (
    request: vscode.ChatRequest,
    _context: vscode.ChatContext,
    stream: vscode.ChatResponseStream,
    _token: vscode.CancellationToken,
  ) => {
    const sessionId = await sessions.ensure();

    if (request.command === "new") {
      await sessions.reset();
      stream.markdown("Started a fresh FEWS agent session — your next message begins it.");
      return;
    }

    if (request.command === "status") {
      const [route, modules] = await Promise.all([api.getRoute(sessionId), api.getModules(sessionId)]);
      stream.markdown(renderStatusMarkdown(route, modules));
      return;
    }

    if (request.command === "build") {
      stream.progress("Building…");
      try {
        const build = await api.build(sessionId, {});
        stream.markdown(renderBuildMarkdown(build));
      } catch (e) {
        stream.markdown(`⚠️ Build failed: ${e instanceof ApiError ? e.detail : String(e)}`);
      } finally {
        onProjectChanged.fire();
      }
      return;
    }

    if (!request.prompt.trim()) {
      stream.markdown(
        'Tell me what to configure (e.g. "import NOAA GFS grids, no basin model"), ' +
          "or use `/status`, `/build`, `/new`.",
      );
      return;
    }

    stream.progress("Thinking…");
    let turn: TurnResponse;
    try {
      turn = await api.turn(sessionId, request.prompt);
    } catch (e) {
      if (e instanceof ApiError && e.status === 503) {
        stream.markdown(
          `⚠️ The agent's LLM backend isn't reachable right now (${e.detail}). ` +
            "This doesn't affect the deterministic build path — `/build` still works.",
        );
        return;
      }
      throw e;
    }

    if (turn.confirmation) {
      stream.markdown(`_${turn.confirmation}_\n\n`);
    }
    stream.markdown(turn.reply);

    for (const label of turn.new_patterns) {
      stream.button({
        command: "fewsAgent.previewFromChat",
        title: `Preview ${label}`,
        arguments: [label],
      });
    }
    if (turn.wants_build) {
      stream.button({ command: "fewsAgent.build", title: "Build now", arguments: [{}] });
    }

    // A turn can also write input files or resolve new patterns — always
    // refresh so the sidebar/file tree never needs a manual pull. This is
    // the entire "container regenerated, IDE updates automatically"
    // mechanism for v1: no polling, no server push, just refresh right
    // after every action the extension itself took.
    onProjectChanged.fire();
  };
}
