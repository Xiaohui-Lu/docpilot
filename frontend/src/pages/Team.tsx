import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Card, ErrorNote, PageHeader, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDateTime, timeAgo } from "../lib/format";
import type { Role } from "../lib/types";

const ROLE_HELP: Record<Role, string> = {
  admin: "Manage users, upload and delete",
  member: "Upload, analyze and ask",
  viewer: "Read-only access",
};

export function TeamPage() {
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: api.users });
  const audit = useQuery({ queryKey: ["audit"], queryFn: api.audit });
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "member" as Role });

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["users"] });
    void qc.invalidateQueries({ queryKey: ["audit"] });
  };
  const create = useMutation({
    mutationFn: () => api.createUser(form),
    onSuccess: () => {
      setForm({ name: "", email: "", password: "", role: "member" });
      refresh();
    },
  });
  const changeRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: Role }) => api.updateRole(id, role),
    onSuccess: refresh,
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };

  return (
    <>
      <PageHeader kicker="Administration" title="Team & audit log" />
      <div className="grid gap-5 xl:grid-cols-[1.2fr_1fr]">
        <div className="space-y-5">
          <Card title="Members" bodyClassName="p-0">
            {users.isLoading ? (
              <Spinner />
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-paper/60 text-left text-xs text-muted">
                  <tr>
                    <th className="px-5 py-2 font-medium">Name</th>
                    <th className="px-3 py-2 font-medium">Role</th>
                    <th className="px-3 py-2 font-medium">Last sign-in</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {users.data?.map((u) => (
                    <tr key={u.id}>
                      <td className="px-5 py-2.5">
                        <div className="font-medium">
                          {u.name}
                          {u.id === me?.id && <span className="ml-1 text-xs text-muted">(you)</span>}
                        </div>
                        <div className="text-xs text-muted">{u.email}</div>
                      </td>
                      <td className="px-3 py-2.5">
                        <select
                          className="input w-auto py-1 text-xs"
                          value={u.role}
                          aria-label={`Role for ${u.name}`}
                          disabled={u.id === me?.id || changeRole.isPending}
                          onChange={(e) => changeRole.mutate({ id: u.id, role: e.target.value as Role })}
                        >
                          <option value="admin">Admin</option>
                          <option value="member">Member</option>
                          <option value="viewer">Viewer</option>
                        </select>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-muted">
                        {u.last_login_at ? timeAgo(u.last_login_at) : "Never"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card
            title={
              <span className="flex items-center gap-2">
                <UserPlus className="size-4" /> Add a team member
              </span>
            }
          >
            <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="label" htmlFor="u-name">
                  Name
                </label>
                <input
                  id="u-name"
                  className="input"
                  required
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </div>
              <div>
                <label className="label" htmlFor="u-email">
                  Email
                </label>
                <input
                  id="u-email"
                  type="email"
                  className="input"
                  required
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </div>
              <div>
                <label className="label" htmlFor="u-pass">
                  Temporary password
                </label>
                <input
                  id="u-pass"
                  type="password"
                  className="input"
                  required
                  minLength={8}
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                />
              </div>
              <div>
                <label className="label" htmlFor="u-role">
                  Role
                </label>
                <select
                  id="u-role"
                  className="input"
                  value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value as Role })}
                >
                  {(Object.keys(ROLE_HELP) as Role[]).map((r) => (
                    <option key={r} value={r}>
                      {r[0]!.toUpperCase() + r.slice(1)} - {ROLE_HELP[r]}
                    </option>
                  ))}
                </select>
              </div>
              <div className="sm:col-span-2">
                <ErrorNote error={create.error ?? changeRole.error} />
              </div>
              <div className="sm:col-span-2">
                <button className="btn-primary" disabled={create.isPending} type="submit">
                  Add member
                </button>
              </div>
            </form>
          </Card>
        </div>

        <Card title="Audit log" bodyClassName="p-0">
          <ul className="max-h-[680px] divide-y divide-line overflow-y-auto text-sm">
            {audit.data?.map((e) => (
              <li key={e.id} className="px-5 py-2.5">
                <div className="flex items-center justify-between gap-3">
                  <code className="rounded bg-paper px-1.5 py-0.5 text-[11px] font-semibold text-night">
                    {e.action}
                  </code>
                  <span className="text-[11px] text-muted">{formatDateTime(e.created_at)}</span>
                </div>
                <div className="mt-1 truncate text-xs text-muted">
                  {e.user_email ?? "system"}
                  {e.target ? ` → ${e.target}` : ""}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}
