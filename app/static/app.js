// Bybit & OKX Tracker Frontend Logic

const EVENT_OPTIONS = {
  Bybit: {
    types: ["Splash", "Alpha", "Stock Buzz", "Puzzle Hunt", "Others"],
    markets: ["Spot", "Futures", "Alpha"]
  },
  OKX: {
    types: ["Flash Earn", "Others"],
    markets: ["Spot", "Futures"]
  }
};

document.addEventListener("DOMContentLoaded", () => {
  handleExchangeChange();
  setDefaultDate();
  loadStatus();
  loadEvents();
  loadLogs();

  // Auto-refresh status and logs every 30 seconds
  setInterval(() => {
    loadStatus();
    loadLogs();
  }, 30000);
});

function setDefaultDate() {
  const today = new Date().toISOString().split("T")[0];
  const dateInput = document.getElementById("ev-start-date");
  if (dateInput && !dateInput.value) {
    dateInput.value = today;
  }
}

function switchTab(tabName) {
  document.querySelectorAll(".tab-content").forEach(el => el.classList.add("hidden"));
  document.querySelectorAll(".tab-btn").forEach(el => {
    el.classList.remove("border-blue-500", "text-blue-400");
    el.classList.add("border-transparent", "text-slate-400");
  });

  const targetContent = document.getElementById(`tab-${tabName}`);
  const targetBtn = document.getElementById(`tab-btn-${tabName}`);

  if (targetContent) targetContent.classList.remove("hidden");
  if (targetBtn) {
    targetBtn.classList.add("border-blue-500", "text-blue-400");
    targetBtn.classList.remove("border-transparent", "text-slate-400");
  }

  if (tabName === "logs") loadLogs();
  if (tabName === "events") loadEvents();
}

function handleExchangeChange() {
  const exchange = document.getElementById("ev-exchange").value;
  const config = EVENT_OPTIONS[exchange] || EVENT_OPTIONS.Bybit;

  const typeSelect = document.getElementById("ev-type");
  typeSelect.innerHTML = config.types.map(t => `<option value="${t}">${t}</option>`).join("");

  const marketSelect = document.getElementById("ev-market");
  marketSelect.innerHTML = config.markets.map(m => `<option value="${m}">${m}</option>`).join("");
}

// HTML escape helper
function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Toast notification
let toastTimeout = null;
function showToast(message, type = "success") {
  const toast = document.getElementById("toast");
  if (toastTimeout) {
    clearTimeout(toastTimeout);
  }
  toast.className = `fixed bottom-5 right-5 z-50 max-w-md p-4 rounded-xl shadow-2xl transition transform ease-out duration-300 text-xs font-semibold flex items-center space-x-2 ${
    type === "success" ? "bg-emerald-600 text-white" : "bg-red-600 text-white"
  }`;
  toast.innerHTML = `<i class="fa-solid ${type === "success" ? "fa-circle-check" : "fa-triangle-exclamation"} text-base"></i> <span>${escapeHtml(message)}</span>`;
  toast.classList.remove("hidden");
  toastTimeout = setTimeout(() => {
    toast.classList.add("hidden");
  }, 4000);
}

// Safe API Fetch Wrapper
async function apiFetch(url, options = {}) {
  let res;
  try {
    res = await fetch(url, options);
  } catch (err) {
    throw new Error("Sunucuya bağlanılamadı. Lütfen sunucunun (start.bat) çalıştığından emin olun.");
  }

  let data = null;
  const text = await res.text().catch(() => "");
  try {
    data = JSON.parse(text);
  } catch {
    data = { success: res.ok, message: text || res.statusText };
  }

  if (!res.ok) {
    let msg = "Sunucu hatası";
    if (data && data.detail) {
      if (Array.isArray(data.detail)) {
        msg = data.detail.map(d => (d.loc ? d.loc.slice(-1)[0] + ": " : "") + d.msg).join(", ");
      } else if (typeof data.detail === "string") {
        msg = data.detail;
      }
    } else if (data && data.message) {
      msg = data.message;
    } else if (typeof data === "string" && data.trim()) {
      msg = data;
    } else {
      msg = `Sunucu hatası (${res.status})`;
    }
    throw new Error(msg);
  }

  return data;
}

