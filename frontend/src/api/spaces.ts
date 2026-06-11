// Espacios compartidos (ESP-02..07).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { SpaceOut } from "./me";

export interface MemberOut {
  user_id: string;
  display_name: string;
  email: string | null;
  role: "owner" | "editor" | "viewer";
}

export interface InviteOut {
  id: string;
  email: string;
  role: string;
  token: string;
  expires_at: string;
  claimed_at: string | null;
}

export function useMembers(spaceId: string) {
  return useQuery({
    queryKey: ["members", spaceId],
    queryFn: () => api<MemberOut[]>(`/api/v1/spaces/${spaceId}/members`),
  });
}

export function useInvites(spaceId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["invites", spaceId],
    queryFn: () => api<InviteOut[]>(`/api/v1/spaces/${spaceId}/invites`),
    enabled,
    retry: false,
  });
}

function useInvalidateSpaces() {
  const qc = useQueryClient();
  return () =>
    ["members", "invites", "me"].forEach((k) => void qc.invalidateQueries({ queryKey: [k] }));
}

export function useCreateSpace() {
  const invalidate = useInvalidateSpaces();
  return useMutation({
    mutationFn: (body: { name: string }) =>
      api<SpaceOut>("/api/v1/spaces", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: invalidate,
  });
}

export function useCreateInvite() {
  const invalidate = useInvalidateSpaces();
  return useMutation({
    mutationFn: ({ spaceId, ...body }: { spaceId: string; email: string; role: string }) =>
      api<InviteOut>(`/api/v1/spaces/${spaceId}/invites`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  });
}

export function useClaimInvite() {
  const invalidate = useInvalidateSpaces();
  return useMutation({
    mutationFn: (token: string) =>
      api<SpaceOut>("/api/v1/invites/claim", {
        method: "POST",
        body: JSON.stringify({ token }),
      }),
    onSuccess: invalidate,
  });
}

export function useChangeRole() {
  const invalidate = useInvalidateSpaces();
  return useMutation({
    mutationFn: ({
      spaceId,
      userId,
      role,
    }: {
      spaceId: string;
      userId: string;
      role: string;
    }) =>
      api<MemberOut>(`/api/v1/spaces/${spaceId}/members/${userId}`, {
        method: "PATCH",
        body: JSON.stringify({ role }),
      }),
    onSuccess: invalidate,
  });
}

export function useRemoveMember() {
  const invalidate = useInvalidateSpaces();
  return useMutation({
    mutationFn: ({ spaceId, userId }: { spaceId: string; userId: string }) =>
      api<void>(`/api/v1/spaces/${spaceId}/members/${userId}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

export function useDeleteSpace() {
  const invalidate = useInvalidateSpaces();
  return useMutation({
    mutationFn: ({ spaceId, confirmName }: { spaceId: string; confirmName: string }) =>
      api<void>(`/api/v1/spaces/${spaceId}`, {
        method: "DELETE",
        body: JSON.stringify({ confirm_name: confirmName }),
      }),
    onSuccess: invalidate,
  });
}
