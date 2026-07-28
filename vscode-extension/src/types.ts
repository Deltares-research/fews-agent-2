// TypeScript mirrors of the Pydantic response models in app/api/models.py.
// Keep in sync by hand — there is no shared codegen between the two sides.

export interface BuildFileResult {
  path: string;
  xsd_ok: boolean;
  xsd_msg?: string | null;
  byte_equivalent?: boolean | null;
}

export interface FilesResponse {
  built: boolean;
  files: BuildFileResult[];
}

export interface FileContentResponse {
  relpath: string;
  content: string;
  source: string; // "generated" | "rev:<rev>"
}

export interface LegModel {
  id: string;
  title: string;
  kind: "blocking" | "advisory";
  active: boolean;
  done: boolean;
  guidance: string;
  detail: string;
}

export interface RouteResponse {
  legs: LegModel[];
  current: string | null;
  blocking_open: string[];
  advisory_open: string[];
  ready_to_assemble: boolean;
  assembled: boolean;
}

export interface ModuleStatusModel {
  key: string;
  label: string;
  built: boolean;
  status: "built" | "none" | "forced" | "stale";
  focused: boolean;
}

export interface ModulesResponse {
  modules: ModuleStatusModel[];
}

export interface PreviewFileModel {
  relpath: string;
  content: string;
  xsd_ok: boolean | null;
  source: string; // "live render" | "last build"
  label: string;
}

export interface PreviewResponse {
  target: string;
  files: PreviewFileModel[];
}

export interface CreateSessionResponse {
  session_id: string;
  project_name: string;
  project_dir: string;
  model: string;
}

export interface SessionStateResponse {
  session_id: string;
  project_name: string;
  intent: string | null;
  slots: Record<string, unknown>;
  patterns: Array<Record<string, unknown>>;
  warnings: string[];
  built_phases: string[];
}

export interface TurnResponse {
  reply: string;
  short_circuit: boolean;
  intent: string | null;
  patterns: Array<Record<string, unknown>>;
  slots: Record<string, unknown>;
  warnings: string[];
  ready: boolean;
  next_question: string | null;
  new_patterns: string[];
  internals: string | null;
  module_mode: boolean;
  current_module: string | null;
  wants_build: boolean;
  confirmation: string;
}

export interface BuildRequest {
  force?: boolean;
  phase?: string;
  module?: string;
}

export interface BuildResponse {
  ok: boolean;
  scope: string;
  built_phases: string[];
  blueprint?: string | null;
  project_yaml: string;
  output_root?: string | null;
  files_total: number;
  files_xml: number;
  files_non_xml: number;
  files_xsd_ok: number;
  errors: string[];
  unbacked_interpolation_sets: string[];
  files: BuildFileResult[];
}

export interface HealthResponse {
  status: string;
  provider: string;
  model: string;
  ollama_reachable: boolean;
  detail?: string | null;
}
