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
  // المكافآت والكوبونات
  rewardsConfig: () => request("/rewards/config"),
  saveRewardsConfig: (patch) => request("/rewards/config", { method: "PUT", body: JSON.stringify(patch) }),
  rewardCards: (uid) => request(`/rewards/cards${uid ? `?uid=${encodeURIComponent(uid)}` : ""}`),
  grantReward: (data) => request("/rewards/grant", { method: "POST", body: JSON.stringify(data) }),
  revokeReward: (id) => request(`/rewards/${encodeURIComponent(id)}/revoke`, { method: "POST" }),
  extendReward: (id, hours) =>
    request(`/rewards/${encodeURIComponent(id)}/extend`, { method: "POST", body: JSON.stringify({ hours }) }),
};

export { ApiError };
