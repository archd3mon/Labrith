/**
 * Auto-generated Typed API Client and UI State Hooks for FrontForge.
 * Generated at: 2026-10-14T07:59:16.220333+00:00
 * OpenAPI Title: Support Ticket Service API
 */

// --- Core UI Loading and Error State Types -------------------------------
export interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export interface ApiResponse<T> {
  data?: T;
  error?: string;
  status: number;
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public details?: any) {
    super(message);
    this.name = 'ApiError';
  }
}

// --- Schema Interfaces ---------------------------------------------------
export interface Ticket {
  id: string;
  title: string;
  priority: "low" | "medium" | "high" | "urgent";
  status: "open" | "pending" | "resolved" | "closed";
  created_at: string;
  assigned_to?: string;
}

export interface TicketDetail {
  id: string;
  title: string;
  priority: string;
  status: string;
  messages: Message[];
}

export interface Message {
  id: string;
  author: string;
  body: string;
  timestamp: string;
}

export interface ReplyRequest {
  body: string;
}

export interface CreateTicketRequest {
  title: string;
  priority: "low" | "medium" | "high" | "urgent";
  initial_message: string;
}

// --- Typed API Client Implementation -------------------------------------
export class ApiClient {
  constructor(private baseUrl: string = '') {}

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
    });

    if (!response.ok) {
      let errorBody: any = null;
      try { errorBody = await response.json(); } catch (_) { errorBody = await response.text(); }
      throw new ApiError(response.status, `HTTP ${response.status} from ${path}`, errorBody);
    }

    return response.json() as Promise<T>;
  }

  /** List open support tickets */
  async listTickets(): Promise<Ticket[]> {
    return this.request<Ticket[]>(`/api/tickets`, { method: 'GET' });
  }

  /** Create a new support ticket */
  async createTicket(payload: CreateTicketRequest): Promise<Ticket> {
    return this.request<Ticket>(`/api/tickets`, { method: 'POST', body: JSON.stringify(payload) });
  }

  /** Retrieve ticket details and message thread */
  async getTicketDetail(id: string): Promise<TicketDetail> {
    return this.request<TicketDetail>(`/api/tickets/${id}`, { method: 'GET' });
  }

  /** Post a reply to a support ticket thread */
  async sendReply(id: string, payload: ReplyRequest): Promise<TicketDetail> {
    return this.request<TicketDetail>(`/api/tickets/${id}/reply`, { method: 'POST', body: JSON.stringify(payload) });
  }

}

// Export singleton instance
export const apiClient = new ApiClient();