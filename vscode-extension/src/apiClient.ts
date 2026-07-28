import {
  BuildRequest,
  BuildResponse,
  CreateSessionResponse,
  FileContentResponse,
  FilesResponse,
  HealthResponse,
  ModulesResponse,
  PreviewResponse,
  RouteResponse,
  SessionStateResponse,
  TurnResponse,
} from "./types";

/** An error response from the FEWS agent API — `detail` is FastAPI's
 * standard error body field (a plain message, or a JSON-stringified
 * structured detail for the 409 "warnings" case). */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(`FEWS agent API ${status}: ${detail}`);
  }
}

/** Thin fetch wrapper over app/api/server.py. Every call goes through this
 * — the extension never assumes it shares a filesystem or git repo with
 * the running agent (local uvicorn, or the Azure VM behind an SSH tunnel). */
export class ApiClient {
  constructor(private readonly getBaseUrl: () => string) {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const base = this.getBaseUrl().replace(/\/+$/, "");
    const res = await fetch(`${base}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = (await res.json()) as { detail?: unknown };
        if (body && body.detail !== undefined) {
          detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
        }
      } catch {
        // Response body wasn't JSON — fall back to statusText.
      }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as T;
  }

  health(): Promise<HealthResponse> {
    return this.request<HealthResponse>("/health");
  }

  createSession(projectName?: string, model?: string): Promise<CreateSessionResponse> {
    return this.request<CreateSessionResponse>("/sessions", {
      method: "POST",
      body: JSON.stringify({ project_name: projectName, model }),
    });
  }

  getSession(sessionId: string): Promise<SessionStateResponse> {
    return this.request<SessionStateResponse>(`/sessions/${encodeURIComponent(sessionId)}`);
  }

  turn(sessionId: string, message: string): Promise<TurnResponse> {
    return this.request<TurnResponse>(`/sessions/${encodeURIComponent(sessionId)}/turn`, {
      method: "POST",
      body: JSON.stringify({ message }),
    });
  }

  build(sessionId: string, req: BuildRequest = {}): Promise<BuildResponse> {
    return this.request<BuildResponse>(`/sessions/${encodeURIComponent(sessionId)}/build`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  }

  listFiles(sessionId: string): Promise<FilesResponse> {
    return this.request<FilesResponse>(`/sessions/${encodeURIComponent(sessionId)}/files`);
  }

  /** `rev` accepts "prev" (the natural diff baseline — before the last
   * build), "HEAD"/"HEAD~<n>", or an explicit commit sha; omit for the
   * current on-disk content. */
  getFileContent(sessionId: string, relpath: string, rev?: string): Promise<FileContentResponse> {
    const encodedPath = relpath
      .split("/")
      .filter(Boolean)
      .map(encodeURIComponent)
      .join("/");
    const qs = rev ? `?rev=${encodeURIComponent(rev)}` : "";
    return this.request<FileContentResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/files/${encodedPath}${qs}`,
    );
  }

  getRoute(sessionId: string): Promise<RouteResponse> {
    return this.request<RouteResponse>(`/sessions/${encodeURIComponent(sessionId)}/route`);
  }

  getModules(sessionId: string): Promise<ModulesResponse> {
    return this.request<ModulesResponse>(`/sessions/${encodeURIComponent(sessionId)}/modules`);
  }

  preview(sessionId: string, target: string): Promise<PreviewResponse> {
    return this.request<PreviewResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/preview?target=${encodeURIComponent(target)}`,
    );
  }
}