// Load System & API Status
async function loadStatus() {
  try {
    const data = await apiFetch("/api/status");

    const badgeBybit = document.getElementById("badge-bybit");
    const badgeOkx = document.getElementById("badge-okx");

    if (data.has_bybit) {
      badgeBybit.className = "px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20";
      badgeBybit.textContent = `Bybit: Aktif (${data.bybit_key_masked})`;
    } else {
      badgeBybit.className = "px-2.5 py-1 rounded-full bg-slate-800 text-slate-400 border border-slate-700";
      badgeBybit.textContent = "Bybit: Anahtar Yok";
    }

    if (data.has_okx) {
      badgeOkx.className = "px-2.5 py-1 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20";
      badgeOkx.textContent = `OKX: Aktif (${data.okx_key_masked})`;
    } else {
      badgeOkx.className = "px-2.5 py-1 rounded-full bg-slate-800 text-slate-400 border border-slate-700";
      badgeOkx.textContent = "OKX: Anahtar Yok";
    }

    const testnetCheck = document.getElementById("set-bybit-testnet");
    if (testnetCheck && data.bybit_testnet !== undefined) {
      testnetCheck.checked = Boolean(data.bybit_testnet);
    }
  } catch (err) {
    console.error("Status load error:", err);
    const badgeBybit = document.getElementById("badge-bybit");
    const badgeOkx = document.getElementById("badge-okx");
    if (badgeBybit) {
      badgeBybit.className = "px-2.5 py-1 rounded-full bg-red-500/10 text-red-400 border border-red-500/20";
      badgeBybit.textContent = "Bağlantı Kesildi";
    }
    if (badgeOkx) {
      badgeOkx.className = "px-2.5 py-1 rounded-full bg-red-500/10 text-red-400 border border-red-500/20";
      badgeOkx.textContent = "Bağlantı Kesildi";
    }
  }
}

// Load and Render Events
async function loadEvents() {
  try {
    const data = await apiFetch("/api/events");
    const events = data.events || [];

    const tbody = document.getElementById("events-tbody");
    const countBadge = document.getElementById("events-count");
    countBadge.textContent = `${events.length} Aktif Etkinlik`;

    if (events.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center py-6 text-slate-500">Kayıtlı etkinlik bulunamadı. Yukarıdaki formu kullanarak takip başlatabilirsiniz.</td></tr>`;
      return;
    }

    tbody.innerHTML = events.map(ev => `
      <tr class="hover:bg-slate-800/40 transition">
        <td class="py-3 px-3">
          <span class="px-2 py-0.5 rounded text-[11px] font-bold ${ev.exchange === 'Bybit' ? 'bg-amber-500/20 text-amber-400' : 'bg-blue-500/20 text-blue-400'}">
            ${escapeHtml(ev.exchange)}
          </span>
        </td>
        <td class="py-3 px-3 font-semibold text-white">${escapeHtml(ev.event_name)}</td>
        <td class="py-3 px-3 text-slate-400">${escapeHtml(ev.market)}</td>
        <td class="py-3 px-3 font-mono font-bold text-slate-200">${escapeHtml(ev.coin)}</td>
        <td class="py-3 px-3 text-slate-400 font-mono text-xs">${escapeHtml(ev.start_date)}</td>
        <td class="py-3 px-3 text-slate-300 font-mono text-xs">${ev.target_volume > 0 ? '$' + Number(ev.target_volume).toLocaleString('en-US') : '-'}</td>
        <td class="py-3 px-3">
          <span class="inline-flex items-center gap-1.5 text-xs text-emerald-400 font-semibold">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> Aktif
          </span>
        </td>
        <td class="py-3 px-3 text-right">
          <button onclick="deleteEvent(${ev.id})" class="text-slate-500 hover:text-red-400 p-1 rounded transition" title="Takipten Çıkar">
            <i class="fa-solid fa-trash-can"></i>
          </button>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    console.error("Events load error:", err);
    const tbody = document.getElementById("events-tbody");
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center py-6 text-red-400 font-semibold"><i class="fa-solid fa-triangle-exclamation mr-1"></i> Sunucuya bağlanılamadı (${escapeHtml(err.message)})</td></tr>`;
    }
  }
}

// Add Event
async function handleAddEvent(e) {
  e.preventDefault();
  const exchange = document.getElementById("ev-exchange").value;
  const event_type = document.getElementById("ev-type").value;
  const market = document.getElementById("ev-market").value;
  const coin = document.getElementById("ev-coin").value.trim().toUpperCase();
  const start_date = document.getElementById("ev-start-date").value;
  const target_volume = parseFloat(document.getElementById("ev-target-vol").value) || 0.0;

  if (!coin) {
    showToast("Lütfen bir coin sembolü giriniz!", "error");
    return;
  }

  const event_name = `${coin} ${event_type}`;

  try {
    const data = await apiFetch("/api/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        exchange,
        event_name,
        event_type,
        market,
        coin,
        pair: `${coin}USDT`,
        start_date,
        target_volume
      })
    });
    if (data.success) {
      showToast(`${coin} etkinliği başarıyla takibe alındı!`);
      document.getElementById("ev-coin").value = "";
      document.getElementById("ev-target-vol").value = "";
      loadEvents();
    } else {
      showToast(data.message || "Hata oluştu", "error");
    }
  } catch (err) {
    showToast(err.message, "error");
  }
}

