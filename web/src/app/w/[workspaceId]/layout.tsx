import { WorkspaceShell } from "@/components/workspace-shell";

export default function WorkspaceLayout({ children }: LayoutProps<"/w/[workspaceId]">) {
  return <WorkspaceShell>{children}</WorkspaceShell>;
}
