import { useCallback, useEffect, useState } from "react";
import { useLabStore } from "../../app/store";
import {
  cancelUserGroupRequest,
  createUser,
  createUserGroup,
  createWorkspace,
  deleteUserGroup,
  deleteWorkspace,
  fetchMyGroupState,
  fetchPendingGroupRequests,
  fetchRegistrationGroups,
  fetchSession,
  fetchUserDirectory,
  fetchUserGroups,
  fetchUsers,
  fetchWorkspaceMembers,
  leaveUserGroup,
  replaceWorkspaceMembers,
  requestUserGroups,
  reviewUserGroupRequest,
  updateUser,
  updateUserGroups,
  updateUserPassword,
  updateWorkspace,
} from "../../shared/api/client";
import { Badge, controls, PageHeader, SectionCard, StatCard, surface } from "../../shared/components/Ui";
import { SearchableMultiSelect } from "../../shared/components/SearchableMultiSelect";
import type {
  GroupJoinRequestSummary,
  MyGroupStateResponse,
  RegistrationGroupSummary,
  UserDirectoryEntry,
  UserGroupSummary,
  UserSummary,
  WorkspaceMemberResponse,
} from "../../shared/types/api";
import { DeepSeekSettingsPanel } from "./DeepSeekSettingsPanel";
import { LocalMaintenancePanel } from "./LocalMaintenancePanel";

function userOptions(users: UserDirectoryEntry[], excludeUserId?: string) {
  return users.filter((user) => user.userId !== excludeUserId).map((user) => ({
    value: user.userId,
    label: user.displayName,
    description: `@${user.username}`,
    keywords: user.username,
  }));
}

