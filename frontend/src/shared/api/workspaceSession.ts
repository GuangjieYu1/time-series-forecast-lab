const AUTH_USER_KEY = "tsfl_auth_user_id";
const WORKSPACE_PREFIX = "tsfl_active_workspace";

function workspaceStorageKey(userId: string) {
  return `${WORKSPACE_PREFIX}:${userId}`;
}

export function getCurrentAuthUserId(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(AUTH_USER_KEY) ?? null;
}

export function setCurrentAuthUserId(userId: string | null): void {
  if (typeof window === "undefined") return;
  if (userId) {
    window.sessionStorage.setItem(AUTH_USER_KEY, userId);
  } else {
    window.sessionStorage.removeItem(AUTH_USER_KEY);
  }
}

export function loadSelectedWorkspaceId(userId?: string | null): string | null {
  if (typeof window === "undefined") return null;
  const resolvedUserId = userId ?? getCurrentAuthUserId();
  if (!resolvedUserId) return null;
  return window.localStorage.getItem(workspaceStorageKey(resolvedUserId));
}

export function saveSelectedWorkspaceId(userId: string, workspaceId: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(workspaceStorageKey(userId), workspaceId);
}

export function clearSelectedWorkspaceId(userId?: string | null): void {
  if (typeof window === "undefined") return;
  const resolvedUserId = userId ?? getCurrentAuthUserId();
  if (!resolvedUserId) return;
  window.localStorage.removeItem(workspaceStorageKey(resolvedUserId));
}
