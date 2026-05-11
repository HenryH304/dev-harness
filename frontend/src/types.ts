export interface Ticket {
  id: number;
  project: string;
  title: string;
  description: string;
  acceptance_criteria: unknown[];
  priority: number;
  state: string;
  branch_name: string | null;
  worktree_path: string | null;
  current_agent: string | null;
  assigned_at: string | null;
  agent_attempts: number;
  developer_timeouts: number;
  reviewer_timeouts: number;
  tester_timeouts: number;
  merger_timeouts: number;
  review_rejection_count: number;
  tester_rejection_count: number;
  created_at: string;
  updated_at: string;
}

export const COLUMNS = [
  { key: 'to_do', label: 'To Do' },
  { key: 'blocked', label: 'Blocked' },
  { key: 'in_progress', label: 'In Progress' },
  { key: 'ready_for_review', label: 'Ready for Review' },
  { key: 'in_review', label: 'In Review' },
  { key: 'ready_for_test', label: 'Ready for Test' },
  { key: 'in_test', label: 'In Test' },
  { key: 'ready_to_merge', label: 'Ready to Merge' },
  { key: 'done', label: 'Done' },
] as const;

export type ColumnKey = (typeof COLUMNS)[number]['key'];
