export interface UserProfile {
  id?: string | number;
  username?: string;
  email?: string;
  display_name?: string;
  displayName?: string;
  role?: string;
  status?: string;
  auth_code_configured?: boolean;
  authCodeConfigured?: boolean;
  has_user_auth_code?: boolean;
  hasUserAuthCode?: boolean;
  credits?: number;
  credit_balance?: number;
  creditBalance?: number;
  created_at?: string;
  createdAt?: string;
}

export interface UserApiKey {
  id: string | number;
  name: string;
  key_prefix?: string;
  keyPrefix?: string;
  key_masked?: string;
  keyMasked?: string;
  masked_key?: string;
  maskedKey?: string;
  api_key?: string;
  apiKey?: string;
  legacy_hash_only?: boolean;
  legacyHashOnly?: boolean;
  enabled?: boolean;
  last_used_at?: string | null;
  lastUsedAt?: string | null;
  created_at?: string;
  createdAt?: string;
}

export interface UserAuthCodeInfo {
  configured: boolean;
  user_auth_code?: string;
  userAuthCode?: string;
  legacy_hash_only?: boolean;
  legacyHashOnly?: boolean;
  updated_at?: string | null;
  updatedAt?: string | null;
  pop_host: string;
  popHost?: string;
  pop_port: number;
  popPort?: number;
  mailboxes: string[];
}

export interface CreditTransaction {
  id: string | number;
  amount: number;
  balance?: number;
  balance_after?: number;
  balanceAfter?: number;
  type?: string;
  reason?: string;
  description?: string;
  created_at?: string;
  createdAt?: string;
}

export interface CreditSummary {
  balance: number;
  transactions: CreditTransaction[];
}

export interface UserMailbox {
  id: string | number;
  mailbox_id?: string;
  mailboxId?: string;
  address: string;
  purpose?: string;
  source?: string;
  status?: string;
  verification_status?: string;
  verificationStatus?: string;
  verification_code?: string;
  verificationCode?: string;
  domain?: string;
  error_message?: string;
  errorMessage?: string;
  created_at?: string;
  createdAt?: string;
  expires_at?: string | null;
  expiresAt?: string | null;
}

export interface BatchCreateMailboxesResult {
  requested: number;
  succeeded: number;
  failed: number;
  created: UserMailbox[];
  errors: Array<{ index: number; code: string; message: string }>;
}
