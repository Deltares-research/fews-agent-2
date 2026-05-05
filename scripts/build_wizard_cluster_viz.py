"""Build an interactive wizard-cluster visualization from variable_to_files.json.

Emits a single self-contained HTML at data/variables/wizard_clusters.html
with three coordinated views:

  1. Co-occurrence heatmap of cross-cutting variables, ordered by cluster.
  2. Bipartite force-directed graph (variables x file types).
  3. Cluster summary table with proposed wizard step groupings.

Run:
    python scripts/build_wizard_cluster_viz.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "variables"
OUT = DATA / "wizard_clusters.html"

# Declaration phases from elicitation_strategy_hints.declaration_order.
PHASES = [
    ("registries", ["Parameters", "Qualifiers", "ThresholdWarningLevels",
                    "Locations", "LocationSets"]),
    ("mapping",    ["UnitConversions", "IdMapFile"]),
    ("modules",    ["ImportModule", "PreprocessModule", "ModelRunModule",
                    "DataProcessingModule", "MaintenanceModule",
                    "ModuleParameters", "ModuleInstanceSets",
                    "ModuleInstanceDescriptors"]),
    ("workflows",  ["Workflow"]),
    ("thresholds", ["Thresholds", "ThresholdValueSets",
                    "ValidationRuleSets", "ModifierTypes"]),
    ("ui",         ["Topology", "ManualForecastDisplay", "ModifiersDisplay",
                    "TimeSeriesDisplayConfig", "Permissions", "UserGroups"]),
]
PHASE_OF = {f: phase for phase, files in PHASES for f in files}


def load_variables() -> tuple[list[dict], list[str]]:
    """Return (variables, files). Each variable has name, category, kind,
    declared_in, files (set), paths (list of dicts)."""
    with open(DATA / "variable_to_files.json", encoding="utf-8") as fh:
        doc = json.load(fh)

    variables: list[dict] = []

    def add_section(section: dict, category: str) -> None:
        for name, body in section.items():
            if name == "version":  # static, not elicited
                continue
            files = set()
            paths = []
            for entry in body.get("appears_in", []):
                ft = entry.get("file_type")
                if not ft or ft == "*":
                    continue
                files.add(ft)
                for p in entry.get("paths", []):
                    paths.append({"file": ft, "path": p})
            declared_in = None
            if (d := body.get("declared_in")) and isinstance(d, dict):
                declared_in = d.get("file_type")
                if declared_in and "|" not in declared_in and "(" not in declared_in:
                    files.add(declared_in)
            variables.append({
                "name": name,
                "category": category,
                "kind": body.get("kind", ""),
                "declared_in": declared_in,
                "files": sorted(files),
                "paths": paths,
            })

    add_section(doc.get("shared_cross_file_references", {}), "id_reference")
    add_section(doc.get("shared_substructures", {}), "substructure")
    add_section(doc.get("shared_enums", {}), "enum")

    # per-variable per-file path counts (for sankey ribbon weight)
    for v in variables:
        counts: dict[str, int] = {}
        for p in v["paths"]:
            counts[p["file"]] = counts.get(p["file"], 0) + 1
        for f in v["files"]:
            counts.setdefault(f, 1)  # files added via declared_in only
        v["file_counts"] = counts

    files = sorted({f for v in variables for f in v["files"]})
    return variables, files


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster_variables(variables: list[dict], threshold: float = 0.5) -> list[list[int]]:
    """Single-linkage agglomerative clustering on (1 - Jaccard) distance.
    Merges while min inter-cluster distance <= 1 - threshold."""
    n = len(variables)
    sets = [set(v["files"]) for v in variables]
    sim = [[jaccard(sets[i], sets[j]) for j in range(n)] for i in range(n)]
    clusters = [[i] for i in range(n)]
    cutoff = threshold
    while len(clusters) > 1:
        best = (-1.0, -1, -1)
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                # single linkage: max similarity (= min distance)
                s = max(sim[a][b] for a in clusters[i] for b in clusters[j])
                if s > best[0]:
                    best = (s, i, j)
        if best[0] < cutoff:
            break
        _, i, j = best
        clusters[i] = clusters[i] + clusters[j]
        clusters.pop(j)
    # order: largest first, then by total file-reach desc
    clusters.sort(
        key=lambda c: (-len(c), -sum(len(variables[k]["files"]) for k in c))
    )
    return clusters


def suggest_step_label(members: list[dict]) -> str:
    """Heuristic: name a cluster after its dominant theme."""
    names = {m["name"] for m in members}
    if names & {"timeSeriesSet", "timeStep", "relativeViewPeriod",
                "valueType", "timeSeriesType", "readWriteMode"}:
        return "Time-series specification"
    if names & {"parameterId", "qualifierId"}:
        return "Parameter declaration"
    if names & {"locationId", "locationSetId"}:
        return "Location declaration"
    if names & {"moduleInstanceId", "workflowId"}:
        return "Module / workflow wiring"
    if names & {"idMapId", "unitConversionsId"}:
        return "Mapping & unit conversion"
    if names & {"warningLevelId", "levelThresholdId"}:
        return "Thresholds & warning levels"
    if names & {"modifierId"}:
        return "Modifiers"
    if names & {"userGroupId"}:
        return "Permissions"
    if names & {"variableId"}:
        return "Module-local variables"
    return ", ".join(sorted(names))[:60]


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FEWS wizard cluster explorer</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/d3-sankey@0.12.3/dist/d3-sankey.min.js"></script>
<style>
  body { font: 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         margin: 0; padding: 16px; background: #fafafa; color: #222; }
  h1 { font-size: 18px; margin: 0 0 4px 0; }
  .sub { color: #666; margin-bottom: 14px; }
  .tabs { display: flex; gap: 4px; margin-bottom: 12px; border-bottom: 1px solid #ddd; }
  .tab { padding: 8px 14px; cursor: pointer; border: 1px solid transparent;
         border-bottom: none; border-radius: 4px 4px 0 0; }
  .tab.active { background: #fff; border-color: #ddd; font-weight: 600; }
  .panel { display: none; background: #fff; border: 1px solid #ddd;
           border-radius: 0 4px 4px 4px; padding: 14px; min-height: 600px; }
  .panel.active { display: block; }
  .legend { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 10px;
            font-size: 12px; color: #444; }
  .legend span.swatch { display: inline-block; width: 12px; height: 12px;
                        border-radius: 2px; margin-right: 4px; vertical-align: middle; }
  table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
  th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #eee;
           vertical-align: top; }
  th { background: #f4f4f4; font-weight: 600; }
  td.cluster-name { font-weight: 600; }
  td.tags span { display: inline-block; background: #eef; color: #225;
                 padding: 1px 6px; margin: 1px 2px 1px 0; border-radius: 3px;
                 font-size: 11.5px; }
  td.files span { display: inline-block; padding: 1px 6px; margin: 1px 2px 1px 0;
                  border-radius: 3px; font-size: 11.5px; color: #fff; }
  .reach-row { display: flex; align-items: center; gap: 6px; margin: 2px 0; }
  .reach-name { flex: 0 0 160px; font-family: ui-monospace, monospace; font-size: 11.5px; }
  .reach-bar-bg { flex: 1; height: 12px; background: #f0f0f0; border-radius: 2px; position: relative; }
  .reach-bar { height: 100%; border-radius: 2px; }
  .reach-count { flex: 0 0 28px; text-align: right; font-size: 11px; color: #666; }
  text.tick { font-size: 10.5px; fill: #333; }
  .tooltip { position: absolute; pointer-events: none; background: #222;
             color: #fff; padding: 6px 8px; border-radius: 3px; font-size: 12px;
             max-width: 320px; opacity: 0; transition: opacity 0.1s; }
  rect.cell { stroke: #fff; stroke-width: 0.5; }
  rect.cluster-frame { fill: none; stroke: #ff5500; stroke-width: 2; }
  .node circle, .node rect { stroke: #fff; stroke-width: 1.2; cursor: pointer; }
  .link { stroke: #999; stroke-opacity: 0.35; }
  .node text { font-size: 11px; pointer-events: none; }
  .sankey-node rect { stroke: #fff; stroke-width: 1; cursor: pointer; }
  .sankey-node text { font-size: 11.5px; pointer-events: none; }
  .sankey-link { fill: none; stroke-opacity: 0.35; transition: stroke-opacity 0.15s; }
  .sankey-link.dim { stroke-opacity: 0.06; }
  .sankey-link.hi { stroke-opacity: 0.75; }
</style>
</head>
<body>
<h1>FEWS wizard cluster explorer</h1>
<div class="sub">Cross-cutting variables grouped by file-set similarity (single-linkage, Jaccard &ge; __THRESHOLD__).
Each cluster is a candidate wizard step.</div>

<div class="tabs">
  <div class="tab active" data-panel="sankey">Variable &rarr; file flow</div>
  <div class="tab" data-panel="clusters">Cluster summary</div>
  <div class="tab" data-panel="heatmap">Co-occurrence heatmap</div>
  <div class="tab" data-panel="bipartite">Bipartite graph</div>
</div>

<div id="panel-sankey" class="panel active">
  <div class="legend">
    Each variable on the left flows into every file it contributes to.
    Ribbon thickness = number of distinct paths.
    Hover a variable to isolate its reach.
  </div>
  <svg id="sankey" width="1200" height="780"></svg>
</div>

<div id="panel-clusters" class="panel">
  <div class="legend">
    <span><span class="swatch" style="background:#4e79a7"></span>id reference</span>
    <span><span class="swatch" style="background:#f28e2b"></span>substructure</span>
    <span><span class="swatch" style="background:#59a14f"></span>enum</span>
    <span style="margin-left:24px"><b>File phase:</b></span>
    <span><span class="swatch" style="background:#9c755f"></span>registries</span>
    <span><span class="swatch" style="background:#bab0ab"></span>mapping</span>
    <span><span class="swatch" style="background:#76b7b2"></span>modules</span>
    <span><span class="swatch" style="background:#edc949"></span>workflows</span>
    <span><span class="swatch" style="background:#e15759"></span>thresholds</span>
    <span><span class="swatch" style="background:#b07aa1"></span>ui</span>
  </div>
  <table id="cluster-table">
    <thead><tr>
      <th style="width:18%">Suggested wizard step</th>
      <th style="width:32%">Variables</th>
      <th>Files reached</th>
    </tr></thead>
    <tbody></tbody>
  </table>
</div>

<div id="panel-heatmap" class="panel">
  <div class="legend">
    Cell = Jaccard(filesA &cap; filesB / filesA &cup; filesB).
    Variables ordered by cluster (orange frames).
  </div>
  <svg id="heatmap"></svg>
</div>

<div id="panel-bipartite" class="panel">
  <div class="legend">
    Circles = variables (color = category). Squares = file types (color = phase).
    Drag nodes; hover for details.
  </div>
  <svg id="bipartite" width="1100" height="700"></svg>
</div>

<div id="tt" class="tooltip"></div>

<script>
const DATA = __DATA__;
const CAT_COLOR = {id_reference: "#4e79a7", substructure: "#f28e2b", enum: "#59a14f"};
const PHASE_COLOR = {registries: "#9c755f", mapping: "#bab0ab", modules: "#76b7b2",
                     workflows: "#edc949", thresholds: "#e15759", ui: "#b07aa1",
                     "": "#888"};

document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
  document.querySelectorAll(".panel").forEach(x => x.classList.remove("active"));
  t.classList.add("active");
  document.getElementById("panel-" + t.dataset.panel).classList.add("active");
}));

const tt = d3.select("#tt");
const showTip = (html, e) => tt.html(html).style("opacity", 1)
  .style("left", (e.pageX + 12) + "px").style("top", (e.pageY + 12) + "px");
const hideTip = () => tt.style("opacity", 0);

// ---- cluster summary table with reach bars ----
const maxReach = d3.max(DATA.variables, v => v.files.length);
const tbody = d3.select("#cluster-table tbody");
DATA.clusters.forEach(cl => {
  const tr = tbody.append("tr");
  tr.append("td").attr("class", "cluster-name").text(cl.label);
  const vt = tr.append("td");
  cl.members.forEach(m => {
    const v = DATA.variables[m];
    const row = vt.append("div").attr("class", "reach-row");
    row.append("div").attr("class", "reach-name")
       .style("color", CAT_COLOR[v.category]).text(v.name);
    const bg = row.append("div").attr("class", "reach-bar-bg");
    bg.append("div").attr("class", "reach-bar")
       .style("width", (100 * v.files.length / maxReach) + "%")
       .style("background", CAT_COLOR[v.category]);
    row.append("div").attr("class", "reach-count").text(v.files.length);
  });
  const ft = tr.append("td").attr("class", "files");
  const allFiles = new Set();
  cl.members.forEach(m => DATA.variables[m].files.forEach(f => allFiles.add(f)));
  Array.from(allFiles).sort().forEach(f => {
    ft.append("span").style("background", PHASE_COLOR[DATA.file_phase[f] || ""])
      .text(f);
  });
});

// ---- sankey ----
const skW = 1200, skH = 780;
const sk = d3.select("#sankey");
const phaseOrder = {registries: 0, mapping: 1, modules: 2, workflows: 3,
                    thresholds: 4, ui: 5, "": 6};
// sort variables by file-reach desc; sort files by phase then name
const varOrder = DATA.variables.map((v, i) => i)
  .sort((a, b) => DATA.variables[b].files.length - DATA.variables[a].files.length
                  || DATA.variables[a].name.localeCompare(DATA.variables[b].name));
const fileOrder = DATA.files.slice().sort((a, b) => {
  const pa = phaseOrder[DATA.file_phase[a] || ""];
  const pb = phaseOrder[DATA.file_phase[b] || ""];
  return pa - pb || a.localeCompare(b);
});

const skNodes = [];
const nodeIdx = {};
varOrder.forEach(i => {
  nodeIdx["v:" + DATA.variables[i].name] = skNodes.length;
  skNodes.push({name: DATA.variables[i].name, side: "var",
                category: DATA.variables[i].category,
                files: DATA.variables[i].files.length});
});
fileOrder.forEach(f => {
  nodeIdx["f:" + f] = skNodes.length;
  skNodes.push({name: f, side: "file", phase: DATA.file_phase[f] || ""});
});
const skLinks = [];
DATA.variables.forEach(v => {
  Object.entries(v.file_counts).forEach(([f, c]) => {
    skLinks.push({
      source: nodeIdx["v:" + v.name],
      target: nodeIdx["f:" + f],
      value: c,
      varName: v.name,
      category: v.category,
    });
  });
});

const sankey = d3.sankey()
  .nodeWidth(14).nodePadding(6)
  .nodeSort((a, b) => 0)  // keep our pre-sort
  .extent([[180, 10], [skW - 220, skH - 10]]);

const skGraph = sankey({
  nodes: skNodes.map(d => Object.assign({}, d)),
  links: skLinks.map(d => Object.assign({}, d)),
});

const skLink = sk.append("g").selectAll("path").data(skGraph.links).enter().append("path")
  .attr("class", "sankey-link")
  .attr("d", d3.sankeyLinkHorizontal())
  .attr("stroke", d => CAT_COLOR[d.category])
  .attr("stroke-width", d => Math.max(1, d.width))
  .on("mouseover", function(e, d) {
    skLink.classed("dim", true).classed("hi", false);
    d3.select(this).classed("dim", false).classed("hi", true);
    showTip(`<b>${d.varName}</b> &rarr; <b>${d.target.name}</b><br>` +
            `paths: ${d.value}`, e);
  })
  .on("mousemove", e => tt.style("left", (e.pageX + 12) + "px")
                          .style("top", (e.pageY + 12) + "px"))
  .on("mouseout", () => { skLink.classed("dim", false).classed("hi", false); hideTip(); });

const skNode = sk.append("g").selectAll("g").data(skGraph.nodes).enter().append("g")
  .attr("class", "sankey-node");

skNode.append("rect")
  .attr("x", d => d.x0).attr("y", d => d.y0)
  .attr("width", d => d.x1 - d.x0).attr("height", d => Math.max(1, d.y1 - d.y0))
  .attr("fill", d => d.side === "var" ? CAT_COLOR[d.category] : PHASE_COLOR[d.phase])
  .on("mouseover", (e, d) => {
    if (d.side === "var") {
      skLink.classed("dim", l => l.source.index !== d.index)
            .classed("hi", l => l.source.index === d.index);
      showTip(`<b>${d.name}</b><br>category: ${d.category}<br>` +
              `reaches ${d.files} file${d.files === 1 ? "" : "s"}`, e);
    } else {
      skLink.classed("dim", l => l.target.index !== d.index)
            .classed("hi", l => l.target.index === d.index);
      showTip(`<b>${d.name}</b><br>phase: ${d.phase || "(unassigned)"}`, e);
    }
  })
  .on("mousemove", e => tt.style("left", (e.pageX + 12) + "px")
                          .style("top", (e.pageY + 12) + "px"))
  .on("mouseout", () => { skLink.classed("dim", false).classed("hi", false); hideTip(); });

skNode.append("text")
  .attr("x", d => d.side === "var" ? d.x0 - 6 : d.x1 + 6)
  .attr("y", d => (d.y0 + d.y1) / 2)
  .attr("dy", "0.35em")
  .attr("text-anchor", d => d.side === "var" ? "end" : "start")
  .text(d => d.name);

// section labels for sankey
sk.append("text").attr("x", 180).attr("y", 28)
  .attr("font-weight", 600).attr("text-anchor", "end")
  .text("variables (sorted by reach)");
sk.append("text").attr("x", skW - 220).attr("y", 28)
  .attr("font-weight", 600).attr("text-anchor", "start")
  .text("files (grouped by phase)");

// ---- heatmap ----
const HM_CELL = 22;
const HM_PAD = {top: 180, left: 200, right: 20, bottom: 20};
const order = DATA.heatmap_order;
const N = order.length;
const hmW = HM_PAD.left + N * HM_CELL + HM_PAD.right;
const hmH = HM_PAD.top + N * HM_CELL + HM_PAD.bottom;
const hm = d3.select("#heatmap").attr("width", hmW).attr("height", hmH);
const color = d3.scaleSequential(d3.interpolateBlues).domain([0, 1]);

for (let i = 0; i < N; i++) {
  for (let j = 0; j < N; j++) {
    const vi = DATA.variables[order[i]], vj = DATA.variables[order[j]];
    const s = DATA.sim[order[i]][order[j]];
    hm.append("rect").attr("class", "cell")
      .attr("x", HM_PAD.left + j * HM_CELL).attr("y", HM_PAD.top + i * HM_CELL)
      .attr("width", HM_CELL).attr("height", HM_CELL)
      .attr("fill", i === j ? "#222" : color(s))
      .on("mouseover", e => showTip(
        `<b>${vi.name}</b> &harr; <b>${vj.name}</b><br>Jaccard: ${s.toFixed(2)}`, e))
      .on("mousemove", e => showTip(
        `<b>${vi.name}</b> &harr; <b>${vj.name}</b><br>Jaccard: ${s.toFixed(2)}`, e))
      .on("mouseout", hideTip);
  }
}
order.forEach((idx, i) => {
  const v = DATA.variables[idx];
  hm.append("text").attr("class", "tick")
    .attr("x", HM_PAD.left - 6).attr("y", HM_PAD.top + i * HM_CELL + HM_CELL * 0.7)
    .attr("text-anchor", "end").attr("fill", CAT_COLOR[v.category]).text(v.name);
  hm.append("text").attr("class", "tick")
    .attr("transform",
      `translate(${HM_PAD.left + i * HM_CELL + HM_CELL * 0.7}, ${HM_PAD.top - 6}) rotate(-60)`)
    .attr("fill", CAT_COLOR[v.category]).text(v.name);
});
// cluster frames
let cursor = 0;
DATA.clusters.forEach(cl => {
  const sz = cl.members.length;
  hm.append("rect").attr("class", "cluster-frame")
    .attr("x", HM_PAD.left + cursor * HM_CELL).attr("y", HM_PAD.top + cursor * HM_CELL)
    .attr("width", sz * HM_CELL).attr("height", sz * HM_CELL);
  cursor += sz;
});

// ---- bipartite force ----
const bpW = 1100, bpH = 700;
const bp = d3.select("#bipartite");
const nodes = [
  ...DATA.variables.map((v, i) => ({id: "v:" + v.name, type: "var", idx: i, ...v})),
  ...DATA.files.map(f => ({id: "f:" + f, type: "file", name: f, phase: DATA.file_phase[f] || ""})),
];
const links = [];
DATA.variables.forEach(v => v.files.forEach(f => {
  links.push({source: "v:" + v.name, target: "f:" + f});
}));

const sim = d3.forceSimulation(nodes)
  .force("link", d3.forceLink(links).id(d => d.id).distance(80).strength(0.4))
  .force("charge", d3.forceManyBody().strength(-220))
  .force("x", d3.forceX(d => d.type === "var" ? bpW * 0.32 : bpW * 0.68).strength(0.18))
  .force("y", d3.forceY(bpH / 2).strength(0.05))
  .force("collide", d3.forceCollide(18));

const link = bp.append("g").selectAll("line").data(links).enter().append("line")
  .attr("class", "link");

const node = bp.append("g").selectAll("g").data(nodes).enter().append("g")
  .attr("class", "node")
  .call(d3.drag()
    .on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
    .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; })
    .on("end", (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

node.each(function(d) {
  const g = d3.select(this);
  if (d.type === "var") {
    g.append("circle").attr("r", 8).attr("fill", CAT_COLOR[d.category]);
  } else {
    g.append("rect").attr("x", -7).attr("y", -7).attr("width", 14).attr("height", 14)
      .attr("fill", PHASE_COLOR[d.phase]);
  }
  g.append("text").attr("dx", 11).attr("dy", 4).text(d.name);
});

node.on("mouseover", (e, d) => {
  if (d.type === "var") {
    showTip(`<b>${d.name}</b><br>kind: ${d.kind}<br>category: ${d.category}` +
            `<br>files: ${d.files.length}`, e);
  } else {
    showTip(`<b>${d.name}</b><br>phase: ${d.phase || "(unassigned)"}`, e);
  }
}).on("mousemove", (e, d) => tt.style("left", (e.pageX + 12) + "px")
                                 .style("top", (e.pageY + 12) + "px"))
  .on("mouseout", hideTip);

sim.on("tick", () => {
  link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
  node.attr("transform", d => `translate(${d.x},${d.y})`);
});
</script>
</body>
</html>
"""


