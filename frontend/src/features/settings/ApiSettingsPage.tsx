import { useCallback, useEffect, useMemo, useState } from "react";
import { useLabStore } from "../../app/store";
import {
  addWorkspaceMember,
  createUser,
  createUserGroup,
  createWorkspace,
  deleteUserGroup,
  deleteWorkspace,
  fetchSession,
  fetchUserGroups,
  fetchUsers,
  fetchWorkspaceMembers,
  removeWorkspaceMember,
  updateUserGroups,
  updateUser,
  updateUserPassword,
  updateWorkspace,
} from "../../shared/api/client";
import { Badge, controls, PageHeader, SectionCard, StatCard, surface } from "../../shared/components/Ui";
import type { UserGroupSummary, UserSummary, WorkspaceMemberResponse } from "../../shared/types/api";
import { DeepSeekSettingsPanel } from "./DeepSeekSettingsPanel";
import { LocalMaintenancePanel } from "./LocalMaintenancePanel";

export function ApiSettingsPage() {
  const { currentUser, workspaces, selectedWorkspaceId, setSession } = useLabStore();
  const selectedWorkspace = workspaces.find((item) => item.workspaceId === selectedWorkspaceId) ?? null;
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [groups, setGroups] = useState<UserGroupSummary[]>([]);
  const [members, setMembers] = useState<WorkspaceMemberResponse[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [loadingGroups, setLoadingGroups] = useState(false);
  const [loadingMembers, setLoadingMembers] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [userForm, setUserForm] = useState({ username: "", displayName: "", password: "", isAdmin: false });
  const [groupForm, setGroupForm] = useState({ name: "", description: "" });
  const [groupFilter, setGroupFilter] = useState<"all" | "ungrouped" | string>("all");
  const [workspaceName, setWorkspaceName] = useState("");
  const [renameWorkspaceName, setRenameWorkspaceName] = useState("");
  const [memberUserId, setMemberUserId] = useState("");
  const [passwordDrafts, setPasswordDrafts] = useState<Record<string, string>>({});
  const [savingUserGroupIds, setSavingUserGroupIds] = useState<Record<string, boolean>>({});

  const refreshSessionState = useCallback(async () => {
    const session = await fetchSession();
    if (session.authenticated && session.user) {
      setSession(session);
    }
  }, [setSession]);

  const loadUsers = useCallback(async () => {
    if (!currentUser?.isAdmin) {
      setUsers([]);
      return;
    }
    setLoadingUsers(true);
    try {
      setUsers(await fetchUsers());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "用户列表加载失败。");
    } finally {
      setLoadingUsers(false);
    }
  }, [currentUser?.isAdmin]);

  const loadGroups = useCallback(async () => {
    if (!currentUser?.isAdmin) {
      setGroups([]);
      return;
    }
    setLoadingGroups(true);
    try {
      setGroups(await fetchUserGroups());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "用户分组加载失败。");
    } finally {
      setLoadingGroups(false);
    }
  }, [currentUser?.isAdmin]);

  const loadMembers = useCallback(async () => {
    if (!selectedWorkspaceId) {
      setMembers([]);
      return;
    }
    setLoadingMembers(true);
    try {
      setMembers(await fetchWorkspaceMembers(selectedWorkspaceId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "工作区成员加载失败。");
    } finally {
      setLoadingMembers(false);
    }
  }, [selectedWorkspaceId]);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  useEffect(() => {
    void loadGroups();
  }, [loadGroups]);

  useEffect(() => {
    void loadMembers();
  }, [loadMembers]);

  useEffect(() => {
    setRenameWorkspaceName(selectedWorkspace?.name ?? "");
  }, [selectedWorkspace?.name]);

  useEffect(() => {
    if (groupFilter === "all" || groupFilter === "ungrouped") return;
    if (!groups.some((group) => group.groupId === groupFilter)) {
      setGroupFilter("all");
    }
  }, [groupFilter, groups]);

  const availableMemberCandidates = useMemo(() => {
    const memberIds = new Set(members.map((item) => item.userId));
    return users.filter((user) => user.isActive && !memberIds.has(user.userId));
  }, [members, users]);

  const visibleUsers = useMemo(() => {
    if (groupFilter === "all") return users;
    if (groupFilter === "ungrouped") return users.filter((user) => user.groups.length === 0);
    return users.filter((user) => user.groups.some((group) => group.groupId === groupFilter));
  }, [groupFilter, users]);

  async function handleCreateUser(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      await createUser(userForm);
      setUserForm({ username: "", displayName: "", password: "", isAdmin: false });
      await loadUsers();
      await refreshSessionState();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建用户失败。");
    }
  }

  async function handleCreateGroup(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!groupForm.name.trim()) return;
    setError(null);
    try {
      await createUserGroup({
        name: groupForm.name.trim(),
        description: groupForm.description.trim() || undefined,
      });
      setGroupForm({ name: "", description: "" });
      await loadGroups();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建用户分组失败。");
    }
  }

  async function handleToggleUser(user: UserSummary) {
    setError(null);
    try {
      await updateUser(user.userId, { isActive: !user.isActive });
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新用户状态失败。");
    }
  }

  async function handleToggleUserGroup(user: UserSummary, groupId: string) {
    setSavingUserGroupIds((state) => ({ ...state, [user.userId]: true }));
    setError(null);
    try {
      const hasGroup = user.groups.some((group) => group.groupId === groupId);
      const nextGroupIds = hasGroup
        ? user.groups.filter((group) => group.groupId !== groupId).map((group) => group.groupId)
        : [...user.groups.map((group) => group.groupId), groupId];
      await updateUserGroups(user.userId, { groupIds: nextGroupIds });
      await Promise.all([loadUsers(), loadGroups()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新用户分组失败。");
    } finally {
      setSavingUserGroupIds((state) => ({ ...state, [user.userId]: false }));
    }
  }

  async function handleDeleteGroup(group: UserGroupSummary) {
    if (!window.confirm(`确认删除用户分组「${group.name}」吗？这会同时清空该分组下的成员归属。`)) return;
    setError(null);
    try {
      await deleteUserGroup(group.groupId);
      await Promise.all([loadUsers(), loadGroups()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除用户分组失败。");
    }
  }

  async function handleResetPassword(userId: string) {
    const password = passwordDrafts[userId]?.trim() ?? "";
    if (!password) {
      setError("请先填写新密码。");
      return;
    }
    setError(null);
    try {
      await updateUserPassword(userId, { password });
      setPasswordDrafts((state) => ({ ...state, [userId]: "" }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "密码重置失败。");
    }
  }

  async function handleCreateWorkspace(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!workspaceName.trim()) return;
    setError(null);
    try {
      await createWorkspace({ name: workspaceName.trim() });
      setWorkspaceName("");
      await refreshSessionState();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建共享工作区失败。");
    }
  }

  async function handleRenameWorkspace(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWorkspaceId || !renameWorkspaceName.trim()) return;
    setError(null);
    try {
      await updateWorkspace(selectedWorkspaceId, { name: renameWorkspaceName.trim() });
      await refreshSessionState();
    } catch (err) {
      setError(err instanceof Error ? err.message : "工作区重命名失败。");
    }
  }

  async function handleDeleteWorkspace() {
    if (!selectedWorkspaceId || !selectedWorkspace) return;
    if (!window.confirm(`确认删除共享工作区「${selectedWorkspace.name}」吗？该空间内实验和报告会一并删除。`)) return;
    setError(null);
    try {
      await deleteWorkspace(selectedWorkspaceId);
      await refreshSessionState();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除工作区失败。");
    }
  }

  async function handleAddMember(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWorkspaceId || !memberUserId.trim()) return;
    setError(null);
    try {
      await addWorkspaceMember(selectedWorkspaceId, { userId: memberUserId.trim() });
      setMemberUserId("");
      await loadMembers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "添加成员失败。");
    }
  }

  async function handleRemoveMember(userId: string) {
    if (!selectedWorkspaceId) return;
    setError(null);
    try {
      await removeWorkspaceMember(selectedWorkspaceId, userId);
      await loadMembers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "移除成员失败。");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="设置中心"
        title="API、本地用户与工作区管理"
        description="DeepSeek 仍然只保存在浏览器本地；用户、会话、工作区、实验和报告边界已经切到本地多用户模式。"
        action={<Badge tone="info">{currentUser?.isAdmin ? "管理员视图" : "成员视图"}</Badge>}
      />

      <div className="grid gap-4 md:grid-cols-4">
        <StatCard label="当前用户" value={currentUser?.displayName ?? "-"} hint={currentUser?.username ? `@${currentUser.username}` : "未登录"} tone="info" />
        <StatCard label="当前工作区" value={selectedWorkspace?.name ?? "未选择"} hint={selectedWorkspace ? `${selectedWorkspace.kind} / ${selectedWorkspace.role}` : "请先选择工作区"} tone="good" />
        <StatCard label="可访问空间" value={workspaces.length} hint="Personal / Shared / Example" />
        <StatCard label="API Key 存储" value="按用户隔离" hint="浏览器 localStorage 命名空间隔离" tone="warn" />
      </div>

      {error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-400/20 dark:bg-red-400/10 dark:text-red-200">
          {error}
        </div>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
        <div className="space-y-5">
          <DeepSeekSettingsPanel />
          <LocalMaintenancePanel />

          {currentUser?.isAdmin ? (
            <SectionCard title="用户分组" description="分组只用于组织、筛选和批量观察用户，不会改变现有登录、管理员或工作区权限。">
              <form className="grid gap-3 rounded-2xl border border-dashed border-slate-200 p-4 dark:border-white/10 md:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)_auto]" onSubmit={handleCreateGroup}>
                <input className={controls.input} placeholder="分组名称，例如：分析团队" value={groupForm.name} onChange={(event) => setGroupForm((state) => ({ ...state, name: event.target.value }))} />
                <input className={controls.input} placeholder="说明（可选），例如：负责业务分析与报表" value={groupForm.description} onChange={(event) => setGroupForm((state) => ({ ...state, description: event.target.value }))} />
                <button className={controls.primaryButton} type="submit">创建分组</button>
              </form>

              <div className="mt-4 grid gap-3 md:grid-cols-4">
                <StatCard label="分组数" value={groups.length} hint={loadingGroups ? "分组加载中..." : "可用于筛选和归类"} tone="info" />
                <StatCard label="已分组用户" value={users.filter((user) => user.groups.length > 0).length} hint="至少属于 1 个分组" tone="good" />
                <StatCard label="未分组用户" value={users.filter((user) => user.groups.length === 0).length} hint="建议补充分组，便于筛选" tone="warn" />
                <StatCard label="当前筛选" value={groupFilter === "all" ? "全部" : groupFilter === "ungrouped" ? "未分组" : groups.find((group) => group.groupId === groupFilter)?.name ?? "全部"} hint="会同步影响下方用户列表" />
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <button className={groupFilter === "all" ? controls.primaryButton : controls.secondaryButton} type="button" onClick={() => setGroupFilter("all")}>
                  全部用户
                </button>
                <button className={groupFilter === "ungrouped" ? controls.primaryButton : controls.secondaryButton} type="button" onClick={() => setGroupFilter("ungrouped")}>
                  未分组
                </button>
                {groups.map((group) => (
                  <button
                    key={group.groupId}
                    className={groupFilter === group.groupId ? controls.primaryButton : controls.secondaryButton}
                    type="button"
                    onClick={() => setGroupFilter(group.groupId)}
                  >
                    {group.name} · {group.memberCount}
                  </button>
                ))}
              </div>

              <div className="mt-4 space-y-3">
                {loadingGroups ? <div className={`text-sm ${surface.mutedText}`}>正在加载用户分组...</div> : null}
                {!groups.length && !loadingGroups ? (
                  <div className={`${surface.softPanel} p-4 text-sm ${surface.mutedText}`}>还没有任何用户分组。先创建几个组，下面的用户卡片就可以直接点标签分配了。</div>
                ) : null}
                {groups.map((group) => (
                  <div key={group.groupId} className={`${surface.softPanel} flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between`}>
                    <div className="min-w-0">
                      <div className={`truncate text-sm font-semibold ${surface.strongText}`}>{group.name}</div>
                      <div className={`mt-1 text-xs ${surface.mutedText}`}>{group.description || "没有额外说明。"}</div>
                      <div className={`mt-1 text-[11px] ${surface.mutedText}`}>{group.memberCount} 位成员 · {group.groupId}</div>
                    </div>
                    <button className={controls.dangerButton} type="button" onClick={() => void handleDeleteGroup(group)}>
                      删除分组
                    </button>
                  </div>
                ))}
              </div>
            </SectionCard>
          ) : null}

          {currentUser?.isAdmin ? (
            <SectionCard title="用户管理" description="普通用户现在可以在登录页自行注册；管理员仍然可以在这里直接创建用户、禁用账号和重置密码。">
              <form className="grid gap-3 rounded-2xl border border-dashed border-slate-200 p-4 dark:border-white/10 md:grid-cols-4" onSubmit={handleCreateUser}>
                <input className={controls.input} placeholder="用户名" value={userForm.username} onChange={(event) => setUserForm((state) => ({ ...state, username: event.target.value }))} />
                <input className={controls.input} placeholder="显示名称" value={userForm.displayName} onChange={(event) => setUserForm((state) => ({ ...state, displayName: event.target.value }))} />
                <input className={controls.input} type="password" placeholder="初始密码（至少 8 位）" value={userForm.password} onChange={(event) => setUserForm((state) => ({ ...state, password: event.target.value }))} />
                <label className={`${surface.softPanel} flex items-center justify-between px-3 py-2 text-sm ${surface.strongText}`}>
                  <span>管理员</span>
                  <input type="checkbox" checked={userForm.isAdmin} onChange={(event) => setUserForm((state) => ({ ...state, isAdmin: event.target.checked }))} />
                </label>
                <div className="md:col-span-4">
                  <button className={controls.primaryButton} type="submit">创建用户并自动生成 Personal Workspace</button>
                </div>
              </form>

              <div className="mt-4 space-y-3">
                <div className={`${surface.softPanel} flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between`}>
                  <div>
                    <div className={`text-sm font-semibold ${surface.strongText}`}>用户筛选</div>
                    <div className={`mt-1 text-xs ${surface.mutedText}`}>当前展示 {visibleUsers.length} / {users.length} 位用户。可按分组切换，并在用户卡片上直接点击标签完成归组。</div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button className={groupFilter === "all" ? controls.primaryButton : controls.secondaryButton} type="button" onClick={() => setGroupFilter("all")}>
                      全部
                    </button>
                    <button className={groupFilter === "ungrouped" ? controls.primaryButton : controls.secondaryButton} type="button" onClick={() => setGroupFilter("ungrouped")}>
                      未分组
                    </button>
                    {groups.map((group) => (
                      <button
                        key={group.groupId}
                        className={groupFilter === group.groupId ? controls.primaryButton : controls.secondaryButton}
                        type="button"
                        onClick={() => setGroupFilter(group.groupId)}
                      >
                        {group.name}
                      </button>
                    ))}
                  </div>
                </div>

                {loadingUsers ? <div className={`text-sm ${surface.mutedText}`}>正在加载用户列表...</div> : null}
                {visibleUsers.map((user) => (
                  <div key={user.userId} className={`${surface.softPanel} grid gap-3 p-4 lg:grid-cols-[minmax(0,1fr)_auto_auto] lg:items-center`}>
                    <div className="min-w-0">
                      <div className={`truncate text-sm font-semibold ${surface.strongText}`}>{user.displayName}</div>
                      <div className={`truncate text-xs ${surface.mutedText}`}>
                        @{user.username} · {user.isAdmin ? "Admin" : "User"} · {user.isActive ? "Active" : "Disabled"}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {user.groups.length ? user.groups.map((group) => <Badge key={group.groupId} tone="info">{group.name}</Badge>) : <Badge tone="neutral">未分组</Badge>}
                      </div>
                      <div className={`mt-1 truncate text-[11px] ${surface.mutedText}`}>{user.userId}</div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button className={user.isActive ? controls.secondaryButton : controls.primaryButton} type="button" onClick={() => void handleToggleUser(user)}>
                        {user.isActive ? "停用" : "启用"}
                      </button>
                      <div className="flex flex-col gap-2 sm:flex-row">
                        <input
                          className={controls.input}
                          type="password"
                          placeholder="新密码"
                          value={passwordDrafts[user.userId] ?? ""}
                          onChange={(event) => setPasswordDrafts((state) => ({ ...state, [user.userId]: event.target.value }))}
                        />
                        <button className={controls.secondaryButton} type="button" onClick={() => void handleResetPassword(user.userId)}>
                          重置密码
                        </button>
                      </div>
                    </div>
                    <div className="flex flex-wrap items-start gap-2">
                      {groups.length ? (
                        groups.map((group) => {
                          const active = user.groups.some((item) => item.groupId === group.groupId);
                          const disabled = savingUserGroupIds[user.userId] ?? false;
                          return (
                            <button
                              key={group.groupId}
                              className={active ? controls.primaryButton : controls.secondaryButton}
                              type="button"
                              disabled={disabled}
                              onClick={() => void handleToggleUserGroup(user, group.groupId)}
                            >
                              {active ? "已在" : "加入"} {group.name}
                            </button>
                          );
                        })
                      ) : (
                        <div className={`text-xs ${surface.mutedText}`}>还没有可分配的用户分组。</div>
                      )}
                    </div>
                  </div>
                ))}
                {!loadingUsers && !visibleUsers.length ? (
                  <div className={`${surface.softPanel} p-4 text-sm ${surface.mutedText}`}>当前筛选下没有匹配用户。</div>
                ) : null}
              </div>
            </SectionCard>
          ) : null}

          <SectionCard title="工作区管理" description="每个用户默认拥有 Personal Workspace；Shared Workspace 由 owner 负责成员管理。">
            <form className="grid gap-3 rounded-2xl border border-dashed border-slate-200 p-4 dark:border-white/10 sm:grid-cols-[minmax(0,1fr)_auto]" onSubmit={handleCreateWorkspace}>
              <input className={controls.input} placeholder="新建 Shared Workspace 名称" value={workspaceName} onChange={(event) => setWorkspaceName(event.target.value)} />
              <button className={controls.primaryButton} type="submit">创建 Shared Workspace</button>
            </form>

            <div className="mt-4 grid gap-3">
              {workspaces.map((workspace) => (
                <div key={workspace.workspaceId} className={`${surface.softPanel} flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between`}>
                  <div className="min-w-0">
                    <div className={`truncate text-sm font-semibold ${surface.strongText}`}>{workspace.name}</div>
                    <div className={`mt-1 flex flex-wrap gap-2 text-xs ${surface.mutedText}`}>
                      <Badge tone={workspace.kind === "example" ? "warn" : workspace.kind === "shared" ? "info" : "good"}>{workspace.kind}</Badge>
                      <Badge tone="neutral">{workspace.role}</Badge>
                      {workspace.isReadOnly ? <Badge tone="warn">只读</Badge> : null}
                      {workspace.isPersonal ? <Badge tone="neutral">自动生成</Badge> : null}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {workspace.workspaceId === selectedWorkspaceId ? <Badge tone="good">当前空间</Badge> : null}
                  </div>
                </div>
              ))}
            </div>
          </SectionCard>

          <SectionCard
            title="当前工作区详情"
            description={selectedWorkspace ? "这里的成员、命名和删除权限都跟随当前选中的工作区。" : "请先在顶部选择一个工作区。"}
          >
            {!selectedWorkspace ? (
              <div className={`text-sm ${surface.mutedText}`}>没有可编辑的工作区上下文。</div>
            ) : (
              <div className="space-y-4">
                <div className="grid gap-3 md:grid-cols-4">
                  <StatCard label="名称" value={selectedWorkspace.name} hint="顶部切换器实时同步" />
                  <StatCard label="类型" value={selectedWorkspace.kind} hint={selectedWorkspace.isReadOnly ? "只读" : "可写"} tone={selectedWorkspace.isReadOnly ? "warn" : "good"} />
                  <StatCard label="角色" value={selectedWorkspace.role} hint={selectedWorkspace.isOwner ? "可管理" : "仅使用"} />
                  <StatCard label="成员数" value={members.length} hint={loadingMembers ? "加载中..." : "当前空间成员"} tone="info" />
                </div>

                {selectedWorkspace.kind === "shared" && selectedWorkspace.isOwner && !selectedWorkspace.isReadOnly ? (
                  <form className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]" onSubmit={handleRenameWorkspace}>
                    <input className={controls.input} value={renameWorkspaceName} onChange={(event) => setRenameWorkspaceName(event.target.value)} />
                    <button className={controls.secondaryButton} type="submit">重命名当前共享空间</button>
                  </form>
                ) : null}

                <div className="space-y-3">
                  {members.map((member) => (
                    <div key={member.userId} className={`${surface.softPanel} flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between`}>
                      <div className="min-w-0">
                        <div className={`truncate text-sm font-semibold ${surface.strongText}`}>{member.displayName}</div>
                        <div className={`truncate text-xs ${surface.mutedText}`}>@{member.username} · {member.role} · {member.isActive ? "Active" : "Disabled"}</div>
                        <div className={`truncate text-[11px] ${surface.mutedText}`}>{member.userId}</div>
                      </div>
                      {selectedWorkspace.kind === "shared" && selectedWorkspace.isOwner && member.role !== "owner" ? (
                        <button className={controls.dangerButton} onClick={() => void handleRemoveMember(member.userId)}>
                          移除成员
                        </button>
                      ) : null}
                    </div>
                  ))}
                </div>

                {selectedWorkspace.kind === "shared" && selectedWorkspace.isOwner && !selectedWorkspace.isReadOnly ? (
                  <form className="grid gap-3 rounded-2xl border border-dashed border-slate-200 p-4 dark:border-white/10" onSubmit={handleAddMember}>
                    {availableMemberCandidates.length ? (
                      <select className={controls.input} value={memberUserId} onChange={(event) => setMemberUserId(event.target.value)}>
                        <option value="">选择要加入的用户</option>
                        {availableMemberCandidates.map((user) => (
                          <option key={user.userId} value={user.userId}>
                            {user.displayName} (@{user.username})
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input className={controls.input} placeholder="输入 userId 添加成员" value={memberUserId} onChange={(event) => setMemberUserId(event.target.value)} />
                    )}
                    <div className="flex flex-wrap gap-2">
                      <button className={controls.primaryButton} type="submit">添加成员</button>
                      {selectedWorkspace.kind === "shared" ? (
                        <button className={controls.dangerButton} type="button" onClick={() => void handleDeleteWorkspace()}>
                          删除当前共享工作区
                        </button>
                      ) : null}
                    </div>
                  </form>
                ) : null}
              </div>
            )}
          </SectionCard>
        </div>

        <div className="space-y-5">
          <SectionCard title="报告生成流程" description="生成时后端只读取实验结果摘要，不读取原始上传文件。">
            <div className="space-y-3">
              {["读取模型排行榜", "分析自动优化策略与逐轮结果", "分析残差与误差分布", "整理最终预测区间", "生成中文业务建议"].map((step, index) => (
                <div key={step} className={`${surface.softPanel} flex items-center gap-3 p-3`}>
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-xs font-semibold text-white dark:bg-indigo-400 dark:text-slate-950">
                    {index + 1}
                  </span>
                  <span className={`text-sm font-medium ${surface.strongText}`}>{step}</span>
                </div>
              ))}
            </div>
            <div className="mt-4 rounded-2xl border border-cyan-200 bg-cyan-50 p-4 text-sm leading-6 text-cyan-800 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-100">
              没有配置 API Key 时，报告面板会显示可操作提示；预测实验本身仍可完整运行。当前浏览器中 DeepSeek 设置会按 userId 自动分开保存，避免多账号串号。
            </div>
          </SectionCard>

          <SectionCard title="v1 工作区规则" description="这轮故意把边界定得很明确，避免多用户下出现串空间或 future leakage。">
            <div className="space-y-3 text-sm leading-6">
              <div className={`${surface.softPanel} p-4`}>
                <div className={`font-semibold ${surface.strongText}`}>上传与运行</div>
                <div className={`mt-2 ${surface.mutedText}`}>uploadId 现在绑定当前登录用户与当前工作区，切换工作区后会自动清空 upload / rerun / forecast 草稿。</div>
              </div>
              <div className={`${surface.softPanel} p-4`}>
                <div className={`font-semibold ${surface.strongText}`}>历史记录</div>
                <div className={`mt-2 ${surface.mutedText}`}>Overview、Experiments、Runtime、Manifest、Feature Factory、Report 都只看当前工作区。</div>
              </div>
              <div className={`${surface.softPanel} p-4`}>
                <div className={`font-semibold ${surface.strongText}`}>Example Workspace</div>
                <div className={`mt-2 ${surface.mutedText}`}>Example 空间固定只读，用来展示当前 UI walkthrough；可以查看但不能写入、删除或重跑。</div>
              </div>
            </div>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
