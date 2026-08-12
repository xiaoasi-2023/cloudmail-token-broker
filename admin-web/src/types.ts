export interface Overview {
  instance_total: number;
  instance_enabled: number;
  instance_healthy: number;
  domain_total: number;
  domain_enabled: number;
  mailbox_total: number;
  error_total: number;
}

export interface CloudMailInstance {
  id: number;
  name: string;
  base_url: string;
  admin_email: string;
  proxy_url: string;
  verify_tls: boolean;
  enabled: boolean;
  health_status: string;
  last_checked_at?: string | null;
  last_error?: string;
  domain_count?: number;
  created_at: string;
  updated_at: string;
}

export interface MailDomain {
  id: number;
  instance_id: number;
  instance_name?: string;
  domain: string;
  enabled: boolean;
  weight: number;
  status: string;
  failure_count: number;
  cooldown_until?: string | null;
  last_used_at?: string | null;
  success_count: number;
  failure_total: number;
  remark: string;
  created_at: string;
  updated_at: string;
}

export interface MailboxRecord {
  id: string;
  address: string;
  purpose?: string;
  source?: string;
  status: string;
  verification_status?: string;
  verification_code?: string;
  domain: string;
  instance_name: string;
  created_at: string;
  expires_at?: string | null;
}

export interface RequestLog {
  id: number;
  request_id?: string;
  user_id?: number;
  user_username?: string;
  user_email?: string;
  method?: string;
  path?: string;
  source?: string;
  mailbox_id?: string;
  domain?: string;
  instance_name?: string;
  status_code: number;
  error_code?: string;
  error_message?: string;
  duration_ms?: number;
  created_at: string;
}

export interface AdminUser {
  id: number;
  username: string;
  email?: string | null;
  role: "admin" | "user" | string;
  status: string;
  pop_enabled: boolean;
  credit_balance: number;
  api_key_count?: number;
  has_user_auth_code: boolean;
  has_admin_pop_auth_code: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreditRule {
  operation: string;
  cost_points: number;
  initial_user_points: number;
  updated_by?: number | null;
  updated_at?: string | null;
}

export interface CreditAdjustResult {
  user_id: number;
  amount: number;
  balance_after: number;
  transaction_id: number;
  remark: string;
}

export interface PopAuthCodeResult {
  configured: boolean;
  admin_pop_auth_code: string;
  legacy_hash_only?: boolean;
  updated_at?: string | null;
}

export interface InstancePayload {
  name: string;
  base_url: string;
  admin_email: string;
  admin_password?: string;
  proxy_url: string;
  verify_tls: boolean;
  enabled: boolean;
}

export interface DomainPayload {
  instance_id: number;
  domain: string;
  enabled: boolean;
  weight: number;
  remark: string;
}
