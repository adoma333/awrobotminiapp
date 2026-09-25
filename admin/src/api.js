const BASE = "/api/admin";

class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, options = {}) {
  const res = await fetch(BASE + path, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* بدون محتوى JSON */
  }
  if (!res.ok) {
    throw new ApiError(res.status, body && body.detail);
  }
  return body;
}

export const api = {
  verify: (token, code) =>
    request("/verify", { method: "POST", body: JSON.stringify({ token, code }) }),
  me: () => request("/me"),
  logout: () => request("/logout", { method: "POST" }),
  stats: () => request("/stats"),
  users: (params = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") qs.set(k, v);
    });
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request(`/users${suffix}`);
  },
  userDetail: (id) => request(`/users/${id}`),
  decide: (id, action, reason) =>
    request(`/users/${id}/decision`, {
      method: "POST",
      body: JSON.stringify({ action, reason }),
    }),
  // الإعدادات العامة
  settings: () => request("/settings"),
  saveSettings: (patch) => request("/settings", { method: "PUT", body: JSON.stringify(patch) }),
  // الباقات
  packages: () => request("/packages"),
  createPackage: (data) => request("/packages", { method: "POST", body: JSON.stringify(data) }),
  updatePackage: (id, patch) => request(`/packages/${id}`, { method: "PUT", body: JSON.stringify(patch) }),
  deletePackage: (id) => request(`/packages/${id}`, { method: "DELETE" }),
  seedPackages: () => request("/packages/seed", { method: "POST" }),
  leaderboard: () => request("/leaderboard"),
  saveLeaderboard: (patch) => request("/leaderboard", { method: "PUT", body: JSON.stringify(patch) }),
  ceo: () => request("/ceo"),
  staff: () => request("/staff"),
  saveStaff: (m) => request("/staff", { method: "PUT", body: JSON.stringify(m) }),
  removeStaff: (id) => request(`/staff/${id}`, { method: "DELETE" }),
  audit: (params = {}) => request(`/audit?${new URLSearchParams(params).toString()}`),
  servers: () => request("/servers"),
  importServers: (text) => request("/servers/import", { method: "POST", body: JSON.stringify({ text }) }),
  backfillServers: () => request("/servers/backfill", { method: "POST" }),
  deleteServer: (id) => request(`/servers/${encodeURIComponent(id)}`, { method: "DELETE" }),
  leaderboardPhoto: (photo) => request("/leaderboard/photo", { method: "POST", body: JSON.stringify({ photo }) }),
  // المكافآت والكوبونات
  rewardsConfig: () => request("/rewards/config"),
  saveRewardsConfig: (patch) => request("/rewards/config", { method: "PUT", body: JSON.stringify(patch) }),
  rewardCards: (uid) => request(`/rewards/cards${uid ? `?uid=${encodeURIComponent(uid)}` : ""}`),
  grantReward: (data) => request("/rewards/grant", { method: "POST", body: JSON.stringify(data) }),
  revokeReward: (id) => request(`/rewards/${encodeURIComponent(id)}/revoke`, { method: "POST" }),
  extendReward: (id, hours) =>
    request(`/rewards/${encodeURIComponent(id)}/extend`, { method: "POST", body: JSON.stringify({ hours }) }),
  // الدعم الفني الذكي
  supportConfig: () => request("/support/config"),
  saveSupportConfig: (patch) => request("/support/config", { method: "PUT", body: JSON.stringify(patch) }),
  tickets: (params = {}) => request(`/support/tickets?${new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString()}`),
  ticket: (id) => request(`/support/tickets/${encodeURIComponent(id)}`),
  replyTicket: (id, text) => request(`/support/tickets/${encodeURIComponent(id)}/reply`, { method: "POST", body: JSON.stringify({ text }) }),
  ticketStatus: (id, status, note = "", priority = null) =>
    request(`/support/tickets/${encodeURIComponent(id)}/status`, { method: "POST", body: JSON.stringify({ status, note, priority }) }),
  kb: () => request("/support/kb"),
  addKb: (q, a) => request("/support/kb", { method: "POST", body: JSON.stringify({ q, a }) }),
  deleteKb: (id) => request(`/support/kb/${encodeURIComponent(id)}`, { method: "DELETE" }),
  fixes: () => request("/support/fixes"),
  errors: (params = {}) => request(`/errors?${new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString()}`),
  // الإشعارات ونافذة التحديثات
  notifPreview: (target) => request("/notifications/preview", { method: "POST", body: JSON.stringify(target) }),
  broadcast: (data) => request("/notifications/broadcast", { method: "POST", body: JSON.stringify(data) }),
  broadcasts: () => request("/notifications/broadcasts"),
  announcements: () => request("/announcements"),
  createAnnouncement: (data) => request("/announcements", { method: "POST", body: JSON.stringify(data) }),
  saveAnnouncement: (id, patch) => request(`/announcements/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(patch) }),
  deleteAnnouncement: (id) => request(`/announcements/${encodeURIComponent(id)}`, { method: "DELETE" }),
  seedAnnouncement: () => request("/announcements/seed", { method: "POST" }),
  uploadImage: (photo) => request("/media/image", { method: "POST", body: JSON.stringify({ photo }) }),
  // محفظة TON (العمليات الحساسة تتطلب OTP)
  tonOverview: () => request("/ton/overview"),
  tonOtp: (action, params) => request("/ton/otp", { method: "POST", body: JSON.stringify({ action, params }) }),
  tonExecute: (otp_id, code) => request("/ton/execute", { method: "POST", body: JSON.stringify({ otp_id, code }) }),
  tonTransferResult: (data) => request("/ton/transfer-result", { method: "POST", body: JSON.stringify(data) }),
  tonLog: () => request("/ton/log"),
  // حسابات تلجرام الحقيقية للدعم (احتياطية بالأولوية)
  supportAccounts: () => request("/support/accounts"),
  addSupportAccount: (data) => request("/support/accounts", { method: "POST", body: JSON.stringify(data) }),
  verifySupportAccount: (id, code, password) =>
    request(`/support/accounts/${encodeURIComponent(id)}/verify`, { method: "POST", body: JSON.stringify({ code, password }) }),
  updateSupportAccount: (id, patch) => request(`/support/accounts/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(patch) }),
  deleteSupportAccount: (id) => request(`/support/accounts/${encodeURIComponent(id)}`, { method: "DELETE" }),
  // النمو والتسويق
  funnel: (campaign) => request(`/growth/funnel${campaign ? `?campaign=${encodeURIComponent(campaign)}` : ""}`),
  coupons: () => request("/growth/coupons"),
  saveCoupon: (data) => request("/growth/coupons", { method: "POST", body: JSON.stringify(data) }),
  deleteCoupon: (code) => request(`/growth/coupons/${encodeURIComponent(code)}`, { method: "DELETE" }),
  gifts: () => request("/growth/gifts"),
  saveGift: (data) => request("/growth/gifts", { method: "POST", body: JSON.stringify(data) }),
  deleteGift: (code) => request(`/growth/gifts/${encodeURIComponent(code)}`, { method: "DELETE" }),
  campaigns: () => request("/growth/campaigns"),
  saveCampaign: (data) => request("/growth/campaigns", { method: "POST", body: JSON.stringify(data) }),
  deleteCampaign: (slug) => request(`/growth/campaigns/${encodeURIComponent(slug)}`, { method: "DELETE" }),
  automations: () => request("/growth/automations"),
  saveAutomation: (id, data) => request(`/growth/automations/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteAutomation: (id) => request(`/growth/automations/${encodeURIComponent(id)}`, { method: "DELETE" }),
  runAutomations: () => request("/growth/automations/run", { method: "POST" }),
  privatePackage: (data) => request("/packages/private", { method: "POST", body: JSON.stringify(data) }),
  leaderboardScriptPreview: (script, interval_sec) =>
    request("/leaderboard/script/preview", { method: "POST", body: JSON.stringify({ script, interval_sec }) }),
  // بوابة الدفع الخاصة (AW Pay)
  gateway: () => request("/gateway"),
  saveGateway: (patch) => request("/gateway", { method: "PUT", body: JSON.stringify(patch) }),
  gatewayInvoices: (status = "") => request(`/gateway/invoices${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  gatewayCheck: (id) => request(`/gateway/invoices/${encodeURIComponent(id)}/check`, { method: "POST" }),
  gatewayAccept: (id, note) => request(`/gateway/invoices/${encodeURIComponent(id)}/accept`, { method: "POST", body: JSON.stringify({ note }) }),
  gatewayCancel: (id) => request(`/gateway/invoices/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  gatewayAddresses: () => request("/gateway/addresses"),
  gatewaySweep: (network, uid) => request("/gateway/sweep", { method: "POST", body: JSON.stringify({ network, uid: String(uid) }) }),
  gatewaySweeps: () => request("/gateway/sweeps"),
  gatewayTonIncoming: () => request("/gateway/ton-incoming"),
  // تنبيهات فورية
  alerts: (since) => request(`/alerts?since=${since || 0}`),
};

// تصدير CSV (يفتح في Excel): رابط تنزيل مباشر بجلسة الأدمن الحالية
export const exportUrl = (kind) => `${BASE}/export/${kind}`;

export { ApiError };
