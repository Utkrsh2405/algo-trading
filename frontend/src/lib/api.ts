const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;

  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? "Request failed");
  }

  return res.json() as Promise<T>;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface CurrentUser {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
}

export interface Order {
  id: string;
  user_id: string;
  strategy_id: string | null;
  idempotency_key: string;
  broker_order_id: string | null;
  symbol: string;
  side: "BUY" | "SELL";
  order_type: "MARKET" | "LIMIT" | "SL" | "SL-M";
  quantity: number;
  filled_quantity: number;
  price: number | null;
  status: "PENDING" | "PLACED" | "FILLED" | "FAILED" | "CANCELLED";
  rejection_reason: string | null;
  correlation_id: string | null;
  placed_at: string;
  filled_at: string | null;
}

export function login(email: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function signup(email: string, password: string, fullName?: string): Promise<CurrentUser> {
  return request<CurrentUser>("/api/auth/signup", {
    method: "POST",
    body: JSON.stringify({ email, password, full_name: fullName ?? null }),
  });
}

export function getCurrentUser(): Promise<CurrentUser> {
  return request<CurrentUser>("/api/auth/me");
}

export function getOrders(limit = 50, offset = 0): Promise<Order[]> {
  return request<Order[]>(`/api/orders?limit=${limit}&offset=${offset}`);
}

export function engageKillSwitch(reason = "Manual kill switch triggered from dashboard"): Promise<unknown> {
  return request<unknown>("/api/orders/kill-switch", {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function clearKillSwitch(): Promise<unknown> {
  return request<unknown>("/api/orders/kill-switch", { method: "DELETE" });
}

export function getStrategies(): Promise<any[]> {
  return request<any[]>("/api/strategies");
}

export function startStrategy(id: string): Promise<unknown> {
  return request<unknown>(`/api/strategies/${id}/start`, { method: "POST" });
}

export function stopStrategy(id: string): Promise<unknown> {
  return request<unknown>(`/api/strategies/${id}/stop`, { method: "POST" });
}

export function getPositions(): Promise<any[]> {
  return request<any[]>("/api/positions");
}