def main(threshold: float = 0.5) -> None:
    variables, files = load_variables()
    n = len(variables)

    sets = [set(v["files"]) for v in variables]
    sim = [[jaccard(sets[i], sets[j]) for j in range(n)] for i in range(n)]

    clusters_idx = cluster_variables(variables, threshold=threshold)

    clusters_out = []
    heatmap_order = []
    for cl in clusters_idx:
        members = [variables[i] for i in cl]
        # within a cluster, sort by reach desc for stable display
        cl_sorted = sorted(cl, key=lambda i: -len(variables[i]["files"]))
        heatmap_order.extend(cl_sorted)
        clusters_out.append({
            "label": suggest_step_label(members),
            "members": cl_sorted,
        })

    file_phase = {f: PHASE_OF.get(f, "") for f in files}

    payload = {
        "variables": variables,
        "files": files,
        "file_phase": file_phase,
        "sim": sim,
        "clusters": clusters_out,
        "heatmap_order": heatmap_order,
    }

    html = HTML.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    html = html.replace("__THRESHOLD__", f"{threshold:.2f}")
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"  variables: {n}")
    print(f"  files: {len(files)}")
    print(f"  clusters: {len(clusters_out)}")
    for c in clusters_out:
        print(f"    - {c['label']}: {[variables[i]['name'] for i in c['members']]}")


if __name__ == "__main__":
    main()