export function ApiSettingsPage() {
  const { currentUser, workspaces, selectedWorkspaceId, setSession } = useLabStore();
  const selectedWorkspace = workspaces.find((item) => item.workspaceId === selectedWorkspaceId) ?? null;
  const [directory, setDirectory] = useState<UserDirectoryEntry[]>([]);
  const [registrationGroups, setRegistrationGroups] = useState<RegistrationGroupSummary[]>([]);
  const [groupState, setGroupState] = useState<MyGroupStateResponse>({ memberships: [], requests: [] });
  const [pendingRequests, setPendingRequests] = useState<GroupJoinRequestSummary[]>([]);
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [groups, setGroups] = useState<UserGroupSummary[]>([]);
  const [members, setMembers] = useState<WorkspaceMemberResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applyGroupIds, setApplyGroupIds] = useState<string[]>([]);
  const [workspaceName, setWorkspaceName] = useState("");
  const [customMemberIds, setCustomMemberIds] = useState<string[]>([]);
  const [editMemberIds, setEditMemberIds] = useState<string[]>([]);
  const [renameWorkspaceName, setRenameWorkspaceName] = useState("");
  const [groupForm, setGroupForm] = useState({ name: "", description: "", managerUserIds: [] as string[] });
  const [userForm, setUserForm] = useState({ username: "", displayName: "", password: "", isAdmin: false, groupIds: [] as string[] });
  const [passwordDrafts, setPasswordDrafts] = useState<Record<string, string>>({});
  const [adminUserQuery, setAdminUserQuery] = useState("");
  const [adminUserPage, setAdminUserPage] = useState(0);

  const refreshSessionState = useCallback(async () => {
    const session = await fetchSession();
    if (session.authenticated && session.user) setSession(session);
  }, [setSession]);

  const loadPage = useCallback(async () => {
    if (!currentUser) return;
    setLoading(true);
    try {
      const [nextDirectory, nextRegistrationGroups, nextGroupState, nextPending] = await Promise.all([
        fetchUserDirectory(),
        fetchRegistrationGroups(),
        fetchMyGroupState(),
        fetchPendingGroupRequests(),
      ]);
      setDirectory(nextDirectory);
      setRegistrationGroups(nextRegistrationGroups);
      setGroupState(nextGroupState);
      setPendingRequests(nextPending);
      if (currentUser.isAdmin) {
        const [nextUsers, nextGroups] = await Promise.all([fetchUsers(), fetchUserGroups()]);
        setUsers(nextUsers);
        setGroups(nextGroups);
      } else {
        setUsers([]);
        setGroups([]);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "设置数据加载失败。");
    } finally {
      setLoading(false);
    }
  }, [currentUser]);

  const loadMembers = useCallback(async () => {
    if (!selectedWorkspace || selectedWorkspace.kind !== "custom") {
      setMembers([]);
      setEditMemberIds([]);
      return;
    }
    try {
      const nextMembers = await fetchWorkspaceMembers(selectedWorkspace.workspaceId);
      setMembers(nextMembers);
      setEditMemberIds(nextMembers.filter((member) => member.role !== "owner").map((member) => member.userId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "协作成员加载失败。");
    }
  }, [selectedWorkspace]);

  useEffect(() => { void loadPage(); }, [loadPage]);
  useEffect(() => { void loadMembers(); }, [loadMembers]);
  useEffect(() => { setRenameWorkspaceName(selectedWorkspace?.name ?? ""); }, [selectedWorkspace?.name]);

  const activeGroupIds = new Set(groupState.memberships.map((membership) => membership.groupId));
  const pendingGroupIds = new Set(groupState.requests.filter((request) => request.status === "pending").map((request) => request.groupId));
  const requestableGroups = registrationGroups.filter((group) => !activeGroupIds.has(group.groupId) && !pendingGroupIds.has(group.groupId));
  const normalizedAdminUserQuery = adminUserQuery.trim().toLowerCase();
  const filteredAdminUsers = users.filter((user) => !normalizedAdminUserQuery || `${user.displayName} ${user.username}`.toLowerCase().includes(normalizedAdminUserQuery));
  const adminUserPageSize = 20;
  const adminUserPageCount = Math.max(1, Math.ceil(filteredAdminUsers.length / adminUserPageSize));
  const safeAdminUserPage = Math.min(adminUserPage, adminUserPageCount - 1);
  const visibleAdminUsers = filteredAdminUsers.slice(safeAdminUserPage * adminUserPageSize, (safeAdminUserPage + 1) * adminUserPageSize);

  async function runAction(action: () => Promise<void>, fallback: string, refreshSession = false) {
    setSaving(true);
    setError(null);
    try {
      await action();
      if (refreshSession) await refreshSessionState();
      await loadPage();
    } catch (err) {
      setError(err instanceof Error ? err.message : fallback);
    } finally {
      setSaving(false);
    }
  }

  async function handleApplyGroups() {
    if (!applyGroupIds.length) return;
    await runAction(async () => {
      await requestUserGroups(applyGroupIds);
      setApplyGroupIds([]);
    }, "提交入组申请失败。");
  }

  async function handleCreateCustom(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!workspaceName.trim()) return;
    await runAction(async () => {
      await createWorkspace({ name: workspaceName.trim(), memberUserIds: customMemberIds });
      setWorkspaceName("");
      setCustomMemberIds([]);
    }, "创建 Custom Space 失败。", true);
  }

  async function handleSaveCustomMembers() {
    if (!selectedWorkspace) return;
    await runAction(async () => {
      await replaceWorkspaceMembers(selectedWorkspace.workspaceId, editMemberIds);
      await loadMembers();
    }, "保存协作成员失败。", true);
  }

  async function handleRenameCustom(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWorkspace || !renameWorkspaceName.trim()) return;
    await runAction(async () => { await updateWorkspace(selectedWorkspace.workspaceId, { name: renameWorkspaceName.trim() }); }, "重命名失败。", true);
  }

  async function handleDeleteCustom() {
    if (!selectedWorkspace || !window.confirm(`确认删除 Custom Space「${selectedWorkspace.name}」及其中内容吗？`)) return;
    await runAction(async () => { await deleteWorkspace(selectedWorkspace.workspaceId); }, "删除 Custom Space 失败。", true);
  }

  async function handleCreateGroup(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!groupForm.name.trim()) return;
    await runAction(async () => {
      await createUserGroup({
        name: groupForm.name.trim(),
        description: groupForm.description.trim() || undefined,
        managerUserIds: groupForm.managerUserIds,
      });
      setGroupForm({ name: "", description: "", managerUserIds: [] });
    }, "创建用户组失败。", true);
  }

  async function handleCreateUser(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runAction(async () => {
      await createUser(userForm);
      setUserForm({ username: "", displayName: "", password: "", isAdmin: false, groupIds: [] });
    }, "创建用户失败。", true);
  }

  async function handleToggleUserGroup(user: UserSummary, groupId: string) {
    const nextIds = user.groups.some((group) => group.groupId === groupId)
      ? user.groups.filter((group) => group.groupId !== groupId).map((group) => group.groupId)
      : [...user.groups.map((group) => group.groupId), groupId];
    await runAction(async () => { await updateUserGroups(user.userId, { groupIds: nextIds }); }, "更新用户组失败。", true);
  }

  async function handleResetPassword(userId: string) {
    const password = passwordDrafts[userId]?.trim();
    if (!password) { setError("请填写新密码。"); return; }
    await runAction(async () => {
      await updateUserPassword(userId, { password });
      setPasswordDrafts((current) => ({ ...current, [userId]: "" }));
    }, "重置密码失败。");
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="设置中心"
        title="用户组与工作区"
        description="组内共享使用 Public Space；临时或跨组协作使用 Custom Space。Private 永远只属于本人。"
        action={<Badge tone={pendingRequests.length ? "warn" : "info"}>入组待审批 {pendingRequests.length}</Badge>}
      />

      <div className="grid gap-4 md:grid-cols-4">
        <StatCard label="当前用户" value={currentUser?.displayName ?? "-"} hint={currentUser?.isAdmin ? "全局管理员" : "普通用户"} tone="info" />
        <StatCard label="已加入组" value={groupState.memberships.length} hint="可访问对应 Public Space" tone="good" />
        <StatCard label="待审批申请" value={groupState.requests.filter((request) => request.status === "pending").length} hint="审批前只有 Private" tone="warn" />
        <StatCard label="可访问空间" value={workspaces.length} hint="Private / Public / Custom / Example" />
      </div>

      {error ? <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-400/20 dark:bg-red-400/10 dark:text-red-200">{error}</div> : null}
      {loading ? <div className={`text-sm ${surface.mutedText}`}>正在加载设置…</div> : null}

      <div className="grid gap-5 xl:grid-cols-2">
        <div className="space-y-5">
          <SectionCard title="我的用户组" description="一个账号可以加入多个组；每个已批准组自动对应一个组内 Public Space。">
            <div className="space-y-3">
              {groupState.memberships.map((membership) => (
                <div key={membership.groupId} className={`${surface.softPanel} flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between`}>
                  <div>
                    <div className={`font-semibold ${surface.strongText}`}>{membership.name}</div>
                    <div className="mt-1 flex gap-2"><Badge tone={membership.role === "manager" ? "info" : "neutral"}>{membership.role}</Badge>{membership.isArchived ? <Badge tone="warn">已归档 · 只读</Badge> : <Badge tone="good">Public 可用</Badge>}</div>
                  </div>
                  {!membership.isArchived ? <button className={controls.dangerButton} disabled={saving} onClick={() => {
                    if (window.confirm(`确认退出「${membership.name}」吗？退出后会立即失去 Public Space 访问权。`)) {
                      void runAction(async () => { await leaveUserGroup(membership.groupId); }, "退出组失败。", true);
                    }
                  }}>退出组</button> : null}
                </div>
              ))}
              {!groupState.memberships.length ? <div className={`${surface.softPanel} p-4 text-sm ${surface.mutedText}`}>尚未加入任何组。</div> : null}
            </div>

            {requestableGroups.length ? (
              <div className="mt-4 space-y-3 rounded-2xl border border-dashed border-slate-200 p-4 dark:border-white/10">
                <div className={`text-sm font-semibold ${surface.strongText}`}>继续申请入组</div>
                <SearchableMultiSelect
                  options={requestableGroups.map((group) => ({ value: group.groupId, label: group.name, description: group.description ?? undefined }))}
                  value={applyGroupIds}
                  onChange={setApplyGroupIds}
                  placeholder="搜索并选择要申请的用户组"
                  searchPlaceholder="按组名或说明搜索"
                  emptyMessage="没有匹配的可申请用户组。"
                  disabled={saving}
                />
                <button className={controls.primaryButton} disabled={!applyGroupIds.length || saving} onClick={() => void handleApplyGroups()}>提交申请</button>
              </div>
            ) : null}

            <div className="mt-4 space-y-2">
              {groupState.requests.filter((request) => request.status !== "approved").map((request) => (
                <div key={request.requestId} className={`${surface.softPanel} flex items-center justify-between gap-3 p-3 text-sm`}>
                  <div><span className={surface.strongText}>{request.groupName}</span> <Badge tone={request.status === "pending" ? "warn" : request.status === "rejected" ? "bad" : "neutral"}>{request.status}</Badge></div>
                  {request.status === "pending" ? <button className={controls.secondaryButton} disabled={saving} onClick={() => void runAction(async () => { await cancelUserGroupRequest(request.requestId); }, "撤回申请失败。")} >撤回</button> : null}
                </div>
              ))}
            </div>
          </SectionCard>

          {pendingRequests.length ? (
            <SectionCard title={`入组审批（${pendingRequests.length}）`} description="只有该组 manager 或全局管理员可以审批。企业微信失败不会影响这里的待办。">
              <div className="space-y-3">
                {pendingRequests.map((request) => (
                  <div key={request.requestId} className={`${surface.softPanel} flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between`}>
                    <div><div className={`font-semibold ${surface.strongText}`}>{request.displayName} <span className={`text-sm font-normal ${surface.mutedText}`}>@{request.username}</span></div><div className={`mt-1 text-xs ${surface.mutedText}`}>申请加入 {request.groupName} · 通知 {request.notifyStatus}</div></div>
                    <div className="flex gap-2"><button className={controls.primaryButton} disabled={saving} onClick={() => void runAction(async () => { await reviewUserGroupRequest(request.requestId, "approved"); }, "审批失败。", true)}>同意</button><button className={controls.dangerButton} disabled={saving} onClick={() => void runAction(async () => { await reviewUserGroupRequest(request.requestId, "rejected"); }, "拒绝失败。")} >拒绝</button></div>
                  </div>
                ))}
              </div>
            </SectionCard>
          ) : null}

          <SectionCard title="创建 Custom Space" description="从活跃用户目录搜索并多选成员，可跨组组队；Owner 后续可随时调整。">
            <form className="space-y-4" onSubmit={handleCreateCustom}>
              <input className={controls.input} placeholder="Custom Space 名称" value={workspaceName} onChange={(event) => setWorkspaceName(event.target.value)} />
              <SearchableMultiSelect options={userOptions(directory, currentUser?.userId)} value={customMemberIds} onChange={setCustomMemberIds} placeholder="搜索并选择协作成员" searchPlaceholder="按姓名或用户名搜索" emptyMessage="没有匹配的活跃用户。" disabled={saving} />
              <button className={controls.primaryButton} type="submit" disabled={!workspaceName.trim() || saving}>创建 Custom Space</button>
            </form>
          </SectionCard>

          <SectionCard title="当前工作区" description="Private 不显示成员管理；Public 成员由组同步；只有 Custom Owner 可以调整协作者。">
            {!selectedWorkspace ? <div className={surface.mutedText}>未选择工作区。</div> : (
              <div className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-3"><StatCard label="名称" value={selectedWorkspace.name} /><StatCard label="类型" value={selectedWorkspace.kind} hint={selectedWorkspace.isReadOnly ? "只读" : "可写"} /><StatCard label="角色" value={selectedWorkspace.role} /></div>
                {selectedWorkspace.kind === "private" ? <div className={`${surface.softPanel} p-4 text-sm ${surface.mutedText}`}>Private Space 只有你本人可见，不存在成员管理。</div> : null}
                {selectedWorkspace.kind === "public" ? <div className={`${surface.softPanel} p-4 text-sm ${surface.mutedText}`}>Public Space 成员由「{groupState.memberships.find((membership) => membership.groupId === selectedWorkspace.groupId)?.name ?? "用户组"}」自动同步，不能在工作区内单独添加。</div> : null}
                {selectedWorkspace.kind === "custom" ? (
                  <div className="space-y-4">
                    <div className={`${surface.softPanel} p-4 text-sm ${surface.mutedText}`}>当前 {members.length} 位成员（含 Owner）。</div>
                    {selectedWorkspace.canManageMembers ? <><form className="flex gap-2" onSubmit={handleRenameCustom}><input className={controls.input} value={renameWorkspaceName} onChange={(event) => setRenameWorkspaceName(event.target.value)} /><button className={controls.secondaryButton} type="submit" disabled={saving}>重命名</button></form><SearchableMultiSelect options={userOptions(directory, selectedWorkspace.ownerUserId)} value={editMemberIds} onChange={setEditMemberIds} placeholder="搜索并调整协作成员" searchPlaceholder="按姓名或用户名搜索" emptyMessage="没有匹配的活跃用户。" disabled={saving} /><div className="flex gap-2"><button className={controls.primaryButton} disabled={saving} onClick={() => void handleSaveCustomMembers()}>保存成员</button><button className={controls.dangerButton} disabled={saving} onClick={() => void handleDeleteCustom()}>删除空间</button></div></> : <div className={`${surface.softPanel} p-4 text-sm ${surface.mutedText}`}>只有 Owner 可以调整成员。</div>}
                  </div>
                ) : null}
              </div>
            )}
          </SectionCard>
        </div>

        <div className="space-y-5">
          {currentUser?.isAdmin ? (
            <>
              <SectionCard title="全局管理：用户组" description="创建组时指定至少一位组管理员；归档后 Public Space 对原成员只读。">
                <form className="space-y-4" onSubmit={handleCreateGroup}>
                  <div className="grid gap-3 sm:grid-cols-2"><input className={controls.input} placeholder="组名称" value={groupForm.name} onChange={(event) => setGroupForm((current) => ({ ...current, name: event.target.value }))} /><input className={controls.input} placeholder="说明（可选）" value={groupForm.description} onChange={(event) => setGroupForm((current) => ({ ...current, description: event.target.value }))} /></div>
                  <div><div className={`mb-2 text-sm font-medium ${surface.strongText}`}>初始组管理员</div><SearchableMultiSelect options={userOptions(directory)} value={groupForm.managerUserIds} onChange={(managerUserIds) => setGroupForm((current) => ({ ...current, managerUserIds }))} placeholder="搜索并选择组管理员" searchPlaceholder="按姓名或用户名搜索" emptyMessage="没有匹配的活跃用户。" disabled={saving} /></div>
                  <button className={controls.primaryButton} type="submit" disabled={!groupForm.name.trim() || saving}>创建组与 Public Space</button>
                </form>
                <div className="mt-4 space-y-2">{groups.map((group) => <div key={group.groupId} className={`${surface.softPanel} flex items-center justify-between gap-3 p-4`}><div><div className={`font-semibold ${surface.strongText}`}>{group.name}</div><div className={`text-xs ${surface.mutedText}`}>{group.memberCount} 成员 · {group.managerCount} manager {group.isArchived ? "· 已归档" : ""}</div></div>{!group.isArchived ? <button className={controls.dangerButton} disabled={saving} onClick={() => { if (window.confirm(`归档「${group.name}」并将 Public Space 设为只读？`)) void runAction(async () => { await deleteUserGroup(group.groupId); }, "归档失败。", true); }}>归档</button> : <Badge tone="warn">只读</Badge>}</div>)}</div>
              </SectionCard>

              <SectionCard title="全局管理：用户" description="管理员创建用户时可直接批准加入多个组；用户 A 不需要也不应被初始化为管理员。">
                <form className="space-y-3 rounded-2xl border border-dashed border-slate-200 p-4 dark:border-white/10" onSubmit={handleCreateUser}>
                  <div className="grid gap-3 sm:grid-cols-3"><input className={controls.input} placeholder="用户名" value={userForm.username} onChange={(event) => setUserForm((current) => ({ ...current, username: event.target.value }))} /><input className={controls.input} placeholder="显示名称" value={userForm.displayName} onChange={(event) => setUserForm((current) => ({ ...current, displayName: event.target.value }))} /><input className={controls.input} type="password" placeholder="初始密码" value={userForm.password} onChange={(event) => setUserForm((current) => ({ ...current, password: event.target.value }))} /></div>
                  <SearchableMultiSelect options={groups.filter((group) => !group.isArchived).map((group) => ({ value: group.groupId, label: group.name }))} value={userForm.groupIds} onChange={(groupIds) => setUserForm((current) => ({ ...current, groupIds }))} placeholder="搜索并选择直接加入的用户组" searchPlaceholder="按组名搜索" emptyMessage="没有匹配的可用用户组。" disabled={saving} />
                  <label className={`${surface.softPanel} flex gap-2 p-3 text-sm`}><input type="checkbox" checked={userForm.isAdmin} onChange={(event) => setUserForm((current) => ({ ...current, isAdmin: event.target.checked }))} />全局管理员</label>
                  <button className={controls.primaryButton} type="submit" disabled={saving}>创建用户</button>
                </form>
                <div className="mt-4 space-y-3">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <input className={controls.input} placeholder="按姓名或用户名筛选用户" value={adminUserQuery} onChange={(event) => { setAdminUserQuery(event.target.value); setAdminUserPage(0); }} />
                    <div className={`shrink-0 text-xs ${surface.mutedText}`}>匹配 {filteredAdminUsers.length} 人 · 每页最多 {adminUserPageSize} 人</div>
                  </div>
                  {visibleAdminUsers.map((user) => <div key={user.userId} className={`${surface.softPanel} space-y-3 p-4`}><div className="flex flex-wrap items-center justify-between gap-2"><div><div className={`font-semibold ${surface.strongText}`}>{user.displayName} <span className={`text-sm font-normal ${surface.mutedText}`}>@{user.username}</span></div><div className="mt-1 flex flex-wrap gap-1">{user.isAdmin ? <Badge tone="warn">Admin</Badge> : null}{user.groups.map((group) => <Badge key={group.groupId} tone={group.role === "manager" ? "info" : "neutral"}>{group.name} · {group.role}</Badge>)}</div></div><button className={user.isActive ? controls.dangerButton : controls.primaryButton} onClick={() => void runAction(async () => { await updateUser(user.userId, { isActive: !user.isActive }); }, "更新用户失败。")} >{user.isActive ? "停用" : "启用"}</button></div><div className="flex flex-wrap gap-2">{groups.filter((group) => !group.isArchived).map((group) => <button key={group.groupId} className={user.groups.some((item) => item.groupId === group.groupId) ? controls.primaryButton : controls.secondaryButton} disabled={saving} onClick={() => void handleToggleUserGroup(user, group.groupId)}>{user.groups.some((item) => item.groupId === group.groupId) ? "已加入" : "加入"} {group.name}</button>)}</div><div className="flex gap-2"><input className={controls.input} type="password" placeholder="新密码" value={passwordDrafts[user.userId] ?? ""} onChange={(event) => setPasswordDrafts((current) => ({ ...current, [user.userId]: event.target.value }))} /><button className={controls.secondaryButton} onClick={() => void handleResetPassword(user.userId)}>重置密码</button></div></div>)}
                  {!visibleAdminUsers.length ? <div className={`${surface.softPanel} p-4 text-sm ${surface.mutedText}`}>没有匹配的用户。</div> : null}
                  {adminUserPageCount > 1 ? <div className="flex items-center justify-end gap-2"><button className={controls.secondaryButton} disabled={safeAdminUserPage === 0} onClick={() => setAdminUserPage((current) => Math.max(0, current - 1))}>上一页</button><span className={`text-xs ${surface.mutedText}`}>第 {safeAdminUserPage + 1} / {adminUserPageCount} 页</span><button className={controls.secondaryButton} disabled={safeAdminUserPage >= adminUserPageCount - 1} onClick={() => setAdminUserPage((current) => Math.min(adminUserPageCount - 1, current + 1))}>下一页</button></div> : null}
                </div>
              </SectionCard>
            </>
          ) : null}

          <DeepSeekSettingsPanel />
          <LocalMaintenancePanel />
        </div>
      </div>
    </div>
  );
}
