export type ConnectorStatus = {
  id: string;
  name: string;
  status: string;
  message: string;
  write_actions_enabled?: boolean;
  http_probing_enabled?: boolean;
};

export type HaloReadResult = {
  status: string;
  message: string;
  count: number;
};

export type HaloTicket = {
  id: string;
  summary: string;
  status: string;
  priority: string;
  client_name: string;
};

export type ApprovalRequest = {
  id: number;
  subject_id: string;
  action_type: string;
  status: string;
  comment: string;
  execution_status: string;
  execution_message: string;
  payload?: {
    fields?: Record<string, string | number | boolean | null>;
    [key: string]: unknown;
  };
  can_execute?: boolean;
  block_reason?: string;
  workflow_run_id?: string | number | null;
};

export type EventHistory = {
  id: number;
  event_type: string;
  subject_id: string;
  status: string;
  message: string;
};

export type WorkflowRun = {
  id: string | number;
  status: string;
  goal?: string;
  message?: string;
  created_at?: string;
  updated_at?: string;
  approval_request_id?: number;
};

export type HaloTicketsResponse = {
  result: HaloReadResult;
  items: HaloTicket[];
};

export type AuthRoleResponse = {
  role: "admin" | "technician" | "viewer";
  api_auth_required: boolean;
  demo_mode: boolean;
};
