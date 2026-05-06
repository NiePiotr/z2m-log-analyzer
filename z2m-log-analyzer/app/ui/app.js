const CATEGORIES = [
  "failed_to_ping", "publish_failed", "device_announce", "interview_started",
  "interview_failed", "interview_successful", "device_joined", "device_leave",
  "nwk_error", "coordinator_error", "mqtt_error", "ota_event", "unknown",
];

function rangeSeconds(range) {
  const map = { "1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800, "30d": 2592000 };
  return (map[range] || 86400) * 1000;
}

function fmtTs(ts) {
  const d = new Date(ts);
  return d.toLocaleString();
}

document.addEventListener("alpine:init", () => {
  Alpine.data("app", () => ({
    tab: "overview",
    kpi: { errors1h: "-", errors24h: "-", warnings1h: "-", warnings24h: "-" },
    tlWindow: "1h", tlCategory: "", tlLevel: "", tlRange: "24h",
    devRange: "24h", devFilter: "", devSort: "total", devices: [], expandedDevice: null, deviceDetail: {},
    evLevel: "", evCategory: "", evDevice: "", evOffset: 0, evLimit: 50, events: [],
    cfg: { retention_days: 30, enable_raw_events: false, raw_events_topic: "", publish_sensors: [], db_size_mb: 0, db_over_limit: false, mqtt_connected: false },
    availableSensors: ["errors_1h", "errors_24h", "warnings_1h", "warnings_24h", "failed_to_ping_1h"],
    overviewChart: null,
    timelineChart: null,
    toast: null,

    async init() {
      this.loadOverview();
      this.loadSettings();
      setInterval(() => this.loadOverview(), 60000);
    },

    async api(url) {
      const r = await fetch(url);
      return r.json();
    },

    async loadOverview() {
      try {
        const now = Date.now();
        const [d1h, d24h] = await Promise.all([
          this.api(`/api/aggregates/totals?window=1h&since=${now - 3600000}&until=${now}`),
          this.api(`/api/aggregates/totals?window=1h&since=${now - 86400000}&until=${now}`),
        ]);
        const sum = (data, level) => data.filter(r => level === "error" ? r.category !== "unknown" : true)
          .reduce((s, r) => s + r.count, 0);
        this.kpi.errors1h = d1h.data ? sum(d1h.data, "error") : 0;
        this.kpi.errors24h = d24h.data ? sum(d24h.data, "error") : 0;

        const w1h = await this.api(`/api/aggregates/totals?window=1h&since=${now - 3600000}&until=${now}`);
        const w24h = await this.api(`/api/aggregates/totals?window=1h&since=${now - 86400000}&until=${now}`);

        this.renderOverviewChart(d24h.data || []);
        this.renderOverviewChart(d24h.data || []);
      } catch (e) { }
    },

    renderOverviewChart(data) {
      const ctx = document.getElementById("overviewChart");
      if (!ctx) return;
      if (this.overviewChart) this.overviewChart.destroy();

      const cats = [...new Set(data.map(d => d.category))];
      const colors = ["#ef5350", "#ffa726", "#42a5f5", "#66bb6a", "#ab47bc", "#26c6da", "#9e9e9e", "#ff7043"];
      const datasets = cats.map((cat, i) => ({
        label: cat, data: data.filter(d => d.category === cat).map(d => d.count),
        backgroundColor: colors[i % colors.length],
      }));

      this.overviewChart = new Chart(ctx, {
        type: "bar",
        data: { labels: cats, datasets },
        options: {
          responsive: true,
          plugins: { legend: { position: "bottom", labels: { color: "#8892a4" } } },
          scales: {
            x: { ticks: { color: "#8892a4" }, grid: { color: "#2a3a5c" } },
            y: { ticks: { color: "#8892a4" }, grid: { color: "#2a3a5c" } },
          },
        },
      });
    },

    async initTimeline() {
      const now = Date.now();
      const since = now - rangeSeconds(this.tlRange);
      const params = new URLSearchParams({
        window: this.tlWindow, since, until: now,
      });
      if (this.tlCategory) params.set("category", this.tlCategory);
      if (this.tlLevel) params.set("level", this.tlLevel);

      const resp = await this.api(`/api/aggregates?${params}`);
      this.renderTimelineChart(resp.data || []);
    },

    renderTimelineChart(data) {
      const ctx = document.getElementById("timelineChart");
      if (!ctx) return;
      if (this.timelineChart) this.timelineChart.destroy();

      const series = {};
      data.forEach(d => {
        const key = `${d.category}/${d.level}`;
        if (!series[key]) series[key] = [];
        series[key].push({ x: d.bucket_ts, y: d.count });
      });

      const colors = ["#4fc3f7", "#ef5350", "#ffa726", "#66bb6a", "#ab47bc"];
      const datasets = Object.entries(series).map(([label, points], i) => ({
        label, data: points, borderColor: colors[i % colors.length],
        tension: 0.2, pointRadius: 0, fill: false,
      }));

      this.timelineChart = new Chart(ctx, {
        type: "line",
        data: { datasets },
        options: {
          responsive: true,
          plugins: { legend: { position: "bottom", labels: { color: "#8892a4" } } },
          scales: {
            x: {
              type: "time",
              time: { unit: "minute" },
              ticks: { color: "#8892a4" },
              grid: { color: "#2a3a5c" },
            },
            y: { ticks: { color: "#8892a4" }, grid: { color: "#2a3a5c" } },
          },
        },
      });
    },

    async loadDevices() {
      const now = Date.now();
      const since = now - rangeSeconds(this.devRange);
      const resp = await this.api(`/api/devices/ranking?since=${since}&until=${now}&limit=100`);
      this.devices = resp.devices || [];
    },

    async toggleDevice(name) {
      if (this.expandedDevice === name) {
        this.expandedDevice = null;
        return;
      }
      this.expandedDevice = name;
      const now = Date.now();
      const since = now - rangeSeconds(this.devRange);
      const detail = await this.api(`/api/devices/${encodeURIComponent(name)}?since=${since}&until=${now}`);
      this.deviceDetail = detail;
      this.$nextTick(() => this.renderSparkline(name, detail.sparkline || []));
    },

    renderSparkline(name, data) {
      const safeId = name.replace(/[^a-z0-9]/gi, "_");
      const canvas = document.getElementById("spark-" + safeId);
      if (!canvas || !data.length) return;
      const existing = Chart.getChart(canvas);
      if (existing) existing.destroy();
      new Chart(canvas, {
        type: "line",
        data: {
          datasets: [{
            label: name,
            data: data.map(d => ({ x: d.ts, y: d.count })),
            borderColor: "#4fc3f7",
            backgroundColor: "rgba(79,195,247,0.1)",
            fill: true,
            tension: 0.3,
            pointRadius: 0,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { type: "time", time: { unit: "hour" }, ticks: { color: "#8892a4", maxTicksLimit: 6 }, grid: { color: "#2a3a5c" } },
            y: { ticks: { color: "#8892a4" }, grid: { color: "#2a3a5c" }, min: 0 },
          },
        },
      });
    },

    get filteredDevices() {
      let list = [...(this.devices || [])];
      if (this.devFilter) {
        const q = this.devFilter.toLowerCase();
        list = list.filter(d => d.device && d.device.toLowerCase().includes(q));
      }
      list.sort((a, b) => (b[this.devSort] || 0) - (a[this.devSort] || 0));
      return list;
    },

    async loadEvents() {
      const params = new URLSearchParams({ limit: this.evLimit, offset: this.evOffset });
      if (this.evLevel) params.set("level", this.evLevel);
      if (this.evCategory) params.set("category", this.evCategory);
      if (this.evDevice) params.set("device", this.evDevice);
      const resp = await this.api(`/api/events?${params}`);
      this.events = resp.events || [];
    },

    exportCsv() {
      const params = new URLSearchParams();
      if (this.evLevel) params.set("level", this.evLevel);
      if (this.evCategory) params.set("category", this.evCategory);
      if (this.evDevice) params.set("device", this.evDevice);
      window.location = `/api/events/export.csv?${params}`;
    },

    async loadSettings() {
      try {
        const resp = await this.api("/api/settings");
        Object.assign(this.cfg, resp);
      } catch (e) { }
    },

    async saveSettings() {
      try {
        const r = await fetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(this.cfg),
        });
        if (r.ok) this.showToast("Settings saved", "success");
        else this.showToast("Failed to save", "error");
      } catch (e) {
        this.showToast("Network error", "error");
      }
    },

    showToast(msg, type) {
      this.toast = { msg, type };
      setTimeout(() => this.toast = null, 3000);
    },

    fmtTs,
  }));
});
