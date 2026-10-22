// Espacios compartidos (R8): miembros, invitaciones (ESP-04), roles (ESP-03/05),
// salir (ESP-05/07), eliminar espacio (ESP-06), crear espacio y reclamar token.
import { useState, type FormEvent } from "react";
import {
  useChangeRole,
  useClaimInvite,
  useCreateInvite,
  useCreateSpace,
  useDeleteSpace,
  useInvites,
  useMembers,
  useRemoveMember,
  type MemberOut,
} from "../../api/spaces";
import CollapsibleCard from "../../components/ui/CollapsibleCard";
import ConfirmDialog from "../../components/ui/ConfirmDialog";
import { useSpace } from "./SpaceProvider";

const ROLE_LABELS: Record<string, string> = {
  owner: "Owner",
  editor: "Editor",
  viewer: "Solo lectura",
};

function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p className="mt-2 text-sm text-red-600 dark:text-red-400">
      {error instanceof Error ? error.message : "Error"}
    </p>
  );
}

export default function MembersSection() {
  const { me, activeSpace, setActiveSpace } = useSpace();
  const isOwner = activeSpace.role === "owner";
  const isShared = activeSpace.type === "shared";

  const members = useMembers(activeSpace.id);
  const invites = useInvites(activeSpace.id, isOwner && isShared);
  const createInvite = useCreateInvite();
  const changeRole = useChangeRole();
  const removeMember = useRemoveMember();
  const deleteSpace = useDeleteSpace();
  const createSpace = useCreateSpace();
  const claimInvite = useClaimInvite();

  // GLO-09: remover a un miembro (o salir) se confirma.
  const [removing, setRemoving] = useState<MemberOut | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("editor");
  const [newSpaceName, setNewSpaceName] = useState("");
  const [claimToken, setClaimToken] = useState("");
  const [confirmName, setConfirmName] = useState("");
  const [copied, setCopied] = useState<string | null>(null);

  function handleInvite(e: FormEvent) {
    e.preventDefault();
    createInvite.mutate(
      { spaceId: activeSpace.id, email: inviteEmail, role: inviteRole },
      { onSuccess: () => setInviteEmail("") },
    );
  }

  return (
    <CollapsibleCard
      title={`Espacio: ${activeSpace.name}`}
      description={
        isShared
          ? "Espacio compartido — los miembros ven y registran según su rol."
          : "Tu espacio personal es solo tuyo; crea uno compartido para invitar a alguien."
      }
    >

      {/* Miembros (ESP-03) */}
      <ul className="mb-4 divide-y divide-line">
        {(members.data ?? []).map((m) => (
          <li key={m.user_id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
            <div>
              <span className="font-medium">{m.display_name}</span>
              <span className="ml-2 text-xs text-ink-muted">{m.email}</span>
            </div>
            <div className="flex items-center gap-2">
              {isOwner && isShared ? (
                <select
                  className="input w-32 py-1 text-xs"
                  value={m.role}
                  onChange={(e) =>
                    changeRole.mutate({
                      spaceId: activeSpace.id,
                      userId: m.user_id,
                      role: e.target.value,
                    })
                  }
                >
                  {Object.entries(ROLE_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              ) : (
                <span className="rounded-full bg-muted px-2 py-0.5 text-xs">
                  {ROLE_LABELS[m.role]}
                </span>
              )}
              {isShared && (isOwner || m.user_id === me.profile.id) && (
                <button
                  className="text-xs text-red-600 hover:underline dark:text-red-400"
                  onClick={() => setRemoving(m)}
                >
                  {m.user_id === me.profile.id ? "Salir" : "Remover"}
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
      <ErrorText error={changeRole.error ?? removeMember.error} />

      {/* Invitaciones (ESP-04) */}
      {isOwner && isShared && (
        <div className="mb-6 border-t border-line pt-4">
          <h3 className="mb-2 text-sm font-medium">Invitar</h3>
          <form onSubmit={handleInvite} className="flex flex-wrap gap-2">
            <input
              type="email"
              className="input w-56"
              placeholder="correo@ejemplo.com"
              required
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
            />
            <select
              className="input w-36"
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value)}
            >
              <option value="editor">Editor</option>
              <option value="viewer">Solo lectura</option>
              <option value="owner">Owner</option>
            </select>
            <button className="btn-primary" disabled={createInvite.isPending}>Invitar</button>
          </form>
          <ErrorText error={createInvite.error} />
          {(invites.data ?? []).length > 0 && (
            <ul className="mt-3 space-y-1 text-xs text-ink-muted">
              {(invites.data ?? []).map((inv) => (
                <li key={inv.id} className="flex flex-wrap items-center gap-2">
                  ✉️ {inv.email} ({ROLE_LABELS[inv.role]}) — expira{" "}
                  {inv.expires_at.slice(0, 10)}
                  <button
                    className="text-accent hover:underline"
                    onClick={() => {
                      void navigator.clipboard.writeText(inv.token);
                      setCopied(inv.id);
                      setTimeout(() => setCopied(null), 1500);
                    }}
                  >
                    {copied === inv.id ? "¡Copiado!" : "Copiar token"}
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-xs text-ink-muted">
            Comparte el token con la persona invitada; lo pega aquí abajo desde su cuenta.
          </p>
        </div>
      )}

      {/* Reclamar invitación + crear espacio */}
      <div className="grid gap-4 border-t border-line pt-4 md:grid-cols-2">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            claimInvite.mutate(claimToken, { onSuccess: () => setClaimToken("") });
          }}
        >
          <h3 className="mb-2 text-sm font-medium">¿Te invitaron? Pega tu token</h3>
          <div className="flex gap-2">
            <input
              className="input"
              placeholder="token de invitación"
              required
              value={claimToken}
              onChange={(e) => setClaimToken(e.target.value)}
            />
            <button className="btn-secondary" disabled={claimInvite.isPending}>Unirme</button>
          </div>
          <ErrorText error={claimInvite.error} />
        </form>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            createSpace.mutate(
              { name: newSpaceName },
              {
                onSuccess: (space) => {
                  setNewSpaceName("");
                  setActiveSpace(space.id);
                },
              },
            );
          }}
        >
          <h3 className="mb-2 text-sm font-medium">Nuevo espacio compartido</h3>
          <div className="flex gap-2">
            <input
              className="input"
              placeholder="Nombre (Familia, Roomies…)"
              required
              value={newSpaceName}
              onChange={(e) => setNewSpaceName(e.target.value)}
            />
            <button className="btn-secondary" disabled={createSpace.isPending}>Crear</button>
          </div>
          <ErrorText error={createSpace.error} />
        </form>
      </div>

      {/* Eliminar espacio (ESP-06) */}
      {isOwner && isShared && (
        <form
          className="mt-6 border-t border-line pt-4"
          onSubmit={(e) => {
            e.preventDefault();
            deleteSpace.mutate(
              { spaceId: activeSpace.id, confirmName },
              {
                onSuccess: () => {
                  setConfirmName("");
                  const personal = me.spaces.find((s) => s.type === "personal");
                  if (personal) setActiveSpace(personal.id);
                },
              },
            );
          }}
        >
          <h3 className="mb-1 text-sm font-medium text-red-600 dark:text-red-400">
            Eliminar este espacio
          </h3>
          <p className="mb-2 text-xs text-ink-muted">
            Borra TODOS sus datos de forma permanente. Escribe el nombre exacto
            (&ldquo;{activeSpace.name}&rdquo;) para confirmar.
          </p>
          <div className="flex gap-2">
            <input
              className="input w-56"
              placeholder={activeSpace.name}
              required
              value={confirmName}
              onChange={(e) => setConfirmName(e.target.value)}
            />
            <button className="btn-secondary text-red-600 dark:text-red-400" disabled={deleteSpace.isPending}>
              Eliminar definitivamente
            </button>
          </div>
          <ErrorText error={deleteSpace.error} />
        </form>
      )}

      <ConfirmDialog
        open={removing !== null}
        title={removing?.user_id === me.profile.id ? "Salir del espacio" : "Remover miembro"}
        confirmLabel={removing?.user_id === me.profile.id ? "Sí, salir" : "Sí, remover"}
        pending={removeMember.isPending}
        error={removeMember.error?.message}
        onClose={() => setRemoving(null)}
        onConfirm={() =>
          removing &&
          removeMember.mutate(
            { spaceId: activeSpace.id, userId: removing.user_id },
            { onSuccess: () => setRemoving(null) },
          )
        }
      >
        {removing?.user_id === me.profile.id ? (
          <p>
            ¿Salir de <strong>{activeSpace.name}</strong>? Dejarás de ver sus datos y necesitarás una
            nueva invitación para volver.
          </p>
        ) : (
          <p>
            ¿Remover a <strong>{removing?.display_name}</strong> de{" "}
            <strong>{activeSpace.name}</strong>? Dejará de ver sus datos; lo que registró se conserva.
          </p>
        )}
      </ConfirmDialog>
    </CollapsibleCard>
  );
}