// Delete Event
async function deleteEvent(id) {
  if (!confirm("Bu etkinliği takipten çıkarmak istediğinize emin misiniz?")) return;
  try {
    const data = await apiFetch(`/api/events/${id}`, { method: "DELETE" });
    if (data.success) {
      showToast("Etkinlik silindi.");
      loadEvents();
    } else {
      showToast(data.message || "Silme işlemi başarısız.", "error");
    }
  } catch (err) {
    showToast(err.message, "error");
  }
}

// Parse Announcement with AI
async function parseWithAI() {
  const text = document.getElementById("ai-announcement-text").value.trim();
  if (!text) {
    showToast("Lütfen bir duyuru metni yapıştırınız!", "error");
    return;
  }

  const btn = document.getElementById("btn-parse-ai");
  btn.disabled = true;
  btn.innerHTML = `<i class="fa-solid fa-spinner animate-spin"></i> <span>Yapay Zekâ Analiz Ediyor...</span>`;

  try {
    const result = await apiFetch("/api/parse-announcement", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });
    if (result.success && result.data) {
      const d = result.data;
      if (d.exchange) document.getElementById("ev-exchange").value = d.exchange;
      handleExchangeChange();

      if (d.event_type) document.getElementById("ev-type").value = d.event_type;
      if (d.market) document.getElementById("ev-market").value = d.market;
      if (d.coin) document.getElementById("ev-coin").value = d.coin;
      if (d.start_date) document.getElementById("ev-start-date").value = d.start_date;
      if (d.target_volume) document.getElementById("ev-target-vol").value = d.target_volume;

      showToast(`AI ile analiz edildi: ${d.coin || ''} (${d.event_type || ''}) formu dolduruldu!`);
    } else {
      showToast("Duyuru ayrıştırılamadı.", "error");
    }
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i class="fa-solid fa-robot"></i> <span>AI ile Analiz Et ve Forma Doldur</span>`;
  }
}

// Save Settings
async function saveSettings() {
  const bybit_api_key = document.getElementById("set-bybit-key").value;
  const bybit_api_secret = document.getElementById("set-bybit-secret").value;
  const bybit_testnet = document.getElementById("set-bybit-testnet").checked;

  const okx_api_key = document.getElementById("set-okx-key").value;
  const okx_api_secret = document.getElementById("set-okx-secret").value;
  const okx_passphrase = document.getElementById("set-okx-passphrase").value;

  const gemini_api_key = document.getElementById("set-gemini-key").value;

  // Build payload only with non-empty fields so we don't wipe existing keys
  const payload = {};
  if (bybit_api_key.trim()) payload.bybit_api_key = bybit_api_key.trim();
  if (bybit_api_secret.trim()) payload.bybit_api_secret = bybit_api_secret.trim();
  payload.bybit_testnet = bybit_testnet;
  if (okx_api_key.trim()) payload.okx_api_key = okx_api_key.trim();
  if (okx_api_secret.trim()) payload.okx_api_secret = okx_api_secret.trim();
  if (okx_passphrase.trim()) payload.okx_passphrase = okx_passphrase.trim();
  if (gemini_api_key.trim()) payload.gemini_api_key = gemini_api_key.trim();

  try {
    const data = await apiFetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (data.success) {
      showToast("Ayarlar yerel .env dosyasına başarıyla kaydedildi!");
      loadStatus();
    } else {
      showToast(data.message || "Ayarlar kaydedilemedi.", "error");
    }
  } catch (err) {
    showToast(err.message, "error");
  }
}

// Test Connections
async function testConnections() {
  const btn = document.getElementById("btn-test-conn");
  btn.disabled = true;
  btn.innerHTML = `<i class="fa-solid fa-spinner animate-spin mr-1"></i> Bağlantılar Test Ediliyor...`;

  const bybitBox = document.getElementById("bybit-test-result");
  const okxBox = document.getElementById("okx-test-result");

  try {
    const data = await apiFetch("/api/test-keys", { method: "POST" });

    // Bybit
    bybitBox.classList.remove("hidden");
    if (data.bybit && data.bybit.success) {
      bybitBox.className = "p-3 rounded-xl text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/20";
      bybitBox.innerHTML = `<strong>✓ Bybit Bağlantısı Başarılı:</strong><br>Seviye: ${data.bybit.vip_tier} | Maker: ${data.bybit.spot_maker_fee} | Taker: ${data.bybit.spot_taker_fee}`;
    } else {
      bybitBox.className = "p-3 rounded-xl text-xs bg-red-500/10 text-red-400 border border-red-500/20";
      bybitBox.innerHTML = `<strong>✗ Bybit:</strong> ${data.bybit?.message || data.bybit?.error || 'Hata'}`;
    }

    // OKX
    okxBox.classList.remove("hidden");
    if (data.okx && data.okx.success) {
      okxBox.className = "p-3 rounded-xl text-xs bg-blue-500/10 text-blue-400 border border-blue-500/20";
      okxBox.innerHTML = `<strong>✓ OKX Bağlantısı Başarılı:</strong><br>Seviye: ${data.okx.vip_tier} | Maker: ${data.okx.spot_maker_fee} | Taker: ${data.okx.spot_taker_fee}`;
    } else {
      okxBox.className = "p-3 rounded-xl text-xs bg-red-500/10 text-red-400 border border-red-500/20";
      okxBox.innerHTML = `<strong>✗ OKX:</strong> ${data.okx?.message || data.okx?.error || 'Hata'}`;
    }

    showToast("Bağlantı testleri tamamlandı.");
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i class="fa-solid fa-plug mr-1.5"></i> Bağlantıları Test Et`;
  }
}

