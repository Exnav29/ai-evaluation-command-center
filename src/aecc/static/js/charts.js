/* AECC Milestone 1 charts — progressive enhancement over server tables.
 * Reads embedded JSON payloads, renders Apache ECharts panels, wires
 * tooltips + click drill-down. Tables remain authoritative when JS is off.
 */
(function () {
  "use strict";

  var PASS = "#34d399";
  var FINDINGS = "#a7f3d0";
  var REVIEW = "#fbbf24";
  var FAIL = "#f87171";
  var INFRA = "#fb923c";
  var EXCLUDED = "#c084fc";
  var UNKNOWN = "#8ca0b3";
  var ACCENT = "#5b8cff";
  var INK = "#eaf0f6";
  var MUTED = "#8ca0b3";

  function reducedMotion() {
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (e) {
      return false;
    }
  }

  function baseTooltip(extra) {
    return {
      trigger: "item",
      backgroundColor: "#131c26",
      borderColor: "#243242",
      borderWidth: 1,
      textStyle: { color: INK, fontSize: 12 },
      confine: true,
      formatter: extra || "{b}: <b>{c}</b>"
    };
  }

  function commonText() {
    return { color: INK, fontFamily: "Inter,system-ui,sans-serif" };
  }

  function mount(id, build) {
    var el = document.getElementById(id);
    if (!el || typeof window.echarts === "undefined") return null;
    var dataEl = document.getElementById(id + "-data");
    if (!dataEl) return null;
    var payload;
    try {
      payload = JSON.parse(dataEl.textContent || "{}");
    } catch (e) {
      return null;
    }
    var chart = window.echarts.init(el, null, { renderer: "canvas" });
    var animate = !reducedMotion();
    var option = build(payload, animate);
    if (!option) return null;
    chart.setOption(option);
    var onResize = function () { try { chart.resize(); } catch (e) {} };
    window.addEventListener("resize", onResize);
    if (typeof ResizeObserver !== "undefined") {
      try { new ResizeObserver(onResize).observe(el); } catch (e) {}
    }
    return { chart: chart, payload: payload };
  }

  function shortLabel(s, n) {
    s = String(s || "");
    if (s.length > (n || 22)) return s.slice(0, (n || 22) - 1) + "…";
    return s;
  }

  function initQualDonut(id) {
    return mount(id, function (p, animate) {
      var labels = p.labels || [];
      var counts = p.counts || [];
      var total = p.triples_total || 0;
      var colors = { QUALIFIED: PASS, SHADOW: REVIEW, RESTRICTED: INFRA, UNQUALIFIED: UNKNOWN, NOT_AUTHORIZED: EXCLUDED };
      var data = labels.map(function (l, i) {
        return {
          name: l + " (" + (counts[i] || 0) + ")",
          value: counts[i] || 0,
          itemStyle: {
            color: colors[l] || MUTED,
            borderColor: "#0b1118",
            borderWidth: 2,
            borderType: l === "SHADOW" || l === "UNQUALIFIED" ? "dashed" : "solid",
            shadowBlur: (counts[i] || 0) > 0 ? 12 : 0,
            shadowColor: "rgba(91,140,255,0.25)"
          }
        };
      });
      if (!total) {
        return {
          backgroundColor: "transparent",
          textStyle: commonText(),
          graphic: { type: "text", left: "center", top: "middle", style: { text: "No qualification decisions yet", fill: MUTED, fontSize: 13 } }
        };
      }
      return {
        backgroundColor: "transparent",
        textStyle: commonText(),
        animationDuration: animate ? 450 : 0,
        tooltip: Object.assign(baseTooltip(), {
          formatter: function (params) {
            return params.marker + " " + params.name + "<br/>Triples: <b>" + params.value + "</b> of " + total;
          }
        }),
        legend: { bottom: 0, textStyle: { color: MUTED, fontSize: 11 }, inactiveColor: "#3b4c60" },
        series: [{
          type: "pie",
          radius: ["56%", "78%"],
          center: ["50%", "44%"],
          avoidLabelOverlap: true,
          label: { color: INK, fontSize: 11, formatter: "{b}" },
          labelLine: { lineStyle: { color: "#3b4c60" } },
          emphasis: { scale: true, scaleSize: 4 },
          data: data
        }],
        graphic: { type: "text", left: "center", top: "36%", style: { text: total + "\ntriples", fill: INK, fontSize: 15, fontWeight: 700, textAlign: "center" } }
      };
    });
  }

  function verdictSeries(groups) {
    var cats = ["PASS", "PASS_WITH_FINDINGS", "NEEDS_REVIEW", "FAIL", "INFRASTRUCTURE_FAILURE", "EXCLUDED", "UNKNOWN"];
    var colors = { PASS: PASS, PASS_WITH_FINDINGS: FINDINGS, NEEDS_REVIEW: REVIEW, FAIL: FAIL, INFRASTRUCTURE_FAILURE: INFRA, EXCLUDED: EXCLUDED, UNKNOWN: UNKNOWN };
    return cats.map(function (c) {
      return {
        name: c,
        type: "bar",
        stack: "verdict",
        barMaxWidth: 26,
        itemStyle: {
          color: colors[c],
          borderType: c === "UNKNOWN" || c === "PASS_WITH_FINDINGS" ? "dashed" : "solid",
          borderColor: "rgba(0,0,0,0.4)",
          borderWidth: 1,
          opacity: c === "UNKNOWN" ? 0.75 : 0.95
        },
        emphasis: { focus: "series" },
        data: groups.map(function (g) { return (g.counts || {})[c] || 0; })
      };
    });
  }

  function initVerdict(id, drillBase) {
    var mounted = mount(id, function (p, animate) {
      var groups = p.groups || [];
      if (!groups.length) {
        return { backgroundColor: "transparent", textStyle: commonText(), graphic: { type: "text", left: "center", top: "middle", style: { text: "No completed evidence in this context", fill: MUTED, fontSize: 13 } } };
      }
      return {
        backgroundColor: "transparent",
        textStyle: commonText(),
        animationDuration: animate ? 450 : 0,
        tooltip: Object.assign(baseTooltip(), {
          trigger: "axis",
          axisPointer: { type: "shadow" },
          formatter: function (params) {
            var g = groups[params[0].dataIndex];
            var lines = ["<b>" + g.label + "</b>", "Evaluated: " + g.evaluated + " · pass rate: " + (g.pass_rate === null || g.pass_rate === undefined ? "n/a (no evaluated runs)" : (g.pass_rate * 100).toFixed(1) + "%")];
            params.forEach(function (s) { if (s.value) lines.push(s.marker + " " + s.seriesName + ": <b>" + s.value + "</b>"); });
            lines.push("<span style='color:" + MUTED + "'>Click a bar for run drill-down</span>");
            return lines.join("<br/>");
          }
        }),
        legend: { top: 0, textStyle: { color: MUTED, fontSize: 10 }, inactiveColor: "#3b4c60" },
        grid: { left: 8, right: 12, top: 46, bottom: 8, containLabel: true },
        xAxis: { type: "category", data: groups.map(function (g) { return shortLabel(g.label); }), axisLabel: { color: MUTED, fontSize: 10, interval: 0, rotate: groups.length > 3 ? 18 : 0 }, axisLine: { lineStyle: { color: "#243242" } } },
        yAxis: { type: "value", name: "runs", nameTextStyle: { color: MUTED }, axisLabel: { color: MUTED }, splitLine: { lineStyle: { color: "#1b2634" } } },
        series: verdictSeries(groups)
      };
    });
    if (mounted) {
      mounted.chart.on("click", function (params) {
        var g = mounted.payload.groups[params.dataIndex];
        if (g && g.run_ids && g.run_ids.length) {
          window.location.href = (drillBase || "/operator/runs/") + g.run_ids[0];
        }
      });
    }
    return mounted;
  }

  function hbarInit(id, kind) {
    var mounted = mount(id, function (p, animate) {
      var groups = p.groups || [];
      var knownKey = kind === "cost" ? "avg_known" : "avg_known";
      var rows = groups.slice().sort(function (a, b) { return (b[knownKey] || -1) - (a[knownKey] || -1); });
      if (!rows.length) {
        return { backgroundColor: "transparent", textStyle: commonText(), graphic: { type: "text", left: "center", top: "middle", style: { text: "No completed evidence in this context", fill: MUTED, fontSize: 13 } } };
      }
      var unit = kind === "cost" ? "USD" : "s";
      return {
        backgroundColor: "transparent",
        textStyle: commonText(),
        animationDuration: animate ? 450 : 0,
        tooltip: Object.assign(baseTooltip(), {
          trigger: "item",
          formatter: function (params) {
            var g = rows[params.dataIndex];
            if (kind === "cost") {
              var sum = g.sum_known === null || g.sum_known === undefined ? "n/a" : "$" + g.sum_known.toFixed(4);
              var avg = g.avg_known === null || g.avg_known === undefined ? "n/a (no known cost)" : "$" + g.avg_known.toFixed(4);
              return "<b>" + g.label + "</b><br/>Known: <b>" + g.n_known + "</b> · unknown: <b>" + g.n_unknown + "</b><br/>Avg known: " + avg + " · sum: " + sum + (g.has_zero_cost ? "<br/>Includes $0.00 free-tier runs (known zero, not unknown)" : "") + "<br/><span style='color:" + MUTED + "'>Missing cost is never zero — see table</span>";
            }
            var avgE = g.avg_known === null || g.avg_known === undefined ? "n/a (not recorded)" : g.avg_known.toFixed(1) + "s";
            return "<b>" + g.label + "</b><br/>Known: <b>" + g.n_known + "</b> · not recorded: <b>" + g.n_unknown + "</b><br/>Avg: " + avgE + " · range: " + (g.min_known === null ? "n/a" : g.min_known.toFixed(1) + "–" + g.max_known.toFixed(1) + "s");
          }
        }),
        grid: { left: 8, right: 16, top: 10, bottom: 8, containLabel: true },
        xAxis: {
          type: "value",
          axisLabel: { color: MUTED, fontSize: 10, formatter: kind === "cost" ? function (v) { return "$" + v; } : "{value}s" },
          splitLine: { lineStyle: { color: "#1b2634" } }
        },
        yAxis: { type: "category", data: rows.map(function (g) { return shortLabel(g.label); }), axisLabel: { color: INK, fontSize: 11 }, axisLine: { lineStyle: { color: "#243242" } } },
        series: [{
          type: "bar",
          barMaxWidth: 20,
          data: rows.map(function (g, i) {
            var v = g.avg_known;
            var isUnknownOnly = v === null || v === undefined;
            return {
              value: isUnknownOnly ? 0 : v,
              itemStyle: {
                color: isUnknownOnly ? "rgba(140,160,179,0.25)" : (kind === "cost" ? ACCENT : "#22d3ee"),
                borderColor: isUnknownOnly ? UNKNOWN : "transparent",
                borderWidth: isUnknownOnly ? 1 : 0,
                borderType: "dashed",
                shadowBlur: isUnknownOnly ? 0 : 14,
                shadowColor: kind === "cost" ? "rgba(91,140,255,0.35)" : "rgba(34,211,238,0.3)"
              }
            };
          }),
          label: {
            show: true,
            position: "right",
            color: MUTED,
            fontSize: 10,
            formatter: function (params) {
              var g = rows[params.dataIndex];
              if (g.avg_known === null || g.avg_known === undefined) return "Not recorded (" + g.n_unknown + ")";
              return (kind === "cost" ? "$" + g.avg_known.toFixed(3) : g.avg_known.toFixed(1) + "s") + " · n=" + g.n_known + (g.n_unknown ? " (+" + g.n_unknown + " unknown)" : "");
            }
          }
        }]
      };
    });
    if (mounted) {
      mounted.chart.on("click", function (params) {
        var rows = mounted.payload.groups.slice();
        var g = rows[params.dataIndex];
        var ids = (g && (g.run_ids_known || []).concat(g.run_ids_unknown || [])) || [];
        if (ids.length) window.location.href = "/operator/runs/" + ids[0];
      });
    }
    return mounted;
  }

  function initScores(id) {
    var mounted = mount(id, function (p, animate) {
      var groups = p.groups || [];
      if (!groups.length) {
        return { backgroundColor: "transparent", textStyle: commonText(), graphic: { type: "text", left: "center", top: "middle", style: { text: "No completed evidence in this context", fill: MUTED, fontSize: 13 } } };
      }
      return {
        backgroundColor: "transparent",
        textStyle: commonText(),
        animationDuration: animate ? 450 : 0,
        tooltip: Object.assign(baseTooltip(), {
          trigger: "axis",
          axisPointer: { type: "shadow" },
          formatter: function (params) {
            var g = groups[params[0].dataIndex];
            var avg = g.avg_scored === null || g.avg_scored === undefined ? "n/a (no scored runs)" : g.avg_scored.toFixed(2);
            var range = g.min_scored === null || g.min_scored === undefined ? "n/a" : g.min_scored.toFixed(2) + "–" + g.max_scored.toFixed(2);
            return "<b>" + g.label + "</b><br/>Scored: <b>" + g.n_scored + "</b> · unscored/UNKNOWN: <b>" + g.n_unscored_unknown + "</b><br/>Avg scored: " + avg + " · range: " + range + "<br/><span style='color:" + MUTED + "'>UNKNOWN never averaged as zero</span>";
          }
        }),
        legend: { top: 0, data: ["avg scored", "unscored / UNKNOWN"], textStyle: { color: MUTED, fontSize: 10 }, inactiveColor: "#3b4c60" },
        grid: { left: 8, right: 12, top: 46, bottom: 8, containLabel: true },
        xAxis: { type: "category", data: groups.map(function (g) { return shortLabel(g.label); }), axisLabel: { color: MUTED, fontSize: 10, interval: 0, rotate: groups.length > 3 ? 18 : 0 }, axisLine: { lineStyle: { color: "#243242" } } },
        yAxis: { type: "value", min: 0, max: 1, axisLabel: { color: MUTED }, splitLine: { lineStyle: { color: "#1b2634" } } },
        series: [
          {
            name: "avg scored",
            type: "bar",
            barMaxWidth: 30,
            itemStyle: { color: ACCENT, shadowBlur: 14, shadowColor: "rgba(91,140,255,0.4)" },
            label: { show: true, position: "top", color: INK, fontSize: 10, formatter: function (params) { var g = groups[params.dataIndex]; return g.avg_scored === null ? "n/a" : g.avg_scored.toFixed(2); } },
            data: groups.map(function (g) { return g.avg_scored === null ? 0 : g.avg_scored; })
          },
          {
            name: "unscored / UNKNOWN",
            type: "bar",
            barMaxWidth: 30,
            itemStyle: { color: "rgba(140,160,179,0.3)", borderColor: UNKNOWN, borderWidth: 1, borderType: "dashed" },
            data: groups.map(function (g) { return g.n_unscored_unknown; })
          }
        ]
      };
    });
    if (mounted) {
      mounted.chart.on("click", function (params) {
        var g = mounted.payload.groups[params.dataIndex];
        var ids = (g && (g.run_ids_scored || []).concat(g.run_ids_unscored || [])) || [];
        if (ids.length) window.location.href = "/operator/runs/" + ids[0];
      });
    }
    return mounted;
  }

  function boot() {
    document.querySelectorAll("[data-cc-chart]").forEach(function (node) {
      var kind = node.getAttribute("data-cc-chart");
      var id = node.id;
      if (!id) return;
      if (kind === "qual") initQualDonut(id);
      else if (kind === "verdict") initVerdict(id);
      else if (kind === "cost") hbarInit(id, "cost");
      else if (kind === "elapsed") hbarInit(id, "elapsed");
      else if (kind === "scores") initScores(id);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