// Trigger Manual Sync
async function triggerSync() {
  const btn = document.getElementById("btn-sync-now");
  const icon = document.getElementById("sync-icon");
  btn.disabled = true;
  icon.classList.add("animate-spin-fast");

  try {
    const data = await apiFetch("/api/sync", { method: "POST" });
    if (data.success) {
      const added = data.excel_result?.added || 0;
      const updated = data.excel_result?.updated || 0;
      if (data.status === "Warning") {
        showToast(`Kısmi Senkronizasyon: Excel güncellendi (${added} yeni, ${updated} güncellendi), ancak bazı borsalarda hata oluştu.`, "error");
      } else {
        showToast(`Senkronizasyon Başarılı! Excel güncellendi: ${added} yeni eklendi, ${updated} güncellendi.`);
      }
    } else {
      showToast(data.message || data.excel_result?.error || "Senkronizasyon hatası oluştu!", "error");
    }
    loadLogs();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    btn.disabled = false;
    icon.classList.remove("animate-spin-fast");
  }
}

// Open Excel File
async function openExcel() {
  try {
    const data = await apiFetch("/api/open-excel", { method: "POST" });
    if (data.success) {
      showToast("Excel dosyası bilgisayarınızda açılıyor...");
    } else {
      showToast(data.error || data.message || "Excel açılamadı", "error");
    }
  } catch (err) {
    showToast(err.message, "error");
  }
}

// Load Logs
async function loadLogs() {
  try {
    const data = await apiFetch("/api/logs");
    const logs = data.logs || [];

    const tbody = document.getElementById("logs-tbody");
    if (logs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-slate-500">Henüz senkronizasyon kaydı bulunamadı.</td></tr>`;
      return;
    }

    tbody.innerHTML = logs.map(l => `
      <tr class="hover:bg-slate-800/40 transition">
        <td class="py-2.5 px-3 text-slate-400 font-mono text-[11px]">${escapeHtml(l.timestamp)}</td>
        <td class="py-2.5 px-3 font-semibold text-white">${escapeHtml(l.exchange)}</td>
        <td class="py-2.5 px-3">
          <span class="px-2 py-0.5 rounded text-[10px] font-bold ${l.status === 'Success' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}">
            ${escapeHtml(l.status)}
          </span>
        </td>
        <td class="py-2.5 px-3 text-slate-300">${escapeHtml(l.message)}</td>
        <td class="py-2.5 px-3 font-mono">${escapeHtml(l.trades_found)}</td>
        <td class="py-2.5 px-3 font-bold ${l.excel_updated ? 'text-emerald-400' : 'text-slate-500'}">
          ${l.excel_updated ? '✓ Yazıldı' : '-'}
        </td>
      </tr>
    `).join("");
  } catch (err) {
    console.error("Logs load error:", err);
    const tbody = document.getElementById("logs-tbody");
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-red-400 font-semibold"><i class="fa-solid fa-triangle-exclamation mr-1"></i> Sunucuya bağlanılamadı (${escapeHtml(err.message)})</td></tr>`;
    }
  }
}
